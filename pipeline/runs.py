"""pipeline/runs.py — tabela de controle `pipeline_runs` (versionamento.md §4).

Em Bronze (Sprint 2), `pipeline_runs` é gravada como Parquet de controle **não
particionado** (um arquivo por `run_id`). Na Sprint 4, a camada Gold migra
essas linhas para a tabela DuckDB documentada em versionamento.md §4 — o
schema desta camada é o contrato dessa migração.

Sprint 26, Onda 1 (ADR-056 D1): status granular (`status_detalhado`,
coluna nova aditiva — o `status` legado de 3 valores fica intocado) e
duração por task (`PipelineTaskRun`, grão `(run_id, task)`, um arquivo por
span em `controle/pipeline_task_runs/`). A instrumentação é própria
(`medir_task`), não o metadata do Airflow — o exporter só lê o Gold
`read_only` (ADR-026/051) e o banco do Airflow é efêmero (perfil `pipeline`).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import pandas as pd
import structlog
from pydantic import BaseModel, Field

from pipeline.storage import Storage

logger = structlog.get_logger()

DIRETORIO_CONTROLE = Path("controle") / "pipeline_runs"
DIRETORIO_TASK_RUNS = Path("controle") / "pipeline_task_runs"

StatusLegado = Literal["success", "failed", "partial"]

StatusDetalhado = Literal[
    "success", "failed", "partial", "warning", "running", "cancelled", "timeout"
]

# Tasks conhecidas do DAG (`pipeline/dags/pipeline_dag.py`) + sub-spans por
# fonte medidos dentro das callables (ADR-056 D1). O exporter usa a mesma
# lista como allowlist de cardinalidade (mesmo padrão do `_STATUS_CONHECIDOS`
# — `run_id` nunca é label).
TASKS_CONHECIDAS = (
    "executar_bronze",
    "executar_silver",
    "executar_gold_core",
    "executar_analytics",
    "executar_gold_analytics",
    "bronze_camara",
    "bronze_senado",
    "bronze_cgu_emenda",
    "bronze_cgu_cartao",
    "bronze_parlamentares",
    "silver_camara",
    "silver_senado",
    "silver_cartao",
    "silver_emenda",
    "silver_parlamentares",
    "gold_core",
    "gold_analytics",
    "analytics",
)


class PipelineRun(BaseModel):
    """Uma execução do pipeline Bronze (tabela de controle, não é fato).

    Schema espelha versionamento.md §4 e adiciona `fontes_com_erro` para
    falhas isoladas (status `partial`, §5).
    """

    run_id: UUID
    pipeline_version: str
    execution_timestamp: datetime
    status: StatusLegado
    # Status granular (ADR-056 D1, Onda 1): coluna NOVA e nullable — espelha
    # o `status` legado nas execuções concluídas; os valores novos (warning,
    # running, cancelled, timeout) ficam expressáveis no schema para a
    # integração futura com o orquestrador, sem reescrever o contrato de 3
    # valores nem as 11 regras de alerta. Nulo = execução pré-Sprint 26.
    status_detalhado: StatusDetalhado | None = None
    fontes_com_erro: list[str] = []
    watermark_camara: str | None = None
    watermark_senado: str | None = None
    watermark_cgu_emenda: str | None = None
    watermark_cgu_cartao: str | None = None


class PipelineTaskRun(BaseModel):
    """Um span de task dentro de uma execução (ADR-056 D1, Onda 1).

    Grão `(run_id, task)` — grão distinto de `PipelineRun` (1 linha por run),
    por isso tabela de controle própria (`pipeline_task_runs`), não colunas
    novas em `pipeline_runs`. `status` no nível da task: `success`/`failed`
    no caminho instrumentado; os demais valores do vocabulário granular ficam
    expressáveis para o orquestrador futuro.
    """

    run_id: UUID
    task: str
    status: StatusDetalhado = "success"
    duration_seconds: float = Field(ge=0)
    pipeline_version: str
    execution_timestamp: datetime


def write_pipeline_run(storage: Storage, run: PipelineRun) -> None:
    """Grava a linha de controle da execução (um arquivo por run_id)."""
    df = pd.DataFrame([run.model_dump(mode="json")])
    storage.write_file(DIRETORIO_CONTROLE, df, f"{run.run_id}.parquet")


def write_pipeline_task_run(storage: Storage, span: PipelineTaskRun) -> None:
    """Grava um span de task (um arquivo por `(run_id, task)`).

    Nunca lança para o chamador via `medir_task` — observabilidade não
    derruba pipeline; chamada direta ainda propaga erro de storage (testes).
    """
    df = pd.DataFrame([span.model_dump(mode="json")])
    storage.write_file(DIRETORIO_TASK_RUNS, df, f"{span.run_id}__{span.task}.parquet")


@contextmanager
def medir_task(
    storage: Storage,
    *,
    run_id: UUID,
    task: str,
    pipeline_version: str,
    execution_timestamp: datetime | None = None,
) -> Iterator[None]:
    """Mede a duração de uma task e persiste o span (ADR-056 D1).

    Sucesso → `success`; exceção → grava `failed` e re-lança. Falha NA
    GRAVAÇÃO do span é apenas logada — a observabilidade nunca quebra a
    execução observada.
    """
    from datetime import UTC

    inicio = time.perf_counter()
    try:
        yield
    except Exception:
        _gravar_span_seguro(
            storage,
            run_id=run_id,
            task=task,
            status="failed",
            duration_seconds=time.perf_counter() - inicio,
            pipeline_version=pipeline_version,
            execution_timestamp=execution_timestamp or datetime.now(UTC),
        )
        raise
    _gravar_span_seguro(
        storage,
        run_id=run_id,
        task=task,
        status="success",
        duration_seconds=time.perf_counter() - inicio,
        pipeline_version=pipeline_version,
        execution_timestamp=execution_timestamp or datetime.now(UTC),
    )


def _gravar_span_seguro(
    storage: Storage,
    *,
    run_id: UUID,
    task: str,
    status: StatusDetalhado,
    duration_seconds: float,
    pipeline_version: str,
    execution_timestamp: datetime,
) -> None:
    """Persiste o span; falha de observabilidade vira log, nunca exceção."""
    try:
        write_pipeline_task_run(
            storage,
            PipelineTaskRun(
                run_id=run_id,
                task=task,
                status=status,
                duration_seconds=max(duration_seconds, 0.0),
                pipeline_version=pipeline_version,
                execution_timestamp=execution_timestamp,
            ),
        )
    except Exception as exc:  # noqa: BLE001 — observabilidade não derruba pipeline
        logger.warning("span_task_nao_gravado", task=task, erro=str(exc))
