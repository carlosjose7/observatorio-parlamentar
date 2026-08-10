"""api/routers/parlamentares.py — endpoints de parlamentares (PROJECT_CONTEXT §11).

Onda 1: `GET /parlamentares` (lista paginada com filtros) e
`GET /parlamentares/{id}/gastos` (histórico de despesas com dimensões
resolvidas). Onda 2: `GET /parlamentares/{id}` (perfil vigente do SCD2) e
`GET /parlamentares/{id}/rede` (rede do parlamentar APENAS a partir dos
resultados materializados da Sprint 5 no Gold — a API não recalcula
grafo/PageRank/comunidades, regra da Onda 2).

Regras de paginação vêm de `config/api.yaml` (ADR-008), nunca hardcoded.
Gold inacessível → HTTP 503 (degradação de serviço intencional); parlamentar
inexistente → HTTP 404.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query

from pipeline.config import get_api

from api.repo import (
    GoldIndisponivel,
    listar_gastos,
    listar_parlamentares,
    obter_perfil_parlamentar,
    obter_rede_parlamentar,
)
from api.schemas.parlamentares import (
    GastosParlamentar,
    ListaParlamentares,
    PerfilParlamentar,
    RedeParlamentar,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/parlamentares", tags=["parlamentares"])

_config = get_api()


def _erro_gold(endpoint: str, exc: Exception) -> HTTPException:
    logger.error("erro_repositorio_gold", endpoint=endpoint, erro=str(exc))
    return HTTPException(status_code=503, detail="Camada Gold indisponível")


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
        raise _erro_gold("parlamentares", exc)


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
        raise _erro_gold("parlamentar_gastos", exc)
    if resultado is None:
        raise HTTPException(status_code=404, detail=f"Parlamentar {id_parlamentar} não encontrado")
    return resultado


@router.get("/{id_parlamentar}", response_model=PerfilParlamentar)
def get_parlamentar(
    id_parlamentar: int,
) -> PerfilParlamentar:
    """Perfil completo do parlamentar na versão vigente do SCD2 (ADR-020)."""
    try:
        resultado = obter_perfil_parlamentar(id_parlamentar)
    except GoldIndisponivel as exc:
        raise _erro_gold("parlamentar_perfil", exc)
    if resultado is None:
        raise HTTPException(status_code=404, detail=f"Parlamentar {id_parlamentar} não encontrado")
    return resultado


@router.get("/{id_parlamentar}/rede", response_model=RedeParlamentar)
def get_rede_parlamentar(
    id_parlamentar: int,
) -> RedeParlamentar:
    """Rede do parlamentar — nós e arestas materializados no Gold (ADR-030).

    Não recalcula análise: consulta `network_nodes`/`network_edges` da Gold,
    produzidos pela Sprint 5 (Onda 3). Sem staging ainda → listas vazias.
    """
    try:
        resultado = obter_rede_parlamentar(id_parlamentar)
    except GoldIndisponivel as exc:
        raise _erro_gold("parlamentar_rede", exc)
    if resultado is None:
        raise HTTPException(status_code=404, detail=f"Parlamentar {id_parlamentar} não encontrado")
    return resultado