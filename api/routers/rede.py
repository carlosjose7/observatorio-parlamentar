"""api/routers/rede.py — endpoints de rede (PROJECT_CONTEXT §11, Onda 3).

`GET /rede/comunidades` => agrupamento por `comunidade_id` dos nós já
materializados na Gold (`network_nodes`, ADR-030). Leitura de resultado da
Sprint 5 — a API não recalcula o particionamento nem métricas do grafo.

Gate 3 (auditoria Sprint 7): `limite_nos` (default 200, teto 1000) limita os
nós por comunidade na própria consulta — o payload nunca cresce sem teto com
grafos reais.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query

from api.repo import (
    GoldIndisponivel,
    listar_comunidades,
    obter_rede_fornecedor,
)
from api.schemas.rede import ListaComunidades, RedeFornecedor

logger = structlog.get_logger()

router = APIRouter(prefix="/rede", tags=["rede"])


def _erro_gold(endpoint: str, exc: Exception) -> HTTPException:
    logger.error("erro_repositorio_gold", endpoint=endpoint, erro=str(exc))
    return HTTPException(status_code=503, detail="Camada Gold indisponível")


@router.get("/comunidades", response_model=ListaComunidades)
def get_comunidades(
    limite_nos: int = Query(default=200, ge=1, le=1000),
) -> ListaComunidades:
    try:
        return listar_comunidades(limite_nos=limite_nos)
    except GoldIndisponivel as exc:
        raise _erro_gold("rede_comunidades", exc)


@router.get("/fornecedores/{id_fornecedor}", response_model=RedeFornecedor)
def get_rede_fornecedor(id_fornecedor: int) -> RedeFornecedor:
    """Rede INVERSA: parlamentares conectados a um fornecedor (ADR-030).

    Mesma regra do `/parlamentares/{id}/rede`: leitura das arestas
    materializadas na Gold — sem recálculo de grafo.
    """
    try:
        resultado = obter_rede_fornecedor(id_fornecedor)
    except GoldIndisponivel as exc:
        raise _erro_gold("rede_fornecedor", exc)
    if resultado is None:
        raise HTTPException(
            status_code=404,
            detail=f"Fornecedor {id_fornecedor} não encontrado",
        )
    return resultado
