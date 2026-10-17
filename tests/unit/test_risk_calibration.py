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
        "pooling": {
            "k": {"camara": None, "senado": None},
            "k_grid": [1, 4, 16],
            "tolerance": 1e-9,
            "strict_casas": ["camara"],
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


# ------------------------------------------------------- pooling (ADR-063)


def _pooled_frame(groups: dict[tuple[str, str], list[float]]) -> pd.DataFrame:
    """Frame whose ``ln x`` equals the given values (meses = 12, total = 12 * exp(v))."""
    rows = [
        (f"{casa}-{uf}-{i}", 12.0 * float(np.exp(value)), 12.0, casa, uf)
        for (casa, uf), values in groups.items()
        for i, value in enumerate(values)
    ]
    return pd.DataFrame(rows, columns=["id", "total", "meses", "casa", "uf"]).set_index("id")


def test_pooled_score_matches_hand_computation() -> None:
    frame = _pooled_frame({("camara", "A"): [1.0, 2.0, 3.0], ("camara", "B"): [4.0, 5.0, 9.0, 10.0]})
    result = rc.compute_volume_score_pooled(frame, {"camara": 2.0}, meses_min=3)
    # m_c = 4, m_A = 2, m_B = 7, lambda_A = 3/5, lambda_B = 4/6
    m_a, m_b = 0.6 * 2 + 0.4 * 4, (4 / 6) * 7 + (2 / 6) * 4
    residual = np.array([1 - m_a, 2 - m_a, 3 - m_a, 4 - m_b, 5 - m_b, 9 - m_b, 10 - m_b])
    scale = 1.4826 * np.median(np.abs(residual))
    assert result["ln_dev"].to_numpy() == pytest.approx(residual)
    assert result["z"].to_numpy() == pytest.approx(residual / scale)
    assert result["lambda_u"].iloc[0] == pytest.approx(0.6)
    assert result["lambda_u"].iloc[-1] == pytest.approx(4 / 6)
    assert (result["v_flag"] == "ok").all()
    assert result["V"].max() == 1.0


def test_pooled_with_huge_k_reproduces_casa_level_rule() -> None:
    frame = _volume_frame()
    baseline = rc.compute_volume_score(frame, n_min=1000, meses_min=3)  # every group falls back to casa
    pooled = rc.compute_volume_score_pooled(frame, {"camara": 1e12}, meses_min=3)
    assert pooled["z"].to_numpy() == pytest.approx(baseline["z"].to_numpy(), abs=1e-6)


def test_pooled_with_tiny_k_approaches_uf_median() -> None:
    frame = _pooled_frame({("camara", "A"): [1.0, 2.0, 3.0], ("camara", "B"): [4.0, 5.0, 9.0]})
    pooled = rc.compute_volume_score_pooled(frame, {"camara": 1e-9}, meses_min=3)
    assert pooled["ln_dev"].iloc[:3].to_numpy() == pytest.approx([-1.0, 0.0, 1.0], abs=1e-6)
    assert pooled["ln_dev"].iloc[3:].to_numpy() == pytest.approx([-1.0, 0.0, 4.0], abs=1e-6)


def test_pooled_guards_and_missing_k() -> None:
    frame = pd.DataFrame(
        {
            "total": [100.0, -5.0, 100.0, 100.0, 100.0],
            "meses": [12.0, 12.0, 1.0, np.nan, 12.0],
            "casa": ["camara", "camara", "camara", "camara", None],
            "uf": ["AA"] * 5,
        },
        index=list("abcde"),
    )
    result = rc.compute_volume_score_pooled(frame, {"camara": 4.0}, meses_min=3)
    assert result.loc["b", "v_flag"] == "sem_gasto_positivo"
    assert result.loc["c", "v_flag"] == "janela_curta"
    assert result.loc["d", "v_flag"] == "sem_intervalo"
    assert result.loc["e", "v_flag"] == "sem_grupo"
    assert result.loc["a", "v_flag"] == "sem_referencia"  # a lone eligible member: scale is zero
    assert (result["V"] == 0).all()
    with pytest.raises(ValueError, match="no pooling k"):
        rc.compute_volume_score_pooled(frame, {"senado": 4.0}, meses_min=3)
    with pytest.raises(ValueError, match="missing columns"):
        rc.compute_volume_score_pooled(pd.DataFrame({"total": [1.0]}), {"camara": 1.0}, 1)


def test_loo_components_and_error_sums_hand_example() -> None:
    frame = _pooled_frame({("c", "A"): [1.0, 2.0], ("c", "B"): [3.0, 5.0]})
    components = rc.loo_components(frame, meses_min=3)
    assert components["m_c_loo"].tolist() == pytest.approx([3.0, 3.0, 2.0, 2.0])
    assert components["m_u_loo"].tolist() == pytest.approx([2.0, 1.0, 5.0, 3.0])
    assert components["n_u"].tolist() == [2.0, 2.0, 2.0, 2.0]

    sums = rc.loo_error_sums(components, [1.0, 1e12, 1e-9], n_min=2)["c"]
    assert sums["casa_only"] == (pytest.approx(7.0), 4)
    assert sums["adr062_rule"][0] == pytest.approx(6.0)  # n_u = 2 >= n_min -> UF median
    assert sums["k=1"][0] == pytest.approx(4.5)
    assert sums["k=1e+12"][0] == pytest.approx(7.0, abs=1e-6)
    assert sums["k=1e-09"][0] == pytest.approx(6.0, abs=1e-6)
    assert rc.loo_error_sums(components, [1.0], n_min=3)["c"]["adr062_rule"][0] == pytest.approx(7.0)


def test_loo_components_drops_singleton_house() -> None:
    frame = _pooled_frame({("solo", "A"): [1.0]})
    assert rc.loo_components(frame, meses_min=3).empty


def test_aggregate_loo_pools_sums_not_means() -> None:
    per_year = {
        2023: {"c": {"casa_only": (10.0, 10), "k=1": (4.0, 10)}},
        2024: {"c": {"casa_only": (30.0, 30), "k=1": (6.0, 30)}},
    }
    result = rc.aggregate_loo(per_year)
    assert result["mean"]["c"]["casa_only"] == pytest.approx(1.0)
    assert result["mean"]["c"]["k=1"] == pytest.approx(10.0 / 40.0)
    assert result["n_obs"] == {"c": 40}
    assert result["by_year"][2023]["c"]["k=1"] == pytest.approx(0.4)


def test_select_k_prefers_larger_k_on_ties() -> None:
    errors = {"k=1": 1.0, "k=2": 0.5, "k=4": 0.5, "k=8": 0.9}
    assert rc.select_k(errors, [1, 2, 4, 8], 1e-9) == 4.0
    near_tie = {"k=1": 0.5, "k=2": 0.5 + 1e-12}
    assert rc.select_k(near_tie, [1, 2], 1e-9) == 2.0
    assert rc.select_k({"k=1": 0.2, "k=2": 0.9}, [1, 2], 1e-9) == 1.0


def test_uf_share_residual_known_values() -> None:
    uf = pd.Series(["A", "A", "B", "B"])
    assert rc.uf_share_residual(pd.Series([0.0, 0.0, 2.0, 2.0]), uf) == pytest.approx(1.0)
    assert rc.uf_share_residual(pd.Series([0.0, 2.0, 0.0, 2.0]), uf) == pytest.approx(0.0)
    assert math.isnan(rc.uf_share_residual(pd.Series([1.0, 1.0, 1.0, 1.0]), uf))
    assert math.isnan(rc.uf_share_residual(pd.Series([1.0, 2.0, 3.0]), pd.Series(["A", "A", "A"])))


def _acceptance(**overrides: object) -> dict:
    data = {
        "uf_residual": {
            2023: {"camara": {"baseline": 0.20, "pooled": 0.10}, "senado": {"baseline": 0.30, "pooled": 0.30}},
            2024: {"camara": {"baseline": 0.25, "pooled": 0.12}, "senado": {"baseline": 0.30, "pooled": 0.29}},
        },
        "loo_mean": {
            "camara": {"casa_only": 1.0, "adr062_rule": 0.9, "k=4": 0.8},
            "senado": {"casa_only": 1.0, "adr062_rule": 1.0, "k=64": 1.0},
        },
        "k_by_casa": {"camara": 4.0, "senado": 64.0},
        "strict_casas": ["camara"],
        "tolerance": 1e-9,
    }
    data.update(overrides)
    return rc.evaluate_acceptance(**data)  # type: ignore[arg-type]


def test_evaluate_acceptance_pass() -> None:
    result = _acceptance()
    assert result["a1"]["pass"] and result["a2"]["pass"] and result["all_pass"]
    assert len(result["a1"]["rows"]) == 4 and len(result["a2"]["rows"]) == 2


def test_evaluate_acceptance_a1_fails_when_strict_house_does_not_improve() -> None:
    bad = {2023: {"camara": {"baseline": 0.10, "pooled": 0.10}, "senado": {"baseline": 0.3, "pooled": 0.3}}}
    result = _acceptance(uf_residual=bad)
    assert not result["a1"]["pass"] and not result["all_pass"]
    assert result["a2"]["pass"]


def test_evaluate_acceptance_a1_non_strict_house_cannot_worsen() -> None:
    worse = {2023: {"camara": {"baseline": 0.2, "pooled": 0.1}, "senado": {"baseline": 0.3, "pooled": 0.4}}}
    assert not _acceptance(uf_residual=worse)["a1"]["pass"]


def test_evaluate_acceptance_a2_fails_when_chosen_k_is_worse_than_a_comparator() -> None:
    loo = {
        "camara": {"casa_only": 1.0, "adr062_rule": 0.7, "k=4": 0.8},
        "senado": {"casa_only": 1.0, "adr062_rule": 1.0, "k=64": 1.0},
    }
    result = _acceptance(loo_mean=loo)
    assert result["a1"]["pass"] and not result["a2"]["pass"] and not result["all_pass"]


def test_evaluate_acceptance_nan_or_empty_fails() -> None:
    nan = {2023: {"camara": {"baseline": float("nan"), "pooled": 0.1}}}
    assert not _acceptance(uf_residual=nan)["a1"]["pass"]
    assert not _acceptance(uf_residual={})["a1"]["pass"]
    assert not _acceptance(loo_mean={})["a2"]["pass"]


def test_attach_pooled_adds_columns_and_normalized_score() -> None:
    volume = rc.compute_volume_score(_volume_frame(), n_min=10, meses_min=3)
    scores = pd.DataFrame({"V": volume["V"].iloc[:12]})
    volume_out, scores_out = rc.attach_pooled(volume, scores, {"camara": 4.0}, meses_min=3)
    for column in ("z_pooled", "ln_dev_pooled", "lambda_u_pooled", "v_flag_pooled", "v_raw_pooled", "V_pooled"):
        assert column in volume_out.columns
    assert "V_pooled" not in scores.columns  # input untouched
    assert scores_out["V_pooled"].max() == 1.0 and scores_out["V_pooled"].min() >= 0.0
    assert scores_out["V_pooled"].idxmax() == "c0"


def test_calibrate_weights_accepts_alternative_volume_column() -> None:
    rng = np.random.default_rng(9)
    frame = pd.DataFrame(rng.random((60, len(rc.SCORE_COLUMNS))), columns=list(rc.SCORE_COLUMNS))
    frame["V_pooled"] = frame["V"] ** 2
    base = rc.calibrate_weights({2023: frame}, 0.05)
    pooled = rc.calibrate_weights({2023: frame}, 0.05, v_column="V_pooled")
    assert sum(pooled["pooled"].values()) == pytest.approx(1.0)
    assert pooled["pooled"] != base["pooled"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["pooling"].update(k={"camara": 1.0}), "exactly camara and senado"),
        (lambda p: p["pooling"].update(k={"camara": -1.0, "senado": None}), "must be > 0"),
        (lambda p: p["pooling"].update(k_grid=[1]), "at least 2"),
        (lambda p: p["pooling"].update(k_grid=[1, 1, 2]), "unique values"),
        (lambda p: p["pooling"].update(k_grid=[0, 1, 2]), "unique values"),
        (lambda p: p["pooling"].update(strict_casas=["outra"]), "subset"),
        (lambda p: p["pooling"].update(tolerance=-1), "greater than or equal to 0"),
    ],
)
def test_pooling_config_validation(tmp_path: Path, mutate, message: str) -> None:  # type: ignore[no-untyped-def]
    payload = _settings_dict()
    mutate(payload)
    with pytest.raises(rc.ConfigError, match=message):
        rc.load_settings(_write_yaml(tmp_path / "c.yaml", payload))


def test_k_columns_order_and_k_search_markdown() -> None:
    errors = {"k=16": 0.3, "casa_only": 0.5, "k=1": 0.4, "adr062_rule": 0.45}
    assert rc._k_columns(errors) == ["casa_only", "adr062_rule", "k=1", "k=16"]
    report = {
        "meta": {
            "run_id": "abc",
            "stage": "k_search",
            "execution_timestamp": "t",
            "window_years": [2023],
            "n_min_pares": 8,
        },
        "k_search": {
            "k_grid": [1, 16],
            "loo_mean": {"camara": errors},
            "n_obs": {"camara": 10},
            "k_argmin": {"camara": 16.0},
            "k_argmin_by_year": {2023: {"camara": 16.0}},
        },
    }
    markdown = rc.render_markdown(report)
    assert "# ADR-063 — k search" in markdown and "k = 16.000" in markdown


def test_loo_residuals_hand_example() -> None:
    frame = _pooled_frame({("c", "A"): [1.0, 2.0], ("c", "B"): [3.0, 5.0]})
    components = rc.loo_components(frame, meses_min=3)
    residuals = rc.loo_residuals(components, {"c": 1.0}, n_min=2)
    assert residuals["r_casa_only"].tolist() == pytest.approx([-2.0, -1.0, 1.0, 3.0])
    assert residuals["r_adr062_rule"].tolist() == pytest.approx([-1.0, 1.0, -2.0, 2.0])
    assert residuals["r_pooled"].tolist() == pytest.approx([-1.5, 0.0, -0.5, 2.5])
    fallback = rc.loo_residuals(components, {"c": 1.0}, n_min=3)  # UF too small -> house median
    assert fallback["r_adr062_rule"].tolist() == pytest.approx(residuals["r_casa_only"].tolist())


def test_evaluate_acceptance_a1_loo_is_informative_only() -> None:
    in_sample_fails = {2023: {"camara": {"baseline": 0.05, "pooled": 0.10}, "senado": {"baseline": 0.3, "pooled": 0.3}}}
    out_of_sample = {
        2023: {
            "camara": {"adr062_rule": 0.20, "pooled": 0.12, "casa_only": 0.30},
            "senado": {"adr062_rule": 0.30, "pooled": 0.30, "casa_only": 0.30},
        }
    }
    result = _acceptance(uf_residual=in_sample_fails, uf_share_loo=out_of_sample)
    assert not result["a1"]["pass"] and not result["all_pass"]  # the locked criterion still decides
    assert result["a1_loo"]["pass"] and result["a1_loo"]["informative"]
    assert result["a1_loo"]["rows"][0]["casa_only"] == 0.30
    assert not _acceptance()["a1_loo"]["pass"]  # no rows -> cannot be verified
