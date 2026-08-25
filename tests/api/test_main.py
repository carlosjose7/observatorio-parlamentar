"""tests/api/test_main.py — fronteira da documentação interativa da API.

`API_DOCS_ENABLED=false` (produção) remove `/docs`, `/redoc` e `/openapi.json`
— a API deixa de autodocumentar a superfície de ataque atrás do nginx.
Default é habilitado (dev/HML preservam a DX do Swagger).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app as app_padrao
from api.main import criar_app
from pipeline.config import load_env_settings


def test_docs_desabilitado_nao_expoe_openapi(monkeypatch) -> None:
    monkeypatch.setenv("API_DOCS_ENABLED", "false")
    load_env_settings.cache_clear()
    with TestClient(criar_app()) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_docs_habilitado_por_padrao() -> None:
    load_env_settings.cache_clear()
    with TestClient(app_padrao) as client:
        assert client.get("/openapi.json").status_code == 200
