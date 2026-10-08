"""Integration test: ADR-062 calibration against a synthetic Gold DuckDB."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest
import yaml

from analytics.parliamentarians import risk_calibration as rc

YEARS = [2023, 2024]


def _build_gold(con: duckdb.DuckDBPyConnection) -> None:
    """Create a small Gold: 36 deputies (3 UFs x 12) and 12 senators (2 UFs x 6)."""
    rng = np.random.default_rng(11)
    parliamentarians: list[tuple[int, str, str]] = []
    pid = 1
    for uf in ("AA", "BB", "CC"):
        for _ in range(12):
            parliamentarians.append((pid, "camara", uf))
            pid += 1
    for uf in ("DD", "EE"):
        for _ in range(6):
            parliamentarians.append((pid, "senado", uf))
            pid += 1

    dim_rows, fact_rows, input_rows = [], [], []
    surrogate = 1000
    suppliers = [f"f{i}" for i in range(15)]
    for parl_id, casa, uf in parliamentarians:
        base = float(np.exp(rng.normal(8, 0.4)))
        if parl_id == 1:
            base *= 12  # a clear high spender within its peer group
        effective = "2020-01-01"
        if parl_id == 2:  # substitute who took office in July 2024
            effective = "2024-07-01"
        versions = [(surrogate, effective, None)]
        if parl_id == 3:  # party change on 2024-04-01 (new SCD2 version)
            versions = [(surrogate, "2020-01-01", "2024-04-01"), (surrogate + 1, "2024-04-01", None)]
        for sk, start, end in versions:
            dim_rows.append((parl_id, sk, casa, uf, start, end))
        for year in YEARS:
            for month in range(1, 13):
                if parl_id == 2 and year == 2024 and month < 7:
                    continue
                active_sk = versions[-1][0] if (parl_id == 3 and year == 2024 and month >= 4) else versions[0][0]
                supplier = suppliers[int(rng.integers(0, len(suppliers)))]
                value = base * float(np.exp(rng.normal(0, 0.3)))
                fact_rows.append((parl_id, supplier, year * 10000 + month * 100 + 15, value, active_sk))
            input_rows.append(
                (parl_id, year * 10000 + 101, float(rng.random()), float(rng.random()), float(rng.random()))
            )
        surrogate += 10

    con.execute("CREATE SCHEMA gold")
    dim = pd.DataFrame(
        dim_rows, columns=["id_parlamentar", "surrogate_key", "fonte", "sigla_uf", "effective_date", "end_date"]
    )
    dim["effective_date"] = pd.to_datetime(dim["effective_date"]).dt.date
    dim["end_date"] = pd.to_datetime(dim["end_date"]).dt.date
    fact = pd.DataFrame(
        fact_rows, columns=["id_parlamentar", "id_fornecedor", "data_sk", "valor_liquido", "surrogate_key"]
    )
    inputs = pd.DataFrame(
        input_rows,
        columns=["id_parlamentar", "data_sk", "political_exposure", "expense_anomaly", "network_influence"],
    )
    for name, frame in (("dim_df", dim), ("fact_df", fact), ("inputs_df", inputs)):
        con.register(name, frame)
    con.execute("CREATE TABLE gold.dim_parlamentar AS SELECT * FROM dim_df")
    con.execute("CREATE TABLE gold.fact_despesa AS SELECT * FROM fact_df")
    con.execute("CREATE TABLE gold.risk_inputs AS SELECT * FROM inputs_df")


def _settings(tmp_path: Path) -> rc.CalibrationSettings:
    return rc.CalibrationSettings(
        window_years=YEARS,
        days_per_month=30.4375,
        n_min_pares=10,
        n_min_sensitivity=[5, 10],
        meses_min=3,
        w_min_aviso=0.05,
        min_pair_value=0.0,
        top_fraction=0.1,
        dispersion_quantiles=[(0.9, 0.1), (0.99, 0.01)],
        tables=rc.TablesConfig(fact_despesa="gold.fact_despesa", dim_parlamentar="gold.dim_parlamentar"),
        scores_source=rc.ScoresSource(
            table="gold.risk_inputs",
            id_column="id_parlamentar",
            period_expression="CAST(data_sk // 10000 AS INTEGER)",
            aggregation="mean",
            columns={"E": "political_exposure", "A": "expense_anomaly", "N": "network_influence"},
        ),
        output_dir=tmp_path / "reports",
    )


@pytest.fixture()
def gold() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    _build_gold(con)
    yield con
    con.close()


def test_full_calibration_run(gold: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    report = rc.run_calibration(gold, _settings(tmp_path))

    assert set(report["years"]) == set(YEARS)
    weights = report["weights"]
    assert sum(weights["pooled"].values()) == pytest.approx(1.0)
    assert set(weights["pooled"]) == set(rc.SCORE_COLUMNS)

    section = report["years"][2024]
    assert section["n_universe"] == 48
    assert section["n_scored"] == 48
    # Senate groups (6 members) are below n_min=10; Chamber groups (12) are not.
    assert section["groups"]["groups_below_n_min_by_casa"] == {"senado": 2}
    assert section["groups"]["share_fallback_casa"] == pytest.approx(12 / 48)
    # The substitute (id 2) took office in July 2024: ~6 months, partial-year share > 0.
    assert section["months"]["share_partial_year"] == pytest.approx(1 / 48)
    assert section["variance_decomposition"]["r2_meses"] >= 0
    assert [row["n_min"] for row in section["sensitivity_n_min"]] == [5, 10]
    assert section["d_old_vs_new"]["spearman"] <= 1.0


def test_party_change_does_not_shorten_months(gold: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    months = rc.months_in_office(rc.load_intervals(gold, settings), YEARS, settings.days_per_month)
    row = months.set_index(["id_parlamentar", "periodo"]).loc[(3, 2024)]
    assert row["dias"] == 366  # two contiguous SCD2 versions count as one stay


def test_high_spender_has_top_volume_score(gold: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    totals = rc.load_totals(gold, settings)
    groups = rc.load_groups(gold, settings)
    months = rc.months_in_office(rc.load_intervals(gold, settings), YEARS, settings.days_per_month)
    year_totals = totals.loc[totals["periodo"] == 2023].set_index("id_parlamentar")
    frame = year_totals.join(groups.loc[groups["periodo"] == 2023].set_index("id_parlamentar")[["casa", "uf"]]).join(
        months.loc[months["periodo"] == 2023].set_index("id_parlamentar")[["meses"]]
    )
    volume = rc.compute_volume_score(frame, settings.n_min_pares, settings.meses_min)
    assert volume["V"].idxmax() == 1


def test_missing_year_raises(gold: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"window_years": [2023, 2030]})
    with pytest.raises(ValueError, match="no spending rows found for year 2030"):
        rc.run_calibration(gold, settings)


def test_write_report_and_cli(tmp_path: Path) -> None:
    database = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(database))
    _build_gold(con)
    con.close()

    settings = _settings(tmp_path)
    payload = json.loads(settings.model_dump_json())
    config_path = tmp_path / "risk_calibration.yaml"
    config_path.write_text(yaml.safe_dump({"risk_calibration": payload}), encoding="utf-8")

    assert rc.main(["--config", str(config_path), "--database", str(database)]) == 0
    json_files = list((tmp_path / "reports").glob("risk_calibration_*.json"))
    md_files = list((tmp_path / "reports").glob("risk_calibration_*.md"))
    assert len(json_files) == 1 and len(md_files) == 1
    saved = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert saved["meta"]["config_sha256"]
    assert "## CRITIC weights" in md_files[0].read_text(encoding="utf-8")


def test_cli_without_database_returns_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DUCKDB_DATABASE_PATH", raising=False)
    settings = _settings(tmp_path)
    config_path = tmp_path / "c.yaml"
    config_path.write_text(
        yaml.safe_dump({"risk_calibration": json.loads(settings.model_dump_json())}), encoding="utf-8"
    )
    assert rc.main(["--config", str(config_path)]) == 2


def test_cli_returns_1_on_database_error(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    config_path = tmp_path / "c.yaml"
    config_path.write_text(
        yaml.safe_dump({"risk_calibration": json.loads(settings.model_dump_json())}), encoding="utf-8"
    )
    empty_db = tmp_path / "empty.duckdb"
    duckdb.connect(str(empty_db)).close()
    assert rc.main(["--config", str(config_path), "--database", str(empty_db)]) == 1
