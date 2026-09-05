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
(`fonte`, id_parlamentar`, `data`), base do SCD2 em Gold.

Onda 2 (Sprint 15): backfill SOAP — filiações partidárias históricas
via Deputados.asmx (ADR-043). Lê o cache Parquet em
`bronze/camara/filiacoes/`, mergeia por deputado em timeline SCD2
ordenada e gera snapshots com `partido_uf_aproximado=False` (dado real).
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

DIRETORIO_FILIACOES = Path("camara/filiacoes")


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


def _carregar_cache_filiacoes(storage: Storage) -> pd.DataFrame:
    """Lê o cache Parquet de filiações SOAP (`bronze/camara/filiacoes/`).

    Returns:
        DataFrame com colunas: id_deputado, sigla_partido,
        data_filiacao, id_legislatura, uf, partido_uf_aproximado.
        Vazio se o cache não existir ou estiver vazio.
    """
    df = storage.read_dir(DIRETORIO_FILIACOES)
    if df.empty:
        logger.warning("cache_filiacoes_vazio")
        return df
    logger.info(
        "cache_filiacoes_carregado",
        linhas=len(df),
        deputados_unicos=df["id_deputado"].nunique()
        if "id_deputado" in df.columns
        else 0,
    )
    return df


def _gerar_backfill_scd2_camara(
    df_filiacoes: pd.DataFrame,
    df_bronze: pd.DataFrame,
    run_meta_source_version: str,
) -> pd.DataFrame:
    """Gera snapshots de backfill para filiações partidárias históricas (ADR-043).

    Diferente do Senado (que usa snapshots sintéticos com partido
    aproximado), a Câmara fornece dados REAIS via SOAP — cada filiação
    gera um snapshot com a data exata da mudança de partido.

    Args:
        df_filiacoes: DataFrame de filiações SOAP (cache Parquet).
        df_bronze: Snapshot Bronze dos deputados (para obter nome, UF, etc.).
        run_meta_source_version: source_version para os metadados.

    Returns:
        DataFrame com snapshots de backfill (mesmo schema de
        `construir_silver_parlamentar`) ou vazio.
    """
    if df_filiacoes.empty:
        return pd.DataFrame(columns=COLUNAS_SILVER_PARLAMENTAR)

    # Indexa o bronze por id_deputado para enriquecer os snapshots
    bronze_por_id: dict[int, dict] = {}
    if not df_bronze.empty and "id_deputado" in df_bronze.columns:
        for _, row in df_bronze.iterrows():
            bronze_por_id[int(row["id_deputado"])] = row.to_dict()

    rows_backfill: list[dict] = []

    for id_dep, grupo in df_filiacoes.groupby("id_deputado"):
        # Ordena por data de filiação (timeline cronológica)
        grupo = grupo.sort_values("data_filiacao")

        info_bronze = bronze_por_id.get(id_dep, {})
        nome = info_bronze.get("nome_eleitoral") or info_bronze.get(
            "nome_civil", ""
        )
        if not nome:
            # Fallback: tenta extrair do próprio grupo (se disponível)
            continue

        uf = grupo["uf"].iloc[0] if "uf" in grupo.columns and len(grupo) > 0 else None
        if not uf:
            uf = info_bronze.get("sigla_uf")

        # Metadados compartilhados para todas as linhas deste deputado
        run_id = info_bronze.get("run_id", "")
        pipeline_version = info_bronze.get("pipeline_version", "")
        execution_timestamp = info_bronze.get("execution_timestamp", "")

        for _, fil in grupo.iterrows():
            data_filiacao = fil["data_filiacao"]
            data_snapshot = pd.Timestamp(data_filiacao)

            # Deriva id_legislatura do calendário (ADR-024)
            try:
                data_date = data_snapshot.date()
                id_leg = legislatura_para_data(data_date) or 0
            except Exception:
                id_leg = 0

            rows_backfill.append(
                {
                    "fonte": "camara",
                    "id_parlamentar": int(id_dep),
                    "nome": nome,
                    "sigla_partido": fil.get("sigla_partido"),
                    "sigla_uf": uf,
                    "id_legislatura": id_leg,
                    "id_legislatura_fonte": int(
                        fil.get("id_legislatura", 0) or 0
                    ),
                    "situacao_bruta": info_bronze.get("situacao"),
                    "situacao_normalizada": normalizar_situacao(
                        "camara", info_bronze.get("situacao")
                    ),
                    "url_foto": info_bronze.get("url_foto"),
                    "partido_uf_aproximado": False,  # ADR-043 item 3
                    "data": data_snapshot,
                    "run_id": run_id,
                    "pipeline_version": pipeline_version,
                    "execution_timestamp": execution_timestamp,
                    "source_version": run_meta_source_version,
                }
            )

    if not rows_backfill:
        return pd.DataFrame(columns=COLUNAS_SILVER_PARLAMENTAR)

    df = pd.DataFrame(rows_backfill)

    # Dedup por chave composta: mesmo deputado + mesma data = mantém primeiro
    df = df.drop_duplicates(
        subset=["fonte", "id_parlamentar", "data"], keep="first"
    )

    logger.info(
        "backfill_scd2_camara_gerado",
        total_snapshots=len(df),
        deputados_unicos=df["id_parlamentar"].nunique(),
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

    Quando há filiações SOAP em cache (`bronze/camara/filiacoes/`),
    gera snapshots de backfill com dados reais (ADR-043, `partido_uf_aproximado=False`).

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

    df_atual = construir_silver_parlamentar(df_bronze)

    # Backfill SOAP (ADR-043) — filiações partidárias históricas
    df_filiacoes = _carregar_cache_filiacoes(storage)
    from datetime import UTC, datetime

    source_version = datetime.now(UTC).date().isoformat()
    df_backfill = _gerar_backfill_scd2_camara(
        df_filiacoes, df_bronze, source_version
    )

    if not df_backfill.empty:
        df_silver = pd.concat(
            [df_atual, df_backfill], ignore_index=True
        )[COLUNAS_SILVER_PARLAMENTAR]
    else:
        df_silver = df_atual

    return carregar_tabela_silver(
        df_silver,
        "silver_parlamentar",
        run_id,
        chaves_dedup=["fonte", "id_parlamentar", "data"],
        campos_criticos=["nome", "id_parlamentar"],
    )
