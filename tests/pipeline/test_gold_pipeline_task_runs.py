"""Integração dbt Gold — `pipeline_task_runs` + `status_detalhado` (ADR-056 D1).

1. **Spans por task**: Parquet escritos pelo writer real
   (`write_pipeline_task_run`) consolidam em `gold.pipeline_task_runs` com
   a chave de merge `task_run_id` (`run_id__task`); rebuild é idempotente.
2. **Coluna nova em glob legado**: Parquet de `pipeline_runs` escritos
   pré-Sprint 26 (SEM `status_detalhado`) não quebram o build — a
   introspecção de schema do model preenche NULL (sem `Binder Error`).
3. **Ramo vazio**: sem arquivos, `pipeline_task_runs` nasce vazia com
   schema compatível (nunca linha fictícia, mesmo contrato do ADR-019).

Molde de `test_gold_pipeline_runs.py`: `dbtRunner` de verdade, vars com
override para diretórios temporários.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

_RAIZ = Path(__file__).resolve().parents[2]
_GOLD = _RAIZ / "pipeline" / "gold"

if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))
if str(_GOLD) not in sys.path:
    sys.path.insert(0, str(_GOLD))


def _build(tmp_path, monkeypatch, selecao: str, vars_extra: dict) -> None:
    from dbt.cli.main import dbtRunner

    from pipeline.config import get_dbt_vars

    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "gold.duckdb"))
    monkeypatch.setenv("PYTHONPATH", str(_GOLD))

    vars_dbt = {**get_dbt_vars(), **vars_extra}

    from dbt.adapters.duckdb.connections import DuckDBConnectionManager
    DuckDBConnectionManager._ENV = None

    result = dbtRunner().invoke(
        [
            "build",
            "--project-dir",
            str(_GOLD),
            "--profiles-dir",
            str(_GOLD),
            "--select",
            selecao,
            "--vars",
            json.dumps(vars_dbt),
        ]
    )
    assert result.success, result.exception


def _seed_task_runs(tmp_path: Path) -> Path:
    """Spans via writer real — prova o contrato Bronze→Gold ponta a ponta."""
    from pipeline.runs import PipelineTaskRun, write_pipeline_task_run
    from pipeline.storage import LocalParquetStorage

    storage = LocalParquetStorage(tmp_path / "bronze")
    run_id = uuid.uuid4()
    momento = datetime(2026, 9, 19, 3, 0, tzinfo=UTC)
    for task, duracao, status in (
        ("bronze_camara", 12.5, "success"),
        ("bronze_senado", 30.0, "success"),
        ("silver_camara", 5.25, "failed"),
    ):
        write_pipeline_task_run(
            storage,
            PipelineTaskRun(
                run_id=run_id,
                task=task,
                status=status,
                duration_seconds=duracao,
                pipeline_version="0.1.0",
                execution_timestamp=momento,
            ),
        )
    return tmp_path / "bronze" / "controle" / "pipeline_task_runs"


def test_task_runs_consolida_spans_e_rebuild_idempotente(tmp_path, monkeypatch):
    dir_tasks = _seed_task_runs(tmp_path)
    vars_extra = {"bronze_pipeline_task_runs_dir": str(dir_tasks / "*.parquet")}
    _build(tmp_path, monkeypatch, "+pipeline_task_runs", vars_extra)
    _build(tmp_path, monkeypatch, "+pipeline_task_runs", vars_extra)

    con = duckdb.connect(str(tmp_path / "gold.duckdb"))
    try:
        linhas = con.execute(
            "select task, status, duration_seconds from pipeline_task_runs"
            " order by task"
        ).fetchall()
    finally:
        con.close()

    assert linhas == [
        ("bronze_camara", "success", 12.5),
        ("bronze_senado", "success", 30.0),
        ("silver_camara", "failed", 5.25),
    ]


def test_task_runs_vazio_sem_arquivos(tmp_path, monkeypatch):
    dir_tasks = tmp_path / "bronze" / "controle" / "pipeline_task_runs"
    dir_tasks.mkdir(parents=True, exist_ok=True)
    _build(
        tmp_path,
        monkeypatch,
        "+pipeline_task_runs",
        {"bronze_pipeline_task_runs_dir": str(dir_tasks / "*.parquet")},
    )

    con = duckdb.connect(str(tmp_path / "gold.duckdb"))
    try:
        n = con.execute("select count(*) from pipeline_task_runs").fetchone()[0]
    finally:
        con.close()

    assert n == 0


def _seed_runs_legado_sem_detalhado(tmp_path: Path) -> Path:
    """Parquet pré-Sprint 26: SEM a coluna `status_detalhado`."""
    dir_controle = tmp_path / "bronze" / "controle" / "pipeline_runs"
    dir_controle.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "run_id": ["00000000-0000-0000-0000-000000000001"],
            "pipeline_version": ["0.0.9"],
            "execution_timestamp": ["2025-12-01T01:00:00"],
            "status": ["failed"],
            "fontes_com_erro": [["senado"]],
            "watermark_camara": ["11/2025"],
            "watermark_senado": [None],
            "watermark_cgu_emenda": [None],
            "watermark_cgu_cartao": [None],
        }
    ).to_parquet(dir_controle / "legado.parquet", index=False)
    return dir_controle


def _seed_runs_novo_com_detalhado(tmp_path: Path) -> Path:
    """Parquet Sprint 26+: COM `status_detalhado` (writer real)."""
    from pipeline.runs import PipelineRun, write_pipeline_run
    from pipeline.storage import LocalParquetStorage

    storage = LocalParquetStorage(tmp_path / "bronze")
    write_pipeline_run(
        storage,
        PipelineRun(
            run_id=uuid.uuid4(),
            pipeline_version="0.1.0",
            execution_timestamp=datetime(2026, 9, 19, 3, 0, tzinfo=UTC),
            status="partial",
            status_detalhado="warning",
            fontes_com_erro=["camara"],
        ),
    )
    return tmp_path / "bronze" / "controle" / "pipeline_runs"


def test_pipeline_runs_legado_sem_detalhado_nao_quebra_build(tmp_path, monkeypatch):
    """Glob só com arquivos legados: build passa, `status_detalhado` NULL.

    Sem a introspecção de schema do model, este cenário quebra com
    `Binder Error` (coluna ausente em TODOS os arquivos, mesmo com
    `union_by_name`) — exatamente o estado do primeiro build pós-deploy.
    """
    dir_controle = _seed_runs_legado_sem_detalhado(tmp_path)
    _build(
        tmp_path,
        monkeypatch,
        "+pipeline_runs",
        {"bronze_pipeline_runs_dir": str(dir_controle / "*.parquet")},
    )

    con = duckdb.connect(str(tmp_path / "gold.duckdb"))
    try:
        linhas = con.execute(
            "select status, status_detalhado from pipeline_runs"
        ).fetchall()
    finally:
        con.close()

    assert linhas == [("failed", None)]


def test_pipeline_runs_misto_legado_e_novo(tmp_path, monkeypatch):
    dir_controle = _seed_runs_legado_sem_detalhado(tmp_path)
    _seed_runs_novo_com_detalhado(tmp_path)
    _build(
        tmp_path,
        monkeypatch,
        "+pipeline_runs",
        {"bronze_pipeline_runs_dir": str(dir_controle / "*.parquet")},
    )

    con = duckdb.connect(str(tmp_path / "gold.duckdb"))
    try:
        linhas = con.execute(
            "select status, status_detalhado from pipeline_runs order by status"
        ).fetchall()
    finally:
        con.close()

    assert linhas == [("failed", None), ("partial", "warning")]


def test_get_dbt_vars_injeta_tasks_s3_quando_minio(monkeypatch):
    """Em produção o controle de tasks também vem do MinIO via S3."""
    monkeypatch.setenv("MINIO_ENDPOINT", "http://minio:9000")

    from pipeline import config as pipeline_config

    pipeline_config.load_env_settings.cache_clear()

    from pipeline.config import get_dbt_vars

    vars_dbt = get_dbt_vars()
    assert vars_dbt["bronze_pipeline_task_runs_dir"] == (
        "s3://bronze/controle/pipeline_task_runs/*.parquet"
    )
