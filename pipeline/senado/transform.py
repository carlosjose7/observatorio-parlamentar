"""pipeline/senado/transform.py — Bronze → Silver das despesas CEAPS do Senado (Trilha B).

Mesmo contrato do `transform.py` da Câmara (ADR-023): lê o Parquet Bronze,
normaliza para o grão canônico de `silver_despesa` e delega a carga ao
`carregar_tabela_silver`.

Diferenças de fonte (ADR-016):
- Datas em DD/MM/AAAA e valores em string pt-BR (`parse_decimal_ptbr`).
- Não existe conceito de glosa — `valor_glosa` é fixado em 0.0.
- `fonte='senado'`; chave de negócio `["fonte", "cod_documento"]`.
- Como não há glosa, `valor_liquido` = `VALOR_REEMBOLSADO`.

O HMAC de CPF é aplicado no Gold (dbt) — aqui apenas digitação limpa
(`clean_document_number`) + classificação (ADR-011).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import structlog

from pipeline.contracts import resolve_tipo_documento
from pipeline.normalize import parse_date_multi_format, parse_decimal_ptbr
from pipeline.silver import ResultadoCargaSilver, carregar_tabela_silver
from pipeline.storage import Storage

logger = structlog.get_logger()

COLUNAS_SILVER = [
    "fonte",
    "ano",
    "mes",
    "cod_documento",
    "data_documento",
    "tipo_despesa",
    "cnpj_cpf_valor",
    "tipo_documento",
    "nome_fornecedor",
    "valor_liquido",
    "valor_glosa",
    "run_id",
    "pipeline_version",
    "execution_timestamp",
    "source_version",
]

DIRETORIO_BRONZE = Path("senado")


def construir_silver(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Mapeia o DataFrame Bronze do Senado para o formato canônico Silver.

    Args:
        df_bronze: DataFrame com os registros brutos CEAPS do Senado
            (leitura de `storage`, com metadados achatados).

    Returns:
        DataFrame com as colunas canônicas de `silver_despesa` (fonte='senado')
        ou DataFrame vazio com o schema fixo quando não há registros.
    """
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER)

    n = len(df_bronze)
    classificados = [resolve_tipo_documento(v) for v in df_bronze["cnpj_cpf"]]
    cnpj_cpf_valor = [par[0] for par in classificados]
    tipo_documento = [par[1].value if par[1] else None for par in classificados]

    df = pd.DataFrame(
        {
            "fonte": ["senado"] * n,
            "ano": df_bronze["ano"].astype("int64"),
            "mes": df_bronze["mes"].astype("int64"),
            "cod_documento": df_bronze["cod_documento"].astype(str),
            "data_documento": pd.to_datetime(
                df_bronze["data"].map(parse_date_multi_format)
            ),
            "tipo_despesa": df_bronze["tipo_despesa"],
            "cnpj_cpf_valor": cnpj_cpf_valor,
            "tipo_documento": tipo_documento,
            "nome_fornecedor": df_bronze["fornecedor"],
            "valor_liquido": pd.to_numeric(
                df_bronze["valor_reembolsado"].map(parse_decimal_ptbr)
            ).astype("float64"),
            "valor_glosa": pd.Series([0.0] * n, dtype="float64"),
            "run_id": df_bronze["run_id"],
            "pipeline_version": df_bronze["pipeline_version"],
            "execution_timestamp": df_bronze["execution_timestamp"],
            "source_version": df_bronze["source_version"],
        }
    )
    return df[COLUNAS_SILVER]


def carregar_silver_despesa(
    storage: Storage, run_id: str
) -> ResultadoCargaSilver | None:
    """Lê o Bronze do Senado e carrega `silver_despesa` (fonte='senado').

    Args:
        storage: Persistência Parquet do Bronze (injetável) — lê o
            diretório `senado/` inteiro (todas as partições).
        run_id: Identificador da execução (mesmo da Bronze, via XCom).

    Returns:
        `ResultadoCargaSilver`, ou `None` quando o Bronze da fonte está vazio.
    """
    df_bronze = storage.read_dir(DIRETORIO_BRONZE)
    if df_bronze.empty:
        logger.warning("silver_senado_sem_dados", run_id=run_id)
        return None

    df_silver = construir_silver(df_bronze)
    return carregar_tabela_silver(
        df_silver,
        "silver_despesa",
        run_id,
        chaves_dedup=["fonte", "cod_documento"],
        campos_criticos=["valor_liquido", "nome_fornecedor", "data_documento"],
    )