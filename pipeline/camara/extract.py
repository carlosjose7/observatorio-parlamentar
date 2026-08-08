"""Extração de despesas da Câmara dos Deputados (Sprint 2 — Pipeline Bronze).

Fonte: GET /deputados/{id}/despesas (dadosabertos.camara.leg.br), ingestão
incremental por `dataDocumento` (versionamento.md §2.1). O extractor é puro:
recebe o `last_watermark` e os metadados de carga por parâmetro e não toca em
Airflow nem em armazenamento.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from pipeline.camara.schemas import CamaraBronzeDeputado, CamaraBronzeDespesa
from pipeline.config import CamaraSettings, RetryDefaultSettings
from pipeline.contracts import ExtractResult, LoadMetadata
from pipeline.utils import request_json

logger = structlog.get_logger()


def _itens_por_pagina(cfg: CamaraSettings) -> int:
    return cfg.paginacao.itens_por_pagina or 100


def _listar_deputados(
    cfg: CamaraSettings,
    client: httpx.Client,
    retry_settings: RetryDefaultSettings | None,
) -> list[int]:
    url = cfg.base_url + cfg.endpoints["deputados"].path
    ids: list[int] = []
    pagina = 1
    while True:
        params = {
            cfg.paginacao.parametro_pagina: pagina,
            cfg.paginacao.parametro_itens: _itens_por_pagina(cfg),
        }
        dados = request_json(client, url, params, retry_settings)
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


def extract_despesas(
    cfg: CamaraSettings,
    client: httpx.Client,
    last_watermark: str | None,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None = None,
) -> ExtractResult:
    """Extrai as despesas de todos os deputados a partir do último watermark.

    Args:
        cfg: Configuração da fonte (`config/sources.yaml` → camara).
        client: Cliente HTTP compartilhado (injetável para testes).
        last_watermark: Último `dataDocumento` consolidado, ou None para
            carga inicial. Filtro via `dataInicio` (parametro_filtro).
        run_meta: Metadados de carga (RF-12); `source_version` é preenchido
            com a data de execução (versionamento.md §3).
        retry_settings: Política de retry (tenacity) — override para testes.

    Returns:
        ExtractResult com os registros, o novo watermark (maior
        `dataDocumento` observado) e a versão da fonte.
    """
    logger.info("iniciando_extracao_camara", ultimo_watermark=last_watermark)
    watermark_cfg = cfg.watermark["despesas_por_deputado"]
    registros: list[CamaraBronzeDespesa] = []

    for id_deputado in _listar_deputados(cfg, client, retry_settings):
        url = cfg.base_url + cfg.endpoints["despesas_por_deputado"].path.format(
            id_deputado=id_deputado
        )
        pagina = 1
        while True:
            params: dict[str, Any] = {
                cfg.paginacao.parametro_pagina: pagina,
                cfg.paginacao.parametro_itens: _itens_por_pagina(cfg),
            }
            if last_watermark:
                params[watermark_cfg.parametro_filtro] = last_watermark
            dados = request_json(client, url, params, retry_settings)
            itens = dados.get("dados", [])
            for item in itens:
                registros.append(_construir_registro(item, id_deputado, run_meta))
            if len(itens) < _itens_por_pagina(cfg):
                break
            pagina += 1

    registros = _deduplicar(registros)
    maior_data = max((r.data_documento[:10] for r in registros), default=None)
    novo_watermark = maior_data or last_watermark
    return ExtractResult(
        records=registros,
        new_watermark=novo_watermark,
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
    for id_deputado in _listar_deputados(cfg, client, retry_settings):
        url = cfg.base_url + cfg.endpoints["deputados_detalhe"].path.format(
            id_deputado=id_deputado
        )
        dados = request_json(client, url, None, retry_settings)
        registros.append(_construir_deputado(dados.get("dados", {}), run_meta))

    watermark = run_meta.execution_timestamp.date().isoformat()
    return ExtractResult(
        records=registros,
        new_watermark=watermark,
        source_version=watermark,
    )
