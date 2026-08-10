"""api/routers/qualidade.py — endpoint de qualidade (PROJECT_CONTEXT §11, Onda 3).

`GET /qualidade/relatorio` expõe o Data Quality Report promovido à Gold
(`data_quality_report`, ADR-031): a API é read-only sobre o Gold (ADR-026),
e a promoção via model dbt coloca o relatório da Silver atrás dessa
fronteira. Filtro opcional `tabela` + paginação, do mais recente ao antigo.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query

from pipeline.config import get_api

from api.repo import GoldIndisponivel, listar_relatorio_qualidade
from api.schemas.qualidade import RelatorioQualidade

logger = structlog.get_logger()

router = APIRouter(prefix="/qualidade", tags=["qualidade"])

_config = get_api()


def _erro_gold(endpoint: str, exc: Exception) -> HTTPException:
    logger.error("erro_repositorio_gold", endpoint=endpoint, erro=str(exc))
    return HTTPException(status_code=503, detail="Camada Gold indisponível")


@router.get("/relatorio", response_model=RelatorioQualidade)
def get_relatorio(
    tabela: str | None = Query(default=None, max_length=100, description="Filtra por tabela Silver do relatório"),
    pagina: int = Query(default=_config.pagina_padrao, ge=1, description="Página corrente (1-based)"),
    limite: int = Query(default=_config.limite_padrao, ge=1, le=_config.limite_maximo, description="Itens por página (máx 100)"),
) -> RelatorioQualidade:
    try:
        return listar_relatorio_qualidade(
            tabela=tabela, pagina=pagina, limite=limite
        )
    except GoldIndisponivel as exc:
        raise _erro_gold("qualidade_relatorio", exc)