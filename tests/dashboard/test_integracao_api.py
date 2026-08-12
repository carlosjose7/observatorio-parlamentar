# tests/dashboard/test_integracao_api.py
"""E2E real do dashboard — Streamlit(client) → HTTP real → FastAPI → Gold.

Gate 5 (auditoria Sprint 7): comprova o fluxo ponta-a-ponta SEM mock algum.
Sobe a FastAPI real com `uvicorn` num subprocesso (socket TCP de verdade)
apontando para um DuckDB Gold semeado (`tests/api/conftest.py::sembrar_gold`)
e conecta o `ApiClient` do dashboard via HTTP real (`http://localhost:<porta>`).
A única coisa "semeada" é o Gold — nenhuma resposta HTTP é simulada.

Nota: `sembrar_gold` vive em `tests/api/conftest.py` (pytest injeta conftest
por diretório, não por import). Carregamos a função via `importlib`.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

_CONFTEST_API = _RAIZ / "tests" / "api" / "conftest.py"


def _carregar_sembrar_gold():
    """Importa `sembrar_gold` de tests/api/conftest.py via importlib."""
    spec = importlib.util.spec_from_file_location("conftest_api", _CONFTEST_API)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.sembrar_gold


_sembrar_gold = _carregar_sembrar_gold()


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def _api_real(tmp_path):
    """Sobe a FastAPI real (uvicorn) sobre um DuckDB Gold semeado.

    Yields o `ApiClient` do dashboard conectado via HTTP real. O servidor é
    encerrado ao final do teste.
    """
    db_path = tmp_path / f"gold_{uuid.uuid4().hex[:8]}.duckdb"
    _sembrar_gold(db_path)

    porta = _porta_livre()
    env = {
        **os.environ,
        "DUCKDB_DATABASE_PATH": str(db_path),
        "PYTHONIOENCODING": "utf-8",
    }
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "api.main:app",
            "--host", "127.0.0.1",
            "--port", str(porta),
            "--log-level", "warning",
        ],
        cwd=_RAIZ,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    base_url = f"http://127.0.0.1:{porta}"
    # Aguarda a API subir (até ~15s).
    for _ in range(75):
        try:
            with httpx.Client(timeout=2) as c:
                if c.get(f"{base_url}/health", timeout=2).status_code == 200:
                    break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.terminate()
        proc.wait(timeout=10)
        pytest.fail("API real não subiu em tempo hábil")

    try:
        yield ApiClient(base_url=base_url)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


from dashboard.client import ApiClient, ApiError  # noqa: E402


class TestFluxoReal:
    def test_parlamentares_chegam_do_gold(self, _api_real):
        payload = _api_real.listar_parlamentares(limite=20)
        assert payload["total"] >= 1
        assert "itens" in payload
        assert payload["itens"][0]["nome"]

    def test_perfil_e_gastos_de_parlamentar(self, _api_real):
        perfil = _api_real.perfil_parlamentar(1)
        assert perfil["id_parlamentar"] == 1
        gastos = _api_real.gastos_parlamentar(1)
        assert gastos["total"] >= 1
        # Decimal pode serializar como number ou string — aceita ambos.
        assert float(gastos["itens"][0]["valor_liquido"]) > 0

    def test_agente_parlamentar_com_risco(self, _api_real):
        agente = _api_real.agent_parlamentar(1)
        assert agente["id_parlamentar"] == 1
        assert agente["metricas"]["num_transacoes"] >= 1
        assert agente["risco"]["risk_index"] == pytest.approx(0.52, abs=1e-3)

    def test_contexto_global(self, _api_real):
        contexto = _api_real.agent_context()
        assert contexto["metricas_globais"]["num_transacoes"] >= 1
        assert 2023 in contexto["periodos_com_dados"]

    def test_fornecedor_e_parlamentares(self, _api_real):
        perfil = _api_real.perfil_fornecedor("11222333000181")
        assert perfil["nome_fornecedor"] == "Transportes Brasil Ltda"
        parl = _api_real.parlamentares_fornecedor("11222333000181")
        assert parl["total"] >= 1

    def test_anomalias_e_qualidade(self, _api_real):
        anomalias = _api_real.listar_anomalias()
        assert anomalias["total"] >= 1
        qualidade = _api_real.relatorio_qualidade()
        assert qualidade["total"] >= 1

    def test_404_vira_api_error_amigavel(self, _api_real):
        with pytest.raises(ApiError):
            _api_real.perfil_parlamentar(99999)

    def test_comunidades_respeitam_limite_nos(self, _api_real):
        payload = _api_real.comunidades(limite_nos=50)
        for comunidade in payload["itens"]:
            assert len(comunidade["nos"]) <= 50
