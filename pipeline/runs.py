"""pipeline/runs.py — tabela de controle `pipeline_runs` (versionamento.md §4).

Em Bronze (Sprint 2), `pipeline_runs` é gravada como Parquet de controle **não
particionado** (um arquivo por `run_id`). Na Sprint 4, a camada Gold migra
essas linhas para a tabela DuckDB documentada em versionamento.md §4 — o
schema desta camada é o contrato dessa migração.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import pandas as pd
from pydantic import BaseModel

from pipeline.storage import Storage

DIRETORIO_CONTROLE = Path("controle") / "pipeline_runs"


class PipelineRun(BaseModel):
    """Uma execução do pipeline Bronze (tabela de controle, não é fato).

    Schema espelha versionamento.md §4 e adiciona `fontes_com_erro` para
    falhas isoladas (status `partial`, §5).
    """

    run_id: UUID
    pipeline_version: str
    execution_timestamp: datetime
    status: Literal["success", "failed", "partial"]
    fontes_com_erro: list[str] = []
    watermark_camara: str | None = None
    watermark_senado: str | None = None
    watermark_cgu_emenda: str | None = None
    watermark_cgu_cartao: str | None = None


def write_pipeline_run(storage: Storage, run: PipelineRun) -> None:
    """Grava a linha de controle da execução (um arquivo por run_id)."""
    df = pd.DataFrame([run.model_dump(mode="json")])
    storage.write_file(DIRETORIO_CONTROLE, df, f"{run.run_id}.parquet")
