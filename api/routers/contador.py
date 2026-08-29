"""api/routers/contador.py — endpoint de contador global de visitas (Sprint 12).

`GET /contador/visitas` incrementa e retorna a contagem de visitas do dia
e o total acumulado. Dados persistidos em DuckDB dedicado (`data/analytics/
visitas.duckdb`), separado do Gold read-only (ADR-026).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException

from api.repo import GoldIndisponivel, incrementar_visitas
from api.schemas.contador import ContadorVisitas

logger = structlog.get_logger()

router = APIRouter(prefix="/contador", tags=["contador"])


@router.get("/visitas", response_model=ContadorVisitas)
def get_contador_visitas() -> ContadorVisitas:
    """Incrementa e retorna o contador de visitas.

    Cada chamada incrementa o contador do dia corrente. O frontend deve
    deduplicar por sessão (localStorage) para não inflar o contador a cada
    reload.
    """
    try:
        return incrementar_visitas()
    except GoldIndisponivel as exc:
        logger.error("erro_contador_visitas", erro=str(exc))
        raise HTTPException(
            status_code=503,
            detail="Contador de visitas indisponível",
        )
