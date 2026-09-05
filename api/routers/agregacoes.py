"""api/routers/agregacoes.py — endpoints de agregação para gráficos.

Expõe recortes de `fact_despesa` consumidos pelas análises do dashboard:
gastos por UF, por partido, top parlamentares e série mensal. Consultas
puramente agregativas sobre o Gold materializado (ADR-026); Gold
inacessível → HTTP 503, como nos demais routers.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query

from api.repo import (
    GoldIndisponivel,
    agregar_despesas_no_tempo,
    agregar_gastos_por_partido,
    agregar_gastos_por_uf,
    agregar_top_fornecedores,
    agregar_top_parlamentares,
)
from api.schemas.agregacoes import ListaAgregacao, ListaTopFornecedores, SerieTemporal
from pipeline.config import get_api

logger = structlog.get_logger()

router = APIRouter(prefix="/agregacoes", tags=["agregacoes"])

_config = get_api()


def _erro_gold(endpoint: str, exc: Exception) -> HTTPException:
    logger.error("erro_repositorio_gold", endpoint=endpoint, erro=str(exc))
    return HTTPException(status_code=503, detail="Camada Gold indisponível")


@router.get("/por-uf", response_model=ListaAgregacao)
def get_gastos_por_uf(
    limite: int = Query(
        default=10,
        ge=1,
        le=_config.limite_maximo,
        description="Quantidade de UFs no ranking",
    ),
    ano: int | None = Query(
        default=None, ge=2000, le=2100, description="Ano de competência (None = todos)",
    ),
) -> ListaAgregacao:
    try:
        return agregar_gastos_por_uf(limite=limite, ano=ano)
    except GoldIndisponivel as exc:
        raise _erro_gold("agregacoes_por_uf", exc)


@router.get("/por-partido", response_model=ListaAgregacao)
def get_gastos_por_partido(
    limite: int = Query(
        default=10,
        ge=1,
        le=_config.limite_maximo,
        description="Quantidade de partidos no ranking",
    ),
    ano: int | None = Query(
        default=None, ge=2000, le=2100, description="Ano de competência (None = todos)",
    ),
) -> ListaAgregacao:
    try:
        return agregar_gastos_por_partido(limite=limite, ano=ano)
    except GoldIndisponivel as exc:
        raise _erro_gold("agregacoes_por_partido", exc)


@router.get("/top-parlamentares", response_model=ListaAgregacao)
def get_top_parlamentares(
    limite: int = Query(
        default=10,
        ge=1,
        le=_config.limite_maximo,
        description="Quantidade de parlamentares no ranking",
    ),
    ano: int | None = Query(
        default=None, ge=2000, le=2100, description="Ano de competência (None = todos)",
    ),
) -> ListaAgregacao:
    try:
        return agregar_top_parlamentares(limite=limite, ano=ano)
    except GoldIndisponivel as exc:
        raise _erro_gold("agregacoes_top_parlamentares", exc)


@router.get("/top-fornecedores", response_model=ListaTopFornecedores)
def get_top_fornecedores(
    limite: int = Query(
        default=10,
        ge=1,
        le=_config.limite_maximo,
        description="Quantidade de fornecedores no ranking",
    ),
) -> ListaTopFornecedores:
    """Top fornecedores por valor recebido, com parlamentares distintos."""
    try:
        return agregar_top_fornecedores(limite=limite)
    except GoldIndisponivel as exc:
        raise _erro_gold("agregacoes_top_fornecedores", exc)


@router.get("/no-tempo", response_model=SerieTemporal)
def get_despesas_no_tempo() -> SerieTemporal:
    """Série mensal (AAAAMM) de total gasto e quantidade de despesas."""
    try:
        return agregar_despesas_no_tempo()
    except GoldIndisponivel as exc:
        raise _erro_gold("agregacoes_no_tempo", exc)
