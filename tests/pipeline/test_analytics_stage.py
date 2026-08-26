"""tests/pipeline/test_analytics_stage.py — etapa `executar_etapa_analytics`.

Cobre a orquestração das ondas de ML (2→3→4) sobre um Gold mínimo semeado:
`ml_staging` sai populado (outliers/nós/arestas/risk_scores) e o caso sem
fatos promovidos encerra sem escrever (contrato da Fase 1, test_gold_risk).
A materialização final no Gold é responsabilidade do dbt — coberta por
test_gold_risk/test_gold_expense_outliers/test_gold_network.
"""

from __future__ import annotations

import datetime

import duckdb

from pipeline.analytics_stage import MODELS_ANALYTICS, executar_etapa_analytics


def _semear_gold(db) -> None:
    """Gold mínimo: fato + dim_data + supplier_concentration + staging vazio."""
    con = duckdb.connect(str(db))
    try:
        con.execute(
            "create table fact_despesa (id_despesa bigint, id_parlamentar bigint,"
            " surrogate_key bigint, id_fornecedor bigint, id_orgao bigint,"
            " id_unidade_gestora bigint, cod_tipo varchar, data_sk bigint,"
            " cod_documento varchar, valor_liquido decimal(18,2),"
            " valor_glosa decimal(18,2), run_id varchar, pipeline_version varchar,"
            " execution_timestamp varchar, source_version varchar)"
        )
        con.executemany(
            "insert into fact_despesa values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                # Parlamentar 7 com fornecedor 10 em valores distintos + 1 repetido
                (1, 7, 70001, 10, 1, None, "t1", 20260310, "d1", 1500.00, 0.0, "r", "p", "2026-08-26T00:00:00", "s"),
                (2, 7, 70001, 10, 1, None, "t2", 20260311, "d2", 80.50, 0.0, "r", "p", "2026-08-26T00:00:00", "s"),
                (3, 7, 70001, 12, 1, None, "t1", 20260312, "d3", 40.00, 0.0, "r", "p", "2026-08-26T00:00:00", "s"),
                # Sábado (dia não útil) com valor repetido — critérios 5/6
                (4, 7, 70001, 12, 1, None, "t3", 20260314, "d4", 40.00, 0.0, "r", "p", "2026-08-26T00:00:00", "s"),
                (5, 8, 80001, 13, 2, None, "t1", 20260401, "d5", 90.00, 0.0, "r", "p", "2026-08-26T00:00:00", "s"),
                # Fornecedor 10 compartilhado entre os dois — similaridade > 0
                (6, 8, 80001, 10, 1, None, "t1", 20260402, "d6", 60.00, 0.0, "r", "p", "2026-08-26T00:00:00", "s"),
            ],
        )
        con.execute(
            "create table dim_data (data_sk bigint, data date, ano integer,"
            " mes integer, dia integer, is_dia_util boolean)"
        )
        con.executemany(
            "insert into dim_data values (?,?,?,?,?,?)",
            [
                (20260310, datetime.date(2026, 3, 10), 2026, 3, 10, True),
                (20260311, datetime.date(2026, 3, 11), 2026, 3, 11, True),
                (20260312, datetime.date(2026, 3, 12), 2026, 3, 12, True),
                (20260314, datetime.date(2026, 3, 14), 2026, 3, 14, False),
                (20260401, datetime.date(2026, 4, 1), 2026, 4, 1, True),
            ],
        )
        con.execute(
            "create table supplier_concentration (ano bigint, id_parlamentar bigint,"
            " num_fornecedores bigint, total_valor decimal(18,2), hhi double)"
        )
        con.executemany(
            "insert into supplier_concentration values (?,?,?,?,?)",
            [
                (2026, 7, 2, 1660.5, 0.82),
                (2026, 8, 1, 90.0, 1.0),
            ],
        )
        con.execute("create schema if not exists ml_staging")
        con.execute(
            "create table ml_staging.expense_outliers (id_despesa bigint,"
            " id_parlamentar bigint, id_fornecedor bigint, data_sk bigint,"
            " valor_liquido double, zscore double, if_score double,"
            " criterio_zscore boolean, criterio_if boolean,"
            " criterio_fornecedor_poucos_clientes boolean,"
            " criterio_empresa_nova boolean, criterio_valores_identicos boolean,"
            " criterio_dia_sem_sessao boolean, num_criterios bigint,"
            " is_anomalia boolean, run_id varchar, pipeline_version varchar,"
            " execution_timestamp timestamp, source_version varchar)"
        )
    finally:
        con.close()


def _contagens(db) -> dict[str, int]:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return {
            tabela: con.execute(f"select count(*) from ml_staging.{tabela}").fetchone()[0]
            for tabela in ("expense_outliers", "network_edges", "network_nodes",
                           "politician_similarity", "risk_scores")
        }
    finally:
        con.close()


def test_etapa_popula_ml_staging(tmp_path):
    db = tmp_path / "gold.duckdb"
    _semear_gold(db)

    resumo = executar_etapa_analytics("run-stage-teste", db_path=str(db))

    assert resumo["num_fatos"] == 6
    contagens = _contagens(db)
    assert contagens["expense_outliers"] == 6
    assert resumo["raw_outliers"] == 6
    assert resumo["anomalias"] >= 1
    assert contagens["risk_scores"] == resumo["risk_scores"]
    for tabela in ("network_edges", "network_nodes", "politician_similarity"):
        assert contagens[tabela] > 0

    con = duckdb.connect(str(db), read_only=True)
    try:
        run_ids = {r[0] for r in con.execute(
            "select distinct run_id from ml_staging.expense_outliers"
        ).fetchall()}
        tipos = {r[0] for r in con.execute(
            "select distinct tipo_no from ml_staging.network_nodes"
        ).fetchall()}
    finally:
        con.close()
    assert run_ids == {"run-stage-teste"}
    assert tipos == {"parlamentar", "fornecedor"}


def test_etapa_sem_fatos_nao_escreve(tmp_path):
    db = tmp_path / "gold_vazio.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute(
            "create table fact_despesa (id_despesa bigint, valor_liquido decimal(18,2),"
            " valor_glosa decimal(18,2))"
        )
    finally:
        con.close()

    resumo = executar_etapa_analytics("run-vazio", db_path=str(db))

    assert resumo == {"num_fatos": 0}


def test_models_analytics_sao_os_cinco_do_staging():
    assert set(MODELS_ANALYTICS) == {
        "expense_outliers",
        "network_edges",
        "network_nodes",
        "politician_similarity",
        "risk_scores",
    }
