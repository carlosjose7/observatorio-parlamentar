"""pipeline/camara/transform.py — Bronze → Silver das despesas da Câmara (Trilha B).

Implementa o pré-requisito do ADR-023: cada fonte possui um `transform.py`
que lê o Parquet Bronze (storage), normaliza para o grão Silver canônico e
chama `carregar_tabela_silver` (pipeline/silver.py) — que aplica a dedup
independente (ADR-014) e o gate Pandera (ADR-013) antes de persistir.

Normalização usada (ADR-016):
- Data ISO 8601 da API → `data_documento` (`parse_date_multi_format`).
- CNPJ/CPF sanitizado e classificado por comprimento (`resolve_tipo_documento`, ADR-011).
- Valores monetários já são `float` na Bronze da Câmara — mantidos como estão.

A coluna `fonte` é `'camara'` (chave de negócio de `silver_despesa` é
`["fonte", "cod_documento"]`, ADR-023). O HMAC de CPF é aplicado na carga
Gold (dbt), não aqui — o CPF viaja em dígitos limpos até o Gold
(`CamaraSilverDespesa.cnpj_cpf_valor`, ADR-011).

Onda 2: snapshot de dados mestres dos deputados (ADR-020). O bronze de
`parlamento/` (um Parquet por dia de execução) é consolidado em
`silver_parlamentar` — Deduplicação colapsa snapshots idênticos e o gate
Pandera (`carregar_tabela_silver`) garante a chave de negócio
(`fonte`, `id_parlamentar`, `data`), base do SCD2 em Gold.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import structlog

from pipeline.contracts import resolve_tipo_documento
from pipeline.normalize import parse_date_multi_format
from pipeline.silver import (
    COLUNAS_SILVER_PARLAMENTAR,
    ResultadoCargaSilver,
    carregar_tabela_silver,
)
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

DIRETORIO_BRONZE = Path("camara")

DIRETORIO_PARLAMENTO = Path("parlamento/camara")


def construir_silver(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Mapeia o DataFrame Bronze da Câmara para o formato canônico Silver.

    Args:
        df_bronze: DataFrame com os registros brutos (leitura de `storage`),
            com metadados de carga achatados (records_to_dataframe).

    Returns:
        DataFrame com as colunas canônicas de `silver_despesa` (fonte='camara')
        ou DataFrame vazio com o schema fixo quando não há registros.
    """
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER)

    n = len(df_bronze)
    classificados = [
        resolve_tipo_documento(v) for v in df_bronze["cnpj_cpf_fornecedor"]
    ]
    cnpj_cpf_valor = [par[0] for par in classificados]
    tipo_documento = [par[1].value if par[1] else None for par in classificados]

    df = pd.DataFrame(
        {
            "fonte": ["camara"] * n,
            "ano": df_bronze["ano"].astype("int64"),
            "mes": df_bronze["mes"].astype("int64"),
            "cod_documento": df_bronze["cod_documento"].astype(str),
            "data_documento": pd.to_datetime(
                df_bronze["data_documento"].map(parse_date_multi_format)
            ),
            "tipo_despesa": df_bronze["tipo_despesa"],
            "cnpj_cpf_valor": cnpj_cpf_valor,
            "tipo_documento": tipo_documento,
            "nome_fornecedor": df_bronze["nome_fornecedor"],
            "valor_liquido": df_bronze["valor_liquido"].astype("float64"),
            "valor_glosa": df_bronze["valor_glosa"].astype("float64"),
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
    """Lê o Bronze da Câmara e carrega `silver_despesa` (fonte='camara').

    Args:
        storage: Persistência Parquet do Bronze (injetável) — lê o
            diretório `camara/` inteiro (todas as partições).
        run_id: Identificador da execução (mesmo da Bronze, via XCom).

    Returns:
        `ResultadoCargaSilver`, ou `None` quando o Bronze da fonte está vazio.
    """
    df_bronze = storage.read_dir(DIRETORIO_BRONZE)
    if df_bronze.empty:
        logger.warning("silver_camara_sem_dados", run_id=run_id)
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
    """Mapeia o snapshot Bronze de `parlamento/` para o grão Silver canônico.

    Em `nome` prefere o nome eleitoral (campanha) e recai no nome civil.
    A as-of date é `data_status` (a data de vigência de `ultimoStatus`
    informada pela API) — é ela que indexa o SCD2. Colunas que podem
    vir vazias no `ultimoStatus` (partido, UF, situação) seguem nullable.

    Args:
        df_bronze: DataFrame achatado dos snapshots (`records_to_dataframe`).

    Returns:
        DataFrame canônico de `silver_parlamentar` (fonte='camara') ou
        vazio com o schema fixo quando não há registros.
    """
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER_PARLAMENTAR)

    n = len(df_bronze)
    df = pd.DataFrame(
        {
            "fonte": ["camara"] * n,
            "id_parlamentar": df_bronze["id_deputado"].astype("int64"),
            "nome": df_bronze["nome_eleitoral"].fillna(df_bronze["nome_civil"]),
            "sigla_partido": df_bronze["sigla_partido"],
            "sigla_uf": df_bronze["sigla_uf"],
            "id_legislatura": df_bronze["id_legislatura"].astype("int64"),
            "situacao": df_bronze["situacao"],
            "data": pd.to_datetime(df_bronze["data_status"]),
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
    """Lê o snapshot Bronze e carrega `silver_parlamentar` (fonte='camara').

    Consolida todo o diretório `parlamento/` (todos os dias já ingeridos):
    a dedup independente do `carregar_tabela_silver` colapsa snapshots de
    meses iguais pela chave `(fonte, id_parlamentar, data)` e o gate
    Pandera isola registros com data inválida ou nome ausente.

    Args:
        storage: Persistência Parquet do Bronze (injetável).
        run_id: Identificador da execução (mesmo da Bronze, via XCom).

    Returns:
        `ResultadoCargaSilver`, ou `None` quando o Bronze da fonte está vazio.
    """
    df_bronze = storage.read_dir(DIRETORIO_PARLAMENTO)
    if df_bronze.empty:
        logger.warning("silver_parlamento_sem_dados", run_id=run_id)
        return None

    df_silver = construir_silver_parlamentar(df_bronze)
    return carregar_tabela_silver(
        df_silver,
        "silver_parlamentar",
        run_id,
        chaves_dedup=["fonte", "id_parlamentar", "data"],
        campos_criticos=["nome", "id_parlamentar"],
    )