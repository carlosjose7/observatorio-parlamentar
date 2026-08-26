"""api/routers/anomalias.py — endpoints de anomalias (PROJECT_CONTEXT §11, Onda 3).

`GET /anomalias` lista as despesas sinalizadas na Gold (`expense_outliers`,
ADR-002/§10). `threshold` é piso opcional de `zscore` sobre o conjunto já
sinalizado pelo pipeline — decisão de Onda 3, fixada na revisão (a API não
reabre o `-0.1` do Isolation Forest nem os `>= 2` critérios; lê resultado
materializado, ADR-026/ADR-030). Threshold não-numérico ou negativo cai em
HTTP 422, mesmo contrato de erro dos filtros de fornecedores (Onda 2).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query

from api.repo import GoldIndisponivel, listar_anomalias
from api.schemas.anomalias import ListaAnomalias
from pipeline.config import get_api

logger = structlog.get_logger()

router = APIRouter(prefix="/anomalias", tags=["anomalias"])

_config = get_api()


def _erro_gold(endpoint: str, exc: Exception) -> HTTPException:
    logger.error("erro_repositorio_gold", endpoint=endpoint, erro=str(exc))
    return HTTPException(status_code=503, detail="Camada Gold indisponível")


@router.get("", response_model=ListaAnomalias)
def get_anomalias(
    threshold: float | None = Query(
        default=None,
        ge=0,
        description="Piso de z-score: retorna apenas sinalizadas com zscore >= threshold",
    ),
    ano: int | None = Query(
        default=None,
        ge=_config.ano_minimo_consulta,
        description="Filtro pelo ano da data do documento",
    ),
    pagina: int = Query(default=_config.pagina_padrao, ge=1, description="Página corrente (1-based)"),
    limite: int = Query(default=_config.limite_padrao, ge=1, le=_config.limite_maximo, description="Itens por página (máx 100)"),
) -> ListaAnomalias:
    try:
        return listar_anomalias(
            threshold=threshold, ano=ano, pagina=pagina, limite=limite
        )
    except GoldIndisponivel as exc:
        raise _erro_gold("anomalias", exc)
