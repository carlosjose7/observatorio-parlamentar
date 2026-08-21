"""tests/api/test_parlamentares.py — endpoints de parlamentares (Sprint 6).

Onda 1: lista paginada com filtros (nome/uf/partido), SCD2 (só versão vigente
aparece), gastos com dimensões resolvidas (fornecedor/categoria/dim_data),
404/422/503. Onda 2: perfil completo do parlamentar e rede materializada do
Gold (nós/arestas da Sprint 5 — sem recalcular análise).

O DuckDB determinístico é semeado por `tests/api/_fixtures.py` (schema real
do Gold) + TestClient, mantendo o padrão de reprodutibilidade do repo — o selo
de contrato via dbt vive em `tests/integration/test_api_gold_contrato.py`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api.main import app
from pipeline.config import load_env_settings


def _dinheiro(valor: float) -> Decimal:
    return Decimal(str(valor))


# ── Smoke — `/` e `/health` não regridem (scaffold original) ─────


def test_health(_cliente):
    resposta = _cliente.get("/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "healthy"}


def test_root(_cliente):
    resposta = _cliente.get("/")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["version"] == "0.1.0"
    assert "Observatório Parlamentar" in corpo["message"]


# ── GET /parlamentares ───────────────────────────────────────────


def test_listar_apenas_versao_vigente(_cliente):
    corpo = _cliente.get("/parlamentares").json()
    assert corpo["pagina"] == 1
    assert corpo["limite"] == 20
    assert corpo["total"] == 2
    assert [item["id_parlamentar"] for item in corpo["itens"]] == [2, 1]
    primeiro = corpo["itens"][0]
    assert primeiro["nome"] == "ANA SOUZA"
    assert primeiro["sigla_partido"] == "PT"
    assert primeiro["sigla_uf"] == "SP"
    assert primeiro["fonte"] == "senado"


def test_filtro_uf(_cliente):
    corpo = _cliente.get("/parlamentares", params={"uf": "DF"}).json()
    assert corpo["total"] == 1
    assert corpo["itens"][0]["id_parlamentar"] == 1


def test_filtro_partido(_cliente):
    corpo = _cliente.get("/parlamentares", params={"partido": "PT"}).json()
    assert corpo["total"] == 1
    assert corpo["itens"][0]["id_parlamentar"] == 2


def test_filtro_nome_parcial_case_accent_insensitive(_cliente):
    corpo = _cliente.get("/parlamentares", params={"nome": "maria"}).json()
    assert corpo["total"] == 1
    assert corpo["itens"][0]["id_parlamentar"] == 1


def test_paginacao(_cliente):
    pagina_1 = _cliente.get("/parlamentares", params={"limite": 1, "pagina": 1}).json()
    assert pagina_1["total"] == 2
    assert [item["id_parlamentar"] for item in pagina_1["itens"]] == [2]

    pagina_2 = _cliente.get("/parlamentares", params={"limite": 1, "pagina": 2}).json()
    assert [item["id_parlamentar"] for item in pagina_2["itens"]] == [1]


# ── GET /parlamentares/{id}/gastos ───────────────────────────────


def test_gastos_com_dimensions_resolvidas(_cliente):
    corpo = _cliente.get("/parlamentares/1/gastos").json()
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


def test_gastos_filtro_ano(_cliente):
    corpo = _cliente.get("/parlamentares/1/gastos", params={"ano": 2023}).json()
    assert corpo["total"] == 2
    assert {item["id_despesa"] for item in corpo["itens"]} == {1, 2}
    corpo_2022 = _cliente.get("/parlamentares/1/gastos", params={"ano": 2022}).json()
    assert corpo_2022["total"] == 1
    assert corpo_2022["itens"][0]["id_despesa"] == 3


def test_gastos_parlamentar_inexistente_404(_cliente):
    resposta = _cliente.get("/parlamentares/999/gastos")
    assert resposta.status_code == 404


def test_gastos_sem_registros_total_zero(_cliente):
    corpo = _cliente.get("/parlamentares/2/gastos", params={"ano": 2022}).json()
    assert corpo["parlamentar"]["id_parlamentar"] == 2
    assert corpo["total"] == 0
    assert corpo["itens"] == []


# ── GET /parlamentares/{id} — perfil (Onda 2) ────────────────────


def test_perfil_versao_vigente(_cliente):
    resposta = _cliente.get("/parlamentares/1")
    assert resposta.status_code == 200
    perfil = resposta.json()
    assert perfil["id_parlamentar"] == 1
    assert perfil["nome"] == "MARIA DA SILVA"
    assert perfil["nome_normalizado"] == "MARIA DA SILVA"
    assert perfil["sigla_partido"] == "PSDB"
    assert perfil["sigla_uf"] == "DF"
    assert perfil["situacao_normalizada"] == "Ativo"
    assert perfil["fonte"] == "camara"
    assert perfil["id_legislatura"] == 57
    assert perfil["effective_date"] == "2018-01-01"
    assert perfil["end_date"] is None
    assert perfil["is_current"] is True
    assert perfil["surrogate_key"] == 100000001002


def test_perfil_inexistente_404(_cliente):
    assert _cliente.get("/parlamentares/999").status_code == 404


# ── GET /parlamentares/{id}/rede — rede materializada (Onda 2) ───


def test_rede_consulta_gold_materializado(_cliente):
    """Nós/arestas vêm das tabelas da Gold (Sprint 5), sem recálculo."""
    resposta = _cliente.get("/parlamentares/1/rede")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["parlamentar"]["id_parlamentar"] == 1
    # nós por período, ordenados ASC
    assert [no["periodo"] for no in corpo["nos"]] == [2022, 2023]
    no_2023 = corpo["nos"][1]
    assert no_2023["pagerank"] == 0.55
    assert no_2023["degree_centrality"] == 3.0
    assert no_2023["comunidade_id"] == 7
    # arestas: periodo DESC, valor DESC; periodo 2023 → valor desc (10 antes de 11)
    assert [(a["id_fornecedor"], a["periodo"]) for a in corpo["arestas"]] == [(10, 2023), (11, 2023), (10, 2022)]
    assert corpo["arestas"][0]["nome_fornecedor"] == "Transportes Brasil Ltda"
    assert corpo["arestas"][0]["valor_total"] == 1500.0


def test_rede_parlamentar_sem_nos_vetor_vazio(_cliente):
    """Sem registros de rede materializados → 200 honesto com listas vazias."""
    corpo = _cliente.get("/parlamentares/2/rede").json()
    assert corpo["parlamentar"]["id_parlamentar"] == 2
    assert corpo["nos"] == []
    # parlamentar 2 tem aresta com fornecedor 10 em 2023 → arestas NÃO vazias
    assert [(a["id_fornecedor"], a["periodo"]) for a in corpo["arestas"]] == [(10, 2023)]


def test_rede_parlamentar_inexistente_404(_cliente):
    assert _cliente.get("/parlamentares/999/rede").status_code == 404


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
def test_validacao_query_params(_cliente, query):
    resposta = _cliente.get("/parlamentares/1/gastos", params=query)
    assert resposta.status_code == 422


# ── Degradação — Gold indisponível ───────────────────────────────


def test_gold_indisponivel_503(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "inexistente.duckdb"))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        resposta = client.get("/parlamentares")
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Camada Gold indisponível"}


@pytest.mark.parametrize(
    ("atributo", "rota"),
    [
        ("listar_gastos", "/parlamentares/1/gastos"),
        ("obter_perfil_parlamentar", "/parlamentares/1"),
        ("obter_rede_parlamentar", "/parlamentares/1/rede"),
    ],
)
def test_rotas_individuais_gold_indisponivel_503(monkeypatch, atributo, rota):
    """Cada leitura individual traduz a indisponibilidade do repositório."""
    import api.routers.parlamentares as router_module
    from api.repo import GoldIndisponivel

    def indisponivel(*_args, **_kwargs):
        raise GoldIndisponivel("offline")

    monkeypatch.setattr(router_module, atributo, indisponivel)
    with TestClient(app) as client:
        assert client.get(rota).status_code == 503
