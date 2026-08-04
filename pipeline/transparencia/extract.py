"""Extração do Portal da Transparência (CGU) — emendas e cartões CPGF.

Fontes: GET /emendas e GET /cartoes (api.portaldatransparencia.gov.br).
Versionamento.md §2.3 (emendas, partição por ano) e §2.4 (cartões,
incremental por `mesExtrato`, com `mesExtratoInicio` = `mesExtratoFim` no
modo incremental). Rate limit respeitado via retry em 429 (tenacity, ADR-009).
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from pipeline.config import RetryDefaultSettings, TransparenciaSettings
from pipeline.contracts import ExtractResult, LoadMetadata
from pipeline.transparencia.schemas import CguBronzeCartao, CguBronzeEmenda
from pipeline.utils import request_json

logger = structlog.get_logger()


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
    while True:
        params = {
            cfg.paginacao.parametro_pagina: pagina,
            watermark_cfg.parametro_filtro: ano,
            **endpoint.parametros_fixos,
        }
        dados = request_json(client, url, params, retry_settings)
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
    while True:
        params = {
            cfg.paginacao.parametro_pagina: pagina,
            watermark_cfg.parametro_filtro: mes,
            watermark_cfg.parametro_filtro_fim: mes,
            **endpoint.parametros_fixos,
        }
        dados = request_json(client, url, params, retry_settings)
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
