"""tests/api/test_pipeline.py — endpoint `/pipeline/status` (Onda 3).

Consome o controle de execuções da Gold (`pipeline_runs`, ADR-019) —
observadora passiva, mais recentes primeiro.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from pipeline.config import load_env_settings
from api.main import app


def test_status_lista_execucoes_recentes_primeiro(_cliente):
    corpo = _cliente.get("/pipeline/status").json()
    assert corpo["total"] == 3
    run_ids = [item["run_id"] for item in corpo["itens"]]
    assert run_ids == ["run-2026-01-10", "run-2026-01-05", "run-2025-12-01"]
    mais_recente = corpo["itens"][0]
    assert mais_recente["status"] == "success"
    assert mais_recente["pipeline_version"] == "0.1.0"
    assert mais_recente["fontes_com_erro"] is None
    assert mais_recente["watermark_camara"] == "2026-01-09"


def test_status_parcial_e_falha(_cliente):
    corpo = _cliente.get("/pipeline/status").json()
    parcial = corpo["itens"][1]
    assert parcial["status"] == "partial"
    assert parcial["fontes_com_erro"] == "camara"
    assert parcial["watermark_senado"] is None
    falha = corpo["itens"][2]
    assert falha["status"] == "failed"
    assert falha["fontes_com_erro"] == "senado,cgu_emenda"
    assert falha["pipeline_version"] == "0.0.9"


def test_limite_de_execucoes(_cliente):
    corpo = _cliente.get("/pipeline/status", params={"limite": 2}).json()
    assert corpo["total"] == 2
    assert [item["run_id"] for item in corpo["itens"]] == [
        "run-2026-01-10", "run-2026-01-05",
    ]


def test_gold_indisponivel_503_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "inexistente.duckdb"))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        resposta = client.get("/pipeline/status")
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Camada Gold indisponível"}