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

    Pseudonimização (ADR-033): o CPF (11 dígitos) é substituído pelo digest
    HMAC-SHA256 (`pipeline.pseudonymize`) na saída — a Silver guarda o hash,
    nunca os dígitos. O CNPJ permanece em texto claro (ADR-011).
    """
    if df_bronze.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER)

    n = len(df_bronze)
    classificados = [
        resolve_tipo_documento(v) for v in df_bronze["cnpj_cpf_fornecedor"]
    ]
    tipos_documento = [par[1] for par in classificados]
    cnpj_cpf_valor = pseudonymize_cpf_column(
        (par[0] for par in classificados),
        (t.value if t else None for t in tipos_documento),
    )
    tipo_documento = [t.value if t else None for t in tipos_documento]

    df = pd.DataFrame(
        {
            "fonte": ["camara"] * n,
            "id_parlamentar": df_bronze["id_deputado"].astype("int64"),
            "nome_parlamentar": pd.Series([None] * n, dtype="object"),
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
    informada pela API) — é ela que indexa o SCD2. **ADR-024**: `id_legislatura`
    é derivada do calendário legislativo a partir de `data` (não copiada da
    API, que mede semântica própria por Casa); o valor bruto da fonte é
    preservado em `id_legislatura_fonte` (auditoria). `situacao_bruta`
    preserva o original e `situacao_normalizada` aplica o de-para versionado
    (pipeline.parlamento) — a taxonomia comum alimenta o SCD2 sem depender do
    vocabulário de cada API.

    Data fora do calendário conhecido → `id_legislatura = 0` (cai no gate
    `gt(0)` da Silver, quarentena — ADR-024).
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
            "fonte": ["camara"] * n,
            "id_parlamentar": df_bronze["id_deputado"].astype("int64"),
            "nome": df_bronze["nome_eleitoral"].fillna(df_bronze["nome_civil"]),
            "sigla_partido": df_bronze["sigla_partido"],
            "sigla_uf": df_bronze["sigla_uf"],
            "id_legislatura": id_legislatura,
            "id_legislatura_fonte": df_bronze["id_legislatura"].astype("Int64"),
            "situacao_bruta": df_bronze["situacao"],
            "situacao_normalizada": df_bronze["situacao"].map(
                lambda v: normalizar_situacao("camara", v)
            ),
            "url_foto": df_bronze.get("url_foto"),
            "partido_uf_aproximado": False,
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
