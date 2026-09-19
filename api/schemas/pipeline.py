"""api/schemas/pipeline.py — contratos de resposta da API (Sprint 6, Onda 3).

`GET /pipeline/status` expõe as execuções consolidadas na Gold
(`pipeline_runs`, ADR-019): uma linha por run, com status e watermarks por
fonte. Leitura direta — a API não interage com o orquestrador.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ExecucaoPipeline(BaseModel):
    """Uma execução do pipeline, do controle `pipeline_runs` (ADR-019)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    pipeline_version: str | None
    execution_timestamp: str | None
    status: str
    # Status granular (ADR-056 D1, Onda 1): nulo em execuções pré-Sprint 26
    # (coluna aditiva no Gold) — consumidores usam `status_detalhado or
    # status` como status efetivo, nunca assumem presença.
    status_detalhado: str | None = None
    fontes_com_erro: list[str] | None
    watermark_camara: str | None
    watermark_senado: str | None
    watermark_cgu_emenda: str | None
    watermark_cgu_cartao: str | None


class PipelineStatus(BaseModel):
    """Execuções mais recentes primeiro (`execution_timestamp` desc)."""

    model_config = ConfigDict(extra="forbid")

    total: int
    itens: list[ExecucaoPipeline]


class TaskRun(BaseModel):
    """Um span de duração de task, do controle `pipeline_task_runs` (ADR-056 D1)."""

    model_config = ConfigDict(extra="forbid")

    task_run_id: str
    run_id: str
    task: str
    status: str
    duration_seconds: float | None
    pipeline_version: str | None
    execution_timestamp: str | None


class ListaTaskRuns(BaseModel):
    """Spans mais recentes primeiro (`execution_timestamp` desc)."""

    model_config = ConfigDict(extra="forbid")

    total: int
    itens: list[TaskRun]
