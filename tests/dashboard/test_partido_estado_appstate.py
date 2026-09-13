"""tests/dashboard/test_partido_estado_appstate.py — regression tests for duplicate widget keys.

Hotfix: ``03_partido.py`` and ``04_estado.py`` registered two widgets under
the same key (``partido_{partido}_ano`` / ``uf_{uf}_ano``) — the ``Ano``
selectbox and the ``Ano`` multiselect built inside ``filtro_periodo`` — which
raised ``StreamlitDuplicateElementKey`` whenever the monthly series was
non-empty. ``ruff``/``py_compile`` cannot catch key collisions; only a real
app run can, hence these ``AppTest`` regression tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_SERIE_ITENS = [
    {"periodo": "202401", "total": 50000.0},
    {"periodo": "202402", "total": 60000.0},
    {"periodo": "202501", "total": 70000.0},
]


def _mock_client_partido() -> MagicMock:
    """ApiClient mock with a non-empty monthly series for the Partido page."""
    client = MagicMock()
    client.agregacao_por_partido.return_value = {"itens": [
        {"rotulo": "PT", "total": 500000.0, "num_despesas": 100},
        {"rotulo": "PSOL", "total": 200000.0, "num_despesas": 50},
    ]}
    client.despesas_no_tempo.return_value = {"itens": list(_SERIE_ITENS)}
    client.top_parlamentares.return_value = {"itens": [
        {"rotulo": "Dep. A", "total": 100000.0, "sigla_uf": "SP", "num_despesas": 20},
        {"rotulo": "Dep. B", "total": 80000.0, "sigla_uf": "RJ", "num_despesas": 15},
    ]}
    client.listar_parlamentares.return_value = {"itens": [
        {"nome": "Dep. A", "sigla_uf": "SP", "situacao_normalizada": "Ativo"},
    ]}
    return client


def _mock_client_estado() -> MagicMock:
    """ApiClient mock with a non-empty monthly series for the Estado page."""
    client = MagicMock()
    client.agregacao_por_uf.return_value = {"itens": [
        {"rotulo": "SP", "total": 500000.0, "num_despesas": 100},
        {"rotulo": "RJ", "total": 300000.0, "num_despesas": 80},
    ]}
    client.despesas_no_tempo.return_value = {"itens": list(_SERIE_ITENS)}
    client.top_parlamentares.return_value = {"itens": [
        {"rotulo": "Dep. A", "total": 100000.0, "sigla_partido": "PT", "num_despesas": 20},
        {"rotulo": "Dep. C", "total": 90000.0, "sigla_partido": "PSOL", "num_despesas": 18},
    ]}
    client.listar_parlamentares.return_value = {"itens": [
        {"nome": "Dep. A", "sigla_partido": "PT", "situacao_normalizada": "Ativo"},
    ]}
    return client


def _run_page(module_path: str, client: MagicMock) -> AppTest:
    """Run a dashboard page with a mocked ApiClient and return the AppTest."""
    st.cache_data.clear()
    abs_path = str(_PROJECT_ROOT / module_path)
    with patch("dashboard.client.ApiClient", return_value=client):
        at = AppTest.from_file(abs_path)
        at.run(timeout=30)
    return at


class TestPartidoDuplicateKey:
    """Page 03 — Partido renders with a non-empty series and across reruns."""

    def test_serie_nao_vazia_sem_duplicate_key(self) -> None:
        """Non-empty monthly series renders with no unhandled exception."""
        at = _run_page("dashboard/pages/03_partido.py", _mock_client_partido())
        assert not at.exception
        # The series path really ran: filtro_periodo renders Ano + Mes.
        assert len(at.multiselect) >= 2

    def test_troca_partido_entre_reruns(self) -> None:
        """Switching partido across reruns keeps widget keys collision-free."""
        st.cache_data.clear()
        client = _mock_client_partido()
        abs_path = str(_PROJECT_ROOT / "dashboard/pages/03_partido.py")
        with patch("dashboard.client.ApiClient", return_value=client):
            at = AppTest.from_file(abs_path)
            at.run(timeout=30)
            assert not at.exception
            at.selectbox[0].set_value("PSOL")
            at.run(timeout=30)
            assert not at.exception


class TestEstadoDuplicateKey:
    """Page 04 — Estado renders with a non-empty series and across reruns."""

    def test_serie_nao_vazia_sem_duplicate_key(self) -> None:
        """Non-empty monthly series renders with no unhandled exception."""
        at = _run_page("dashboard/pages/04_estado.py", _mock_client_estado())
        assert not at.exception
        # The series path really ran: filtro_periodo renders Ano + Mes.
        assert len(at.multiselect) >= 2

    def test_troca_uf_entre_reruns(self) -> None:
        """Switching UF across reruns keeps widget keys collision-free."""
        st.cache_data.clear()
        client = _mock_client_estado()
        abs_path = str(_PROJECT_ROOT / "dashboard/pages/04_estado.py")
        with patch("dashboard.client.ApiClient", return_value=client):
            at = AppTest.from_file(abs_path)
            at.run(timeout=30)
            assert not at.exception
            at.selectbox[0].set_value("SP")
            at.run(timeout=30)
            assert not at.exception
