"""api/routers/agent.py — endpoints agent-ready (PROJECT_CONTEXT §11/RF-05, Onda 4).

`/agent/parlamentar/{id}`, `/agent/fornecedor/{cnpj}`, `/agent/anomalias` e
`/agent/context` entregam JSON **semântico agregado** para consumo por LLMs
(ADR-032): refletem a Camada Semântica (§8) e os scores de risco (§9/ADR-027),
não espelham os endpoints de negócio. Leitura read-only do Gold (ADR-026);
nenhuma métrica analítica é recalculada por request (ADR-030).

Fronteiras de erro idênticas às ondas anteriores: Gold ausente/desatualizada →
503; alvo inexistente → 404 nominal.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query

from api.repo import (
    GoldIndisponivel,
    obter_agente_anomalias,
    obter_agente_contexto,
    obter_agente_fornecedor,
    obter_agente_parlamentar,
)
from api.schemas.agent import (
    AgentAnomalias,
    AgentContext,
    AgentFornecedor,
    AgentParlamentar,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/agent", tags=["agent"])


def _erro_gold(endpoint: str, exc: Exception) -> HTTPException:
    logger.error("erro_repositorio_gold", endpoint=endpoint, erro=str(exc))
    return HTTPException(status_code=503, detail="Camada Gold indisponível")


@router.get("/parlamentar/{id_parlamentar}", response_model=AgentParlamentar)
def get_agente_parlamentar(
    id_parlamentar: int,
    inicio: str | None = Query(
        default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Recorte a partir de AAAA-MM (ex: 2023-01)",
    ),
    fim: str | None = Query(
        default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Recorte até AAAA-MM (ex: 2023-12)",
    ),
) -> AgentParlamentar:
    """Contexto do parlamentar, opcionalmente restrito ao recorte.

    Sprint 21 (mandato x mandato): `?inicio=AAAA-MM&fim=AAAA-MM`
    restringe métricas/top/anomalias/HHI/risco ao intervalo — um ano
    específico é `inicio=AAAA-01&fim=AAAA-12`. `janela_*` segue global
    do histórico; o recorte ecoa em `recorte_inicio/fim`.
    """
    if inicio and fim and inicio > fim:
        raise HTTPException(
            status_code=422, detail="inicio deve ser anterior ou igual a fim (AAAA-MM)",
        )
    try:
        resultado = obter_agente_parlamentar(id_parlamentar, inicio=inicio, fim=fim)
    except GoldIndisponivel as exc:
        raise _erro_gold("agent_parlamentar", exc)
    if resultado is None:
        raise HTTPException(
            status_code=404, detail=f"Parlamentar {id_parlamentar} não encontrado"
        )
    return resultado


@router.get("/fornecedor/{cnpj_cpf_valor}", response_model=AgentFornecedor)
def get_agente_fornecedor(cnpj_cpf_valor: str) -> AgentFornecedor:
    try:
        resultado = obter_agente_fornecedor(cnpj_cpf_valor)
    except GoldIndisponivel as exc:
        raise _erro_gold("agent_fornecedor", exc)
    if resultado is None:
        raise HTTPException(
            status_code=404, detail=f"Fornecedor {cnpj_cpf_valor} não encontrado"
        )
    return resultado


@router.get("/anomalias", response_model=AgentAnomalias)
def get_agente_anomalias() -> AgentAnomalias:
    try:
        return obter_agente_anomalias()
    except GoldIndisponivel as exc:
        raise _erro_gold("agent_anomalias", exc)


@router.get("/context", response_model=AgentContext)
def get_agente_contexto() -> AgentContext:
    try:
        return obter_agente_contexto()
    except GoldIndisponivel as exc:
        raise _erro_gold("agent_context", exc)
