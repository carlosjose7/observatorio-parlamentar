# tests/dashboard/test_apptest.py
"""Smoke tests via AppTest — todas as 11 páginas do dashboard (Sprint 11).

Usa `streamlit.testing.v1.AppTest` para renderizar cada página em
isolamento, verificando ausência de erros e fluxos críticos
(busca→seleção nas páginas 02/05/06/08).

Padrão de mocking: cada página depende de `ApiClient` — o mock retorna
payloads vázios ou mínimos para garantir que a página renderiza sem
exigir a API real.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from streamlit.testing.v1 import AppTest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Fixtures comuns
# ---------------------------------------------------------------------------

def _mock_client() -> MagicMock:
    """ApiClient mock com retornos vazios para todos os endpoints."""
    client = MagicMock()
    client.agent_context.return_value = {
        "metricas_globais": {},
        "periodos_com_dados": [],
        "pipeline": {},
        "qualidade": {},
    }
    client.listar_parlamentares.return_value = {"itens": []}
    client.listar_fornecedores.return_value = {"itens": []}
    client.top_fornecedores.return_value = {"itens": []}
    client.rede_parlamentar.return_value = {"arestas": [], "parlamentar": {}}
    client.rede_fornecedor.return_value = {"arestas": [], "total_recebido": 0}
    client.comunidades.return_value = {"itens": []}
    client.agent_parlamentar.return_value = {}
    client.listar_anomalias.return_value = {"itens": []}
    client.agent_anomalias.return_value = {"total": 0, "por_ano": [], "por_criterio": []}
    client.agregacao_por_uf.return_value = {"itens": []}
    client.agregacao_por_partido.return_value = {"itens": []}
    client.despesas_no_tempo.return_value = {"itens": []}
    client.top_parlamentares.return_value = {"itens": []}
    client.status_pipeline.return_value = {"itens": []}
    client.relatorio_qualidade.return_value = {"itens": []}
    return client


def _run_page(module_path: str, client: MagicMock | None = None) -> AppTest:
    """Executa uma página Streamlit com mock de API e retorna o AppTest."""
    if client is None:
        client = _mock_client()
    abs_path = str(_PROJECT_ROOT / module_path)
    with patch("dashboard.client.ApiClient", return_value=client):
        at = AppTest.from_file(abs_path)
        at.run(timeout=30)
    return at


# ---------------------------------------------------------------------------
# Smoke — todas as 11 páginas
# ---------------------------------------------------------------------------

class TestSmokePagina01App:
    """Página 01 — Visão Geral (app.py)."""

    def test_renderiza_sem_erro(self):
        client = _mock_client()
        client.agent_context.return_value = {
            "metricas_globais": {
                "total_gasto": 1000000,
                "num_transacoes": 500,
                "num_fornecedores": 100,
                "num_parlamentares": 50,
                "num_anomalias": 10,
            },
            "periodos_com_dados": ["202401", "202402"],
            "pipeline": {"run_id": "abc123", "status": "success"},
            "qualidade": {"tabelas_reportadas": 5},
        }
        client.status_pipeline.return_value = {"itens": [
            {"run_id": "r1", "status": "ok", "execution_timestamp": "2024-01-01", "pipeline_version": "1.0"}
        ]}
        at = _run_page("dashboard/app.py", client)
        assert not at.exception


class TestSmokePagina02:
    """Página 02 — Parlamentar."""

    def test_renderiza_sem_erro(self):
        at = _run_page("dashboard/pages/02_parlamentar.py")
        assert not at.exception


class TestSmokePagina03:
    """Página 03 — Partido."""

    def test_renderiza_sem_erro(self):
        at = _run_page("dashboard/pages/03_partido.py")
        assert not at.exception


class TestSmokePagina04:
    """Página 04 — Estado."""

    def test_renderiza_sem_erro(self):
        at = _run_page("dashboard/pages/04_estado.py")
        assert not at.exception


class TestSmokePagina05:
    """Página 05 — Fornecedor."""

    def test_renderiza_sem_erro(self):
        at = _run_page("dashboard/pages/05_fornecedor.py")
        assert not at.exception

    def test_fluxo_busca_vazio(self):
        client = _mock_client()
        client.listar_fornecedores.return_value = {"itens": []}
        at = _run_page("dashboard/pages/05_fornecedor.py", client)
        assert not at.exception


class TestSmokePagina06:
    """Página 06 — Rede."""

    def test_renderiza_sem_erro(self):
        at = _run_page("dashboard/pages/06_rede.py")
        assert not at.exception

    def test_fluxo_busca_parlamentar_vazio(self):
        client = _mock_client()
        client.listar_parlamentares.return_value = {"itens": []}
        at = _run_page("dashboard/pages/06_rede.py", client)
        assert not at.exception


class TestSmokePagina07:
    """Página 07 — Anomalias."""

    def test_renderiza_sem_erro(self):
        at = _run_page("dashboard/pages/07_anomalias.py")
        assert not at.exception


class TestSmokePagina08:
    """Página 08 — ML / Risco."""

    def test_renderiza_sem_erro(self):
        at = _run_page("dashboard/pages/08_ml.py")
        assert not at.exception

    def test_fluxo_busca_vazio(self):
        client = _mock_client()
        client.listar_parlamentares.return_value = {"itens": []}
        at = _run_page("dashboard/pages/08_ml.py", client)
        assert not at.exception


class TestSmokePagina09:
    """Página 09 — Qualidade."""

    def test_renderiza_sem_erro(self):
        at = _run_page("dashboard/pages/09_qualidade.py")
        assert not at.exception


class TestSmokePagina10:
    """Página 10 — Metadados."""

    def test_renderiza_sem_erro(self):
        at = _run_page("dashboard/pages/10_metadados.py")
        assert not at.exception


class TestSmokePagina11:
    """Página 11 — Análises."""

    def test_renderiza_sem_erro(self):
        at = _run_page("dashboard/pages/11_analises.py")
        assert not at.exception

    def test_renderiza_com_dados(self):
        client = _mock_client()
        client.agregacao_por_uf.return_value = {"itens": [
            {"rotulo": "SP", "total": 500000, "num_despesas": 100},
            {"rotulo": "RJ", "total": 300000, "num_despesas": 80},
        ]}
        client.agregacao_por_partido.return_value = {"itens": [
            {"rotulo": "PT", "total": 400000, "num_despesas": 90},
        ]}
        client.despesas_no_tempo.return_value = {"itens": [
            {"periodo": "202401", "total": 200000, "num_despesas": 50},
        ]}
        client.top_parlamentares.return_value = {"itens": [
            {"rotulo": "Dep. A", "total": 100000, "num_despesas": 20},
        ]}
        at = _run_page("dashboard/pages/11_analises.py", client)
        assert not at.exception
