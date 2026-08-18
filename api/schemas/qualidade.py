"""api/schemas/qualidade.py — contratos de resposta da API (Sprint 6, Onda 3).

`GET /qualidade/relatorio` expõe o Data Quality Report da Silver promovido
à Gold (`data_quality_report.sql`, ADR-031): uma linha por tabela/execução
com os agregados do gate Pandera (ADR-013/ADR-015). `regras_violadas` chega
da Gold como lista (JSON desserializado no repo) — nunca como string crua.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LinhaQualidade(BaseModel):
    """Uma linha do relatório de qualidade — conforme `LinhaQualidadeReport` (ADR-015)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    tabela: str
    total_registros: int
    registros_validos: int
    registros_quarentena: int
    registros_deduplicados: int
    regras_violadas: list[str]
    percentual_nulos_criticos: float
    execution_timestamp: str | None


class RelatorioQualidade(BaseModel):
    """Relatório paginado, da execução mais recente para a mais antiga."""

    model_config = ConfigDict(extra="forbid")

    pagina: int
    limite: int
    total: int
    itens: list[LinhaQualidade]
