"""api/schemas/contador.py — schemas do contador global de visitas (Sprint 12).

Endpoint `GET /contador/visitas`: incrementa e retorna contagem de visitas
por dia, persistida em DuckDB dedicado (`data/analytics/visitas.duckdb`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ContadorVisitas(BaseModel):
    """Resposta do contador de visitas."""

    total_hoje: int = Field(..., description="Visitas registradas hoje")
    total_geral: int = Field(..., description="Total acumulado de visitas")
