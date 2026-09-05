"""dashboard/client.py — cliente HTTP da API REST para o dashboard (Sprint 7).

Camada única de acesso a dados do dashboard (RF-05, ADR-026): todas as
páginas Streamlit consultam a API REST via este cliente — o dashboard
NUNCA abre o DuckDB diretamente. A base URL vem de `config/dashboard.yaml`
(ADR-008): variável de ambiente `API_URL` (docker-compose injeta
`http://api:8000`; em dev local `http://localhost:8000`; atrás do nginx o
prefixo externo é `/api/`).

Robustez (Gate 1, auditoria Sprint 7):
- `timeout` explícito para cada requisição (config, ADR-008).
- Erros de transporte (`ConnectError`, `ConnectTimeout`, `ReadTimeout`,
  `RemoteProtocolError`, ...) viram `ApiIndisponivel` — nunca escapam para
  o Streamlit.
- Corpo de resposta não-JSON em status 2xx viram `ApiError` (em vez de
  `JSONDecodeError` cru).
- Retry limitado para erros transitórios (rede/5xx) em GET — idempotente e
  seguro; erro 4xx NUNCA é retried (contractual).
- Limite de tamanho de resposta (`resposta_max_bytes`, config) — corpo maior
  que o teto é rejeitado com `ApiError` (proteção contra payload anômalo).
- Mensagens de erro não expõem a URL interna nem credenciais.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx

from pipeline.config import get_dashboard

PASTA_RAIZ_API = ""  # sem prefixo — a URL base já aponta para a API

#: Máximo de tentativas para erros transitórios (GET idempotente).
_MAX_TENTATIVAS = 3


class ApiError(RuntimeError):
    """Erro de negócio retornado pela API (ex: 404, 422, 503) ou corpo inválido."""


class ApiIndisponivel(RuntimeError):
    """API inacessível (rede/erro de transporte) — dashboard offline."""


def _codificar_path(valor: Any) -> str:
    """Encoda um segmento de path (URL-safe) para uso em `{param}` de rota.

    Ex: CNPJ mascarado `11.222.333/0001-81` → `11.222.333%2F0001-81`
    (o `/` não pode quebrar a rota). Espaços e caracteres especiais também.
    """
    return quote(str(valor), safe="")


class ApiClient:
    """Cliente HTTP para os endpoints da API do Observatório Parlamentar.

    Os métodos retornam o payload JSON (dict) dos endpoints paginados e
    agregados. Para falhas de rede, levantam `ApiIndisponivel`; para erros
    de negócio HTTP ou corpo inválido, `ApiError`.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        max_tentativas: int | None = None,
        resposta_max_bytes: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        cfg = get_dashboard()
        self.base_url = base_url or os.environ.get(
            cfg.url_env_var, cfg.url_padrao
        ).rstrip("/")
        self.timeout = timeout or cfg.timeout_segundos
        self.max_tentativas = max_tentativas or _MAX_TENTATIVAS
        self.resposta_max_bytes = (
            resposta_max_bytes or cfg.resposta_max_bytes
        )
        self._transport = transport

    def _cliente(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self._transport,
        )

    def _mensagem_indisponivel(self) -> str:
        """Mensagem amigável de API offline — sem expor URL interna."""
        return "A API de dados está indisponível no momento. Tente novamente mais tarde."

    def _get(self, caminho: str, params: dict[str, Any] | None = None) -> Any:
        ultimo_erro: Exception | None = None
        for tentativa in range(self.max_tentativas):
            client = self._cliente()
            try:
                resp = client.get(caminho, params=params)
                if resp.status_code >= 500:
                    # Transitório: tenta de novo (GET idempotente).
                    ultimo_erro = ApiError(
                        f"A API retornou um erro temporário (HTTP {resp.status_code})."
                    )
                    continue
                if len(resp.content) > self.resposta_max_bytes:
                    raise ApiError(
                        "Resposta da API acima do limite permitido para exibição."
                    )
                if resp.status_code >= 400:
                    raise ApiError(self._mensagem_erro(resp))
                try:
                    return resp.json()
                except ValueError as exc:
                    raise ApiError(
                        "A API retornou uma resposta inválida (JSON malformado)."
                    ) from exc
            except httpx.HTTPError as exc:
                ultimo_erro = exc
                # Retry apenas para erros de transporte (rede/connect/timeout).
                continue
            except ApiError:
                # Erro de negócio (4xx/limite/JSON inválido): não é retried.
                raise
            finally:
                client.close()
        raise ApiIndisponivel(self._mensagem_indisponivel()) from ultimo_erro

    def _mensagem_erro(self, resp: httpx.Response) -> str:
        """Extrai a mensagem amigável de um erro HTTP sem expor a URL interna."""
        try:
            detail = resp.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, str) and detail:
            return f"Erro na consulta: {detail}"
        return f"A consulta não pôde ser completada (HTTP {resp.status_code})."

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
        return self._get(f"/parlamentares/{_codificar_path(id_parlamentar)}")

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
        return self._get(
            f"/parlamentares/{_codificar_path(id_parlamentar)}/gastos", params
        )

    def gastos_parlamentar_tudo(
        self, id_parlamentar: int, *, max_paginas: int = 5, limite: int = 100,
    ) -> list[dict[str, Any]]:
        """Todas as despesas (páginas até esgotar/total, teto max_paginas).

        Sprint 19: com limite=100 só vinham as ~100 mais recentes (só 2026)
        e o filtro de ano não oferecia os demais anos.
        """
        itens: list[dict[str, Any]] = []
        pagina = 1
        while pagina <= max_paginas:
            payload = self.gastos_parlamentar(id_parlamentar, pagina=pagina, limite=limite)
            lote = (payload or {}).get("itens", [])
            itens.extend(lote)
            total = (payload or {}).get("total", len(itens))
            if len(itens) >= total or len(lote) < limite:
                break
            pagina += 1
        return itens

    def gastos_fornecedor_tudo(
        self, cnpj_cpf_valor: str, *, max_paginas: int = 5, limite: int = 100,
    ) -> list[dict[str, Any]]:
        """Idem, para `GET /fornecedores/{doc}/gastos`."""
        itens: list[dict[str, Any]] = []
        pagina = 1
        while pagina <= max_paginas:
            payload = self.gastos_fornecedor(cnpj_cpf_valor, pagina=pagina, limite=limite)
            lote = (payload or {}).get("itens", [])
            itens.extend(lote)
            total = (payload or {}).get("total", len(itens))
            if len(itens) >= total or len(lote) < limite:
                break
            pagina += 1
        return itens

    def rede_parlamentar(self, id_parlamentar: int) -> dict[str, Any]:
        """GET /parlamentares/{id}/rede (nós e arestas da rede do parlamentar)."""
        return self._get(f"/parlamentares/{_codificar_path(id_parlamentar)}/rede")

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
        return self._get(f"/fornecedores/{_codificar_path(cnpj_cpf_valor)}")

    def parlamentares_fornecedor(
        self,
        cnpj_cpf_valor: str,
        pagina: int = 1,
        limite: int = 20,
    ) -> dict[str, Any]:
        """GET /fornecedores/{cnpj_cpf_valor}/parlamentares (top parlamentares)."""
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        return self._get(
            f"/fornecedores/{_codificar_path(cnpj_cpf_valor)}/parlamentares",
            params,
        )

    def gastos_fornecedor(
        self,
        cnpj_cpf_valor: str,
        ano: int | None = None,
        pagina: int = 1,
        limite: int = 100,
    ) -> dict[str, Any]:
        """GET /fornecedores/{cnpj_cpf_valor}/gastos (despesas com data/ano/mês)."""
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        if ano:
            params["ano"] = ano
        return self._get(
            f"/fornecedores/{_codificar_path(cnpj_cpf_valor)}/gastos",
            params,
        )

    # ── Anomalias ────────────────────────────────────────────────

    def listar_anomalias(
        self,
        threshold: float | None = None,
        ano: int | None = None,
        pagina: int = 1,
        limite: int = 20,
    ) -> dict[str, Any]:
        """GET /anomalias (despesas anômalas paginadas)."""
        params: dict[str, Any] = {"pagina": pagina, "limite": limite}
        if threshold is not None:
            params["threshold"] = threshold
        if ano is not None:
            params["ano"] = ano
        return self._get("/anomalias", params)

    # ── Rede ─────────────────────────────────────────────────────

    def comunidades(self, limite_nos: int = 200) -> dict[str, Any]:
        """GET /rede/comunidades (comunidades detectadas no grafo).

        `limite_nos` limita os nós por comunidade (Gate 3, auditoria Sprint 7)
        — a API aplica o teto na consulta, nunca no cliente.
        """
        return self._get("/rede/comunidades", {"limite_nos": limite_nos})

    def rede_fornecedor(self, id_fornecedor: int) -> dict[str, Any]:
        """GET /rede/fornecedores/{id} (parlamentares conectados ao fornecedor)."""
        return self._get(
            f"/rede/fornecedores/{_codificar_path(id_fornecedor)}"
        )

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

    # ── Agregações (análises/gráficos) ───────────────────────────

    def agregacao_por_uf(self, limite: int = 10, ano: int | None = None) -> dict[str, Any]:
        """GET /agregacoes/por-uf (gastos por UF, ordenados por total)."""
        params: dict[str, Any] = {"limite": limite}
        if ano:
            params["ano"] = ano
        return self._get("/agregacoes/por-uf", params)

    def agregacao_por_partido(self, limite: int = 10, ano: int | None = None) -> dict[str, Any]:
        """GET /agregacoes/por-partido (gastos por partido, por total)."""
        params: dict[str, Any] = {"limite": limite}
        if ano:
            params["ano"] = ano
        return self._get("/agregacoes/por-partido", params)

    def top_parlamentares(self, limite: int = 10, ano: int | None = None) -> dict[str, Any]:
        """GET /agregacoes/top-parlamentares (ranking por gasto acumulado)."""
        params: dict[str, Any] = {"limite": limite}
        if ano:
            params["ano"] = ano
        return self._get("/agregacoes/top-parlamentares", params)

    def top_fornecedores(self, limite: int = 10) -> dict[str, Any]:
        """GET /agregacoes/top-fornecedores (ranking por valor recebido)."""
        return self._get("/agregacoes/top-fornecedores", {"limite": limite})

    def despesas_no_tempo(self) -> dict[str, Any]:
        """GET /agregacoes/no-tempo (série mensal AAAAMM de total e contagem)."""
        return self._get("/agregacoes/no-tempo")

    # ── Agent (JSON semântico agregado, ADR-032) ─────────────────

    def agent_parlamentar(self, id_parlamentar: int) -> dict[str, Any]:
        """GET /agent/parlamentar/{id} (métricas + risco + anomalias)."""
        return self._get(f"/agent/parlamentar/{_codificar_path(id_parlamentar)}")

    def agent_fornecedor(self, cnpj_cpf_valor: str) -> dict[str, Any]:
        """GET /agent/fornecedor/{cnpj_cpf_valor} (métricas + top parlamentares)."""
        return self._get(f"/agent/fornecedor/{_codificar_path(cnpj_cpf_valor)}")

    def agent_anomalias(self) -> dict[str, Any]:
        """GET /agent/anomalias (agregados de anomalias)."""
        return self._get("/agent/anomalias")

    def agent_context(self) -> dict[str, Any]:
        """GET /agent/context (métricas globais + qualidade + pipeline)."""
        return self._get("/agent/context")

