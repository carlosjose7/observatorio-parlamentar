"""Extração de despesas da Câmara dos Deputados (Sprint 2 — Pipeline Bronze).

Fonte: GET /deputados/{id}/despesas (dadosabertos.camara.leg.br), ingestão
incremental por mês de competência (versionamento.md §2.1). O extractor é puro:
recebe o período (`MM/AAAA`) e os metadados de carga por parâmetro e não toca
em Airflow nem em armazenamento.

A API da Câmara **não aceita** filtros de data (`dataInicio`/`dataFim` → 400;
`ano`/`mes` sozinhos retornam 0) — o único filtro temporal confiável é
`idLegislatura`, com `ano`/`mes` como refinamento (corretivo 6.5). Para cada
mês, a legislatura vigente é derivada do calendário canônico (ADR-024,
`parlamento.legislatura_para_data`).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import structlog

from pipeline.camara.schemas import CamaraBronzeDeputado, CamaraBronzeDespesa
from pipeline.config import CamaraSettings, RetryDefaultSettings
from pipeline.contracts import ExtractResult, LoadMetadata
from pipeline.parlamento import legislatura_para_data
from pipeline.utils import RateLimiter, request_json

logger = structlog.get_logger()


def _itens_por_pagina(cfg: CamaraSettings) -> int:
    return cfg.paginacao.itens_por_pagina or 100


def _limitador(cfg: CamaraSettings) -> RateLimiter:
    """Throttling proativo da fonte (ADR-009 §rate limiting, corretivo 6.5).

    Lê o limite declarado em `config/sources.yaml` (camara.rate_limit) e
    aplica a margem de segurança padrão do token bucket.
    """
    return RateLimiter(cfg.rate_limit.requisicoes_por_minuto)


def _listar_deputados(
    cfg: CamaraSettings,
    client: httpx.Client,
    retry_settings: RetryDefaultSettings | None,
    limiter: RateLimiter,
) -> list[int]:
    url = cfg.base_url + cfg.endpoints["deputados"].path
    ids: list[int] = []
    pagina = 1
    while True:
        params = {
            cfg.paginacao.parametro_pagina: pagina,
            cfg.paginacao.parametro_itens: _itens_por_pagina(cfg),
        }
        dados = request_json(client, url, params, retry_settings, limiter=limiter)
        itens = dados.get("dados", [])
        ids.extend(item["id"] for item in itens)
        if len(itens) < _itens_por_pagina(cfg):
            break
        pagina += 1
    return ids


def _construir_registro(
    item: dict[str, Any], id_deputado: int, run_meta: LoadMetadata
) -> CamaraBronzeDespesa:
    meta = run_meta.model_copy(
        update={"source_version": run_meta.execution_timestamp.date().isoformat()}
    )
    return CamaraBronzeDespesa.model_validate(
        {**item, "id_deputado": id_deputado, "metadata": meta.model_dump()}
    )


def _deduplicar(registros: list[CamaraBronzeDespesa]) -> list[CamaraBronzeDespesa]:
    vistos: set[str] = set()
    unicos: list[CamaraBronzeDespesa] = []
    for registro in registros:
        if registro.cod_documento in vistos:
            continue
        vistos.add(registro.cod_documento)
        unicos.append(registro)
    return unicos


def _legislatura_do_mes(mes_ano: str) -> int:
    """Legislatura vigente no último dia do mês `MM/AAAA` (ADR-024).

    A API filtra despesas por `idLegislatura`, então cada mês de competência
    precisa ser atribuído à legislatura que o contém. Usa o último dia do mês
    para evitar ambiguidade na transição (legislatura muda em 1º de fevereiro).
    """
    mes, ano = (int(parte) for parte in mes_ano.split("/"))
    ultimo_dia = 31
    while True:
        try:
            fim_do_mes = date(ano, mes, ultimo_dia)
            break
        except ValueError:
            ultimo_dia -= 1
    legislatura = legislatura_para_data(fim_do_mes)
    if legislatura is None:
        raise ValueError(
            f"mês {mes_ano!r} fora do calendário de legislaturas conhecido (ADR-024)"
        )
    return legislatura


def _parametros_periodo(
    cfg: CamaraSettings, mes_ano: str
) -> dict[str, Any]:
    """Monta os filtros de período para o mês `MM/AAAA`.

    A API da Câmara ignora `ano`/`mes` sozinhos e exige `idLegislatura`
    (corretivo 6.5). `campo` do watermark é `mes` (MM/AAAA).
    """
    wm = cfg.watermark["despesas_por_deputado"]
    mes, ano = (int(parte) for parte in mes_ano.split("/"))
    parametros: dict[str, Any] = {wm.parametro_filtro: _legislatura_do_mes(mes_ano)}
    if wm.parametro_filtro_ano:
        parametros[wm.parametro_filtro_ano] = ano
    if wm.parametro_filtro_mes:
        parametros[wm.parametro_filtro_mes] = mes
    return parametros


def extract_despesas(
    cfg: CamaraSettings,
    client: httpx.Client,
    periodo: str | None,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None = None,
) -> ExtractResult:
    """Extrai as despesas de todos os deputados de um mês de competência.

    Args:
        cfg: Configuração da fonte (`config/sources.yaml` → camara).
        client: Cliente HTTP compartilhado (injetável para testes).
        periodo: Mês `MM/AAAA` a extrair (carga histórica e incremental).
            None usa o mês da execução.
        run_meta: Metadados de carga (RF-12); `source_version` é preenchido
            com a data de execução (versionamento.md §3).
        retry_settings: Política de retry (tenacity) — override para testes.

    Returns:
        ExtractResult com os registros, o novo watermark (o mês `MM/AAAA`
        extraído) e a versão da fonte.
    """
    periodo = periodo or run_meta.execution_timestamp.strftime("%m/%Y")
    logger.info("iniciando_extracao_camara", periodo=periodo)
    registros: list[CamaraBronzeDespesa] = []
    limiter = _limitador(cfg)

    for id_deputado in _listar_deputados(cfg, client, retry_settings, limiter):
        url = cfg.base_url + cfg.endpoints["despesas_por_deputado"].path.format(
            id_deputado=id_deputado
        )
        pagina = 1
        while True:
            params: dict[str, Any] = {
                cfg.paginacao.parametro_pagina: pagina,
                cfg.paginacao.parametro_itens: _itens_por_pagina(cfg),
                **_parametros_periodo(cfg, periodo),
            }
            dados = request_json(client, url, params, retry_settings, limiter=limiter)
            itens = dados.get("dados", [])
            for item in itens:
                registros.append(_construir_registro(item, id_deputado, run_meta))
            if len(itens) < _itens_por_pagina(cfg):
                break
            pagina += 1

    registros = _deduplicar(registros)
    return ExtractResult(
        records=registros,
        new_watermark=periodo,
        source_version=run_meta.execution_timestamp.date().isoformat(),
    )


def _construir_deputado(
    item: dict[str, Any], run_meta: LoadMetadata
) -> CamaraBronzeDeputado:
    """Achata um registro detalhado de deputado (GET /deputados/{id}).

    `dados` do detalhe é um objeto (não lista); os atributos da vigência
    (partido, UF, situação, legislatura) vivem em `ultimoStatus`.
    """
    ul = item.get("ultimoStatus", {})
    meta = run_meta.model_copy(
        update={"source_version": run_meta.execution_timestamp.date().isoformat()}
    )
    return CamaraBronzeDeputado.model_validate(
        {
            "id": item["id"],
            "nomeCivil": item.get("nomeCivil", ""),
            "nomeEleitoral": ul.get("nomeEleitoral") or ul.get("nome"),
            "siglaPartido": ul.get("siglaPartido"),
            "siglaUf": ul.get("siglaUf"),
            "idLegislatura": ul.get("idLegislatura"),
            "situacao": ul.get("situacao"),
            "condicaoEleitoral": ul.get("condicaoEleitoral"),
            "data": ul.get("data"),
            "metadata": meta.model_dump(),
        }
    )


def extract_deputados(
    cfg: CamaraSettings,
    client: httpx.Client,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None = None,
) -> ExtractResult:
    """Extrai o snapshot de dados mestres dos deputados (Onda 2, dim_parlamentar).

    Percorre a lista completa (GET /deputados, paginado) e, para cada id,
    baixa o detalhe (GET /deputados/{id}) — único lugar em que a API expõe
    partido, UF, legislatura e situação vigentes (`ultimoStatus`). Esses são
    os atributos rastreados pela estratégia SCD2 de `dim_parlamentar`
    (ADR-020) e o insumo do matching de autor de emenda (ADR-017).

    O snapshot é o estado observado na data de execução; cada execução gera
    um registro por deputado e a dedup da Silver concentra snapshots
    idênticos.

    Args:
        cfg: Configuração da fonte (`config/sources.yaml` → camara).
        client: Cliente HTTP compartilhado (injetável para testes).
        run_meta: Metadados de carga (RF-12); `source_version` é a data de
            execução (versionamento.md §3).
        retry_settings: Política de retry (tenacity) — override para testes.

    Returns:
        ExtractResult com os registros de deputados e o watermark (data da
        execução).
    """
    logger.info("iniciando_extracao_deputados")
    registros: list[CamaraBronzeDeputado] = []
    limiter = _limitador(cfg)
    for id_deputado in _listar_deputados(cfg, client, retry_settings, limiter):
        url = cfg.base_url + cfg.endpoints["deputados_detalhe"].path.format(
            id_deputado=id_deputado
        )
        dados = request_json(client, url, None, retry_settings, limiter=limiter)
        registros.append(_construir_deputado(dados.get("dados", {}), run_meta))

    watermark = run_meta.execution_timestamp.date().isoformat()
    return ExtractResult(
        records=registros,
        new_watermark=watermark,
        source_version=watermark,
    )
