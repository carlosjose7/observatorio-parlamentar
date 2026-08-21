"""api/routers/pipeline.py — endpoints de pipeline (PROJECT_CONTEXT §11, Onda 3).

`GET /pipeline/status` consome o controle de execuções da Gold
(`pipeline_runs`, ADR-019) — a API é observadora passiva, nunca interage
com o orquestrador. Execuções mais recentes primeiro.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query

from api.repo import GoldIndisponivel, listar_execucoes
from api.schemas.pipeline import PipelineStatus
from pipeline.config import get_api

logger = structlog.get_logger()

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

_config = get_api()


def _erro_gold(endpoint: str, exc: Exception) -> HTTPException:
    logger.error("erro_repositorio_gold", endpoint=endpoint, erro=str(exc))
    return HTTPException(status_code=503, detail="Camada Gold indisponível")


@router.get("/status", response_model=PipelineStatus)
def get_status(
    limite: int = Query(default=20, ge=1, le=_config.limite_maximo, description="Execuções mais recentes a retornar"),
) -> PipelineStatus:
    try:
        return listar_execucoes(limite=limite)
    except GoldIndisponivel as exc:
        raise _erro_gold("pipeline_status", exc)
