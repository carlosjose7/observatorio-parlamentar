"""tests/api/test_anomalias.py — endpoint `/anomalias` (Sprint 6, Onda 3).

Filtro `threshold` = piso sobre `zscore` do conjunto já sinalizado na Gold
(decisão de Onda 3, §11): não reabre o `-0.1` do Isolation Forest nem os
`>= 2` critérios do ADR-002. Negativo não-numérico → 422, mesmo contrato de
erro dos filtros de fornecedores (Onda 2).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from pipeline.config import load_env_settings


def test_listar_anomalias_sem_filtro(_cliente):
    corpo = _cliente.get("/anomalias").json()
    assert corpo["total"] == 3
    assert corpo["threshold"] is None
    # ordenação por zscore desc
    assert [item["id_despesa"] for item in corpo["itens"]] == [1, 4, 3]
    primeira = corpo["itens"][0]
    assert primeira["id_parlamentar"] == 1
    assert primeira["id_fornecedor"] == 10
    assert primeira["zscore"] == 3.1
    assert primeira["if_score"] == -0.2
    assert primeira["criterio_zscore"] is True
    assert primeira["criterio_if"] is True
    assert primeira["num_criterios"] == 2
    assert float(primeira["valor_liquido"]) == 1500.0
    assert primeira["data_sk"] == 20230310


def test_threshold_segmenta_por_zscore(_cliente):
    corpo = _cliente.get("/anomalias", params={"threshold": 2.5}).json()
    assert corpo["threshold"] == 2.5
    assert corpo["total"] == 2
    assert [item["id_despesa"] for item in corpo["itens"]] == [1, 4]
    terceira = corpo["itens"][1]
    assert terceira["id_despesa"] == 4
    assert terceira["zscore"] == 2.6
    # só uma acima do corte mais alto
    assert _cliente.get("/anomalias", params={"threshold": 3.0}).json()["total"] == 1


def test_threshold_nenhum_filtra_tudo(_cliente):
    assert _cliente.get("/anomalias", params={"threshold": 0}).json()["total"] == 3


def test_threshold_negativo_422(_cliente):
    assert _cliente.get("/anomalias", params={"threshold": -1}).status_code == 422


def test_threshold_nao_numerico_422(_cliente):
    assert _cliente.get("/anomalias", params={"threshold": "abc"}).status_code == 422


def test_paginacao_anomalias(_cliente):
    corpo = _cliente.get("/anomalias", params={"pagina": 2, "limite": 2}).json()
    assert corpo["pagina"] == 2
    assert corpo["total"] == 3
    assert [item["id_despesa"] for item in corpo["itens"]] == [3]


def test_gold_indisponivel_503_anomalias(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "inexistente.duckdb"))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        resposta = client.get("/anomalias")
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Camada Gold indisponível"}
