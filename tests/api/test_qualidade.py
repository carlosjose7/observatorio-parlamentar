"""tests/api/test_qualidade.py — endpoint `/qualidade/relatorio` (Onda 3).

Expõe o Data Quality Report da Gold (`data_quality_report`, ADR-031 — a API
não lê a Silver; a promoção via model dbt colocou o relatório atrás da
fronteira do ADR-026). `regras_violadas` sai desserializada como lista.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from pipeline.config import load_env_settings


def test_relatorio_lista_execucoes_recentes_primeiro(_cliente):
    corpo = _cliente.get("/qualidade/relatorio").json()
    assert corpo["total"] == 3
    # execution_timestamp desc → run-2026-01-10 (2 linhas) antes de run-2025-12-01
    run_ids = [item["run_id"] for item in corpo["itens"]]
    assert run_ids == [
        "run-2026-01-10", "run-2026-01-10", "run-2025-12-01",
    ]
    despesa = corpo["itens"][0]
    assert despesa["tabela"] == "silver_despesa"
    assert despesa["total_registros"] == 1000
    assert despesa["registros_validos"] == 990
    assert despesa["registros_quarentena"] == 10
    assert despesa["registros_deduplicados"] == 5
    assert despesa["regras_violadas"] == ["fk_nao_resolvida", "coluna_x_nula"]
    assert despesa["percentual_nulos_criticos"] == 0.05
    assert despesa["execution_timestamp"] is not None


def test_regras_violadas_vazias_vir_a_lista(_cliente):
    itens = _cliente.get("/qualidade/relatorio").json()["itens"]
    parlamentar = next(i for i in itens if i["tabela"] == "silver_parlamentar")
    assert parlamentar["regras_violadas"] == []


def test_filtro_por_tabela(_cliente):
    corpo = _cliente.get("/qualidade/relatorio", params={"tabela": "silver_despesa"}).json()
    assert corpo["total"] == 2
    assert {item["tabela"] for item in corpo["itens"]} == {"silver_despesa"}


def test_paginacao_qualidade(_cliente):
    corpo = _cliente.get("/qualidade/relatorio", params={"pagina": 2, "limite": 2}).json()
    assert corpo["pagina"] == 2
    assert corpo["total"] == 3
    assert [item["run_id"] for item in corpo["itens"]] == ["run-2025-12-01"]


def test_gold_indisponivel_503_qualidade(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "inexistente.duckdb"))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        resposta = client.get("/qualidade/relatorio")
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Camada Gold indisponível"}
