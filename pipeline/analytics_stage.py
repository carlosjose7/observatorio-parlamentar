"""pipeline/analytics_stage.py — etapa de ML/rede entre Silver e Gold (ADR-026).

Orquestra, na ordem de dependência, as três cargas que populam `ml_staging`
— schema de escrita EXCLUSIVA por Python (Opção A do ADR-026):

  1. Onda 2: `executar_carga_outliers` → `ml_staging.expense_outliers`
  2. Onda 3: `executar_carga_ml_rede`  → `ml_staging.network_*` +
     `politician_similarity`
  3. Onda 4: `executar_carga_ml_risco` → `ml_staging.risk_scores` (consome
     os raws das ondas 2/3 lidos de volta, mais a Gold pura-SQL
     `supplier_concentration`)

O consumo do Gold materializado (`fact_despesa`, `dim_data`,
`supplier_concentration`) é somente LEITURA; a escrita fica restrita a
`ml_staging` — mesma fronteira do ADR-026. Depois desta etapa, o dbt
materializa os models analytics do Gold (build com `--select` dos cinco
models que leem `source('ml_staging', ...)`).

Chamadores: task `executar_analytics` do DAG (`pipeline/dags/pipeline_dag.py`)
e `scripts/run_e2e_local.py`.
"""

from __future__ import annotations

from pathlib import Path

import structlog

logger = structlog.get_logger()

#: Models Gold que leem `source('ml_staging', ...)` (`models/analytics/*.sql`) —
#: fronteira exata entre o build core e o build analytics do dbt.
MODELS_ANALYTICS = (
    "expense_outliers",
    "network_edges",
    "network_nodes",
    "politician_similarity",
    "risk_scores",
)


def resolver_caminho_db(db_path: str | None) -> str:
    """Resolve o DuckDB alvo: argumento → env → config, ancorado na raiz."""
    if db_path:
        return db_path
    from pipeline.config import REPO_ROOT, get_env

    bruto = get_env().duckdb_database_path
    caminho = Path(bruto)
    if not caminho.is_absolute():
        caminho = REPO_ROOT / caminho
    return str(caminho)


def _carregar_insumos(caminho: str) -> tuple:
    """Lê fatos, dimensão de datas e concentração do Gold (read-only).

    `valor_liquido`/`valor_glosa` são convertidos para DOUBLE porque a coluna
    física do fato é DECIMAL(18,2) — o pandas traria `decimal.Decimal`
    (object dtype), que quebra a aritmética de z-score/Isolation Forest.
    `dim_data` e `supplier_concentration` são opcionais: ausentes, os
    critérios 4–6 não acusam e o score de concentração fica sem raw — mesma
    degradação segura de quando chegam vazios às cargas.
    """
    import duckdb
    import pandas as pd

    con = duckdb.connect(caminho, read_only=True)

    def _opcional(sql: str) -> pd.DataFrame:
        try:
            return con.execute(sql).fetchdf()
        except duckdb.CatalogException:
            logger.warning("analytics_insumo_ausente", tabela=sql.split()[-1])
            return pd.DataFrame()

    try:
        fatos = con.execute(
            """
            select * replace (
                cast(valor_liquido as double) as valor_liquido,
                cast(valor_glosa as double) as valor_glosa
            )
            from fact_despesa
            """
        ).fetchdf()
        dim_data = _opcional(
            "select data_sk, data, ano, mes, is_dia_util from dim_data"
        )
        concentracao = _opcional(
            "select ano, id_parlamentar, hhi from supplier_concentration"
        )
    finally:
        con.close()
    return fatos, dim_data, concentracao


def _ler_raws_staging(caminho: str) -> tuple:
    """Relê os raws das ondas 2/3 gravados em `ml_staging` (insumo da Onda 4)."""
    import duckdb

    con = duckdb.connect(caminho, read_only=True)
    try:
        outliers = con.execute(
            "select id_despesa, id_parlamentar, id_fornecedor, data_sk,"
            " valor_liquido, is_anomalia from ml_staging.expense_outliers"
        ).fetchdf()
        nos = con.execute(
            "select id_no, tipo_no, periodo, pagerank, degree_centrality,"
            " comunidade_id from ml_staging.network_nodes"
        ).fetchdf()
    finally:
        con.close()
    return outliers, nos


def executar_etapa_analytics(
    run_id: str,
    *,
    db_path: str | None = None,
    source_version: str = "",
) -> dict[str, int]:
    """Popula `ml_staging` completo (ondas 2→3→4) sobre o Gold atual.

    Sem fatos promovidos, encerra sem escrever — o dbt subsequente materializa
    os models analytics vazios (contrato da Fase 1 em test_gold_risk).

    Returns:
        Resumo de contagens (`num_fatos`, `raw_outliers`, `anomalias`,
        `nos_rede`, `risk_scores`) para log/XCom.
    """
    caminho = resolver_caminho_db(db_path)
    fatos, dim_data, concentracao = _carregar_insumos(caminho)
    resumo: dict[str, int] = {"num_fatos": len(fatos)}
    if fatos.empty:
        logger.warning("analytics_sem_fatos", run_id=run_id, caminho=caminho)
        return resumo

    from analytics.anomalies.anomalies import executar_carga_outliers
    from analytics.network.network import executar_carga_ml_rede

    executar_carga_outliers(
        fatos,
        run_id,
        dim_data=dim_data,
        db_path=caminho,
        source_version=source_version,
    )
    executar_carga_ml_rede(
        fatos,
        run_id,
        db_path=caminho,
        source_version=source_version,
    )

    outliers, nos = _ler_raws_staging(caminho)

    from analytics.parliamentarians.risk import executar_carga_ml_risco

    num_risco = executar_carga_ml_risco(
        concentracao,
        fatos,
        outliers,
        nos,
        run_id=run_id,
        db_path=caminho,
        source_version=source_version,
    )

    resumo.update(
        {
            "raw_outliers": len(outliers),
            "anomalias": int(outliers["is_anomalia"].sum()) if not outliers.empty else 0,
            "nos_rede": len(nos),
            "risk_scores": num_risco,
        }
    )
    logger.info("etapa_analytics_concluida", run_id=run_id, **resumo)
    return resumo


def alertar_analytics_vazio(
    models: tuple[str, ...] = MODELS_ANALYTICS,
    *,
    db_path: str | None = None,
) -> None:
    """Guardrail: warning estruturado quando há fatos mas Gold analítico vazio.

    Sintoma do fio solto que motivou o ADR-035 (staging nunca populado):
    build "bem-sucedido" com tabelas analíticas vazias. Não falha a execução
    — anomalias legítimas de zero existem — apenas sinaliza para os logs.
    """
    import duckdb

    caminho = resolver_caminho_db(db_path)
    con = duckdb.connect(caminho, read_only=True)
    try:
        num_fatos = con.execute("select count(*) from fact_despesa").fetchone()[0]
        if not num_fatos:
            return
        for tabela in models:
            try:
                n = con.execute(f"select count(*) from main.{tabela}").fetchone()[0]
            except duckdb.Error:
                n = 0
            if n == 0:
                logger.warning(
                    "gold_analytics_vazio", tabela=tabela, num_fatos=num_fatos
                )
    finally:
        con.close()
