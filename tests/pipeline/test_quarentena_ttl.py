"""TTL da quarentena (Sprint 24, ADR-054, Onda 2).

Prova que `purgar_quarentena_antiga` mantém os N runs mais recentes e
remove só o excedente, sem tocar outras tabelas e sem lançar em erro.
Roda em DuckDB temporário (parâmetro `caminho`) — nunca no Gold real.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from pipeline.silver import RETENCAO_QUARENTENA_RUNS, purgar_quarentena_antiga


def _banco(tmp_path: Path, runs: int) -> Path:
    db = tmp_path / "ttl.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA silver")
    con.execute(
        "CREATE TABLE silver.quarantine_t "
        "(run_id VARCHAR, execution_timestamp TIMESTAMP, v INTEGER)"
    )
    con.execute("CREATE TABLE silver.outra (run_id VARCHAR, v INTEGER)")
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(runs):
        con.execute(
            "INSERT INTO silver.quarantine_t VALUES (?, ?, ?)",
            [f"r{i:02d}", base + timedelta(days=i), i],
        )
    con.execute("INSERT INTO silver.outra VALUES ('x', 1)")
    con.close()
    return db


def test_purga_mantem_n_mais_recentes(tmp_path: Path):
    db = _banco(tmp_path, 20)
    removidas = purgar_quarentena_antiga(manter_ultimos_n_runs=15, caminho=db)
    assert removidas == 5
    con = duckdb.connect(str(db), read_only=True)
    try:
        restam = con.execute(
            "SELECT count(*), min(run_id), max(run_id) FROM silver.quarantine_t"
        ).fetchone()
        outra = con.execute("SELECT count(*) FROM silver.outra").fetchone()[0]
    finally:
        con.close()
    assert restam == (15, "r05", "r19")
    assert outra == 1


def test_purga_sem_excedente_remove_nada(tmp_path: Path):
    db = _banco(tmp_path, 3)
    assert purgar_quarentena_antiga(caminho=db) == 0
    con = duckdb.connect(str(db), read_only=True)
    try:
        total = con.execute("SELECT count(*) FROM silver.quarantine_t").fetchone()[0]
    finally:
        con.close()
    assert total == 3
    assert RETENCAO_QUARENTENA_RUNS == 15
