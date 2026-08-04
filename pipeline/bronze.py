"""pipeline/bronze.py — orquestração da Sprint 2 (Pipeline Bronze).

Para cada fonte: lê o watermark do store, extrai (extractor puro por fonte),
grava Parquet com merge/deduplicação por chave natural (read-merge-write,
versionamento.md §2.2/§2.3) e persiste o novo watermark **após** a escrita
bem-sucedida (§2.1). Ao final, grava a linha de controle `pipeline_runs`.

Entrada usada pelas tasks do Airflow DAG (hoje placeholder): a task instancia
`AirflowVariableStore` e chama `run_pipeline`. Localmente (dev/testes) usa-se
`JsonFileStore` + `LocalParquetStorage`, ambos injetáveis.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import structlog

from pipeline.camara import extract as camara_extract
from pipeline.config import (
    DeduplicacaoSettings,
    RetryDefaultSettings,
    get_pipeline,
    get_pipeline_version,
    get_sources,
)
from pipeline.contracts import ExtractResult, LoadMetadata
from pipeline.runs import PipelineRun, write_pipeline_run
from pipeline.senado import extract as senado_extract
from pipeline.storage import Storage, criar_storage
from pipeline.transparencia import extract as transparencia_extract
from pipeline.utils import records_to_dataframe
from pipeline.watermark import JsonFileStore, WatermarkState, WatermarkStore

logger = structlog.get_logger()

FONTES = ["camara", "senado", "transparencia_emendas", "transparencia_cartoes"]

CHAVE_WATERMARK = {
    "camara": "watermark_camara_despesas",
    "senado": "watermark_senado",
    "transparencia_emendas": "watermark_cgu_emenda",
    "transparencia_cartoes": "watermark_cgu_cartao",
}


def _novo_run_meta() -> LoadMetadata:
    return LoadMetadata(
        run_id=uuid.uuid4(),
        pipeline_version=get_pipeline_version(),
        execution_timestamp=datetime.now(timezone.utc),
        source_version="",
    )


def _deduplicacao(fonte: str) -> DeduplicacaoSettings:
    fontes = get_sources()
    if fonte == "camara":
        return fontes.camara.deduplicacao
    if fonte == "senado":
        return fontes.senado.deduplicacao
    if fonte == "transparencia_emendas":
        return fontes.transparencia.deduplicacao["emendas"]
    return fontes.transparencia.deduplicacao["cartoes"]


def _particao_por_registro(fonte: str, registro) -> tuple[int, int]:
    """Extrai (ano, mes) de partição de um registro de Bronze.

    Emendas não possuem mês na fonte — particionam em `mes=0`.
    """
    if fonte == "transparencia_emendas":
        return registro.ano, 0
    if fonte == "transparencia_cartoes":
        mes, ano = registro.mes_extrato.split("/")
        return int(ano), int(mes)
    return registro.ano, registro.mes


def _agrupar_por_particao(fonte: str, registros: list, escopo: str):
    """Agrupa registros por diretório de escrita `fonte/ano=A/mes=M`.

    `escopo` não altera a escrita (sempre particionada por ano/mês) — apenas
    o escopo de leitura da deduplicação no storage (`merge_scope`).
    """
    grupos: dict[str, list] = {}
    for registro in registros:
        ano, mes = _particao_por_registro(fonte, registro)
        grupos.setdefault(f"{ano}-{mes}", []).append(registro)
    for chave, recs in grupos.items():
        ano, mes = chave.split("-")
        rel = Path(fonte) / f"ano={ano}" / f"mes={mes}"
        yield rel, recs


def _extrair(
    fonte: str,
    client: httpx.Client,
    estado: WatermarkState,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None,
) -> ExtractResult:
    fontes = get_sources()
    if fonte == "camara":
        return camara_extract.extract_despesas(
            fontes.camara, client, estado.last_watermark, run_meta, retry_settings
        )
    if fonte == "senado":
        return senado_extract.extract_ceaps(fontes.senado, client, run_meta, retry_settings)
    if fonte == "transparencia_emendas":
        return transparencia_extract.extract_emendas(
            fontes.transparencia, client, estado.last_watermark, run_meta, retry_settings
        )
    return transparencia_extract.extract_cartoes(
        fontes.transparencia, client, estado.last_watermark, run_meta, retry_settings
    )


def _extrair_e_persistir(
    fonte: str,
    client: httpx.Client,
    store: WatermarkStore,
    storage: Storage,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None,
) -> tuple[str | None, str | None]:
    """Extrai e persiste uma fonte. Retorna (novo_watermark, erro)."""
    chave = CHAVE_WATERMARK[fonte]
    estado = store.get(chave)
    try:
        resultado = _extrair(fonte, client, estado, run_meta, retry_settings)
    except Exception as exc:  # noqa: BLE001 — falha isolada não derruba as demais (§5)
        logger.error("falha_extracao", fonte=fonte, erro=str(exc))
        return None, str(exc)

    if resultado.records:
        dedup = _deduplicacao(fonte)
        for rel, recs in _agrupar_por_particao(fonte, resultado.records, dedup.escopo):
            storage.write_merged(rel, records_to_dataframe(recs), dedup.campo, dedup.escopo)

    # Watermark avança somente após a escrita bem-sucedida (versionamento.md §2.1)
    novo_watermark = resultado.new_watermark or estado.last_watermark
    store.set(chave, WatermarkState(last_watermark=novo_watermark, run_id=run_meta.run_id))
    logger.info("fonte_consolidada", fonte=fonte, novo_watermark=novo_watermark)
    return novo_watermark, None


def run_pipeline(
    storage: Storage | None = None,
    store: WatermarkStore | None = None,
    client: httpx.Client | None = None,
    retry_settings: RetryDefaultSettings | None = None,
) -> PipelineRun:
    """Executa o pipeline Bronze ponta a ponta e grava a linha de controle.

    Args:
        storage: Persistência Parquet (padrão: `criar_storage()`).
        store: Armazenamento de watermark (padrão: `JsonFileStore`).
        client: Cliente HTTP (padrão: novo cliente com timeout configurado).
        retry_settings: Política de retry (tenacity) — override para testes.

    Returns:
        PipelineRun com status consolidado e watermarks por fonte.
    """
    run_meta = _novo_run_meta()
    if client is None:
        client = httpx.Client(timeout=httpx.Timeout(get_pipeline().http.request_timeout_seconds))
    if storage is None:
        storage = criar_storage()
    if store is None:
        store = JsonFileStore()

    watermarks: dict[str, str | None] = {}
    fontes_com_erro: list[str] = []
    for fonte in FONTES:
        novo, erro = _extrair_e_persistir(fonte, client, store, storage, run_meta, retry_settings)
        if erro is not None:
            fontes_com_erro.append(fonte)
        else:
            watermarks[fonte] = novo

    status = "success"
    if fontes_com_erro:
        status = "failed" if len(fontes_com_erro) == len(FONTES) else "partial"

    run = PipelineRun(
        run_id=run_meta.run_id,
        pipeline_version=run_meta.pipeline_version,
        execution_timestamp=run_meta.execution_timestamp,
        status=status,
        fontes_com_erro=fontes_com_erro,
        watermark_camara=watermarks.get("camara"),
        watermark_senado=watermarks.get("senado"),
        watermark_cgu_emenda=watermarks.get("transparencia_emendas"),
        watermark_cgu_cartao=watermarks.get("transparencia_cartoes"),
    )
    write_pipeline_run(storage, run)
    logger.info(
        "pipeline_bronze_concluido",
        run_id=str(run.run_id),
        status=status,
        fontes_com_erro=fontes_com_erro,
    )
    return run
