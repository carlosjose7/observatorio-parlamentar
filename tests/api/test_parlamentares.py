"""tests/api/test_parlamentares.py — endpoints da Sprint 6 (Onda 1).

Espelha o padrão determinístico dos testes Gold: um DuckDB temporário com o
schema REAL emitido pelos modelos dbt do Gold é semeado num fixture e apontado
à API via `DUCKDB_DATABASE_PATH` (a fronteira de leitura da API, ADR-026).
A API nunca toca bronze/silver/analytics.

Cobre: listagem paginada com filtros (nome/uf/partido), SCD2 (só versão
vigente aparece), histórico de gastos com dimensões resolvidas (fornecedor/
categoria/dim_data), filtro por ano, 404 de parlamentar inexistente, 422 de
validação de query, e 503 quando a camada Gold está indisponível.
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

# ── Seed determinístico — schema dos modelos dbt do Gold ─────────


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
}


def _sembrar_gold(caminho) -> None:
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
    con.close()


@pytest.fixture()
def _client(tmp_path, monkeypatch):
    db_path = tmp_path / "gold.duckdb"
    _sembrar_gold(db_path)
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(db_path))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        yield client


def _dinheiro(valor: float) -> Decimal:
    return Decimal(str(valor))


# ── Smoke — `/` e `/health` não regridem (scaffold original) ─────


def test_health(_client):
    resposta = _client.get("/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "healthy"}


def test_root(_client):
    resposta = _client.get("/")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["version"] == "0.1.0"
    assert "Observatório Parlamentar" in corpo["message"]


# ── GET /parlamentares ───────────────────────────────────────────


def test_listar_apenas_versao_vigente(_client):
    corpo = _client.get("/parlamentares").json()
    assert corpo["pagina"] == 1
    assert corpo["limite"] == 20
    assert corpo["total"] == 2
    assert [item["id_parlamentar"] for item in corpo["itens"]] == [2, 1]
    primeiro = corpo["itens"][0]
    assert primeiro["nome"] == "ANA SOUZA"
    assert primeiro["sigla_partido"] == "PT"
    assert primeiro["sigla_uf"] == "SP"
    assert primeiro["fonte"] == "senado"


def test_filtro_uf(_client):
    corpo = _client.get("/parlamentares", params={"uf": "DF"}).json()
    assert corpo["total"] == 1
    assert corpo["itens"][0]["id_parlamentar"] == 1


def test_filtro_partido(_client):
    corpo = _client.get("/parlamentares", params={"partido": "PT"}).json()
    assert corpo["total"] == 1
    assert corpo["itens"][0]["id_parlamentar"] == 2


def test_filtro_nome_parcial_case_accent_insensitive(_client):
    corpo = _client.get("/parlamentares", params={"nome": "maria"}).json()
    assert corpo["total"] == 1
    assert corpo["itens"][0]["id_parlamentar"] == 1


def test_paginacao(_client):
    pagina_1 = _client.get("/parlamentares", params={"limite": 1, "pagina": 1}).json()
    assert pagina_1["total"] == 2
    assert [item["id_parlamentar"] for item in pagina_1["itens"]] == [2]

    pagina_2 = _client.get("/parlamentares", params={"limite": 1, "pagina": 2}).json()
    assert [item["id_parlamentar"] for item in pagina_2["itens"]] == [1]


# ── GET /parlamentares/{id}/gastos ───────────────────────────────


def test_gastos_com_dimensions_resolvidas(_client):
    corpo = _client.get("/parlamentares/1/gastos").json()
    assert corpo["parlamentar"]["id_parlamentar"] == 1
    assert corpo["parlamentar"]["nome"] == "MARIA DA SILVA"
    assert corpo["parlamentar"]["situacao_normalizada"] == "Ativo"
    assert corpo["total"] == 3
    # ordenado por data desc (via dim_data)
    datas = [item["data"] for item in corpo["itens"]]
    assert datas == ["2023-05-01", "2023-03-10", "2022-11-20"]
    primeiro = corpo["itens"][0]
    assert primeiro["tipo_despesa"] == "COMBUSTIVEL"
    assert primeiro["nome_fornecedor"] == "Ana Souza"
    assert primeiro["tipo_documento"] == "CPF"
    assert _dinheiro(primeiro["valor_liquido"]) == Decimal("300.50")
    assert _dinheiro(primeiro["valor_glosa"]) == Decimal("0.00")


def test_gastos_filtro_ano(_client):
    corpo = _client.get("/parlamentares/1/gastos", params={"ano": 2023}).json()
    assert corpo["total"] == 2
    assert {item["id_despesa"] for item in corpo["itens"]} == {1, 2}
    corpo_2022 = _client.get("/parlamentares/1/gastos", params={"ano": 2022}).json()
    assert corpo_2022["total"] == 1
    assert corpo_2022["itens"][0]["id_despesa"] == 3


def test_gastos_parlamentar_inexistente_404(_client):
    resposta = _client.get("/parlamentares/999/gastos")
    assert resposta.status_code == 404


def test_gastos_sem_registros_total_zero(_client):
    corpo = _client.get("/parlamentares/2/gastos", params={"ano": 2022}).json()
    assert corpo["parlamentar"]["id_parlamentar"] == 2
    assert corpo["total"] == 0
    assert corpo["itens"] == []


# ── Validação de query params ────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        {"limite": 0},
        {"limite": 101},
        {"pagina": 0},
        {"ano": 2014},
    ],
)
def test_validacao_query_params(_client, query):
    resposta = _client.get("/parlamentares/1/gastos", params=query)
    assert resposta.status_code == 422


# ── Degradação — Gold indisponível ───────────────────────────────


def test_gold_indisponivel_503(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "inexistente.duckdb"))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        resposta = client.get("/parlamentares")
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Camada Gold indisponível"}