"""Extração do Portal da Transparência (CGU) — emendas e cartões CPGF.

Fontes: GET /emendas e GET /cartoes (api.portaldatransparencia.gov.br).
Versionamento.md §2.3 (emendas, partição por ano) e §2.4 (cartões,
incremental por `mesExtrato`, com `mesExtratoInicio` = `mesExtratoFim` no
modo incremental).

Rate limit respeitado de forma **proativa** (token bucket, ADR-009 §rate
limiting / corretivo 6.5): a CGU suspende a chave inteira por 8h ao exceder
o limite/min — retry reativo em 429 não resolve. `_limitador` lê os limites
de config/sources.yaml (diurno/noturno; override por endpoint, ex: `/cartoes`
a 180/min) e `request_json` consulta o token antes de cada requisição.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import httpx
import structlog

from pipeline.config import (
    RetryDefaultSettings,
    TransparenciaSettings,
    get_env,
)
from pipeline.contracts import ExtractResult, LoadMetadata
from pipeline.transparencia.schemas import CguBronzeCartao, CguBronzeEmenda
from pipeline.utils import RateLimiter, request_json

logger = structlog.get_logger()


def _headers_auth(cfg: TransparenciaSettings) -> dict[str, str]:
    """Header de autenticação da CGU (`chave-api-dados`), valor do `.env`.

    `config/sources.yaml` → transparencia.auth declara o nome do header e a
    env var (ADR-008); o segredo vive em `.env` (`CGU_API_KEY`), nunca no
    código nem no YAML. Sem chave configurada, retorna vazio (o 401 resultante
    é reportado como falha da fonte, não mascarado por retry — utils.py).
    """
    chave = get_env().cgu_api_key.get_secret_value()
    if not chave:
        logger.warning("cgu_api_key_ausente", hint="defina CGU_API_KEY no .env")
        return {}
    return {cfg.auth.header: chave}


def _taxa_por_minuto(
    cfg: TransparenciaSettings, agora: Callable[[], datetime] = datetime.now
) -> Any:
    """Taxa vigente da CGU (diurno/noturno) como callable do token bucket.

    Lê `janela_noturna_inicio`/`fim` de `config/sources.yaml`: dentro da
    janela noturna usa o limite noturno (700/min), fora usa o diurno
    (400/min). Callable porque a hora muda entre requisições — e o token
    bucket reavalia a taxa a cada `aguardar()`, então a transição de janela
    é respeitada sem recriar o limitador.

    `agora` é injetável para testes (provar a transição com relógio fake).
    """

    def taxa() -> float:
        t = agora()
        hora_atual = f"{t.hour:02d}:{t.minute:02d}"
        rl = cfg.rate_limit
        noturno = rl.janela_noturna_inicio <= hora_atual < rl.janela_noturna_fim
        if noturno:
            return float(rl.requisicoes_por_minuto_noturno)
        return float(rl.requisicoes_por_minuto_diurno)

    return taxa


def _limitador(
    cfg: TransparenciaSettings, endpoint: str, agora: Callable[[], datetime] = datetime.now
) -> RateLimiter:
    """Throttling proativo da fonte (ADR-009 §rate limiting, corretivo 6.5).

    Precedência (da maior para a menor): `rate_limit` por endpoint
    (sources.yaml → transparencia.endpoints.X.rate_limit) > taxa da fonte
    (diurna/noturna). Ex: `/cartoes` a 180/min (HIPÓTESE conservadora — não é
    limite oficial confirmado; ver config/sources.yaml e
    docs/sprint6.5_limites_fontes.md §4) ignora a taxa global 400/700.
    """
    ep = cfg.endpoints[endpoint]
    if ep.rate_limit is not None:
        return RateLimiter(ep.rate_limit.requisicoes_por_minuto)
    return RateLimiter(_taxa_por_minuto(cfg, agora))


def _deduplicar_por(registros: list, campo: str) -> list:
    vistos: set[Any] = set()
    unicos: list = []
    for registro in registros:
        chave = getattr(registro, campo)
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(registro)
    return unicos


def _construir_emenda(item: dict[str, Any], run_meta: LoadMetadata, ano: int) -> CguBronzeEmenda:
    source_version = f"{ano}-execution-{run_meta.execution_timestamp.date().isoformat()}"
    meta = run_meta.model_copy(update={"source_version": source_version})
    return CguBronzeEmenda.model_validate({**item, "metadata": meta.model_dump()})


def _construir_cartao(
    item: dict[str, Any], run_meta: LoadMetadata, mes: str
) -> CguBronzeCartao:
    source_version = f"{mes}-execution-{run_meta.execution_timestamp.date().isoformat()}"
    meta = run_meta.model_copy(update={"source_version": source_version})
    return CguBronzeCartao.model_validate({**item, "metadata": meta.model_dump()})


def extract_emendas(
    cfg: TransparenciaSettings,
    client: httpx.Client,
    ano: int | None,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None = None,
) -> ExtractResult:
    """Extrai as emendas de um ano (varredura completa das páginas).

    Args:
        cfg: Configuração da fonte (`config/sources.yaml` → transparencia).
        client: Cliente HTTP compartilhado (injetável para testes).
        ano: Ano a extrair (carga histórica). None usa o ano da execução;
            no modo incremental o orquestrador passa o último ano processado
            (o dataset anual é republicado e a deduplicação absorve as novidades).
        run_meta: Metadados de carga (RF-12).
        retry_settings: Política de retry (tenacity) — override para testes.

    Returns:
        ExtractResult com os registros e o ano como novo watermark.
    """
    ano = int(ano) if ano else run_meta.execution_timestamp.year
    watermark_cfg = cfg.watermark["emendas"]
    endpoint = cfg.endpoints["emendas"]
    url = cfg.base_url + endpoint.path
    logger.info("iniciando_extracao_emendas", ano=ano)

    registros: list[CguBronzeEmenda] = []
    pagina = 1
    limiter = _limitador(cfg, "emendas")
    while True:
        params = {
            cfg.paginacao.parametro_pagina: pagina,
            watermark_cfg.parametro_filtro: ano,
            **endpoint.parametros_fixos,
        }
        dados = request_json(
            client, url, params, retry_settings, headers=_headers_auth(cfg), limiter=limiter
        )
        if not dados:
            break
        for item in dados:
            registros.append(_construir_emenda(item, run_meta, ano))
        pagina += 1

    registros = _deduplicar_por(registros, "codigo_emenda")
    return ExtractResult(
        records=registros,
        new_watermark=str(ano),
        source_version=f"{ano}-execution-{run_meta.execution_timestamp.date().isoformat()}",
    )


def extract_cartoes(
    cfg: TransparenciaSettings,
    client: httpx.Client,
    mes: str | None,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None = None,
) -> ExtractResult:
    """Extrai as transações de cartão CPGF de um mês de extrato.

    Args:
        cfg: Configuração da fonte (`config/sources.yaml` → transparencia).
        client: Cliente HTTP compartilhado (injetável para testes).
        mes: `mesExtrato` (MM/AAAA) a extrair (carga histórica), ou None
            para o mês corrente da execução; no modo incremental o
            orquestrador passa o último mês consolidado.
        run_meta: Metadados de carga (RF-12).
        retry_settings: Política de retry (tenacity) — override para testes.

    Returns:
        ExtractResult com os registros e o `mesExtrato` como novo watermark.
    """
    mes = mes or run_meta.execution_timestamp.strftime("%m/%Y")
    watermark_cfg = cfg.watermark["cartoes"]
    endpoint = cfg.endpoints["cartoes"]
    url = cfg.base_url + endpoint.path
    logger.info("iniciando_extracao_cartoes", mes_extrato=mes)

    registros: list[CguBronzeCartao] = []
    pagina = 1
    limiter = _limitador(cfg, "cartoes")
    while True:
        params = {
            cfg.paginacao.parametro_pagina: pagina,
            watermark_cfg.parametro_filtro: mes,
            watermark_cfg.parametro_filtro_fim: mes,
            **endpoint.parametros_fixos,
        }
        dados = request_json(
            client, url, params, retry_settings, headers=_headers_auth(cfg), limiter=limiter
        )
        if not dados:
            break
        for item in dados:
            registros.append(_construir_cartao(item, run_meta, mes))
        pagina += 1

    registros = _deduplicar_por(registros, "id")
    return ExtractResult(
        records=registros,
        new_watermark=mes,
        source_version=f"{mes}-execution-{run_meta.execution_timestamp.date().isoformat()}",
    )
