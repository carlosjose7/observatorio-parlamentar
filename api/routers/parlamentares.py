"""api/routers/parlamentares.py — endpoints de parlamentares (PROJECT_CONTEXT §11).

Onda 1 da Sprint 6: `GET /parlamentares` (lista paginada com filtros) e
`GET /parlamentares/{id}/gastos` (histórico de despesas com dimensões
resolvidas). Regras de paginação vêm de `config/api.yaml` (ADR-008), nunca
hardcoded. Gold inacessível → HTTP 503 (degradação de serviço intencional);
parlamentar inexistente → HTTP 404.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query

from pipeline.config import get_api

from api.repo import GoldIndisponivel, listar_gastos, listar_parlamentares
from api.schemas.parlamentares import GastosParlamentar, ListaParlamentares

logger = structlog.get_logger()

router = APIRouter(prefix="/parlamentares", tags=["parlamentares"])

_config = get_api()


@router.get("", response_model=ListaParlamentares)
def get_parlamentares(
    nome: str | None = Query(default=None, max_length=100, description="Filtro parcial sobre o nome"),
    uf: str | None = Query(default=None, min_length=2, max_length=2, description="Sigla da UF (ex: DF)"),
    partido: str | None = Query(default=None, min_length=2, max_length=20, description="Sigla do partido (ex: PSDB)"),
    pagina: int = Query(default=_config.pagina_padrao, ge=1, description="Página corrente (1-based)"),
    limite: int = Query(default=_config.limite_padrao, ge=1, le=_config.limite_maximo, description="Itens por página (máx 100)"),
) -> ListaParlamentares:
    try:
        return listar_parlamentares(
            nome=nome, uf=uf, partido=partido, pagina=pagina, limite=limite
        )
    except GoldIndisponivel as exc:
        logger.error("erro_repositorio_gold", endpoint="parlamentares", erro=str(exc))
        raise HTTPException(status_code=503, detail="Camada Gold indisponível") from exc


@router.get("/{id_parlamentar}/gastos", response_model=GastosParlamentar)
def get_gastos_parlamentar(
    id_parlamentar: int,
    ano: int | None = Query(default=None, ge=_config.ano_minimo_consulta, description="Filtro por ano da despesa"),
    pagina: int = Query(default=_config.pagina_padrao, ge=1, description="Página corrente (1-based)"),
    limite: int = Query(default=_config.limite_padrao, ge=1, le=_config.limite_maximo, description="Itens por página (máx 100)"),
) -> GastosParlamentar:
    try:
        resultado = listar_gastos(
            id_parlamentar=id_parlamentar, ano=ano, pagina=pagina, limite=limite
        )
    except GoldIndisponivel as exc:
        logger.error("erro_repositorio_gold", endpoint="parlamentar_gastos", id_parlamentar=id_parlamentar, erro=str(exc))
        raise HTTPException(status_code=503, detail="Camada Gold indisponível") from exc
    if resultado is None:
        raise HTTPException(status_code=404, detail=f"Parlamentar {id_parlamentar} não encontrado")
    return resultado