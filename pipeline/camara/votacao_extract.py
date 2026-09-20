"""Extração de presença e votação da Câmara dos Deputados (Sprint 27 — Onda 1, ADR-058).

Fontes (dadosabertos.camara.leg.br), todas GET públicas:
- GET /eventos — descoberta por intervalo (`dataInicio`/`dataFim`, aceitos
  aqui — ao contrário das despesas); gate "só Encerrada conta" é aplicado
  no Gold, a Bronze preserva todas as situações.
- Arquivo anual em lote `eventosPresencaDeputados-{ano}.json` — presença com
  semântica só-presença; chaves do lote a confirmar no primeiro backfill
  (mapeamento flexível com fallback + log, nunca exceção — ADR-016).
- GET /eventos/{id}/votacoes — descoberta de votações por evento.
- GET /votacoes/{id}/votos — voto nominal (`tipoVoto`, `deputado_.id`
  aninhado, achatado aqui como `id_deputado`).
- GET /votacoes/{id}/orientacoes — orientação de bancada.

Os extractors são puros: recebem configuração, cliente e metadados por
parâmetro e não tocam em Airflow nem em armazenamento (padrão Sprint 2).
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from pipeline.camara.votacao_schemas import (
    CamaraBronzeEvento,
    CamaraBronzeOrientacao,
    CamaraBronzePresenca,
    CamaraBronzeVotacao,
    CamaraBronzeVoto,
)
from pipeline.config import CamaraSettings, RetryDefaultSettings
from pipeline.contracts import ExtractResult, LoadMetadata
from pipeline.utils import RateLimiter, request_json

logger = structlog.get_logger()


def _limitador(cfg: CamaraSettings) -> RateLimiter:
    """Throttling proativo da fonte (mesmo padrão de `extract.py`, ADR-009)."""
    return RateLimiter(cfg.rate_limit.requisicoes_por_minuto)


def _itens_por_pagina(cfg: CamaraSettings) -> int:
    return cfg.paginacao.itens_por_pagina or 100


def _get_paginado(
    cfg: CamaraSettings,
    client: httpx.Client,
    url: str,
    params_base: dict[str, Any],
    retry_settings: RetryDefaultSettings | None,
    limiter: RateLimiter,
) -> list[dict[str, Any]]:
    """Coleta todas as páginas de um endpoint paginado da Câmara (`dados`)."""
    itens: list[dict[str, Any]] = []
    pagina = 1
    por_pagina = _itens_por_pagina(cfg)
    while True:
        params = {
            **params_base,
            cfg.paginacao.parametro_pagina: pagina,
            cfg.paginacao.parametro_itens: por_pagina,
        }
        dados = request_json(client, url, params, retry_settings, limiter=limiter)
        lote = dados.get("dados", [])
        itens.extend(lote)
        if len(lote) < por_pagina:
            break
        pagina += 1
    return itens


def extract_eventos(
    cfg: CamaraSettings,
    client: httpx.Client,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
) -> ExtractResult:
    """Extrai eventos da Câmara no intervalo (`AAAA-MM-DD`, ambos opcionais).

    Watermark = maior `dataHoraInicio` observada (data, sem hora) — janela
    seguinte parte desse dia (overlap absorvido pela dedup por `id_evento`).
    """
    url = cfg.base_url + cfg.endpoints["eventos"].path
    limiter = _limitador(cfg)
    params_base: dict[str, Any] = {"ordenarPor": "dataHoraInicio", "ordem": "ASC"}
    if data_inicio is not None:
        params_base["dataInicio"] = data_inicio
    if data_fim is not None:
        params_base["dataFim"] = data_fim
    brutos = _get_paginado(cfg, client, url, params_base, retry_settings, limiter)
    registros = [
        CamaraBronzeEvento.model_validate({**item, "metadata": run_meta.model_dump()})
        for item in brutos
    ]
    datas = sorted({r.data_inicio[:10] for r in registros if r.data_inicio})
    return ExtractResult(
        records=registros,
        new_watermark=datas[-1] if datas else None,
        source_version=run_meta.execution_timestamp.date().isoformat(),
    )


def extract_presenca_ano(
    cfg: CamaraSettings,
    client: httpx.Client,
    ano: int,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None,
) -> ExtractResult:
    """Extrai o arquivo anual em lote de presença (semântica só-presença).

    As chaves exatas do lote serão confirmadas no primeiro backfill — o
    mapeamento tenta os candidatos conhecidos e registra (sem levantar)
    linhas não-resolvíveis (ADR-016: parser nunca interrompe o pipeline).
    """
    template = cfg.endpoints["presenca_arquivo_ano"].path
    url = template.format(ano=ano)
    limiter = _limitador(cfg)
    dados = request_json(client, url, {}, retry_settings, limiter=limiter)
    brutos = dados.get("dados", dados) if isinstance(dados, dict) else dados
    if not isinstance(brutos, list):
        logger.warning("presenca_lote_formato_inesperado", ano=ano)
        return ExtractResult(records=[], source_version=str(ano))

    registros: list[CamaraBronzePresenca] = []
    for item in brutos:
        if not isinstance(item, dict):
            continue
        id_evento = _primeira_chave(item, ("idEvento", "id_evento", "evento_id", "id"))
        id_deputado = _primeira_chave(item, ("idDeputado", "id_deputado", "deputado_id"))
        if id_evento is None or id_deputado is None:
            logger.warning("presenca_linha_nao_resolvida", ano=ano, chaves=sorted(item.keys()))
            continue
        registros.append(
            CamaraBronzePresenca.model_validate(
                {
                    "id_evento": id_evento,
                    "id_deputado": id_deputado,
                    "data_hora_inicio": _primeira_chave(
                        item, ("dataHoraInicio", "data_hora_inicio", "data")
                    ),
                    "metadata": run_meta.model_dump(),
                }
            )
        )
    return ExtractResult(records=registros, source_version=str(ano))


def _primeira_chave(item: dict[str, Any], candidatas: tuple[str, ...]) -> Any | None:
    """Retorna o valor da primeira chave candidata presente, ou None."""
    for chave in candidatas:
        if item.get(chave) is not None:
            return item[chave]
    return None


def extract_votacoes_evento(
    cfg: CamaraSettings,
    client: httpx.Client,
    id_evento: int,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None,
) -> ExtractResult:
    """Extrai as votações de um evento (`GET /eventos/{id}/votacoes`)."""
    url = cfg.base_url + cfg.endpoints["votacoes_por_evento"].path.format(id_evento=id_evento)
    limiter = _limitador(cfg)
    brutos = _get_paginado(cfg, client, url, {}, retry_settings, limiter)
    registros = [
        CamaraBronzeVotacao.model_validate(
            {**item, "id_evento": id_evento, "metadata": run_meta.model_dump()}
        )
        for item in brutos
    ]
    return ExtractResult(records=registros, source_version=str(id_evento))


def extract_votos(
    cfg: CamaraSettings,
    client: httpx.Client,
    id_votacao: int,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None,
) -> ExtractResult:
    """Extrai os votos nominais de uma votação (`deputado_.id` achatado)."""
    url = cfg.base_url + cfg.endpoints["votos_por_votacao"].path.format(id_votacao=id_votacao)
    limiter = _limitador(cfg)
    brutos = _get_paginado(cfg, client, url, {}, retry_settings, limiter)
    registros: list[CamaraBronzeVoto] = []
    for item in brutos:
        deputado = item.get("deputado_", {}) or {}
        id_deputado = deputado.get("id", item.get("idDeputado"))
        if id_deputado is None:
            logger.warning("voto_sem_deputado", id_votacao=id_votacao)
            continue
        registros.append(
            CamaraBronzeVoto.model_validate(
                {**item, "id_votacao": id_votacao, "id_deputado": id_deputado,
                 "metadata": run_meta.model_dump()}
            )
        )
    return ExtractResult(records=registros, source_version=str(id_votacao))


def extract_orientacoes(
    cfg: CamaraSettings,
    client: httpx.Client,
    id_votacao: int,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None,
) -> ExtractResult:
    """Extrai as orientações de bancada de uma votação (insumo `seguiu_partido`)."""
    url = cfg.base_url + cfg.endpoints["orientacoes_por_votacao"].path.format(id_votacao=id_votacao)
    limiter = _limitador(cfg)
    brutos = _get_paginado(cfg, client, url, {}, retry_settings, limiter)
    registros = [
        CamaraBronzeOrientacao.model_validate(
            {**item, "id_votacao": id_votacao, "metadata": run_meta.model_dump()}
        )
        for item in brutos
    ]
    return ExtractResult(records=registros, source_version=str(id_votacao))


def extrair_janela(
    cfg: CamaraSettings,
    client: httpx.Client,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None,
    data_inicio: str | None,
    data_fim: str | None,
    anos_presenca: list[int] | None = None,
) -> dict[str, ExtractResult]:
    """Extrai a janela completa do domínio votação (eventos em cascata + presença).

    Para cada evento da janela: votações; para cada votação: votos e
    orientações. Presença em lote por ano da janela (`anos_presenca`, default:
    anos cobertos por [data_inicio, data_fim]).
    """
    eventos = extract_eventos(cfg, client, run_meta, retry_settings, data_inicio, data_fim)
    votacoes = ExtractResult()
    votos = ExtractResult()
    orientacoes = ExtractResult()
    for evento in eventos.records:
        try:
            res_vot = extract_votacoes_evento(cfg, client, evento.id_evento, run_meta, retry_settings)
        except Exception as exc:  # noqa: BLE001 — evento sem votação não derruba a janela
            logger.warning("janela_votacoes_evento_falhou", id_evento=evento.id_evento, erro=str(exc))
            continue
        votacoes.records.extend(res_vot.records)
        for votacao in res_vot.records:
            try:
                votos.records.extend(
                    extract_votos(cfg, client, votacao.id_votacao, run_meta, retry_settings).records
                )
                orientacoes.records.extend(
                    extract_orientacoes(cfg, client, votacao.id_votacao, run_meta, retry_settings).records
                )
            except Exception as exc:  # noqa: BLE001 — votação sem votos não derruba a janela
                logger.warning(
                    "janela_votos_votacao_falhou", id_votacao=votacao.id_votacao, erro=str(exc)
                )
                continue
    if anos_presenca is None and data_inicio and data_fim:
        anos_presenca = list(range(int(data_inicio[:4]), int(data_fim[:4]) + 1))
    presenca = ExtractResult()
    for ano in anos_presenca or []:
        presenca.records.extend(
            extract_presenca_ano(cfg, client, ano, run_meta, retry_settings).records
        )
    return {
        "eventos": eventos,
        "presenca": presenca,
        "votacoes": votacoes,
        "votos": votos,
        "orientacoes": orientacoes,
    }
