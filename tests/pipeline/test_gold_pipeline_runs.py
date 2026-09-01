# tests/pipeline/test_gold_pipeline_runs.py
"""Integração dbt Gold — controle `pipeline_runs` (ADR-019).

Regressão dos corretivos QA encontrados no E2E real (Sprint 6.5):

1. **Glob relativo ao cwd**: o DuckDB resolve `read_parquet('...glob...')`
   relativo ao CWD do processo, não ao arquivo do banco. O default
   `bronze_pipeline_runs_dir` (`dbt_project.yml`) é relativo ao repo root
   (`data/bronze/...`) — `../../data/...` resolvia a 0 arquivos e a tabela
   de controle ficava vazia.

2. **Tipos mistos de `fontes_com_erro`**: arquivos de controle escritos por
   versões antigas gravam a lista vazia como `INTEGER[]` e a não vazia como
   `VARCHAR[]` (pyarrow infere da primeira). O `read_parquet` do glob exige
   `union_by_name = true` + `cast(... as varchar[])` para consolidar.

Coberto com `dbtRunner` de verdade (molde de `test_gold_analytics.py`),
apontando `bronze_pipeline_runs_dir` para um diretório temporário com dois
Parquet de controle de tipos divergentes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

_RAIZ = Path(__file__).resolve().parents[2]
_GOLD = _RAIZ / "pipeline" / "gold"

if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))
if str(_GOLD) not in sys.path:
    sys.path.insert(0, str(_GOLD))


def _build(tmp_path, monkeypatch, dir_controle: Path) -> None:
    from dbt.cli.main import dbtRunner

    from pipeline.config import get_dbt_vars

    monkeypatch.setenv("DUCKDB_DATABASE_PATH", str(tmp_path / "gold.duckdb"))
    monkeypatch.setenv("PYTHONPATH", str(_GOLD))

    vars_dbt = {**get_dbt_vars(), "bronze_pipeline_runs_dir": str(dir_controle / "*.parquet")}

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
            "+pipeline_runs",
            "--vars",
            json.dumps(vars_dbt),
        ]
    )
    assert result.success, result.exception


def _seed_controle_tipos_mistos(tmp_path: Path) -> Path:
    """Gera dois Parquet de controle com `fontes_com_erro` de tipos divergentes.

    O arquivo legado (lista vazia) era gravado como `INTEGER[]` pelo pyarrow
    (inferência de lista sem elementos); o atual (não vazio) como `VARCHAR[]`.
    Reproduz a incompatibilidade que derrubava o `read_parquet` do glob.
    """
    dir_controle = tmp_path / "bronze" / "controle" / "pipeline_runs"
    dir_controle.mkdir(parents=True, exist_ok=True)

    df_legado = pd.DataFrame(
        {
            "run_id": ["00000000-0000-0000-0000-000000000001"],
            "pipeline_version": ["0.0.1"],
            "execution_timestamp": ["2025-01-01T00:00:00"],
            "status": ["success"],
            "fontes_com_erro": [[]],
            "watermark_camara": ["01/2025"],
            "watermark_senado": ["2025"],
            "watermark_cgu_emenda": ["2025"],
            "watermark_cgu_cartao": ["01/2025"],
        }
    )
    df_legado.to_parquet(dir_controle / "00000000-0000-0000-0000-000000000001.parquet", index=False)

    df_atual = pd.DataFrame(
        {
            "run_id": ["00000000-0000-0000-0000-000000000002"],
            "pipeline_version": ["0.1.0"],
            "execution_timestamp": ["2026-08-12T00:00:00"],
            "status": ["partial"],
            "fontes_com_erro": [["transparencia_cartoes"]],
            "watermark_camara": ["08/2026"],
            "watermark_senado": ["2026"],
            "watermark_cgu_emenda": ["2026"],
            "watermark_cgu_cartao": [None],
        }
    )
    df_atual.to_parquet(dir_controle / "00000000-0000-0000-0000-000000000002.parquet", index=False)
    return dir_controle


def test_pipeline_runs_consolida_tipos_mistos(tmp_path, monkeypatch):
    """O glob de controle resolve com `union_by_name` e o cast para varchar[].

    O build com `+pipeline_runs` deve ler os DOIS Parquet (legado INTEGER[] e
    atual VARCHAR[]) e consolidar `fontes_com_erro` como lista de strings —
    sem "Unimplemented type for cast (VARCHAR -> NULL)".
    """
    dir_controle = _seed_controle_tipos_mistos(tmp_path)
    _build(tmp_path, monkeypatch, dir_controle)

    con = duckdb.connect(str(tmp_path / "gold.duckdb"))
    try:
        linhas = con.execute(
            "select run_id, status, fontes_com_erro from pipeline_runs"
            " order by run_id"
        ).fetchall()
    finally:
        con.close()

    assert linhas == [
        ("00000000-0000-0000-0000-000000000001", "success", []),
        ("00000000-0000-0000-0000-000000000002", "partial", ["transparencia_cartoes"]),
    ]


def test_pipeline_runs_vazio_sem_arquivos(tmp_path, monkeypatch):
    """Sem arquivos de controle, `pipeline_runs` nasce vazia com schema ok.

    O ramo vazio espelha `fontes_com_erro` como `varchar[]` — o MERGE
    incremental do modelo não deve falhar por incompatibilidade de tipo.
    """
    dir_controle = tmp_path / "bronze" / "controle" / "pipeline_runs"
    dir_controle.mkdir(parents=True, exist_ok=True)
    _build(tmp_path, monkeypatch, dir_controle)

    con = duckdb.connect(str(tmp_path / "gold.duckdb"))
    try:
        n = con.execute("select count(*) from pipeline_runs").fetchone()[0]
        tipo = con.execute(
            "select data_type from information_schema.columns"
            " where table_name = 'pipeline_runs' and column_name = 'fontes_com_erro'"
        ).fetchone()[0]
    finally:
        con.close()

    assert n == 0
    assert tipo == "VARCHAR[]"


def test_get_dbt_vars_injeta_s3_quando_minio(monkeypatch):
    """Em produção (MINIO_ENDPOINT setado), o controle vem do MinIO via S3.

    ADR-019: a Bronze grava `pipeline_runs` no MinIO (storage MinIO). Sem o
    override, o dbt Gold leria do glob local (`data/bronze/...`), que resolve
    0 arquivos em produção — o sintoma "pipeline_runs zero-linhas". O var
    injetado deve apontar para o S3 path-style do bucket configurado.
    """
    monkeypatch.setenv("MINIO_ENDPOINT", "http://minio:9000")

    from pipeline import config as pipeline_config

    pipeline_config.load_env_settings.cache_clear()

    from pipeline.config import get_dbt_vars

    vars_dbt = get_dbt_vars()
    assert vars_dbt["bronze_pipeline_runs_dir"] == (
        "s3://bronze/controle/pipeline_runs/*.parquet"
    )


def test_get_dbt_vars_sem_minio_mantem_local(monkeypatch):
    """Sem MinIO (dev/teste), o controle é lido do glob local padrão.

    `get_dbt_vars` NÃO deve injetar o var — o dbt usa o default do
    `dbt_project.yml` (`data/bronze/controle/pipeline_runs/*.parquet`).
    """
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)

    from pipeline import config as pipeline_config

    pipeline_config.load_env_settings.cache_clear()

    from pipeline.config import get_dbt_vars

    vars_dbt = get_dbt_vars()
    assert "bronze_pipeline_runs_dir" not in vars_dbt
