"""tests/api/test_rede_comunidades.py — endpoint `/rede/comunidades` (Onda 3).

Agrupa nós JÁ materializados na Gold (`network_nodes`, ADR-030) por
`comunidade_id`. A API não recalcula o particionamento — lê resultado.
Nomes resolvidos das dimensões (parlamentar vigente do SCD2 / fornecedor).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from pipeline.config import load_env_settings
from api.main import app


def test_comunidades_agrupam_nos_da_gold(_cliente):
    corpo = _cliente.get("/rede/comunidades").json()
    assert corpo["total"] == 2
    # ordem: periodo desc → 2023 (comunidade 7) antes de 2022 (comunidade 4)
    primeiro = corpo["itens"][0]
    assert primeiro["comunidade_id"] == 7
    assert primeiro["periodo"] == 2023
    assert primeiro["tamanho"] == 2
    nomes = {no["nome"] for no in primeiro["nos"]}
    assert nomes == {"MARIA DA SILVA", "Transportes Brasil Ltda"}
    segundo = corpo["itens"][1]
    assert segundo["comunidade_id"] == 4
    assert segundo["periodo"] == 2022
    assert segundo["tamanho"] == 1
    assert segundo["nos"][0]["tipo_no"] == "parlamentar"


def test_no_tem_metricas_materializadas(_cliente):
    corpo = _cliente.get("/rede/comunidades").json()
    comunidade_7 = corpo["itens"][0]
    parlamentar = next(no for no in comunidade_7["nos"] if no["tipo_no"] == "parlamentar")
    assert parlamentar["id_no"] == 1
    assert parlamentar["pagerank"] == 0.55
    assert parlamentar["degree_centrality"] == 3.0


def test_gold_indisponivel_503_comunidades(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "inexistente.duckdb"))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        resposta = client.get("/rede/comunidades")
    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Camada Gold indisponível"}