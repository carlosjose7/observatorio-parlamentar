# tests/dashboard/test_client.py
"""Testes do cliente HTTP do dashboard (dashboard/client.py, Sprint 7).

Cobre o contrato de consumo da API (RF-05): cada método monta o caminho e
query params corretos; erros HTTP viram `ApiError` com a mensagem de
`detail`; falhas de rede viram `ApiIndisponivel`. Usa `httpx.MockTransport`
para não depender da API real.
"""

from __future__ import annotations

import httpx
import pytest

from dashboard.client import ApiClient, ApiError, ApiIndisponivel


def _cliente(handler) -> ApiClient:
    transport = httpx.MockTransport(handler)
    return ApiClient(base_url="http://api-teste", transport=transport)


def _ok(payload: dict, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


class TestRotas:
    def test_listar_parlamentares_monta_params(self):
        capturado = {}

        def handler(request):
            capturado["url"] = str(request.url)
            return httpx.Response(200, json={"pagina": 1, "limite": 20, "total": 0, "itens": []})

        client = _cliente(handler)
        client.listar_parlamentares(nome="ana", uf="SP", partido="PT", pagina=2, limite=50)

        url = capturado["url"]
        assert "/parlamentares" in url
        assert "nome=ana" in url
        assert "uf=SP" in url
        assert "partido=PT" in url
        assert "pagina=2" in url
        assert "limite=50" in url

    def test_gastos_parlamentar_com_ano(self):
        capturado = {}

        def handler(request):
            capturado["url"] = str(request.url)
            return httpx.Response(
                200, json={"parlamentar": {}, "pagina": 1, "limite": 100, "total": 0, "itens": []}
            )

        client = _cliente(handler)
        client.gastos_parlamentar(42, ano=2023)
        assert "/parlamentares/42/gastos" in capturado["url"]
        assert "ano=2023" in capturado["url"]

    def test_perfil_fornecedor(self):
        capturado = {}

        def handler(request):
            capturado["url"] = str(request.url)
            return httpx.Response(200, json={"id_fornecedor": 7})

        client = _cliente(handler)
        client.perfil_fornecedor("11222333000181")
        assert "/fornecedores/11222333000181" in capturado["url"]

    def test_parlamentares_fornecedor(self):
        capturado = {}

        def handler(request):
            capturado["url"] = str(request.url)
            return httpx.Response(200, json={"fornecedor": {}, "pagina": 1, "limite": 20, "total": 0, "itens": []})

        client = _cliente(handler)
        client.parlamentares_fornecedor("11222333000181")
        assert "/fornecedores/11222333000181/parlamentares" in capturado["url"]

    def test_listar_anomalias_threshold(self):
        capturado = {}

        def handler(request):
            capturado["url"] = str(request.url)
            return httpx.Response(200, json={"pagina": 1, "limite": 20, "total": 0, "itens": []})

        client = _cliente(handler)
        client.listar_anomalias(threshold=2.5)
        assert "/anomalias" in capturado["url"]
        assert "threshold=2.5" in capturado["url"]

    def test_relatorio_qualidade_com_tabela(self):
        capturado = {}

        def handler(request):
            capturado["url"] = str(request.url)
            return httpx.Response(200, json={"pagina": 1, "limite": 20, "total": 0, "itens": []})

        client = _cliente(handler)
        client.relatorio_qualidade(tabela="silver_despesa")
        assert "/qualidade/relatorio" in capturado["url"]
        assert "tabela=silver_despesa" in capturado["url"]

    def test_endpoints_simples(self):
        chamadas = []

        def handler(request):
            chamadas.append(str(request.url))
            return httpx.Response(200, json={})

        client = _cliente(handler)
        client.rede_parlamentar(9)
        client.comunidades()
        client.status_pipeline()
        client.agent_parlamentar(9)
        client.agent_fornecedor("11222333000181")
        client.agent_anomalias()
        client.agent_context()

        assert any("/parlamentares/9/rede" in c for c in chamadas)
        assert any("/rede/comunidades" in c for c in chamadas)
        assert any("/pipeline/status" in c for c in chamadas)
        assert any("/agent/parlamentar/9" in c for c in chamadas)
        assert any("/agent/fornecedor/11222333000181" in c for c in chamadas)
        assert any("/agent/anomalias" in c for c in chamadas)
        assert any("/agent/context" in c for c in chamadas)


class TestErros:
    def test_erro_http_levanta_api_error_com_detail(self):
        def handler(request):
            return httpx.Response(404, json={"detail": "Parlamentar 9 não encontrado"})

        client = _cliente(handler)
        with pytest.raises(ApiError) as exc:
            client.perfil_parlamentar(9)
        assert "404" in str(exc.value)
        assert "não encontrado" in str(exc.value)

    def test_falha_de_rede_levanta_api_indisponivel(self):
        def handler(request):
            raise httpx.ConnectError("connection refused")

        client = _cliente(handler)
        with pytest.raises(ApiIndisponivel):
            client.agent_context()

    def test_erro_sem_json_usa_texto_bruto(self):
        def handler(request):
            return httpx.Response(503, text="Camada Gold indisponível")

        client = _cliente(handler)
        with pytest.raises(ApiError) as exc:
            client.agent_context()
        assert "Gold indisponível" in str(exc.value)


class TestBaseUrl:
    def test_base_url_default_localhost(self, monkeypatch):
        monkeypatch.delenv("API_URL", raising=False)
        client = ApiClient()
        assert client.base_url == "http://localhost:8000"

    def test_base_url_da_env(self, monkeypatch):
        monkeypatch.setenv("API_URL", "http://api:8000")
        client = ApiClient()
        assert client.base_url == "http://api:8000"

    def test_base_url_explicita_prioriza(self, monkeypatch):
        monkeypatch.setenv("API_URL", "http://api:8000")
        client = ApiClient(base_url="http://outro:9000")
        assert client.base_url == "http://outro:9000"
