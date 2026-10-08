"""Unit tests for analytics.parliamentarians.risk_calibration (ADR-062)."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from analytics.parliamentarians import risk_calibration as rc

# ---------------------------------------------------------------- helpers


def _settings_dict() -> dict:
    return {
        "window_years": [2023, 2024],
        "days_per_month": 30.4375,
        "n_min_pares": 10,
        "n_min_sensitivity": [5, 10],
        "meses_min": 3,
        "w_min_aviso": 0.05,
        "min_pair_value": 0.0,
        "top_fraction": 0.1,
        "dispersion_quantiles": [[0.9, 0.1], [0.99, 0.01]],
        "tables": {"fact_despesa": "gold.fact_despesa", "dim_parlamentar": "gold.dim_parlamentar"},
        "scores_source": {
            "table": "gold.risk_inputs",
            "id_column": "id_parlamentar",
            "period_expression": "CAST(data_sk // 10000 AS INTEGER)",
            "aggregation": "mean",
            "columns": {"E": "political_exposure", "A": "expense_anomaly", "N": "network_influence"},
        },
        "output_dir": "reports/risk_calibration",
    }


def _write_yaml(path: Path, payload: dict) -> Path:
    path.write_text(yaml.safe_dump({"risk_calibration": payload}), encoding="utf-8")
    return path


# ------------------------------------------------------------ min_max etc.


def test_min_max_scales_to_unit_interval() -> None:
    result = rc.min_max(pd.Series([2.0, 4.0, 6.0]))
    assert result.tolist() == [0.0, 0.5, 1.0]


def test_min_max_constant_series_is_zero() -> None:
    assert rc.min_max(pd.Series([3.0, 3.0, 3.0])).tolist() == [0.0, 0.0, 0.0]


def test_min_max_all_nan_is_zero() -> None:
    assert rc.min_max(pd.Series([np.nan, np.nan])).tolist() == [0.0, 0.0]


def test_spearman_monotone_relation_is_one() -> None:
    left = pd.Series([1, 2, 3, 4, 5])
    assert rc.spearman(left, left**3) == pytest.approx(1.0)
    assert rc.spearman(left, -left) == pytest.approx(-1.0)


def test_jaccard_top_identical_and_disjoint() -> None:
    values = pd.Series(range(20), index=list("abcdefghijklmnopqrst"), dtype=float)
    assert rc.jaccard_top(values, values, 0.1) == 1.0
    assert rc.jaccard_top(values, -values, 0.1) == 0.0


def test_compare_rankings_identical_scores() -> None:
    values = pd.Series(np.linspace(0, 1, 30))
    result = rc.compare_rankings(values, values, 0.1)
    assert result["spearman"] == pytest.approx(1.0)
    assert result["jaccard_top"] == 1.0
    assert result["mean_rank_shift"] == 0.0


def test_dispersion_ratio_basic_and_guards() -> None:
    values = pd.Series(np.arange(1, 101, dtype=float))
    assert rc.dispersion_ratio(values, 0.9, 0.1) == pytest.approx(
        values.quantile(0.9) / values.quantile(0.1)
    )
    assert math.isnan(rc.dispersion_ratio(pd.Series(dtype=float), 0.9, 0.1))
    assert math.isnan(rc.dispersion_ratio(pd.Series([0.0, 0.0, 1.0]), 0.9, 0.1))


# ------------------------------------------------------------------ CRITIC


def test_critic_weights_sum_to_one_and_penalize_redundancy() -> None:
    rng = np.random.default_rng(0)
    a = rng.random(300)
    frame = pd.DataFrame({"a": a, "b": a, "c": rng.random(300)})
    weights = rc.critic_weights(frame)
    assert weights.sum() == pytest.approx(1.0)
    assert weights["c"] > weights["a"]
    assert weights["a"] == pytest.approx(weights["b"])


def test_critic_constant_column_has_zero_weight_and_does_not_inflate_others() -> None:
    rng = np.random.default_rng(1)
    base = pd.DataFrame({"a": rng.random(200), "b": rng.random(200)})
    with_constant = base.assign(k=0.5)
    weights = rc.critic_weights(with_constant)
    reference = rc.critic_weights(base)
    assert weights["k"] == 0.0
    assert weights["a"] == pytest.approx(reference["a"])
    assert weights["b"] == pytest.approx(reference["b"])


def test_critic_all_constant_raises() -> None:
    with pytest.raises(ValueError, match="zero standard deviation"):
        rc.critic_weights(pd.DataFrame({"a": [1.0, 1.0, 1.0], "b": [2.0, 2.0, 2.0]}))


# ------------------------------------------------------------ robust_log_z


def test_robust_log_z_monotone_within_group() -> None:
    x = pd.Series([1.0, 2.0, 4.0, 8.0, 16.0])
    z = rc.robust_log_z(x, pd.Series(["g"] * 5))
    assert z.is_monotonic_increasing
    assert z.iloc[2] == pytest.approx(0.0)


def test_robust_log_z_nan_for_nonpositive_and_zero_mad() -> None:
    x = pd.Series([0.0, 1.0, 2.0, 4.0])
    z = rc.robust_log_z(x, pd.Series(["g"] * 4))
    assert math.isnan(z.iloc[0])
    flat = rc.robust_log_z(pd.Series([5.0, 5.0, 5.0]), pd.Series(["g"] * 3))
    assert flat.isna().all()


# ------------------------------------------------------ months in office


def _ts(year: int, month: int, day: int = 1) -> pd.Timestamp:
    return pd.Timestamp(year=year, month=month, day=day)


def test_merge_intervals_joins_adjacent_and_drops_invalid() -> None:
    merged = rc.merge_intervals(
        [(_ts(2023, 7), _ts(2024, 1)), (_ts(2023, 1), _ts(2023, 7)), (_ts(2023, 5), _ts(2023, 5))]
    )
    assert merged == [(_ts(2023, 1), _ts(2024, 1))]


def test_months_in_office_party_change_gap_open_end_and_invalid() -> None:
    intervals = pd.DataFrame(
        [
            (1, date(2022, 2, 1), date(2023, 7, 1)),  # party change at 2023-07-01
            (1, date(2023, 7, 1), None),
            (2, date(2023, 3, 1), date(2023, 6, 1)),
            (3, date(2023, 1, 1), date(2023, 2, 1)),  # two disjoint stints
            (3, date(2023, 3, 1), date(2023, 4, 1)),
            (4, date(2023, 5, 1), date(2023, 4, 1)),  # inverted -> skipped
        ],
        columns=["id_parlamentar", "start", "end"],
    )
    result = rc.months_in_office(intervals, [2023, 2024], 30.4375).set_index(["id_parlamentar", "periodo"])
    assert result.loc[(1, 2023), "dias"] == 365
    assert result.loc[(1, 2024), "dias"] == 366
    assert result.loc[(2, 2023), "dias"] == 92
    assert result.loc[(3, 2023), "dias"] == 62
    assert (3, 2024) not in result.index
    assert 4 not in result.index.get_level_values("id_parlamentar")
    assert result.loc[(2, 2023), "meses"] == pytest.approx(92 / 30.4375)


def test_months_in_office_requires_columns() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        rc.months_in_office(pd.DataFrame({"id_parlamentar": [1]}), [2023], 30.4375)


# -------------------------------------------------------------------- HHI


def test_hhi_scores_known_values_and_negative_pairs_excluded() -> None:
    pairs = pd.DataFrame(
        {
            "id_parlamentar": [1, 1, 2, 2],
            "id_fornecedor": ["f1", "f2", "f1", "f3"],
            "valor": [60.0, 40.0, 100.0, -50.0],  # (2, f3) is excluded
        }
    )
    result = rc.hhi_scores(pairs, 0.0)
    assert result.loc[1, "hhi_p"] == pytest.approx(0.52)
    assert result.loc[1, "d_new_raw"] == pytest.approx(0.6 * 0.53125 + 0.4 * 1.0)
    assert result.loc[1, "d_old_raw"] == pytest.approx((0.53125 + 1.0) / 2)
    assert result.loc[2, "hhi_p"] == pytest.approx(1.0)
    assert result.loc[2, "d_new_raw"] == pytest.approx(0.53125)


# ----------------------------------------------------------- volume score


def _volume_frame() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    for i in range(12):  # camara / AA: large group
        rows.append((f"c{i}", 12 * float(np.exp(rng.normal(10, 0.2))), 12.0, "camara", "AA"))
    rows[0] = ("c0", 12 * float(np.exp(10 + 2.5)), 12.0, "camara", "AA")  # ~12x peers
    for i in range(3):  # camara / BB: small group -> fallback to casa
        rows.append((f"s{i}", 12 * float(np.exp(rng.normal(10, 0.2))), 12.0, "camara", "BB"))
    return pd.DataFrame(rows, columns=["id", "total", "meses", "casa", "uf"]).set_index("id")


def test_volume_score_flags_outlier_and_uses_uf_then_casa_fallback() -> None:
    result = rc.compute_volume_score(_volume_frame(), n_min=10, meses_min=3)
    assert result["V"].idxmax() == "c0"
    assert result["V"].max() == 1.0
    assert (result.loc[result.index.str.startswith("c") & (result["uf"] == "AA"), "v_group"] == "uf").all()
    assert (result.loc[result["uf"] == "BB", "v_group"] == "casa").all()
    assert (result["v_flag"] == "ok").all()


def test_volume_score_guards() -> None:
    frame = pd.DataFrame(
        {
            "total": [100.0, -5.0, 100.0, 100.0, 100.0, 100.0],
            "meses": [12.0, 12.0, 1.0, np.nan, 12.0, 12.0],
            "casa": ["camara"] * 4 + [None, "camara"],
            "uf": ["AA"] * 4 + ["AA", "AA"],
        },
        index=list("abcdef"),
    )
    frame.loc["f", "total"] = 400.0
    result = rc.compute_volume_score(frame, n_min=1, meses_min=3)
    assert result.loc["b", "v_flag"] == "sem_gasto_positivo"
    assert result.loc["c", "v_flag"] == "janela_curta"
    assert result.loc["d", "v_flag"] == "sem_intervalo"
    assert result.loc["e", "v_flag"] == "sem_grupo"
    assert (result.loc[list("bcde"), "V"] == 0).all()
    assert (result["V"] >= 0).all() and (result["V"] <= 1).all()


def test_volume_score_zero_mad_falls_back_then_sem_referencia() -> None:
    flat_uf = pd.DataFrame(
        {
            "total": [120.0] * 4 + [100.0, 200.0, 400.0, 800.0],
            "meses": [12.0] * 8,
            "casa": ["camara"] * 8,
            "uf": ["AA"] * 4 + ["BB"] * 4,
        }
    )
    result = rc.compute_volume_score(flat_uf, n_min=2, meses_min=3)
    assert (result.loc[result["uf"] == "AA", "v_group"] == "casa").all()
    all_flat = pd.DataFrame({"total": [120.0] * 4, "meses": [12.0] * 4, "casa": ["camara"] * 4, "uf": ["AA"] * 4})
    flat_result = rc.compute_volume_score(all_flat, n_min=2, meses_min=3)
    assert (flat_result["v_flag"] == "sem_referencia").all()
    assert (flat_result["V"] == 0).all()


def test_volume_score_requires_columns() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        rc.compute_volume_score(pd.DataFrame({"total": [1.0]}), 1, 1)


# --------------------------------------------------- variance decomposition


def test_variance_decomposition_attributes_variance_to_months_and_uf() -> None:
    rng = np.random.default_rng(3)
    n = 400
    meses = rng.uniform(1, 12, n)
    uf = rng.choice(["AA", "BB", "CC", "DD"], n)
    effect = pd.Series(uf).map({"AA": 0.0, "BB": 0.8, "CC": -0.6, "DD": 1.5}).to_numpy()
    casa = rng.choice(["camara", "senado"], n)
    frame = pd.DataFrame(
        {"total": np.exp(np.log(meses) + effect + rng.normal(0, 0.05, n)), "meses": meses, "uf": uf, "casa": casa}
    )
    result = rc.variance_decomposition(frame)
    assert result["r2_meses"] < result["r2_meses_uf"] <= result["r2_meses_uf_casa"] <= 1.0
    assert result["delta_uf"] > 0.3
    assert result["delta_casa"] < 0.02
    assert result["r2_meses_uf"] > 0.95


def test_variance_decomposition_guards() -> None:
    with pytest.raises(ValueError, match="at least one row"):
        rc.variance_decomposition(pd.DataFrame(columns=["total", "meses", "uf", "casa"]))
    constant = pd.DataFrame({"total": [5.0, 5.0, 5.0], "meses": [1.0, 2.0, 3.0], "uf": list("ABC"), "casa": ["x"] * 3})
    with pytest.raises(ValueError, match="constant"):
        rc.variance_decomposition(constant)


# ------------------------------------------------------------ CRITIC pool


def test_calibrate_weights_pooled_and_by_year() -> None:
    rng = np.random.default_rng(5)

    def year_frame() -> pd.DataFrame:
        return pd.DataFrame(rng.random((80, len(rc.SCORE_COLUMNS))), columns=list(rc.SCORE_COLUMNS))

    result = rc.calibrate_weights({2023: year_frame(), 2024: year_frame()}, w_min_aviso=0.5)
    assert sum(result["pooled"].values()) == pytest.approx(1.0)
    assert set(result["by_year"]) == {2023, 2024}
    assert result["below_w_min_aviso"]["pooled"]  # no weight can reach 0.5 with six scores
    assert set(result["cross_year_range"]) == set(rc.SCORE_COLUMNS)


# ------------------------------------------------------------------ config


def test_load_settings_valid(tmp_path: Path) -> None:
    settings = rc.load_settings(_write_yaml(tmp_path / "c.yaml", _settings_dict()))
    assert settings.window_years == [2023, 2024]
    assert settings.scores_source.columns["E"] == "political_exposure"
    assert settings.output_dir == Path("reports/risk_calibration")


def test_load_settings_required_fields_fail_loudly(tmp_path: Path) -> None:
    payload = _settings_dict()
    payload["scores_source"]["table"] = None
    with pytest.raises(rc.ConfigError, match="invalid risk_calibration settings"):
        rc.load_settings(_write_yaml(tmp_path / "c.yaml", payload))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["tables"].update(fact_despesa="gold.f; DROP TABLE x"), "invalid SQL identifier"),
        (lambda p: p["scores_source"].update(period_expression="year -- x"), "single plain expression"),
        (lambda p: p["scores_source"].update(columns={"E": "e", "A": "a"}), "exactly E, A and N"),
        (lambda p: p.update(dispersion_quantiles=[[0.1, 0.9]]), "0<low<high<1"),
        (lambda p: p.update(unexpected_key=1), "unexpected_key"),
        (lambda p: p.update(n_min_sensitivity=[0]), "must be >= 1"),
    ],
)
def test_load_settings_rejects_invalid_values(tmp_path: Path, mutate, message: str) -> None:  # type: ignore[no-untyped-def]
    payload = _settings_dict()
    mutate(payload)
    with pytest.raises(rc.ConfigError, match=message):
        rc.load_settings(_write_yaml(tmp_path / "c.yaml", payload))


def test_load_settings_missing_file_and_missing_section(tmp_path: Path) -> None:
    with pytest.raises(rc.ConfigError, match="cannot read"):
        rc.load_settings(tmp_path / "absent.yaml")
    other = tmp_path / "other.yaml"
    other.write_text("foo: 1\n", encoding="utf-8")
    with pytest.raises(rc.ConfigError, match="risk_calibration"):
        rc.load_settings(other)


# --------------------------------------------------------------- reporting


def test_clean_makes_report_json_safe() -> None:
    cleaned = rc._clean({1: np.float64("nan"), "a": [np.int64(3), float("inf")], "b": (np.float64(1.5),)})
    assert cleaned == {"1": None, "a": [3, None], "b": [1.5]}


def test_main_returns_2_on_config_error(tmp_path: Path) -> None:
    assert rc.main(["--config", str(tmp_path / "absent.yaml")]) == 2
