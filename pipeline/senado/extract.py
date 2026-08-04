"""Extração de despesas CEAPS do Senado Federal (Sprint 2 — Pipeline Bronze).

Fonte: CSV anual `despesa_ceaps_{ano}.csv` (ISO-8859-1, separador ';').
Sem watermark incremental (ADR-009) — o "watermark" é o próprio ano do CSV
(versionamento.md §2.2). Deduplicação por `COD_DOCUMENTO` é aplicada na carga
em Bronze (read-merge-write, ver pipeline/storage.py).
"""

from __future__ import annotations

import io

import httpx
import pandas as pd
import structlog

from pipeline.config import RetryDefaultSettings, SenadoSettings
from pipeline.contracts import ExtractResult, LoadMetadata
from pipeline.senado.schemas import SenadoBronzeDespesa
from pipeline.utils import request_text

logger = structlog.get_logger()


def _url_csv(cfg: SenadoSettings, ano: int) -> str:
    return f"{cfg.base_url.rstrip('/')}/{cfg.padrao_arquivo.format(ano=ano)}"


def _parse_csv(
    texto: str,
    cfg: SenadoSettings,
    run_meta: LoadMetadata,
    ano: int,
) -> list[SenadoBronzeDespesa]:
    # A fonte publica uma linha de rodapé "ULTIMA ATUALIZACAO: ..." que não
    # pertence ao dataset — descartada em qualquer posição antes do parsing.
    linhas = [
        linha
        for linha in texto.splitlines()
        if not linha.strip().upper().startswith("ULTIMA ATUALIZACAO")
    ]
    df = pd.read_csv(
        io.StringIO("\n".join(linhas)),
        sep=cfg.separador,
        quotechar=cfg.quote_char,
        dtype=str,
        keep_default_na=False,
    )

    source_version = cfg.padrao_arquivo.format(ano=ano)
    registros: list[SenadoBronzeDespesa] = []
    for _, row in df.iterrows():
        meta = run_meta.model_copy(update={"source_version": source_version})
        registros.append(
            SenadoBronzeDespesa(
                ano=int(row["ANO"]),
                mes=int(row["MES"]),
                senador=row["SENADOR"],
                tipo_despesa=row["TIPO_DESPESA"],
                cnpj_cpf=row["CNPJ_CPF"],
                fornecedor=row["FORNECEDOR"],
                documento=row["DOCUMENTO"],
                data=row["DATA"],
                detalhamento=(row.get("DETALHAMENTO") or "").strip() or None,
                valor_reembolsado=row["VALOR_REEMBOLSADO"],
                cod_documento=int(row["COD_DOCUMENTO"]),
                metadata=meta,
            )
        )

    vistos: set[int] = set()
    unicos: list[SenadoBronzeDespesa] = []
    for registro in registros:
        if registro.cod_documento in vistos:
            continue
        vistos.add(registro.cod_documento)
        unicos.append(registro)
    return unicos


def extract_ceaps(
    cfg: SenadoSettings,
    client: httpx.Client,
    run_meta: LoadMetadata,
    retry_settings: RetryDefaultSettings | None = None,
    ano: int | None = None,
) -> ExtractResult:
    """Baixa e parseia o CSV anual de despesas CEAPS.

    Args:
        cfg: Configuração da fonte (`config/sources.yaml` → senado).
        client: Cliente HTTP compartilhado (injetável para testes).
        run_meta: Metadados de carga (RF-12); `source_version` é o nome do
            arquivo CSV (versionamento.md §3).
        retry_settings: Política de retry (tenacity) — override para testes.
        ano: Ano do CSV a baixar (carga histórica). None usa o ano da
            execução.

    Returns:
        ExtractResult com os registros e o ano do CSV como novo watermark.
    """
    ano = ano or run_meta.execution_timestamp.year
    url = _url_csv(cfg, ano)
    logger.info("baixando_csv_senado", url=url, ano=ano)
    texto = request_text(client, url, cfg.encoding, retry_settings)
    registros = _parse_csv(texto, cfg, run_meta, ano)
    return ExtractResult(
        records=registros,
        new_watermark=str(ano),
        source_version=cfg.padrao_arquivo.format(ano=ano),
    )
