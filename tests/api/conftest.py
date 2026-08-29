"""tests/api/conftest.py — DuckDB Gold determinístico para os testes da API.

Espelha o schema REAL emitido pelos modelos dbt do Gold (o selo de contrato
pipeline→Gold→API de `tests/integration/test_api_gold_contrato.py` valida o
mesmo schema via dbt; aqui ele é montado por seed para os testes de unidade
da API). Fixtures (`_cliente`) ficam aqui — pytest expõe fixtures de conftest
a todos os testes do diretório; `sembrar_gold` também é importável pelos
arquivos de teste.

Inclui as tabelas de rede (`network_nodes`/`network_edges`) — a Onda 2 lê os
resultados materializados da Sprint 5, sem recalcular nada.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

import duckdb
import pytest
from fastapi.testclient import TestClient

from api.main import app
from pipeline.config import load_env_settings


def _cod_tipo(descricao: str) -> str:
    return hashlib.md5(descricao.upper().encode("utf-8")).hexdigest()[:12]


_DDL = {
    "dim_parlamentar": """
        create table dim_parlamentar (
            surrogate_key bigint,
            fonte varchar,
            id_parlamentar bigint,
            nome varchar,
            nome_normalizado varchar,
            sigla_partido varchar,
            sigla_uf varchar,
            situacao_normalizada varchar,
            url_foto varchar,
            id_legislatura bigint,
            effective_date date,
            end_date date,
            is_current boolean
        )
    """,
    "dim_fornecedor": """
        create table dim_fornecedor (
            id_fornecedor bigint,
            cnpj_cpf_valor varchar,
            tipo_documento varchar,
            nome_fornecedor varchar,
            id_municipio bigint
        )
    """,
    "dim_categoria_despesa": """
        create table dim_categoria_despesa (
            cod_tipo varchar,
            descricao varchar
        )
    """,
    "dim_data": """
        create table dim_data (
            data_sk bigint,
            data date,
            ano integer,
            mes integer,
            dia integer,
            is_dia_util boolean
        )
    """,
    "fact_despesa": """
        create table fact_despesa (
            id_despesa bigint,
            id_parlamentar bigint,
            surrogate_key bigint,
            id_fornecedor bigint,
            id_orgao bigint,
            id_unidade_gestora bigint,
            cod_tipo varchar,
            data_sk bigint,
            cod_documento varchar,
            valor_liquido decimal(18, 2),
            valor_glosa decimal(18, 2),
            run_id varchar,
            pipeline_version varchar,
            execution_timestamp varchar,
            source_version varchar
        )
    """,
    "network_nodes": """
        create table network_nodes (
            id_no bigint,
            tipo_no varchar,
            periodo bigint,
            pagerank double,
            degree_centrality double,
            comunidade_id bigint,
            run_id varchar,
            pipeline_version varchar,
            execution_timestamp varchar,
            source_version varchar
        )
    """,
    "network_edges": """
        create table network_edges (
            id_parlamentar bigint,
            id_fornecedor bigint,
            periodo bigint,
            valor_total double,
            run_id varchar,
            pipeline_version varchar,
            execution_timestamp varchar,
            source_version varchar
        )
    """,
    "expense_outliers": """
        create table expense_outliers (
            id_despesa bigint,
            id_parlamentar bigint,
            id_fornecedor bigint,
            data_sk bigint,
            valor_liquido decimal(18, 2),
            zscore double,
            if_score double,
            criterio_zscore boolean,
            criterio_if boolean,
            criterio_fornecedor_poucos_clientes boolean,
            criterio_empresa_nova boolean,
            criterio_valores_identicos boolean,
            criterio_dia_sem_sessao boolean,
            num_criterios bigint,
            run_id varchar,
            pipeline_version varchar,
            execution_timestamp varchar,
            source_version varchar
        )
    """,
    "data_quality_report": """
        create table data_quality_report (
            run_id varchar,
            tabela varchar,
            total_registros bigint,
            registros_validos bigint,
            registros_quarentena bigint,
            registros_deduplicados bigint,
            regras_violadas varchar,
            percentual_nulos_criticos double,
            execution_timestamp timestamp
        )
    """,
    "pipeline_runs": """
        create table pipeline_runs (
            run_id varchar,
            pipeline_version varchar,
            execution_timestamp timestamp,
            status varchar,
            fontes_com_erro varchar[],
            watermark_camara varchar,
            watermark_senado varchar,
            watermark_cgu_emenda varchar,
            watermark_cgu_cartao varchar
        )
    """,
    "supplier_concentration": """
        create table supplier_concentration (
            ano bigint,
            id_parlamentar bigint,
            num_fornecedores bigint,
            total_valor decimal(18, 2),
            hhi double
        )
    """,
    "risk_scores": """
        create table risk_scores (
            periodo bigint,
            id_parlamentar bigint,
            supplier_concentration_score double,
            political_exposure_score double,
            supplier_dependency_score double,
            expense_anomaly_score double,
            network_influence_score double,
            risk_index double,
            run_id varchar,
            pipeline_version varchar,
            execution_timestamp varchar,
            source_version varchar
        )
    """,
}


def sembrar_gold(caminho) -> None:
    """Cria o DuckDB Gold de teste com o grão dos fixtures Gold determinísticos."""
    con = duckdb.connect(str(caminho))
    for tabela in _DDL:
        con.execute(_DDL[tabela])

    p1_v2 = 100000000000 + 1 * 1000 + 2  # camara, id 1, versão 2
    p2_v1 = 200000000000 + 2 * 1000 + 1  # senado, id 2, versão 1
    con.executemany(
        "insert into dim_parlamentar values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (100000000000 + 1 * 1000 + 1, "camara", 1, "MARIA DA SILVA", "MARIA DA SILVA",
             "PSDB", "DF", "Ativo", None, 55, date(2015, 1, 1), date(2018, 1, 1), False),
            (p1_v2, "camara", 1, "MARIA DA SILVA", "MARIA DA SILVA",
             "PSDB", "DF", "Ativo", "https://example.com/foto1.jpg", 57, date(2018, 1, 1), None, True),
            (p2_v1, "senado", 2, "ANA SOUZA", "ANA SOUZA",
             "PT", "SP", "Ativo", None, 57, date(2019, 2, 1), None, True),
        ],
    )
    con.executemany(
        "insert into dim_fornecedor values (?, ?, ?, ?, ?)",
        [
            (10, "11222333000181", "CNPJ", "Transportes Brasil Ltda", None),
            (11, "hmac-ficticio-cpf-ana", "CPF", "Ana Souza", None),
        ],
    )
    con.executemany(
        "insert into dim_categoria_despesa values (?, ?)",
        [
            (_cod_tipo("PASSAGEM AEREA"), "PASSAGEM AEREA"),
            (_cod_tipo("COMBUSTIVEL"), "COMBUSTIVEL"),
        ],
    )
    con.executemany(
        "insert into dim_data values (?, ?, ?, ?, ?, ?)",
        [
            (20230310, date(2023, 3, 10), 2023, 3, 10, True),
            (20230501, date(2023, 5, 1), 2023, 5, 1, True),
            (20221120, date(2022, 11, 20), 2022, 11, 20, False),
        ],
    )
    con.executemany(
        "insert into fact_despesa values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 1, p1_v2, 10, 1, None, _cod_tipo("PASSAGEM AEREA"), 20230310, "doc-1",
             Decimal("1500.00"), Decimal("0.00"), "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
            (2, 1, p1_v2, 11, 1, None, _cod_tipo("COMBUSTIVEL"), 20230501, "doc-2",
             Decimal("300.50"), Decimal("0.00"), "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
            (3, 1, p1_v2, 10, 1, None, _cod_tipo("PASSAGEM AEREA"), 20221120, "doc-3",
             Decimal("700.00"), Decimal("0.00"), "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
            (4, 2, p2_v1, 10, 2, None, _cod_tipo("PASSAGEM AEREA"), 20230310, "doc-4",
             Decimal("900.00"), Decimal("0.00"), "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
        ],
    )
    con.executemany(
        "insert into network_edges values (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 10, 2023, 1500.0, "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
            (1, 11, 2023, 300.5, "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
            (1, 10, 2022, 700.0, "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
            (2, 10, 2023, 900.0, "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
        ],
    )
    con.executemany(
        "insert into network_nodes values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "parlamentar", 2022, 0.30, 2.0, 4, "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
            (1, "parlamentar", 2023, 0.55, 3.0, 7, "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
            (10, "fornecedor", 2023, 0.20, 2.0, 7, "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
        ],
    )
    con.executemany(
        "insert into expense_outliers values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 1, 10, 20230310, Decimal("1500.00"), 3.10, -0.20, True, True,
             False, False, False, False, 2, "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
            (3, 1, 10, 20221120, Decimal("700.00"), 1.20, -0.30, False, True,
             True, False, False, False, 2, "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
            (4, 2, 10, 20230310, Decimal("900.00"), 2.60, -0.10, True, False,
             False, True, False, False, 2, "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
        ],
    )
    con.executemany(
        "insert into data_quality_report values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("run-2026-01-10", "silver_despesa", 1000, 990, 10, 5,
             '["fk_nao_resolvida", "coluna_x_nula"]', 0.05, "2026-01-10 03:30:00"),
            ("run-2026-01-10", "silver_parlamentar", 200, 190, 10, 0,
             "[]", 0.02, "2026-01-10 03:30:00"),
            ("run-2025-12-01", "silver_despesa", 950, 940, 10, 2,
             '["valor_negativo"]', 0.03, "2025-12-01 01:00:00"),
        ],
    )
    con.executemany(
        "insert into pipeline_runs values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("run-2026-01-10", "0.1.0", "2026-01-10 03:30:00", "success", None,
             "2026-01-09", "2026-01-10", "2026-01-09", "2026-01-10"),
            ("run-2026-01-05", "0.1.0", "2026-01-05 12:00:00", "partial", ["camara"],
             "2026-01-04", None, None, None),
            ("run-2025-12-01", "0.0.9", "2025-12-01 01:00:00", "failed", ["senado", "cgu_emenda"],
             "2025-11-30", None, None, None),
        ],
    )
    con.executemany(
        "insert into supplier_concentration values (?, ?, ?, ?, ?)",
        [
            (2022, 1, 1, Decimal("700.00"), 1.0),
            (2023, 1, 2, Decimal("1800.50"), 0.721918),
            (2023, 2, 1, Decimal("900.00"), 1.0),
        ],
    )
    con.executemany(
        "insert into risk_scores values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (2023, 1, 0.8, 0.2, 0.4, 0.9, 0.6, 0.52, "run-test", "0.1.0",
             "2023-06-01T00:00:00", "s1"),
            (2022, 1, 0.8, 0.2, 0.4, 0.2, 0.3, 0.41, "run-test", "0.1.0",
             "2023-06-01T00:00:00", "s1"),
            (2023, 2, 0.5, 0.7, 0.1, 0.4, 0.8, 0.5, "run-test", "0.1.0",
             "2023-06-01T00:00:00", "s1"),
        ],
    )
    con.close()


@pytest.fixture()
def _cliente(tmp_path, monkeypatch):
    """TestClient apontando para o DuckDB Gold determinístico semeado."""
    db_path = tmp_path / "gold.duckdb"
    sembrar_gold(db_path)
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(db_path))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        yield client
