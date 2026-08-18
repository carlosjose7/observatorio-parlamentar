"""tests/api/test_agent.py — endpoints agent-ready `/agent/*` (Onda 4, ADR-032).

Cobrem os 4 contratos aprovados: `/agent/parlamentar/{id}`, `/agent/
fornecedor/{cnpj_cpf_valor}`, `/agent/anomalias` (resumo agregado) e
`/agent/context` (retrato sistêmico). Verificam que o JSON é **semântico
agregado** (perfil + métricas §8 + risco + top) e não um espelho paginado.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from pipeline.config import load_env_settings


def test_agente_parlamentar_reune_perfil_metricas_risco(_cliente):
    corpo = _cliente.get("/agent/parlamentar/1").json()
    assert corpo["id_parlamentar"] == 1
    assert corpo["fonte"] == "camara"
    assert corpo["nome"] == "MARIA DA SILVA"
    assert corpo["sigla_partido"] == "PSDB"
    assert corpo["sigla_uf"] == "DF"
    assert corpo["periodo_vigente_desde"] == "2018-01-01"

    metricas = corpo["metricas"]
    assert metricas["total_gasto"] == 2500.5
    assert metricas["num_transacoes"] == 3
    assert metricas["num_fornecedores"] == 2
    assert metricas["valor_maximo"] == 1500.0
    assert metricas["hhi_periodo"] == 2023
    assert metricas["hhi_recente"] == pytest.approx(0.721918)

    risco = corpo["risco"]
    assert risco["periodo"] == 2023
    assert risco["supplier_concentration_score"] == 0.8
    assert risco["expense_anomaly_score"] == 0.9
    assert risco["risk_index"] == 0.52

    assert corpo["anomalias"]["num_despesas_anomalas"] == 2
    assert corpo["anomalias"]["proporcao"] == pytest.approx(2 / 3)

    top = corpo["top_fornecedores"]
    assert top[0]["id_fornecedor"] == 10
    assert top[0]["nome_fornecedor"] == "Transportes Brasil Ltda"
    assert top[0]["total_gasto"] == 2200.0
    assert top[0]["num_transacoes"] == 2


def test_agente_parlamentar_inexistente_404(_cliente):
    resposta = _cliente.get("/agent/parlamentar/999")
    assert resposta.status_code == 404
    assert resposta.json() == {"detail": "Parlamentar 999 não encontrado"}


def test_agente_fornecedor_cnpj_reune_perfil_e_top_parlamentares(_cliente):
    corpo = _cliente.get("/agent/fornecedor/11222333000181").json()
    assert corpo["id_fornecedor"] == 10
    assert corpo["cnpj_cpf_valor"] == "11222333000181"
    assert corpo["tipo_documento"] == "CNPJ"
    assert corpo["nome_fornecedor"] == "Transportes Brasil Ltda"

    metricas = corpo["metricas"]
    assert metricas["total_recebido"] == 3100.0
    assert metricas["num_transacoes"] == 3
    assert metricas["num_parlamentares"] == 2
    assert metricas["valor_maximo"] == 1500.0

    top = corpo["top_parlamentares"]
    assert top[0]["id_parlamentar"] == 1
    assert top[0]["nome"] == "MARIA DA SILVA"
    assert top[0]["total_gasto"] == 2200.0


def test_agente_fornecedor_cpf_cru_nao_casa_404(_cliente):
    resposta = _cliente.get("/agent/fornecedor/12345678900")
    assert resposta.status_code == 404


def test_agente_fornecedor_inexistente_404(_cliente):
    resposta = _cliente.get("/agent/fornecedor/00000000000000")
    assert resposta.status_code == 404


def test_agente_anomalias_resumo_agregado_nao_espelho(_cliente):
    corpo = _cliente.get("/agent/anomalias").json()
    assert corpo["total"] == 3
    assert corpo["por_ano"] == [
        {"ano": 2023, "quantidade": 2},
        {"ano": 2022, "quantidade": 1},
    ]
    assert corpo["por_criterio"] == [
        {"criterio": "zscore", "quantidade": 2},
        {"criterio": "isolation_forest", "quantidade": 2},
        {"criterio": "fornecedor_poucos_clientes", "quantidade": 1},
        {"criterio": "empresa_nova", "quantidade": 1},
    ]
    top = corpo["top_por_zscore"]
    assert top[0]["id_despesa"] == 1
    assert top[0]["nome_parlamentar"] == "MARIA DA SILVA"
    assert top[0]["zscore"] == 3.1
    assert top[1]["id_despesa"] == 4
    assert top[1]["nome_parlamentar"] == "ANA SOUZA"
    assert top[2]["zscore"] == 1.2


def test_agente_contexto_retrato_sistemico(_cliente):
    corpo = _cliente.get("/agent/context").json()
    globais = corpo["metricas_globais"]
    assert globais["total_gasto"] == 3400.5
    assert globais["num_transacoes"] == 4
    assert globais["num_fornecedores"] == 2
    assert globais["num_parlamentares"] == 2
    assert globais["num_anomalias"] == 3
    assert corpo["periodos_com_dados"] == [2022, 2023]

    qualidade = corpo["qualidade"]
    assert qualidade["run_id"] == "run-2026-01-10"
    assert qualidade["tabelas_reportadas"] == 2
    assert qualidade["total_registros"] == 1200
    assert qualidade["total_quarentena"] == 20

    pipeline = corpo["pipeline"]
    assert pipeline["run_id"] == "run-2026-01-10"
    assert pipeline["status"] == "success"
    assert pipeline["execution_timestamp"] == "2026-01-10T03:30:00"
    assert pipeline["versao_pipeline"] == "0.1.0"


def test_gold_indisponivel_503_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "inexistente.duckdb"))
    load_env_settings.cache_clear()
    with TestClient(app) as client:
        for caminho in [
            "/agent/context", "/agent/anomalias", "/agent/parlamentar/1",
            "/agent/fornecedor/11222333000181",
        ]:
            resposta = client.get(caminho)
            assert resposta.status_code == 503
            assert resposta.json() == {"detail": "Camada Gold indisponível"}
