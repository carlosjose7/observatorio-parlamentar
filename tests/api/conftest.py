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

from pipeline.config import load_env_settings
from api.main import app


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
}


def sembrar_gold(caminho) -> None:
    """Cria o DuckDB Gold de teste com o grão dos fixtures Gold determinísticos."""
    con = duckdb.connect(str(caminho))
    for tabela in _DDL:
        con.execute(_DDL[tabela])

    p1_v2 = 100000000000 + 1 * 1000 + 2  # camara, id 1, versão 2
    p2_v1 = 200000000000 + 2 * 1000 + 1  # senado, id 2, versão 1
    con.executemany(
        "insert into dim_parlamentar values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (100000000000 + 1 * 1000 + 1, "camara", 1, "MARIA DA SILVA", "MARIA DA SILVA",
             "PSDB", "DF", "Ativo", 55, date(2015, 1, 1), date(2018, 1, 1), False),
            (p1_v2, "camara", 1, "MARIA DA SILVA", "MARIA DA SILVA",
             "PSDB", "DF", "Ativo", 57, date(2018, 1, 1), None, True),
            (p2_v1, "senado", 2, "ANA SOUZA", "ANA SOUZA",
             "PT", "SP", "Ativo", 57, date(2019, 2, 1), None, True),
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
        "insert into network_nodes values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "parlamentar", 2022, 0.30, 2.0, 4, "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
            (1, "parlamentar", 2023, 0.55, 3.0, 7, "run-test", "0.1.0", "2023-06-01T00:00:00", "s1"),
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