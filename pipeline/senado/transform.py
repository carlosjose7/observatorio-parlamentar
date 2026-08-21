"""pipeline/senado/transform.py — Bronze → Silver do Senado (Trilha B, ADR-023).

Duas cargas Silver a partir do Bronze do Senado:

1. Despesas CEAPS → `silver_despesa` (fonte='senado'): lê o Parquet Bronze,
   normaliza para o grão canônico e delega a carga ao `carregar_tabela_silver`.
2. Dados mestres de senadores (Onda 2, ADR-020) → `silver_parlamentar`
   (fonte='senado'), mesmo contrato da Câmara; o snapshot de
   `parlamento/senado/` alimenta o SCD2 de `dim_parlamentar`.

Diferenças de fonte (ADR-016):
- Datas em DD/MM/AAAA e valores em string pt-BR (`parse_decimal_ptbr`).
- Não existe glosa — `valor_glosa` é fixado em 0.0.
- `fonte='senado'`; chave de negócio `["fonte", "cod_documento"]`.

O CPF é pseudonimizado na própria Silver (ADR-033), via HMAC-SHA256
(`pipeline.pseudonymize`) — aqui apenas a digitação limpa
(`clean_document_number`) + classificação (ADR-011) + hash do CPF.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import structlog

from pipeline.contracts import resolve_tipo_documento
from pipeline.normalize import parse_date_multi_format, parse_decimal_ptbr
from pipeline.parlamento import legislatura_para_data, normalizar_situacao
from pipeline.pseudonymize import pseudonymize_cpf_column
from pipeline.silver import (
    COLUNAS_SILVER_PARLAMENTAR,
    ResultadoCargaSilver,
    carregar_tabela_silver,
)
from pipeline.storage import Storage

logger = structlog.get_logger()

COLUNAS_SILVER = [
    "fonte",
    "id_parlamentar",
    "nome_parlamentar",
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

DIRETORIO_PARLAMENTO = Path("parlamento/senado")


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
    tipos_documento = [par[1] for par in classificados]
    cnpj_cpf_valor = pseudonymize_cpf_column(
        (par[0] for par in classificados),
        (t.value if t else None for t in tipos_documento),
    )
    tipo_documento = [t.value if t else None for t in tipos_documento]

    df = pd.DataFrame(
        {
            "fonte": ["senado"] * n,
            "id_parlamentar": pd.Series([None] * n, dtype="object"),
            "nome_parlamentar": df_bronze["senador"],
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


def construir_silver_parlamentar(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Mapeia o snapshot Bronze de `parlamento/senado/` para o grão canônico.

    Mesmo contrato de `silver_parlamentar` da Câmara (ADR-020), com
    `fonte='senado'`: em `nome` prefere o nome parlamentar (urna) e recai no
    completo. **ADR-024**: `id_legislatura` é derivada do calendário a partir
    de `data` (a API do Senado mede a legislatura do *mandato* — semântica
    distinta da Câmara); o bruto vai para `id_legislatura_fonte`.
    `situacao_bruta` (ex: Titular) e `situacao_normalizada` (de-para
    versionado). `data` = `data_status` (as-of do SCD2).

    Args:
        df_bronze: DataFrame achatado dos snapshots (`records_to_dataframe`).

    Returns:
        DataFrame canônico de `silver_parlamentar` (fonte='senado') ou vazio
        com o schema fixo quando não há registros.
    """
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER_PARLAMENTAR)

    n = len(df_bronze)
    data = pd.to_datetime(df_bronze["data_status"], errors="coerce")
    id_legislatura = pd.Series(
        [
            (legislatura_para_data(ts.date()) or 0) if pd.notna(ts) else 0
            for ts in data
        ],
        dtype="int64",
    )

    df = pd.DataFrame(
        {
            "fonte": ["senado"] * n,
            "id_parlamentar": df_bronze["id_senador"].astype("int64"),
            "nome": df_bronze["nome_parlamentar"].fillna(df_bronze["nome_completo"]),
            "sigla_partido": df_bronze["sigla_partido"],
            "sigla_uf": df_bronze["sigla_uf"],
            "id_legislatura": id_legislatura,
            "id_legislatura_fonte": df_bronze["id_legislatura"].astype("Int64"),
            "situacao_bruta": df_bronze["situacao"],
            "situacao_normalizada": df_bronze["situacao"].map(
                lambda v: normalizar_situacao("senado", v)
            ),
            "data": data,
            "run_id": df_bronze["run_id"],
            "pipeline_version": df_bronze["pipeline_version"],
            "execution_timestamp": df_bronze["execution_timestamp"],
            "source_version": df_bronze["source_version"],
        }
    )
    return df[COLUNAS_SILVER_PARLAMENTAR]


def carregar_silver_parlamentar(
    storage: Storage, run_id: str
) -> ResultadoCargaSilver | None:
    """Lê o snapshot Bronze e carrega `silver_parlamentar` (fonte='senado').

    Consolida todo o diretório `parlamento/senado/` (todos os dias já
    ingeridos): a dedup independente colapsa snapshots idênticos pela chave
    `(fonte, id_parlamentar, data)` e o gate Pandera das cargas, junto com o
    da Câmara, mantém a dimensão parlamentar completa (ADR-020).

    Args:
        storage: Persistência Parquet do Bronze (injetável).
        run_id: Identificador da execução (mesmo da Bronze, via XCom).

    Returns:
        `ResultadoCargaSilver`, ou `None` quando o Bronze da fonte está vazio.
    """
    df_bronze = storage.read_dir(DIRETORIO_PARLAMENTO)
    if df_bronze.empty:
        logger.warning("silver_parlamento_senado_sem_dados", run_id=run_id)
        return None

    df_silver = construir_silver_parlamentar(df_bronze)
    return carregar_tabela_silver(
        df_silver,
        "silver_parlamentar",
        run_id,
        chaves_dedup=["fonte", "id_parlamentar", "data"],
        campos_criticos=["nome", "id_parlamentar"],
    )
