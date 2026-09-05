"""api/routers/contador.py — endpoint de contador global de visitas (Sprint 12).

`GET /contador/visitas` incrementa e retorna a contagem de visitas do dia
e o total acumulado. Dados persistidos em DuckDB dedicado (`data/analytics/
visitas.duckdb`), separado do Gold read-only (ADR-026).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query

from api.repo import GoldIndisponivel, incrementar_visitas, ler_visitas
from api.schemas.contador import ContadorVisitas

logger = structlog.get_logger()

router = APIRouter(prefix="/contador", tags=["contador"])


@router.get("/visitas", response_model=ContadorVisitas)
def get_contador_visitas(
    increment: bool = Query(default=True, description="false só lê (deduplicação por browser)"),
) -> ContadorVisitas:
    """Retorna o contador de visitas (e incrementa, salvo ?increment=false).

    Cada chamada com increment=true conta o dia corrente. O frontend deve
    chamar com increment=false quando já contabilizou hoje (localStorage),
    para navegação entre páginas não inflar o contador.
    """
    try:
        return incrementar_visitas() if increment else ler_visitas()
    except GoldIndisponivel as exc:
        logger.error("erro_contador_visitas", erro=str(exc))
        raise HTTPException(
            status_code=503,
            detail="Contador de visitas indisponível",
        )
