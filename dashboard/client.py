"""dashboard/client.py — cliente HTTP da API REST para o dashboard (Sprint 7).

Camada única de acesso a dados do dashboard (RF-05, ADR-026): todas as
páginas Streamlit consultam a API REST via este cliente — o dashboard
NUNCA abre o DuckDB diretamente. A base URL vem de `config/dashboard.yaml`
(ADR-008): variável de ambiente `API_URL` (docker-compose injeta
`http://api:8000`; em dev local `http://localhost:8000`; atrás do nginx o
prefixo externo é `/api/`).

Padrão de falha: chamadas a uma API indisponível não derrubam a página —
os métodos retornam `None` para o estado "indisponível", e a camada de
apresentação exibe estado de erro amigável (UX). Erros HTTP com body JSON
(`{"detail": ...}`) são propagados como `ApiError` com a mensagem.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from pipeline.config import get_dashboard

PASTA_RAIZ_API = ""  # sem prefixo — a URL base já aponta para a API


class ApiError(RuntimeError):
    """Erro de negócio retornado pela API (ex: 404, 422, 503)."""


class ApiIndisponivel(RuntimeError):
    """API inacessível (rede/erro de transporte) — dashboard offline."""


class ApiClient:
    """Cliente HTTP para os endpoints da API do Observatório Parlamentar.

    Os métodos retornam o payload JSON (dict) dos endpoints paginados e
    agregados. Para falhas de rede, levantam `ApiIndisponivel`; para erros
    de negócio HTTP, `ApiError` com a mensagem de `detail`.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        cfg = get_dashboard()
        self.base_url = base_url or os.environ.get(
            cfg.url_env_var, cfg.url_padrao
        ).rstrip("/")
        self.timeout = timeout or cfg.timeout_segundos
        self._transport = transport

    def _cliente(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self._transport,
        )

    def _get(self, caminho: str, params: dict[str, Any] | None = None) -> Any:
        try:
            with self._cliente() as client:
                resp = client.get(caminho, params=params)
        except httpx.HTTPError as exc:
            raise ApiIndisponivel(f"API indisponível em {self.base_url}") from exc
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            raise ApiError(f"Erro HTTP {resp.status_code}: {detail}")
        return resp.json()

    # ── Parlamentares ────────────────────────────────────────────

    def listar_parlamentares(
        self,
        nome: str | None = None,
        uf: str | None = None,
        partido: str | None = None,
        pagina: int = 1,
        limite: int = 20,
    ) -> dict[str, Any]:
        """GET /parlamentares (lista paginada de parlamentares vigentes)."""
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        if nome:
            params["nome"] = nome
        if uf:
            params["uf"] = uf
        if partido:
            params["partido"] = partido
        return self._get("/parlamentares", params)

    def perfil_parlamentar(self, id_parlamentar: int) -> dict[str, Any]:
        """GET /parlamentares/{id} (perfil SCD2 vigente)."""
        return self._get(f"/parlamentares/{id_parlamentar}")

    def gastos_parlamentar(
        self,
        id_parlamentar: int,
        ano: int | None = None,
        pagina: int = 1,
        limite: int = 100,
    ) -> dict[str, Any]:
        """GET /parlamentares/{id}/gastos (despesas paginadas)."""
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        if ano:
            params["ano"] = ano
        return self._get(f"/parlamentares/{id_parlamentar}/gastos", params)

    def rede_parlamentar(self, id_parlamentar: int) -> dict[str, Any]:
        """GET /parlamentares/{id}/rede (nós e arestas da rede do parlamentar)."""
        return self._get(f"/parlamentares/{id_parlamentar}/rede")

    # ── Fornecedores ─────────────────────────────────────────────

    def listar_fornecedores(
        self,
        nome: str | None = None,
        tipo_documento: str | None = None,
        pagina: int = 1,
        limite: int = 20,
    ) -> dict[str, Any]:
        """GET /fornecedores (lista paginada)."""
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        if nome:
            params["nome"] = nome
        if tipo_documento:
            params["tipo_documento"] = tipo_documento
        return self._get("/fornecedores", params)

    def perfil_fornecedor(self, cnpj_cpf_valor: str) -> dict[str, Any]:
        """GET /fornecedores/{cnpj_cpf_valor} (perfil + agregados)."""
        return self._get(f"/fornecedores/{cnpj_cpf_valor}")

    def parlamentares_fornecedor(
        self,
        cnpj_cpf_valor: str,
        pagina: int = 1,
        limite: int = 20,
    ) -> dict[str, Any]:
        """GET /fornecedores/{cnpj_cpf_valor}/parlamentares (top parlamentares)."""
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        return self._get(f"/fornecedores/{cnpj_cpf_valor}/parlamentares", params)

    # ── Anomalias ────────────────────────────────────────────────

    def listar_anomalias(
        self,
        threshold: float | None = None,
        pagina: int = 1,
        limite: int = 20,
    ) -> dict[str, Any]:
        """GET /anomalias (despesas anômalas paginadas)."""
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        if threshold is not None:
            params["threshold"] = threshold
        return self._get("/anomalias", params)

    # ── Rede ─────────────────────────────────────────────────────

    def comunidades(self) -> dict[str, Any]:
        """GET /rede/comunidades (comunidades detectadas no grafo)."""
        return self._get("/rede/comunidades")

    # ── Qualidade ────────────────────────────────────────────────

    def relatorio_qualidade(
        self,
        tabela: str | None = None,
        pagina: int = 1,
        limite: int = 20,
    ) -> dict[str, Any]:
        """GET /qualidade/relatorio (Data Quality Report do Gold)."""
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        if tabela:
            params["tabela"] = tabela
        return self._get("/qualidade/relatorio", params)

    # ── Pipeline ─────────────────────────────────────────────────

    def status_pipeline(self, limite: int = 20) -> dict[str, Any]:
        """GET /pipeline/status (execuções recentes do pipeline)."""
        return self._get("/pipeline/status", {"limite": limite})

    # ── Agent (JSON semântico agregado, ADR-032) ─────────────────

    def agent_parlamentar(self, id_parlamentar: int) -> dict[str, Any]:
        """GET /agent/parlamentar/{id} (métricas + risco + anomalias)."""
        return self._get(f"/agent/parlamentar/{id_parlamentar}")

    def agent_fornecedor(self, cnpj_cpf_valor: str) -> dict[str, Any]:
        """GET /agent/fornecedor/{cnpj_cpf_valor} (métricas + top parlamentares)."""
        return self._get(f"/agent/fornecedor/{cnpj_cpf_valor}")

    def agent_anomalias(self) -> dict[str, Any]:
        """GET /agent/anomalias (agregados de anomalias)."""
        return self._get("/agent/anomalias")

    def agent_context(self) -> dict[str, Any]:
        """GET /agent/context (métricas globais + qualidade + pipeline)."""
        return self._get("/agent/context")
