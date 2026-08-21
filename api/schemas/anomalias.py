"""api/schemas/anomalias.py — contratos de resposta da API (Sprint 6, Onda 3).

`GET /anomalias` expõe as despesas sinalizadas pelo pipeline analítico
(Gold `expense_outliers`), lendo os scores/critérios MATERIALIZADOS pelo
dbt (ADR-002/§10, ADR-026) — nunca recalcula a regra. O filtro `threshold`
é um piso de `zscore` sobre o conjunto já sinalizado (decisão de Onda 3;
§11 de PROJECT_CONTEXT, exemplo `?threshold=2.5`), não uma reabertura de
decisão de treino/inferência.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AnomaliaItem(BaseModel):
    """Uma despesa sinalizada — scores brutos + critérios que dispararam.

    Espelha as colunas emitidas por `expense_outliers.sql`; `num_criterios`
    é >= 2 por construção da Gold (ADR-002).
    """

    model_config = ConfigDict(extra="forbid")

    id_despesa: int
    id_parlamentar: int
    id_fornecedor: int | None
    data_sk: int
    valor_liquido: Decimal
    zscore: float | None
    if_score: float | None
    criterio_zscore: bool
    criterio_if: bool
    criterio_fornecedor_poucos_clientes: bool
    criterio_empresa_nova: bool
    criterio_valores_identicos: bool
    criterio_dia_sem_sessao: bool
    num_criterios: int


class ListaAnomalias(BaseModel):
    """Lista paginada de anomalias; `threshold` ecoa o filtro aplicado (None = todos)."""

    model_config = ConfigDict(extra="forbid")

    pagina: int
    limite: int
    total: int
    threshold: float | None
    itens: list[AnomaliaItem]
