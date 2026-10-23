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


def _settings(tmp_path: Path, k: dict[str, float | None] | None = None) -> rc.CalibrationSettings:
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
        pooling=rc.PoolingConfig(
            k=k if k is not None else {"camara": 4.0, "senado": 64.0},
            k_grid=[1.0, 4.0, 16.0, 64.0],
            tolerance=1e-9,
            strict_casas=["camara"],
        ),
        fingerprint_decimals=10,
        fingerprint_money_decimals=2,
        robustness=rc.RobustnessConfig(
            bootstrap_samples=30,
            random_state=42,
            ci_level=0.9,
            dirichlet_samples=30,
            dirichlet_concentration=50.0,
            stability_threshold=0.9,
            distribution_quantiles=[0.05, 0.5, 0.95],
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


# ------------------------------------------------------- pooling (ADR-063)


def test_k_search_stage_runs_without_configured_k(gold: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    settings = _settings(tmp_path, k={"camara": None, "senado": None})
    report = rc.run_calibration(gold, settings, stage="k_search")
    assert report["meta"]["stage"] == "k_search"
    assert "years" not in report and "k_search" in report
    search = report["k_search"]
    assert set(search["k_argmin"]) == {"camara", "senado"}
    assert all(k in settings.pooling.k_grid for k in search["k_argmin"].values())
    assert {"casa_only", "adr062_rule", "k=1", "k=64"} <= set(search["loo_mean"]["camara"])
    assert search["n_obs"]["camara"] > search["n_obs"]["senado"]
    assert set(search["k_argmin_by_year"]) == set(YEARS)


def test_full_stage_requires_k(gold: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    settings = _settings(tmp_path, k={"camara": 4.0, "senado": None})
    with pytest.raises(rc.ConfigError, match="pooling.k is not set for \\['senado'\\]"):
        rc.run_calibration(gold, settings, stage="full")


def test_full_stage_reports_pooling_and_acceptance(gold: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    report = rc.run_calibration(gold, _settings(tmp_path), stage="full")
    pooling = report["pooling"]
    assert pooling["k"] == {"camara": 4.0, "senado": 64.0}
    assert set(pooling["acceptance"]) == {"a1", "a1_loo", "a2", "all_pass"}
    assert pooling["acceptance"]["a1_loo"]["informative"] is True
    assert len(pooling["acceptance"]["a1_loo"]["rows"]) == len(YEARS) * 2
    assert len(pooling["acceptance"]["a1"]["rows"]) == len(YEARS) * 2
    assert sum(pooling["weights"]["pooled"].values()) == pytest.approx(1.0)
    for year in YEARS:
        block = report["years"][year]["pooling"]
        assert set(block["uf_share_residual"]) == {"camara", "senado"}
        assert 0.0 < block["lambda_u"]["camara"]["quantiles"]["p50"] < 1.0
        assert block["v_pooled_vs_v"]["spearman"] <= 1.0
    markdown = rc.render_markdown(rc._clean(report))
    assert "## ADR-063 — partial pooling" in markdown and "### A1" in markdown and "### A2" in markdown


def test_cli_stages(tmp_path: Path) -> None:
    database = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(database))
    _build_gold(con)
    con.close()

    def write_config(k: dict[str, float | None]) -> Path:
        path = tmp_path / "c.yaml"
        payload = json.loads(_settings(tmp_path, k=k).model_dump_json())
        path.write_text(yaml.safe_dump({"risk_calibration": payload}), encoding="utf-8")
        return path

    no_k = write_config({"camara": None, "senado": None})
    assert rc.main(["--config", str(no_k), "--database", str(database), "--stage", "k_search"]) == 0
    markdown = next((tmp_path / "reports").glob("risk_k_search_*.md")).read_text(encoding="utf-8")
    assert "# ADR-063 — k search" in markdown
    assert rc.main(["--config", str(no_k), "--database", str(database), "--stage", "full"]) == 2

    with_k = write_config({"camara": 4.0, "senado": 64.0})
    assert rc.main(["--config", str(with_k), "--database", str(database), "--stage", "full"]) == 0
    assert list((tmp_path / "reports").glob("risk_calibration_*.json"))


def test_baseline_stage_is_default_and_needs_no_k(gold: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    settings = _settings(tmp_path, k={"camara": None, "senado": None})
    report = rc.run_calibration(gold, settings)
    assert report["meta"]["stage"] == "baseline"
    assert set(report) == {"meta", "years", "weights"}
    assert sum(report["weights"]["pooled"].values()) == pytest.approx(1.0)
    assert "pooling" not in report["years"][YEARS[0]]
    assert "ADR-063" not in rc.render_markdown(rc._clean(report))


def test_cli_default_stage_runs_without_k(tmp_path: Path) -> None:
    database = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(database))
    _build_gold(con)
    con.close()
    path = tmp_path / "c.yaml"
    payload = json.loads(_settings(tmp_path, k={"camara": None, "senado": None}).model_dump_json())
    path.write_text(yaml.safe_dump({"risk_calibration": payload}), encoding="utf-8")
    assert rc.main(["--config", str(path), "--database", str(database)]) == 0
    saved = json.loads(next((tmp_path / "reports").glob("risk_calibration_*.json")).read_text(encoding="utf-8"))
    assert saved["meta"]["stage"] == "baseline"


# ---------------------------------------------- robustness and fingerprint (Onda 2)


def test_robustness_stage_report(gold: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    settings = _settings(tmp_path, k={"camara": None, "senado": None})
    report = rc.run_calibration(gold, settings, stage="robustness")
    assert report["meta"]["stage"] == "robustness"
    assert set(report) == {"meta", "distributions", "robustness"}
    assert set(report["distributions"]["by_year"]) == set(YEARS)
    assert set(report["distributions"]["pooled"]) == set(rc.SCORE_COLUMNS)
    robustness = report["robustness"]
    assert robustness["bootstrap"]["n_draws"] == 30
    assert sum(robustness["weights"]["minmax_pooled"].values()) == pytest.approx(1.0)
    assert set(robustness["sensitivity"]) == set(YEARS)
    markdown = rc.render_markdown(rc._clean(report))
    for heading in (
        "# ADR-029",
        "## Empirical distribution of each score",
        "## Cluster bootstrap of the pooled weights",
        "## Sensitivity of the base-index ranking",
        "- data_fingerprint:",
    ):
        assert heading in markdown


def test_data_fingerprint_is_in_every_stage_stable_and_sensitive(
    gold: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    baseline = rc.run_calibration(gold, settings)
    searched = rc.run_calibration(gold, settings, stage="k_search")
    again = rc.run_calibration(gold, settings)
    fingerprint = baseline["meta"]["data_fingerprint"]
    assert searched["meta"]["data_fingerprint"] == fingerprint == again["meta"]["data_fingerprint"]
    assert fingerprint["rows"]["totals"] == 48 * len(YEARS)
    assert "- data_fingerprint: totals" in rc.render_markdown(rc._clean(baseline))

    gold.execute("UPDATE gold.risk_inputs SET expense_anomaly = expense_anomaly + 0.01 WHERE id_parlamentar = 1")
    changed = rc.run_calibration(gold, settings)["meta"]["data_fingerprint"]
    assert changed["hashes"]["external"] != fingerprint["hashes"]["external"]
    for unchanged in ("totals", "pairs", "groups", "intervals"):
        assert changed["hashes"][unchanged] == fingerprint["hashes"][unchanged]


def test_cli_robustness_stage_writes_report(tmp_path: Path) -> None:
    database = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(database))
    _build_gold(con)
    con.close()
    path = tmp_path / "c.yaml"
    payload = json.loads(_settings(tmp_path, k={"camara": None, "senado": None}).model_dump_json())
    path.write_text(yaml.safe_dump({"risk_calibration": payload}), encoding="utf-8")
    assert rc.main(["--config", str(path), "--database", str(database), "--stage", "robustness"]) == 0
    saved = json.loads(next((tmp_path / "reports").glob("risk_robustness_*.json")).read_text(encoding="utf-8"))
    assert saved["meta"]["stage"] == "robustness" and saved["meta"]["config_sha256"]
    assert next((tmp_path / "reports").glob("risk_robustness_*.md")).read_text(encoding="utf-8").startswith("# ADR-029")


def test_robustness_does_not_depend_on_physical_row_order(
    gold: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    first = rc.run_calibration(gold, settings, stage="robustness")
    for table in ("fact_despesa", "dim_parlamentar", "risk_inputs"):
        gold.execute(f"CREATE OR REPLACE TABLE gold.{table} AS SELECT * FROM gold.{table} ORDER BY random()")
    second = rc.run_calibration(gold, settings, stage="robustness")

    assert second["meta"]["data_fingerprint"] == first["meta"]["data_fingerprint"]
    one, two = first["robustness"], second["robustness"]
    for name in rc.SCORE_COLUMNS:
        assert two["weights"]["minmax_pooled"][name] == pytest.approx(one["weights"]["minmax_pooled"][name], abs=1e-9)
        for stat in ("ci_low", "ci_high", "mean"):
            assert two["bootstrap"]["scores"][name][stat] == pytest.approx(
                one["bootstrap"]["scores"][name][stat], abs=1e-9
            )
    for year in YEARS:
        for scheme in ("bootstrap_weights", "dirichlet_weights"):
            a, b = one["sensitivity"][year][scheme], two["sensitivity"][year][scheme]
            assert b["spearman"]["mean"] == pytest.approx(a["spearman"]["mean"], abs=1e-9)
            assert b["rank_interval"]["median_width"] == a["rank_interval"]["median_width"]
