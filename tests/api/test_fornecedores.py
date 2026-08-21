"""tests/api/test_fornecedores.py — endpoints de fornecedores (Sprint 6, Onda 2).

Cobre: listagem paginada com filtros (nome/tipo_documento), perfil do
fornecedor com agregados de gasto (dimensão + `fact_despesa`), parlamentares
que gastaram no fornecedor (ordenação por total), 404 de fornecedor
inexistente, 422 de validação, e a regra de pseudonimização do CPF (ADR-011):
a busca por CPF cru não casa — o valor armazenado é o hash HMAC.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api.main import app
from pipeline.config import load_env_settings

_CNPJ = "11222333000181"


def _dinheiro(valor: float) -> Decimal:
    return Decimal(str(valor))


# ── GET /fornecedores ────────────────────────────────────────────


def test_listar_fornecedores(_cliente):
    corpo = _cliente.get("/fornecedores").json()
    assert corpo["total"] == 2
    nomes = [item["nome_fornecedor"] for item in corpo["itens"]]
    assert nomes == ["Ana Souza", "Transportes Brasil Ltda"]
    transporte = corpo["itens"][1]
    assert transporte["cnpj_cpf_valor"] == _CNPJ
    assert transporte["tipo_documento"] == "CNPJ"
    ana = corpo["itens"][0]
    assert ana["tipo_documento"] == "CPF"
    assert ana["cnpj_cpf_valor"] == "hmac-ficticio-cpf-ana"


def test_filtro_nome_fornecedor(_cliente):
    corpo = _cliente.get("/fornecedores", params={"nome": "transportes"}).json()
    assert corpo["total"] == 1
    assert corpo["itens"][0]["id_fornecedor"] == 10


def test_filtro_tipo_documento(_cliente):
    corpo = _cliente.get("/fornecedores", params={"tipo_documento": "CNPJ"}).json()
    assert corpo["total"] == 1
    assert corpo["itens"][0]["id_fornecedor"] == 10


def test_filtro_tipo_documento_invalido_422(_cliente):
    resposta = _cliente.get("/fornecedores", params={"tipo_documento": "XX"})
    assert resposta.status_code == 422


# ── GET /fornecedores/{cnpj_cpf_valor} ───────────────────────────


def test_perfil_fornecedor_com_agregados(_cliente):
    resposta = _cliente.get(f"/fornecedores/{_CNPJ}")
    assert resposta.status_code == 200
    perfil = resposta.json()
    assert perfil["id_fornecedor"] == 10
    assert perfil["nome_fornecedor"] == "Transportes Brasil Ltda"
    assert perfil["tipo_documento"] == "CNPJ"
    assert perfil["id_municipio"] is None
    # 3 despesas do fornecedor 10 (doc-1 1500,00 + doc-3 700,00 + doc-4 900,00)
    assert perfil["num_despesas"] == 3
    assert _dinheiro(perfil["valor_liquido_total"]) == Decimal("3100.00")


def test_perfil_cpf_pseudonimizado_nao_casa_por_numero_cru(_cliente):
    """ADR-011: o CPF armazenado é o HMAC — buscar pelo número cru dá 404 honesto."""
    resposta = _cliente.get("/fornecedores/12345678901")
    assert resposta.status_code == 404


def test_perfil_fornecedor_inexistente_404(_cliente):
    assert _cliente.get("/fornecedores/00000000000000").status_code == 404


# ── GET /fornecedores/{cnpj_cpf_valor}/parlamentares ─────────────


def test_parlamentares_do_fornecedor(_cliente):
    corpo = _cliente.get(f"/fornecedores/{_CNPJ}/parlamentares").json()
    assert corpo["fornecedor"]["id_fornecedor"] == 10
    assert corpo["fornecedor"]["nome_fornecedor"] == "Transportes Brasil Ltda"
    assert corpo["total"] == 2
    # ordenação por total_gasto desc: parlamentar 1 (1500+700=2200) > parlamentar 2 (900)
    assert [item["id_parlamentar"] for item in corpo["itens"]] == [1, 2]
    primeiro = corpo["itens"][0]
    assert primeiro["nome"] == "MARIA DA SILVA"
    assert primeiro["sigla_partido"] == "PSDB"
    assert primeiro["sigla_uf"] == "DF"
    assert primeiro["num_despesas"] == 2
    assert _dinheiro(primeiro["total_gasto"]) == Decimal("2200.00")


def test_parlamentares_do_fornecedor_inexistente_404(_cliente):
    assert _cliente.get("/fornecedores/00000000000000/parlamentares").status_code == 404


# ── Degradação — Gold indisponível ───────────────────────────────


def test_gold_indisponivel_503_fornecedores(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "inexistente.duckdb"))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        resposta = client.get("/fornecedores")
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Camada Gold indisponível"}


@pytest.mark.parametrize(
    ("atributo", "rota"),
    [
        ("obter_perfil_fornecedor", f"/fornecedores/{_CNPJ}"),
        ("listar_parlamentares_fornecedor", f"/fornecedores/{_CNPJ}/parlamentares"),
    ],
)
def test_rotas_individuais_gold_indisponivel_503(monkeypatch, atributo, rota):
    import api.routers.fornecedores as router_module
    from api.repo import GoldIndisponivel

    def indisponivel(*_args, **_kwargs):
        raise GoldIndisponivel("offline")

    monkeypatch.setattr(router_module, atributo, indisponivel)
    with TestClient(app) as client:
        assert client.get(rota).status_code == 503
