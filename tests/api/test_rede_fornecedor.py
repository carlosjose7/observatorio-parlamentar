"""tests/api/test_rede_fornecedor.py — endpoint `/rede/fornecedores/{id}`.

A rede INVERSA da do parlamentar: arestas materializadas (`network_edges`,
ADR-030) de um fornecedor com nomes resolvidos pelas dimensões (parlamentar
vigente do SCD2). Seed do conftest: fornecedor 10 conecta-se a MARIA (2022:
700 + 2023: 1500) e ANA (2023: 900) — total 3100, 2 parlamentares.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from pipeline.config import load_env_settings


def test_rede_fornecedor_agrega_parlamentares(_cliente):
    corpo = _cliente.get("/rede/fornecedores/10").json()
    assert corpo["id_fornecedor"] == 10
    assert corpo["nome_fornecedor"] == "Transportes Brasil Ltda"
    assert corpo["num_parlamentares"] == 2
    assert float(corpo["total_recebido"]) == 3100.0

    por_chave = {
        (a["nome"], a["periodo"]): a for a in corpo["arestas"]
    }
    maria_2023 = por_chave[("MARIA DA SILVA", 2023)]
    assert float(maria_2023["valor_total"]) == 1500.0
    assert maria_2023["sigla_partido"] == "PSDB"
    assert maria_2023["sigla_uf"] == "DF"
    ana_2023 = por_chave[("ANA SOUZA", 2023)]
    assert float(ana_2023["valor_total"]) == 900.0
    assert ana_2023["sigla_partido"] == "PT"


def test_rede_fornecedor_inexistente_404(_cliente):
    resposta = _cliente.get("/rede/fornecedores/999")
    assert resposta.status_code == 404
    assert resposta.json() == {"detail": "Fornecedor 999 não encontrado"}


def test_rede_fornecedor_gold_indisponivel_503(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "inexistente.duckdb"))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        resposta = client.get("/rede/fornecedores/10")
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Camada Gold indisponível"}
