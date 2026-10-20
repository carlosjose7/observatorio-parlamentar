"""Offline calibration of the ADR-062 risk index (Sprint 29).

Reads the Gold layer (read-only), builds the six scores per
parliamentarian-year (C, D, E, A, N, V), estimates CRITIC weights on a
pooled reference window and per year, and reports the diagnostics that
ADR-062 requires before a ``model_version`` is frozen:

* CRITIC weights (pooled and per year) and weights below ``w_min_aviso``;
* Spearman(C, D) and Spearman(V, other scores);
* variance decomposition of ``ln(total)`` (months -> + UF -> + house);
* raw vs residual dispersion (p90/p10, p99/p1);
* sensitivity of the volume score to ``n_min_pares``;
* old (simple mean) vs new (value-weighted) supplier-dependency score;
* ADR-063 partial pooling of the volume score: leave-one-out search of the
  shrinkage ``k`` (``--stage k_search``) and the acceptance criteria A1/A2
  with the chosen ``k`` (``--stage full``);
* a data fingerprint (digests and control totals of the inputs) in every report;
* ``--stage robustness`` (ADR-029 criteria): empirical score distributions, cluster
  bootstrap of the CRITIC weights, CRITIC on percentile ranks and the sensitivity of
  the base-index ranking to the weight vector.

This module does not train the Isolation Forest, does not write to the
warehouse and does not persist a model artifact. Those steps belong to
later waves of the sprint.

Usage:
    python -m analytics.parliamentarians.risk_calibration \
        --config config/risk_calibration.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb
import numpy as np
import pandas as pd
import structlog
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

logger = structlog.get_logger(__name__)

#: Order of the six ADR-062 scores. Contract of the weight vector.
SCORE_COLUMNS: tuple[str, ...] = ("C", "D", "E", "A", "N", "V")

#: Consistency constant that makes MAD comparable to a standard deviation
#: under normality (ADR-062, item 4).
MAD_SCALE: float = 1.4826

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_FORBIDDEN_SQL_TOKENS: tuple[str, ...] = (";", "--", "/*", "*/")
_AGGREGATIONS: dict[str, str] = {"mean": "avg", "median": "median", "max": "max"}


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


class ConfigError(ValueError):
    """Raised when the calibration configuration is missing or invalid."""


def _check_identifier(value: str) -> str:
    """Validate a (possibly schema-qualified) SQL identifier.

    Args:
        value: Identifier such as ``gold.fact_despesa``.

    Returns:
        The same value, if valid.

    Raises:
        ValueError: If the value is not a plain SQL identifier.
    """
    if not _IDENTIFIER.match(value):
        raise ValueError(f"invalid SQL identifier: {value!r}")
    return value


class TablesConfig(BaseModel):
    """Gold tables read by the calibration."""

    model_config = ConfigDict(extra="forbid")

    fact_despesa: str
    dim_parlamentar: str

    @field_validator("fact_despesa", "dim_parlamentar")
    @classmethod
    def _identifier(cls, value: str) -> str:
        return _check_identifier(value)


class ScoresSource(BaseModel):
    """Where the E, A and N scores live (already computed upstream)."""

    model_config = ConfigDict(extra="forbid")

    table: str
    id_column: str
    period_expression: str
    aggregation: Literal["mean", "median", "max"]
    columns: dict[str, str]

    @field_validator("table", "id_column")
    @classmethod
    def _identifier(cls, value: str) -> str:
        return _check_identifier(value)

    @field_validator("period_expression")
    @classmethod
    def _period_expression(cls, value: str) -> str:
        if any(token in value for token in _FORBIDDEN_SQL_TOKENS):
            raise ValueError("period_expression must be a single plain expression")
        if not value.strip():
            raise ValueError("period_expression must not be empty")
        return value

    @field_validator("columns")
    @classmethod
    def _columns(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != {"E", "A", "N"}:
            raise ValueError("columns must map exactly E, A and N")
        for column in value.values():
            _check_identifier(column)
        return value


class PoolingConfig(BaseModel):
    """Partial-pooling settings of the volume score (ADR-063, item 7)."""

    model_config = ConfigDict(extra="forbid")

    k: dict[str, float | None]
    k_grid: list[float] = Field(min_length=2)
    tolerance: float = Field(ge=0)
    strict_casas: list[str]

    @field_validator("k")
    @classmethod
    def _k(cls, value: dict[str, float | None]) -> dict[str, float | None]:
        if set(value) != {"camara", "senado"}:
            raise ValueError("k must define exactly camara and senado (null = not calibrated yet)")
        if any(k is not None and k <= 0 for k in value.values()):
            raise ValueError("k values must be > 0")
        return value

    @field_validator("k_grid")
    @classmethod
    def _grid(cls, value: list[float]) -> list[float]:
        if any(k <= 0 for k in value) or len(set(value)) != len(value):
            raise ValueError("k_grid must hold unique values > 0")
        return value

    @model_validator(mode="after")
    def _strict(self) -> PoolingConfig:
        if not set(self.strict_casas) <= set(self.k):
            raise ValueError("strict_casas must be a subset of the houses in k")
        return self


class RobustnessConfig(BaseModel):
    """Weight-robustness and sensitivity settings (ADR-029 criteria; ``--stage robustness``)."""

    model_config = ConfigDict(extra="forbid")

    bootstrap_samples: int = Field(ge=2)
    random_state: int
    ci_level: float = Field(gt=0, lt=1)
    dirichlet_samples: int = Field(ge=2)
    dirichlet_concentration: float = Field(gt=0)
    stability_threshold: float = Field(gt=0, le=1)
    distribution_quantiles: list[float] = Field(min_length=1)

    @field_validator("distribution_quantiles")
    @classmethod
    def _quantiles(cls, value: list[float]) -> list[float]:
        if any(not 0 < q < 1 for q in value) or len(set(value)) != len(value):
            raise ValueError("distribution_quantiles must be unique values in (0, 1)")
        return value


class CalibrationSettings(BaseModel):
    """Validated settings of the calibration (``config/risk_calibration.yaml``)."""

    model_config = ConfigDict(extra="forbid")

    window_years: list[int] = Field(min_length=1)
    days_per_month: float = Field(gt=0)
    n_min_pares: int = Field(ge=1)
    n_min_sensitivity: list[int] = Field(min_length=1)
    meses_min: float = Field(ge=0)
    w_min_aviso: float = Field(ge=0, le=1)
    min_pair_value: float = Field(ge=0)
    top_fraction: float = Field(gt=0, lt=1)
    dispersion_quantiles: list[tuple[float, float]] = Field(min_length=1)
    tables: TablesConfig
    scores_source: ScoresSource
    pooling: PoolingConfig
    robustness: RobustnessConfig
    fingerprint_decimals: int = Field(ge=0, le=15)
    fingerprint_money_decimals: int = Field(ge=0, le=6)
    output_dir: Path

    @field_validator("n_min_sensitivity")
    @classmethod
    def _positive_n(cls, value: list[int]) -> list[int]:
        if any(n < 1 for n in value):
            raise ValueError("n_min_sensitivity values must be >= 1")
        return value

    @model_validator(mode="after")
    def _quantile_pairs(self) -> CalibrationSettings:
        for high, low in self.dispersion_quantiles:
            if not 0 < low < high < 1:
                raise ValueError("dispersion_quantiles must be [high, low] with 0<low<high<1")
        return self


def load_settings(path: Path) -> CalibrationSettings:
    """Load and validate the calibration settings from YAML.

    Args:
        path: Path to ``risk_calibration.yaml``.

    Returns:
        Validated settings.

    Raises:
        ConfigError: If the file is unreadable, malformed or incomplete.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("risk_calibration"), dict):
        raise ConfigError(f"{path} must contain a 'risk_calibration' mapping")
    try:
        return CalibrationSettings(**raw["risk_calibration"])
    except ValidationError as exc:
        raise ConfigError(f"invalid risk_calibration settings in {path}:\n{exc}") from exc


# --------------------------------------------------------------------------
# Statistical helpers (pure functions)
# --------------------------------------------------------------------------


def min_max(values: pd.Series) -> pd.Series:
    """Min-Max normalize to [0, 1]; a constant series maps to zeros.

    Args:
        values: Numeric series.

    Returns:
        Normalized series with the same index.
    """
    low, high = values.min(), values.max()
    if not (np.isfinite(low) and np.isfinite(high)) or high == low:
        return pd.Series(0.0, index=values.index)
    return (values - low) / (high - low)


def spearman(left: pd.Series, right: pd.Series) -> float:
    """Spearman correlation via ranks (no SciPy dependency).

    Args:
        left: First series.
        right: Second series, aligned on the index.

    Returns:
        Correlation, or NaN when undefined.
    """
    return float(left.rank().corr(right.rank()))


def critic_weights(scores: pd.DataFrame) -> pd.Series:
    """CRITIC weights with Spearman correlation and ``(1 - r)``.

    Constant columns get weight zero and are excluded from the
    correlation sum of the other columns (ADR-062, item 3).

    Args:
        scores: One row per parliamentarian-period, one column per score,
            already Min-Max normalized.

    Returns:
        Weights indexed by score name, summing to one.

    Raises:
        ValueError: If every score has zero standard deviation.
    """
    sigma = scores.std(ddof=1).fillna(0.0)
    active = sigma > 0
    if not active.any():
        raise ValueError("all scores have zero standard deviation; CRITIC is undefined")
    corr = scores.loc[:, active].rank().corr().fillna(0.0)
    information = pd.Series(0.0, index=scores.columns)
    information.loc[active] = sigma[active] * (1.0 - corr).sum(axis=1)
    return information / information.sum()


def _robust_log_stats(x: pd.Series, group: pd.Series) -> pd.DataFrame:
    """Group-wise log deviation from the median and log-MAD.

    Args:
        x: Positive values (non-positive become NaN).
        group: Group label aligned with ``x``.

    Returns:
        Frame with ``ln_dev`` (ln x minus group median) and ``mad``.
    """
    log_x = np.log(x.where(x > 0))
    median = log_x.groupby(group).transform("median")
    ln_dev = log_x - median
    mad = ln_dev.abs().groupby(group).transform("median")
    return pd.DataFrame({"ln_dev": ln_dev, "mad": mad})


def robust_log_z(x: pd.Series, group: pd.Series) -> pd.Series:
    """Robust z-score of ``ln(x)`` within groups (median / 1.4826 * MAD).

    Args:
        x: Positive values.
        group: Group label aligned with ``x``.

    Returns:
        Robust z; NaN where ``x <= 0`` or the group MAD is zero.
    """
    stats = _robust_log_stats(x, group)
    return stats["ln_dev"] / (MAD_SCALE * stats["mad"].where(stats["mad"] > 0))


def jaccard_top(left: pd.Series, right: pd.Series, fraction: float) -> float:
    """Jaccard overlap between the top-``fraction`` sets of two scores.

    Args:
        left: First score.
        right: Second score, same index.
        fraction: Share of the universe considered "top" (e.g. 0.10).

    Returns:
        Jaccard index in [0, 1].
    """
    k = max(1, math.ceil(fraction * len(left)))
    top_left = set(left.rank(method="first", ascending=False).loc[lambda r: r <= k].index)
    top_right = set(right.rank(method="first", ascending=False).loc[lambda r: r <= k].index)
    union = top_left | top_right
    return len(top_left & top_right) / len(union) if union else float("nan")


def compare_rankings(old: pd.Series, new: pd.Series, top_fraction: float) -> dict[str, float]:
    """Compare two scores over the same universe.

    Args:
        old: Previous definition.
        new: New definition, same index.
        top_fraction: Share defining the top set for the Jaccard index.

    Returns:
        Spearman, top-set Jaccard, mean absolute rank shift and means.
    """
    shift = (old.rank(ascending=False) - new.rank(ascending=False)).abs().mean()
    return {
        "n": float(len(old)),
        "spearman": spearman(old, new),
        "jaccard_top": jaccard_top(old, new, top_fraction),
        "mean_rank_shift": float(shift),
        "mean_old": float(old.mean()),
        "mean_new": float(new.mean()),
    }


def dispersion_ratio(values: pd.Series, high: float, low: float) -> float:
    """Ratio between two quantiles of a positive series.

    Args:
        values: Positive values.
        high: Upper quantile in (0, 1).
        low: Lower quantile in (0, 1).

    Returns:
        ``q_high / q_low`` or NaN when the lower quantile is not positive.
    """
    if values.empty:
        return float("nan")
    q_high, q_low = values.quantile(high), values.quantile(low)
    return float(q_high / q_low) if q_low > 0 else float("nan")


# --------------------------------------------------------------------------
# Months in office (SCD2 interval union)
# --------------------------------------------------------------------------


def merge_intervals(
    intervals: Sequence[tuple[pd.Timestamp, pd.Timestamp]],
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Union of half-open intervals ``[start, end)``.

    Adjacent or overlapping intervals are merged, so a party change
    (new SCD2 version) does not count as leaving office.

    Args:
        intervals: ``(start, end)`` pairs.

    Returns:
        Disjoint, sorted intervals. Empty or inverted pairs are dropped.
    """
    merged: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for start, end in sorted(intervals, key=lambda pair: pair[0]):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def months_in_office(
    intervals: pd.DataFrame, years: Sequence[int], days_per_month: float
) -> pd.DataFrame:
    """Months in office per parliamentarian and calendar year.

    Args:
        intervals: Columns ``id_parlamentar``, ``start``, ``end``
            (``end`` null means open-ended).
        years: Calendar years to evaluate.
        days_per_month: Days-per-month divisor (e.g. 30.4375).

    Returns:
        Columns ``id_parlamentar``, ``periodo``, ``meses``, ``dias``;
        only rows with at least one day in office.

    Raises:
        ValueError: If a required column is missing.
    """
    missing = {"id_parlamentar", "start", "end"} - set(intervals.columns)
    if missing:
        raise ValueError(f"intervals is missing columns: {sorted(missing)}")
    horizon_end = pd.Timestamp(year=max(years) + 1, month=1, day=1)
    frame = intervals.copy()
    frame["start"] = pd.to_datetime(frame["start"], errors="coerce")
    frame["end"] = pd.to_datetime(frame["end"], errors="coerce").fillna(horizon_end)
    valid = frame["start"].notna() & (frame["end"] > frame["start"])
    skipped = int((~valid).sum())
    if skipped:
        logger.warning("risk_calibration.intervals_skipped", count=skipped)

    rows: list[tuple[Any, int, float, int]] = []
    for parliamentarian, group in frame[valid].groupby("id_parlamentar"):
        merged = merge_intervals(list(zip(group["start"], group["end"], strict=True)))
        for year in years:
            year_start = pd.Timestamp(year=year, month=1, day=1)
            year_end = pd.Timestamp(year=year + 1, month=1, day=1)
            days = sum(
                max(0, (min(end, year_end) - max(start, year_start)).days)
                for start, end in merged
            )
            if days > 0:
                rows.append((parliamentarian, year, days / days_per_month, days))
    return pd.DataFrame(rows, columns=["id_parlamentar", "periodo", "meses", "dias"])


# --------------------------------------------------------------------------
# Scores
# --------------------------------------------------------------------------


def hhi_scores(pairs: pd.DataFrame, min_pair_value: float) -> pd.DataFrame:
    """HHI-based raw scores per parliamentarian (ADR-062, items 1-2).

    Pairs whose net value is not above ``min_pair_value`` are excluded,
    because shares of non-positive values are undefined.

    Args:
        pairs: Columns ``id_parlamentar``, ``id_fornecedor``, ``valor``
            (net value per parliamentarian-supplier pair, one period).
        min_pair_value: Pairs must exceed this value to be used.

    Returns:
        Frame indexed by ``id_parlamentar`` with ``hhi_p`` (concentration),
        ``d_new_raw`` (value-weighted mean supplier HHI) and ``d_old_raw``
        (simple mean supplier HHI, the previous ADR-027 definition).
    """
    used = pairs.loc[pairs["valor"] > min_pair_value].copy()
    parl_total = used.groupby("id_parlamentar")["valor"].transform("sum")
    supp_total = used.groupby("id_fornecedor")["valor"].transform("sum")
    used["share_p"] = used["valor"] / parl_total
    used["share_f"] = used["valor"] / supp_total
    hhi_f = (used["share_f"] ** 2).groupby(used["id_fornecedor"]).sum()
    used["hhi_f"] = used["id_fornecedor"].map(hhi_f)
    by_parl = used["id_parlamentar"]
    return pd.DataFrame(
        {
            "hhi_p": (used["share_p"] ** 2).groupby(by_parl).sum(),
            "d_new_raw": (used["share_p"] * used["hhi_f"]).groupby(by_parl).sum(),
            "d_old_raw": used["hhi_f"].groupby(by_parl).mean(),
        }
    )


def compute_volume_score(frame: pd.DataFrame, n_min: int, meses_min: float) -> pd.DataFrame:
    """Peer-normalized spending-volume score V (ADR-062, item 4).

    Args:
        frame: Indexed by parliamentarian, columns ``total`` (net spending
            in the period), ``meses`` (months in office), ``casa`` and
            ``uf``.
        n_min: Minimum peers in a ``(casa, uf)`` group; smaller groups
            fall back to the ``casa`` group.
        meses_min: Minimum months in office for a parliamentarian to
            enter the peer statistics and receive a non-zero score.

    Returns:
        Copy of ``frame`` plus ``x`` (monthly mean), ``z``, ``ln_dev``,
        ``v_group`` (``uf``/``casa``/``none``), ``v_flag``, ``v_raw``
        (``max(0, z)``) and ``V`` (Min-Max of ``v_raw``).

    Raises:
        ValueError: If a required column is missing.
    """
    missing = {"total", "meses", "casa", "uf"} - set(frame.columns)
    if missing:
        raise ValueError(f"frame is missing columns: {sorted(missing)}")
    out = frame.copy()
    meses = out["meses"].where(out["meses"] > 0)
    out["x"] = out["total"] / meses
    has_group = out["casa"].notna() & out["uf"].notna()
    long_enough = meses.ge(meses_min)
    positive = out["x"].gt(0)
    valid = has_group & long_enough & positive

    z = pd.Series(np.nan, index=out.index, dtype=float)
    ln_dev = pd.Series(np.nan, index=out.index, dtype=float)
    level = pd.Series("none", index=out.index, dtype=object)
    sub = out.loc[valid]
    if not sub.empty:
        uf_key = sub["casa"].astype(str) + "|" + sub["uf"].astype(str)
        uf_size = uf_key.map(uf_key.value_counts())
        uf_stats = _robust_log_stats(sub["x"], uf_key)
        casa_stats = _robust_log_stats(sub["x"], sub["casa"])
        use_uf = (uf_size >= n_min) & (uf_stats["mad"] > 0)
        use_casa = ~use_uf & (casa_stats["mad"] > 0)
        for mask, stats, name in ((use_uf, uf_stats, "uf"), (use_casa, casa_stats, "casa")):
            idx = mask.index[mask]
            ln_dev.loc[idx] = stats.loc[idx, "ln_dev"]
            z.loc[idx] = stats.loc[idx, "ln_dev"] / (MAD_SCALE * stats.loc[idx, "mad"])
            level.loc[idx] = name

    out["z"], out["ln_dev"], out["v_group"] = z, ln_dev, level
    out["v_raw"] = z.clip(lower=0).fillna(0.0)
    out["V"] = min_max(out["v_raw"])
    conditions = [
        meses.isna().to_numpy(),
        (~has_group).to_numpy(),
        (~long_enough).to_numpy(),
        (~positive).to_numpy(),
        (valid & (level == "none")).to_numpy(),
    ]
    choices = ["sem_intervalo", "sem_grupo", "janela_curta", "sem_gasto_positivo", "sem_referencia"]
    out["v_flag"] = np.select(conditions, choices, default="ok")
    return out


def _eligible(frame: pd.DataFrame, meses_min: float) -> tuple[pd.Series, pd.Series]:
    """Monthly mean spending and the eligibility mask of ADR-062 item 4.

    Args:
        frame: Columns ``total``, ``meses``, ``casa`` and ``uf``.
        meses_min: Minimum months in office.

    Returns:
        ``(x, eligible)``: monthly mean and a boolean mask that is true when
        the house and UF are known, ``meses >= meses_min`` and ``x > 0``.
    """
    meses = frame["meses"].where(frame["meses"] > 0)
    x = frame["total"] / meses
    mask = frame["casa"].notna() & frame["uf"].notna() & meses.ge(meses_min) & x.gt(0)
    return x, mask


def compute_volume_score_pooled(
    frame: pd.DataFrame, k_by_casa: Mapping[str, float], meses_min: float
) -> pd.DataFrame:
    """Volume score V with partial pooling by UF (ADR-063, items 1-4).

    For each house ``c`` and UF ``u`` (eligible parliamentarians only)::

        m*_u = (n_u * m_u + k_c * m_c) / (n_u + k_c)
        s_c  = 1.4826 * median_c(|ln x - m*_u|)
        z    = (ln x - m*_u) / s_c,    V = norm(max(0, z))

    Args:
        frame: Indexed by parliamentarian, columns ``total``, ``meses``,
            ``casa`` and ``uf``.
        k_by_casa: Shrinkage strength per house (> 0).
        meses_min: Minimum months in office (ADR-062 guard).

    Returns:
        Copy of ``frame`` plus ``x``, ``z``, ``ln_dev`` (residual against
        the shrunk location), ``lambda_u`` (weight of the UF data),
        ``v_flag``, ``v_raw`` and ``V``.

    Raises:
        ValueError: If a column is missing or an eligible house has no ``k``.
    """
    missing = {"total", "meses", "casa", "uf"} - set(frame.columns)
    if missing:
        raise ValueError(f"frame is missing columns: {sorted(missing)}")
    out = frame.copy()
    x, eligible = _eligible(out, meses_min)
    out["x"] = x
    meses = out["meses"].where(out["meses"] > 0)
    has_group = out["casa"].notna() & out["uf"].notna()
    long_enough = meses.ge(meses_min)
    positive = x.gt(0)

    z = pd.Series(np.nan, index=out.index, dtype=float)
    residual_all = pd.Series(np.nan, index=out.index, dtype=float)
    lam_all = pd.Series(np.nan, index=out.index, dtype=float)
    sub = out.loc[eligible]
    if not sub.empty:
        k_map = {str(casa): float(k) for casa, k in k_by_casa.items()}
        unknown = sorted(set(sub["casa"].astype(str)) - set(k_map))
        if unknown:
            raise ValueError(f"no pooling k configured for casa: {unknown}")
        casa_key = sub["casa"].astype(str)
        ln_x = np.log(sub["x"])
        uf_key = casa_key + "|" + sub["uf"].astype(str)
        n_u = uf_key.map(uf_key.value_counts()).astype(float)
        m_u = ln_x.groupby(uf_key).transform("median")
        m_c = ln_x.groupby(casa_key).transform("median")
        lam = n_u / (n_u + casa_key.map(k_map).astype(float))
        residual = ln_x - (lam * m_u + (1.0 - lam) * m_c)
        scale = MAD_SCALE * residual.abs().groupby(casa_key).transform("median")
        z.loc[sub.index] = residual / scale.where(scale > 0)
        residual_all.loc[sub.index] = residual
        lam_all.loc[sub.index] = lam
        zero_scale = int((scale <= 0).sum())
        if zero_scale:
            logger.warning("risk_calibration.pooled_zero_scale", count=zero_scale)

    out["z"], out["ln_dev"], out["lambda_u"] = z, residual_all, lam_all
    out["v_raw"] = z.clip(lower=0).fillna(0.0)
    out["V"] = min_max(out["v_raw"])
    conditions = [
        meses.isna().to_numpy(),
        (~has_group).to_numpy(),
        (~long_enough).to_numpy(),
        (~positive).to_numpy(),
        (eligible & z.isna()).to_numpy(),
    ]
    choices = ["sem_intervalo", "sem_grupo", "janela_curta", "sem_gasto_positivo", "sem_referencia"]
    out["v_flag"] = np.select(conditions, choices, default="ok")
    return out


def _leave_one_out_medians(values: np.ndarray) -> np.ndarray:
    """Median of the other elements, for every element of ``values``."""
    size = len(values)
    if size < 2:
        return np.full(size, np.nan)
    return np.array([np.median(np.delete(values, position)) for position in range(size)])


def loo_components(frame: pd.DataFrame, meses_min: float) -> pd.DataFrame:
    """Leave-one-out location components of every eligible parliamentarian.

    Args:
        frame: Columns ``total``, ``meses``, ``casa`` and ``uf``.
        meses_min: Minimum months in office.

    Returns:
        Frame indexed like the eligible rows with ``casa``, ``uf``,
        ``ln_x``, ``n_u`` (UF size, self included), ``m_u_loo`` (UF median
        without self; NaN if alone) and ``m_c_loo`` (house median without
        self). Rows whose house has a single member are dropped.
    """
    x, eligible = _eligible(frame, meses_min)
    sub = frame.loc[eligible, ["casa", "uf"]].copy()
    sub["ln_x"] = np.log(x.loc[eligible])
    sub["n_u"] = sub.groupby(["casa", "uf"])["ln_x"].transform("size").astype(float)
    sub["m_u_loo"] = np.nan
    sub["m_c_loo"] = np.nan
    for _, group in sub.groupby("casa"):
        sub.loc[group.index, "m_c_loo"] = _leave_one_out_medians(group["ln_x"].to_numpy(dtype=float))
    for _, group in sub.groupby(["casa", "uf"]):
        sub.loc[group.index, "m_u_loo"] = _leave_one_out_medians(group["ln_x"].to_numpy(dtype=float))
    return sub.dropna(subset=["m_c_loo"])


def k_label(k: float) -> str:
    """Stable label of a shrinkage value, e.g. ``k=4``."""
    return f"k={k:g}"


def loo_error_sums(
    components: pd.DataFrame, k_values: Sequence[float], n_min: int
) -> dict[str, dict[str, tuple[float, int]]]:
    """Sum of absolute leave-one-out errors per house and scheme (ADR-063, item 6).

    Schemes: ``casa_only`` (k -> infinity), ``adr062_rule`` (UF median when
    the UF has at least ``n_min`` eligible members, else house median) and
    one entry per ``k`` in ``k_values``.

    Args:
        components: Output of :func:`loo_components`.
        k_values: Shrinkage values to evaluate.
        n_min: ``n_min_pares`` of the ADR-062 rule.

    Returns:
        ``{casa: {scheme: (sum_abs_error, n_observations)}}``.
    """
    result: dict[str, dict[str, tuple[float, int]]] = {}
    for casa, group in components.groupby("casa"):
        ln_x = group["ln_x"].to_numpy(dtype=float)
        n_others = group["n_u"].to_numpy(dtype=float) - 1.0
        m_u_raw = group["m_u_loo"].to_numpy(dtype=float)
        m_u = np.nan_to_num(m_u_raw, nan=0.0)
        m_c = group["m_c_loo"].to_numpy(dtype=float)
        use_uf = (group["n_u"].to_numpy(dtype=float) >= n_min) & ~np.isnan(m_u_raw)
        predictions = {"casa_only": m_c, "adr062_rule": np.where(use_uf, m_u_raw, m_c)}
        for k in k_values:
            predictions[k_label(k)] = (n_others * m_u + k * m_c) / (n_others + k)
        result[str(casa)] = {
            name: (float(np.abs(ln_x - prediction).sum()), int(len(ln_x)))
            for name, prediction in predictions.items()
        }
    return result


def loo_residuals(
    components: pd.DataFrame, k_by_casa: Mapping[str, float], n_min: int
) -> pd.DataFrame:
    """Out-of-sample (leave-one-out) residuals of ``ln x`` under each scheme.

    Unlike the in-sample ``z`` (whose location includes the parliamentarian
    itself), these residuals compare each parliamentarian with a location
    estimated without it, so a scheme cannot look better just by fitting
    its own group.

    Args:
        components: Output of :func:`loo_components`.
        k_by_casa: Shrinkage strength per house.
        n_min: ``n_min_pares`` of the ADR-062 rule.

    Returns:
        Frame with ``casa``, ``uf`` and the residuals ``r_casa_only``,
        ``r_adr062_rule`` and ``r_pooled``.
    """
    k_map = {str(casa): float(k) for casa, k in k_by_casa.items()}
    n_others = components["n_u"] - 1.0
    m_u = components["m_u_loo"]
    m_c = components["m_c_loo"]
    k = components["casa"].astype(str).map(k_map).astype(float)
    pooled_prediction = (n_others * m_u.fillna(0.0) + k * m_c) / (n_others + k)
    adr_prediction = m_u.where((components["n_u"] >= n_min) & m_u.notna(), m_c)
    return pd.DataFrame(
        {
            "casa": components["casa"],
            "uf": components["uf"],
            "r_casa_only": components["ln_x"] - m_c,
            "r_adr062_rule": components["ln_x"] - adr_prediction,
            "r_pooled": components["ln_x"] - pooled_prediction,
        }
    )


def aggregate_loo(
    per_year: Mapping[int, Mapping[str, Mapping[str, tuple[float, int]]]],
) -> dict[str, Any]:
    """Pool leave-one-out error sums across years.

    Args:
        per_year: ``{year: {casa: {scheme: (sum_abs_error, n)}}}``.

    Returns:
        ``mean`` (pooled mean absolute error per casa and scheme),
        ``n_obs`` (observations per casa) and ``by_year`` (yearly means).
    """
    sums: dict[str, dict[str, list[float]]] = {}
    by_year: dict[int, dict[str, dict[str, float]]] = {}
    for year, per_casa in per_year.items():
        by_year[year] = {}
        for casa, schemes in per_casa.items():
            by_year[year][casa] = {name: total / n for name, (total, n) in schemes.items()}
            bucket = sums.setdefault(casa, {})
            for name, (total, n) in schemes.items():
                acc = bucket.setdefault(name, [0.0, 0.0])
                acc[0] += total
                acc[1] += n
    mean = {casa: {name: acc[0] / acc[1] for name, acc in bucket.items()} for casa, bucket in sums.items()}
    n_obs = {casa: int(bucket["casa_only"][1]) for casa, bucket in sums.items()}
    return {"mean": mean, "n_obs": n_obs, "by_year": by_year}


def select_k(errors: Mapping[str, float], k_grid: Sequence[float], tolerance: float) -> float:
    """Grid value with the lowest error; ties go to the larger ``k``.

    Args:
        errors: Mean error per scheme label (see :func:`k_label`).
        k_grid: Candidate shrinkage values.
        tolerance: Errors closer than this are considered equal.

    Returns:
        The selected ``k``.
    """
    best_k = float("nan")
    best_error = math.inf
    for k in sorted(k_grid, reverse=True):
        error = errors[k_label(k)]
        if error < best_error - tolerance:
            best_k, best_error = float(k), error
    return best_k


def uf_share_residual(z: pd.Series, uf: pd.Series) -> float:
    """R-squared of ``z`` on UF dummies (share of ``z`` variance explained by UF).

    Args:
        z: Volume z-scores.
        uf: UF label aligned with ``z``.

    Returns:
        Between-UF share of the variance, or NaN when undefined.
    """
    frame = pd.DataFrame({"z": z, "uf": uf}).dropna()
    if len(frame) < 3 or frame["uf"].nunique() < 2:
        return float("nan")
    values = frame["z"].to_numpy(dtype=float)
    sst = float(((values - values.mean()) ** 2).sum())
    if sst == 0.0:
        return float("nan")
    group_mean = frame.groupby("uf")["z"].transform("mean").to_numpy(dtype=float)
    return float(((group_mean - values.mean()) ** 2).sum() / sst)


def attach_pooled(
    volume: pd.DataFrame,
    scores: pd.DataFrame,
    k_by_casa: Mapping[str, float],
    meses_min: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add the pooled volume score to the year frames.

    Args:
        volume: Full-universe volume frame from :func:`build_year`.
        scores: Normalized scores from :func:`build_year`.
        k_by_casa: Shrinkage strength per house.
        meses_min: Minimum months in office.

    Returns:
        ``(volume, scores)`` copies with ``*_pooled`` columns in ``volume``
        (``z``, ``ln_dev``, ``lambda_u``, ``v_flag``, ``v_raw``, ``V``) and
        ``V_pooled`` (Min-Max over the scored universe) in ``scores``.
    """
    pooled = compute_volume_score_pooled(volume[["total", "meses", "casa", "uf"]], k_by_casa, meses_min)
    columns = ["z", "ln_dev", "lambda_u", "v_flag", "v_raw", "V"]
    volume_out = volume.join(pooled[columns].add_suffix("_pooled"))
    scores_out = scores.copy()
    scores_out["V_pooled"] = min_max(pooled.loc[scores.index, "v_raw"])
    return volume_out, scores_out


def _a1_passed(base: float, pooled: float, strict: bool, tolerance: float) -> bool:
    """A1 comparison: strict improvement for strict houses, else not worse."""
    if not (math.isfinite(base) and math.isfinite(pooled)):
        return False
    return pooled < base - tolerance if strict else pooled <= base + tolerance


def evaluate_acceptance(
    uf_residual: Mapping[int, Mapping[str, Mapping[str, float]]],
    loo_mean: Mapping[str, Mapping[str, float]],
    k_by_casa: Mapping[str, float],
    strict_casas: Sequence[str],
    tolerance: float,
    uf_share_loo: Mapping[int, Mapping[str, Mapping[str, float]]] | None = None,
) -> dict[str, Any]:
    """Evaluate the ADR-063 acceptance criteria A1 and A2 (item 9).

    A1: ``uf_share_residual`` with the chosen ``k`` is lower than under the
    ADR-062 rule in every year for the strict houses, and not worse for the
    others. A2: the leave-one-out error of the chosen ``k`` is not above
    ``casa_only`` nor the ADR-062 rule, per house.

    ``a1_loo`` repeats the A1 comparison on out-of-sample (leave-one-out)
    residuals. It is informative only and never enters ``all_pass``: the
    in-sample ``z`` of the ADR-062 rule removes the UF location it was fitted
    on, which favours that rule.

    Args:
        uf_residual: ``{year: {casa: {"baseline": r2, "pooled": r2}}}``.
        loo_mean: Pooled mean LOO error per house and scheme.
        k_by_casa: Chosen ``k`` per house.
        strict_casas: Houses where A1 requires a strict improvement.
        tolerance: Numeric tolerance for comparisons.
        uf_share_loo: ``{year: {casa: {"adr062_rule": r2, "pooled": r2, ...}}}``.

    Returns:
        Rows and verdicts for A1, A2, the informative ``a1_loo`` and overall.
    """
    a1_rows: list[dict[str, Any]] = []
    for year, per_casa in uf_residual.items():
        for casa, values in per_casa.items():
            strict = casa in strict_casas
            passed = _a1_passed(values["baseline"], values["pooled"], strict, tolerance)
            a1_rows.append(
                {
                    "year": year,
                    "casa": casa,
                    "baseline": values["baseline"],
                    "pooled": values["pooled"],
                    "strict": strict,
                    "pass": bool(passed),
                }
            )
    a1_loo_rows: list[dict[str, Any]] = []
    for year, per_casa in (uf_share_loo or {}).items():
        for casa, values in per_casa.items():
            strict = casa in strict_casas
            passed = _a1_passed(values["adr062_rule"], values["pooled"], strict, tolerance)
            a1_loo_rows.append(
                {
                    "year": year,
                    "casa": casa,
                    "baseline": values["adr062_rule"],
                    "pooled": values["pooled"],
                    "casa_only": values.get("casa_only"),
                    "strict": strict,
                    "pass": bool(passed),
                }
            )
    a2_rows: list[dict[str, Any]] = []
    for casa, errors in loo_mean.items():
        chosen = errors[k_label(k_by_casa[casa])]
        passed = chosen <= errors["casa_only"] + tolerance and chosen <= errors["adr062_rule"] + tolerance
        a2_rows.append(
            {
                "casa": casa,
                "k": k_by_casa[casa],
                "error_k": chosen,
                "error_casa_only": errors["casa_only"],
                "error_adr062_rule": errors["adr062_rule"],
                "pass": bool(passed),
            }
        )
    a1_pass = bool(a1_rows) and all(row["pass"] for row in a1_rows)
    a2_pass = bool(a2_rows) and all(row["pass"] for row in a2_rows)
    return {
        "a1": {"pass": a1_pass, "rows": a1_rows},
        "a1_loo": {
            "informative": True,
            "pass": bool(a1_loo_rows) and all(row["pass"] for row in a1_loo_rows),
            "rows": a1_loo_rows,
        },
        "a2": {"pass": a2_pass, "rows": a2_rows},
        "all_pass": a1_pass and a2_pass,
    }


def variance_decomposition(frame: pd.DataFrame) -> dict[str, float]:
    """Incremental R-squared of ``ln(total)`` on months, UF and house.

    Args:
        frame: Columns ``total`` (> 0), ``meses`` (> 0), ``uf``, ``casa``.

    Returns:
        ``r2_meses``, ``r2_meses_uf``, ``r2_meses_uf_casa`` (cumulative)
        and the increments ``delta_uf`` and ``delta_casa``.

    Raises:
        ValueError: If the frame is empty or ``ln(total)`` is constant.
    """
    if frame.empty:
        raise ValueError("variance decomposition needs at least one row")
    y = np.log(frame["total"].to_numpy(dtype=float))
    sst = float(((y - y.mean()) ** 2).sum())
    if sst == 0.0:
        raise ValueError("ln(total) is constant; variance decomposition is undefined")
    ones = np.ones((len(frame), 1))
    ln_meses = np.log(frame["meses"].to_numpy(dtype=float)).reshape(-1, 1)
    uf = pd.get_dummies(frame["uf"], drop_first=True, dtype=float).to_numpy()
    casa = pd.get_dummies(frame["casa"], drop_first=True, dtype=float).to_numpy()

    def r_squared(design: np.ndarray) -> float:
        beta, *_ = np.linalg.lstsq(design, y, rcond=None)
        residual = y - design @ beta
        return 1.0 - float((residual**2).sum()) / sst

    x1 = np.hstack([ones, ln_meses])
    x2 = np.hstack([x1, uf])
    x3 = np.hstack([x2, casa])
    r1, r2, r3 = r_squared(x1), r_squared(x2), r_squared(x3)
    return {
        "r2_meses": r1,
        "r2_meses_uf": r2,
        "r2_meses_uf_casa": r3,
        "delta_uf": r2 - r1,
        "delta_casa": r3 - r2,
    }


# --------------------------------------------------------------------------
# Gold access (read-only)
# --------------------------------------------------------------------------


def _years_filter(years: Sequence[int]) -> tuple[str, list[int]]:
    """SQL ``IN`` placeholders and parameters for the window years."""
    return ", ".join("?" for _ in years), list(years)


def load_totals(
    con: duckdb.DuckDBPyConnection, settings: CalibrationSettings
) -> pd.DataFrame:
    """Net spending per parliamentarian-year, including null suppliers.

    Args:
        con: Open DuckDB connection (read-only recommended).
        settings: Calibration settings.

    Returns:
        Columns ``id_parlamentar``, ``periodo``, ``total``,
        ``total_sem_fornecedor``.
    """
    marks, params = _years_filter(settings.window_years)
    sql = f"""
        SELECT f.id_parlamentar AS id_parlamentar,
               CAST(f.data_sk // 10000 AS INTEGER) AS periodo,
               SUM(f.valor_liquido) AS total,
               SUM(CASE WHEN f.id_fornecedor IS NULL THEN f.valor_liquido ELSE 0 END)
                   AS total_sem_fornecedor
        FROM {settings.tables.fact_despesa} f
        WHERE f.data_sk IS NOT NULL
          AND CAST(f.data_sk // 10000 AS INTEGER) IN ({marks})
        GROUP BY 1, 2
    """  # noqa: S608 - identifiers validated by CalibrationSettings
    return con.execute(sql, params).df()


def load_pairs(con: duckdb.DuckDBPyConnection, settings: CalibrationSettings) -> pd.DataFrame:
    """Net value per parliamentarian-supplier-year (non-null suppliers).

    Args:
        con: Open DuckDB connection.
        settings: Calibration settings.

    Returns:
        Columns ``id_parlamentar``, ``id_fornecedor``, ``periodo``, ``valor``.
    """
    marks, params = _years_filter(settings.window_years)
    sql = f"""
        SELECT f.id_parlamentar AS id_parlamentar,
               f.id_fornecedor AS id_fornecedor,
               CAST(f.data_sk // 10000 AS INTEGER) AS periodo,
               SUM(f.valor_liquido) AS valor
        FROM {settings.tables.fact_despesa} f
        WHERE f.data_sk IS NOT NULL
          AND f.id_fornecedor IS NOT NULL
          AND CAST(f.data_sk // 10000 AS INTEGER) IN ({marks})
        GROUP BY 1, 2, 3
    """  # noqa: S608
    return con.execute(sql, params).df()


def load_groups(con: duckdb.DuckDBPyConnection, settings: CalibrationSettings) -> pd.DataFrame:
    """House and UF per parliamentarian-year (latest SCD2 version used).

    Args:
        con: Open DuckDB connection.
        settings: Calibration settings.

    Returns:
        Columns ``id_parlamentar``, ``periodo``, ``casa``, ``uf``.
    """
    marks, params = _years_filter(settings.window_years)
    sql = f"""
        SELECT f.id_parlamentar AS id_parlamentar,
               CAST(f.data_sk // 10000 AS INTEGER) AS periodo,
               arg_max(d.fonte, d.effective_date) AS casa,
               arg_max(d.sigla_uf, d.effective_date) AS uf
        FROM {settings.tables.fact_despesa} f
        LEFT JOIN {settings.tables.dim_parlamentar} d
               ON f.surrogate_key = d.surrogate_key
        WHERE f.data_sk IS NOT NULL
          AND CAST(f.data_sk // 10000 AS INTEGER) IN ({marks})
        GROUP BY 1, 2
    """  # noqa: S608
    return con.execute(sql, params).df()


def load_intervals(con: duckdb.DuckDBPyConnection, settings: CalibrationSettings) -> pd.DataFrame:
    """SCD2 validity intervals of every parliamentarian.

    Args:
        con: Open DuckDB connection.
        settings: Calibration settings.

    Returns:
        Columns ``id_parlamentar``, ``start``, ``end`` (null = open).
    """
    sql = f"""
        SELECT id_parlamentar, effective_date, end_date
        FROM {settings.tables.dim_parlamentar}
    """  # noqa: S608
    rows = con.execute(sql).fetchall()  # python dates: avoids ns-bound overflow
    return pd.DataFrame(rows, columns=["id_parlamentar", "start", "end"])


def load_external_scores(
    con: duckdb.DuckDBPyConnection, settings: CalibrationSettings
) -> pd.DataFrame:
    """E, A and N scores per parliamentarian-year from the mapped table.

    Args:
        con: Open DuckDB connection.
        settings: Calibration settings.

    Returns:
        Columns ``id_parlamentar``, ``periodo``, ``E``, ``A``, ``N``.
    """
    source = settings.scores_source
    marks, params = _years_filter(settings.window_years)
    agg = _AGGREGATIONS[source.aggregation]
    selects = ",\n               ".join(
        f"{agg}({source.columns[name]}) AS {name.lower()}_score" for name in ("E", "A", "N")
    )
    sql = f"""
        SELECT {source.id_column} AS id_parlamentar,
               CAST(({source.period_expression}) AS INTEGER) AS periodo,
               {selects}
        FROM {source.table}
        WHERE CAST(({source.period_expression}) AS INTEGER) IN ({marks})
        GROUP BY 1, 2
    """  # noqa: S608
    frame = con.execute(sql, params).df()
    return frame.rename(columns={"e_score": "E", "a_score": "A", "n_score": "N"})


# --------------------------------------------------------------------------
# Year assembly and analysis
# --------------------------------------------------------------------------


def build_year(
    year: int,
    totals: pd.DataFrame,
    pairs: pd.DataFrame,
    groups: pd.DataFrame,
    months: pd.DataFrame,
    external: pd.DataFrame,
    settings: CalibrationSettings,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Assemble the volume frame and normalized scores for one year.

    Args:
        year: Calendar year.
        totals: Output of :func:`load_totals` (all years).
        pairs: Output of :func:`load_pairs` (all years).
        groups: Output of :func:`load_groups` (all years).
        months: Output of :func:`months_in_office` (all years).
        external: Output of :func:`load_external_scores` (all years).
        settings: Calibration settings.

    Returns:
        ``(volume_frame, scores, meta)``: the full-universe volume frame,
        the normalized scores (``C, D, E, A, N, V`` plus ``D_old``) for
        parliamentarians with every score, and bookkeeping counters.

    Raises:
        ValueError: If the year has no spending rows.
    """
    year_totals = totals.loc[totals["periodo"] == year].set_index("id_parlamentar")
    if year_totals.empty:
        raise ValueError(f"no spending rows found for year {year}")
    base = year_totals[["total", "total_sem_fornecedor"]].copy()
    year_groups = groups.loc[groups["periodo"] == year].set_index("id_parlamentar")
    year_months = months.loc[months["periodo"] == year].set_index("id_parlamentar")
    base = base.join(year_groups[["casa", "uf"]]).join(year_months[["meses", "dias"]])

    volume = compute_volume_score(base, settings.n_min_pares, settings.meses_min)

    hhi = hhi_scores(pairs.loc[pairs["periodo"] == year], settings.min_pair_value)
    ext = external.loc[external["periodo"] == year].set_index("id_parlamentar")[["E", "A", "N"]]
    joined = volume[["v_raw"]].join(hhi, how="left").join(ext, how="left")
    complete = joined.dropna(subset=["hhi_p", "d_new_raw", "d_old_raw", "E", "A", "N"])

    scores = pd.DataFrame(
        {
            "C": min_max(complete["hhi_p"]),
            "D": min_max(complete["d_new_raw"]),
            "E": min_max(complete["E"]),
            "A": min_max(complete["A"]),
            "N": min_max(complete["N"]),
            "V": min_max(complete["v_raw"]),
            "D_old": min_max(complete["d_old_raw"]),
        }
    )
    total_value = float(base["total"].sum())
    null_share = float(base["total_sem_fornecedor"].sum() / total_value) if total_value else float("nan")
    meta = {
        "n_universe": int(len(base)),
        "n_scored": int(len(scores)),
        "n_dropped_missing_scores": int(len(base) - len(scores)),
        "null_supplier_value_share": null_share,
    }
    logger.info("risk_calibration.year_built", year=year, **meta)
    return volume, scores, meta


def _months_diagnostics(volume: pd.DataFrame, year: int, settings: CalibrationSettings) -> dict[str, Any]:
    """Distribution of months in office and partial-year share."""
    days_in_year = (pd.Timestamp(year + 1, 1, 1) - pd.Timestamp(year, 1, 1)).days
    meses = volume["meses"].dropna()
    dias = volume["dias"].dropna()
    return {
        "n_without_interval": int(volume["meses"].isna().sum()),
        "quantiles": {
            f"p{round(q * 100)}": float(meses.quantile(q)) for q in (0.0, 0.05, 0.25, 0.5, 0.75, 1.0)
        }
        if not meses.empty
        else {},
        "share_below_meses_min": float((meses < settings.meses_min).mean()) if not meses.empty else float("nan"),
        "share_partial_year": float((dias < days_in_year - 0.5).mean()) if not dias.empty else float("nan"),
    }


def _group_diagnostics(volume: pd.DataFrame, n_min: int) -> dict[str, Any]:
    """Peer-group sizes among eligible parliamentarians."""
    eligible = volume.loc[volume["v_flag"].isin(["ok", "sem_referencia"])]
    sizes = eligible.groupby(["casa", "uf"]).size()
    below = sizes.loc[sizes < n_min]
    return {
        "n_groups": int(len(sizes)),
        "n_groups_below_n_min": int(len(below)),
        "groups_below_n_min_by_casa": {
            str(casa): int(count) for casa, count in below.groupby(level="casa").size().items()
        },
        "min_group_size_by_casa": {
            str(casa): int(size) for casa, size in sizes.groupby(level="casa").min().items()
        },
        "share_fallback_casa": float((volume["v_group"] == "casa").mean()),
        "flags": {str(k): int(v) for k, v in volume["v_flag"].value_counts().items()},
    }


def analyze_year(
    year: int, volume: pd.DataFrame, scores: pd.DataFrame, meta: dict[str, Any], settings: CalibrationSettings
) -> dict[str, Any]:
    """Diagnostics of one year (dispersion, variance, sensitivity, D, V).

    Args:
        year: Calendar year.
        volume: Full-universe volume frame from :func:`build_year`.
        scores: Normalized scores from :func:`build_year`.
        meta: Counters from :func:`build_year`.
        settings: Calibration settings.
    Returns:
        JSON-friendly report section.
    """
    eligible = volume.loc[volume["v_flag"].isin(["ok", "sem_referencia"])]
    ranked = volume.loc[volume["v_group"] != "none"]
    dispersion: dict[str, dict[str, float]] = {}
    for high, low in settings.dispersion_quantiles:
        key = f"p{round(high * 100)}_p{round(low * 100)}"
        dispersion[key] = {
            "raw_total": dispersion_ratio(eligible["total"], high, low),
            "monthly": dispersion_ratio(eligible["x"], high, low),
            "residual": dispersion_ratio(np.exp(ranked["ln_dev"]), high, low),
        }
    sensitivity = []
    base_v = volume["V"]
    for n_min in settings.n_min_sensitivity:
        variant = compute_volume_score(volume[["total", "meses", "casa", "uf"]], n_min, settings.meses_min)
        sensitivity.append(
            {
                "n_min": n_min,
                "spearman_vs_base": spearman(variant["V"], base_v),
                "jaccard_top_vs_base": jaccard_top(variant["V"], base_v, settings.top_fraction),
                "share_fallback_casa": float((variant["v_group"] == "casa").mean()),
            }
        )
    decomposition_input = eligible.loc[(eligible["total"] > 0) & (eligible["meses"] > 0)]
    return {
        **meta,
        "months": _months_diagnostics(volume, year, settings),
        "groups": _group_diagnostics(volume, settings.n_min_pares),
        "dispersion": dispersion,
        "variance_decomposition": variance_decomposition(decomposition_input),
        "sensitivity_n_min": sensitivity,
        "d_old_vs_new": compare_rankings(scores["D_old"], scores["D"], settings.top_fraction),
        "spearman_cd": spearman(scores["C"], scores["D"]),
        "spearman_v_vs": {name: spearman(scores["V"], scores[name]) for name in SCORE_COLUMNS if name != "V"},
    }


def analyze_pooling(
    volume: pd.DataFrame,
    scores: pd.DataFrame,
    settings: CalibrationSettings,
    components: pd.DataFrame,
    k_by_casa: Mapping[str, float],
) -> dict[str, Any]:
    """Pooling diagnostics of one year (ADR-063, item 8).

    Args:
        volume: Volume frame carrying the ``*_pooled`` columns.
        scores: Normalized scores carrying ``V_pooled``.
        settings: Calibration settings.
        components: Output of :func:`loo_components` for the year.
        k_by_casa: Shrinkage strength per house.

    Returns:
        ``uf_share_residual`` per house (ADR-062 rule vs pooled), its out-of-sample
        counterpart ``uf_share_loo``, the
        distribution of the UF weight ``lambda_u``, pooled flags and the
        comparison of ``V_pooled`` against ``V``.
    """
    both = volume.loc[np.isfinite(volume["z"]) & np.isfinite(volume["z_pooled"])]
    residual: dict[str, dict[str, float]] = {}
    for casa, group in both.groupby("casa"):
        residual[str(casa)] = {
            "baseline": uf_share_residual(group["z"], group["uf"]),
            "pooled": uf_share_residual(group["z_pooled"], group["uf"]),
            "n": float(len(group)),
        }
    residuals = loo_residuals(components, k_by_casa, settings.n_min_pares)
    loo_share: dict[str, dict[str, float]] = {}
    for casa, group in residuals.groupby("casa"):
        loo_share[str(casa)] = {
            name: uf_share_residual(group[column], group["uf"])
            for name, column in (
                ("casa_only", "r_casa_only"),
                ("adr062_rule", "r_adr062_rule"),
                ("pooled", "r_pooled"),
            )
        }
    weights: dict[str, Any] = {}
    eligible = volume.loc[volume["lambda_u_pooled"].notna()]
    for casa, group in eligible.groupby("casa"):
        per_group = group.groupby("uf")["lambda_u_pooled"].first()
        weights[str(casa)] = {
            "groups": int(len(per_group)),
            "groups_below_half": int((per_group < 0.5).sum()),
            "quantiles": {f"p{round(q * 100)}": float(per_group.quantile(q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
        }
    return {
        "uf_share_residual": residual,
        "uf_share_loo": loo_share,
        "lambda_u": weights,
        "flags_pooled": {str(k): int(v) for k, v in volume["v_flag_pooled"].value_counts().items()},
        "v_pooled_vs_v": compare_rankings(scores["V"], scores["V_pooled"], settings.top_fraction),
    }


# --------------------------------------------------------------------------
# Data fingerprint, score distributions and weight robustness (Sprint 29, Onda 2)
# --------------------------------------------------------------------------


def frame_fingerprint(frame: pd.DataFrame, sort_by: Sequence[str], decimals: int) -> str:
    """SHA-256 of a frame, independent of row order and of float noise below ``decimals``.

    Args:
        frame: Data to fingerprint.
        sort_by: Columns that define a deterministic row order.
        decimals: Decimal places kept for floating-point values.

    Returns:
        Hexadecimal digest.
    """
    ordered = frame.sort_values(list(sort_by), kind="mergesort").reset_index(drop=True)
    text = ordered.to_csv(index=False, float_format=f"%.{decimals}f")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def data_fingerprint(
    totals: pd.DataFrame,
    pairs: pd.DataFrame,
    groups: pd.DataFrame,
    external: pd.DataFrame,
    intervals: pd.DataFrame,
    decimals: int,
    money_decimals: int,
) -> dict[str, Any]:
    """Fingerprint of the Gold inputs read by a calibration run.

    The report already stores the SHA-256 of the configuration; this adds the
    identity of the data, so a change of inputs between two runs (a rebuilt
    Silver, a new ingestion) can be told apart from a change of code or config.

    Args:
        totals: Output of :func:`load_totals`.
        pairs: Output of :func:`load_pairs`.
        groups: Output of :func:`load_groups`.
        external: Output of :func:`load_external_scores`.
        intervals: Output of :func:`load_intervals`.
        decimals: Decimal places kept when hashing score-like floating-point values.
        money_decimals: Decimal places kept for monetary sums (``totals`` and
            ``pairs``). Those are aggregates computed by the database, whose
            floating-point summation order is not guaranteed, so they are
            rounded to the cent grid, far above the summation noise.

    Returns:
        ``hashes`` (one digest per input), ``rows`` (row counts) and
        ``sums_by_year`` (control totals per calendar year).
    """
    as_text = intervals.assign(start=intervals["start"].astype(str), end=intervals["end"].astype(str))
    hashes = {
        "totals": frame_fingerprint(totals, ["id_parlamentar", "periodo"], money_decimals),
        "pairs": frame_fingerprint(pairs, ["id_parlamentar", "id_fornecedor", "periodo"], money_decimals),
        "groups": frame_fingerprint(groups, ["id_parlamentar", "periodo"], decimals),
        "external": frame_fingerprint(external, ["id_parlamentar", "periodo"], decimals),
        "intervals": frame_fingerprint(as_text, ["id_parlamentar", "start", "end"], decimals),
    }
    rows = {
        "totals": int(len(totals)),
        "pairs": int(len(pairs)),
        "groups": int(len(groups)),
        "external": int(len(external)),
        "intervals": int(len(intervals)),
    }
    sums: dict[int, dict[str, float]] = {}
    for year in sorted(totals["periodo"].unique()):
        year_totals = totals.loc[totals["periodo"] == year]
        year_pairs = pairs.loc[pairs["periodo"] == year]
        year_external = external.loc[external["periodo"] == year]
        sums[int(year)] = {
            "total": round(float(year_totals["total"].sum()), 2),
            "pairs_valor": round(float(year_pairs["valor"].sum()), 2),
            "E": round(float(year_external["E"].sum()), 6),
            "A": round(float(year_external["A"].sum()), 6),
            "N": round(float(year_external["N"].sum()), 6),
        }
    return {"hashes": hashes, "rows": rows, "sums_by_year": sums}


def score_distribution(scores: pd.DataFrame, quantiles: Sequence[float]) -> dict[str, Any]:
    """Empirical distribution of each normalized score (ADR-029 criterion).

    Args:
        scores: Normalized scores, one column per entry of :data:`SCORE_COLUMNS`.
        quantiles: Quantiles to report, in (0, 1).

    Returns:
        Per score: ``n``, ``mean``, ``std``, ``skew``, ``share_zero`` and ``quantiles``.
    """
    result: dict[str, Any] = {}
    for name in SCORE_COLUMNS:
        values = scores[name]
        result[name] = {
            "n": int(values.size),
            "mean": float(values.mean()),
            "std": float(values.std(ddof=1)),
            "skew": float(values.skew()),
            "share_zero": float((values == 0).mean()),
            "quantiles": {f"p{q * 100:g}": float(values.quantile(q)) for q in quantiles},
        }
    return result


def percentile_rank_scores(scores: pd.DataFrame) -> pd.DataFrame:
    """Percentile ranks in (0, 1] per column (ties share the average rank).

    Args:
        scores: Scores of one period.

    Returns:
        Frame with the same shape; every non-constant column is roughly uniform.
    """
    return scores.rank(pct=True, method="average")


def stack_scores(year_scores: Mapping[int, pd.DataFrame], v_column: str = "V") -> pd.DataFrame:
    """Stack the yearly score frames with ``year`` and ``id`` columns.

    Args:
        year_scores: Normalized scores per year, indexed by parliamentarian.
        v_column: Column acting as ``V``.

    Returns:
        Frame with ``year``, ``id`` and one column per score; rows are sorted by id
        within each year, so the result does not depend on the input row order.
    """
    frames = {year: _ordered_scores(frame, v_column).sort_index() for year, frame in year_scores.items()}
    return pd.concat(frames, names=["year", "id"]).reset_index()


def _id_positions(ids: pd.Series) -> list[np.ndarray]:
    """Row positions of every distinct id (the resampling clusters).

    Clusters are numbered in sorted id order, so the draws of a seeded bootstrap
    do not depend on the order in which the database returned the rows.
    """
    codes, _ = pd.factorize(ids, sort=True)
    order = np.argsort(codes, kind="stable")
    boundaries = np.cumsum(np.bincount(codes))[:-1]
    return np.split(order, boundaries)


def bootstrap_critic_weights(stacked: pd.DataFrame, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """Cluster bootstrap of the pooled CRITIC weights.

    Parliamentarians are resampled with replacement and keep all their
    year-rows, because the same person appears in several years.

    Args:
        stacked: Output of :func:`stack_scores`.
        n_boot: Number of bootstrap draws.
        rng: Random generator (seeded by the caller).

    Returns:
        Array ``(n_boot, n_scores)`` of weights in :data:`SCORE_COLUMNS` order.
    """
    columns = list(SCORE_COLUMNS)
    values = stacked[columns]
    positions = _id_positions(stacked["id"])
    draws = np.empty((n_boot, len(columns)))
    for draw in range(n_boot):
        chosen = rng.integers(0, len(positions), size=len(positions))
        index = np.concatenate([positions[cluster] for cluster in chosen])
        draws[draw] = critic_weights(values.iloc[index]).reindex(columns).to_numpy()
    return draws


def summarize_bootstrap(draws: np.ndarray, reference: pd.Series, ci_level: float) -> dict[str, Any]:
    """Percentile intervals of the bootstrapped weights.

    Args:
        draws: Output of :func:`bootstrap_critic_weights`.
        reference: Weights of the full sample, indexed by score.
        ci_level: Interval level, e.g. 0.95.

    Returns:
        Per score: reference, mean, std, interval and whether the interval
        contains the uniform weight; plus how often each score has the top weight.
    """
    columns = list(SCORE_COLUMNS)
    uniform = 1.0 / len(columns)
    low, high = np.percentile(draws, [(1 - ci_level) / 2 * 100, (1 + ci_level) / 2 * 100], axis=0)
    scores = {
        name: {
            "reference": float(reference[name]),
            "mean": float(draws[:, j].mean()),
            "std": float(draws[:, j].std(ddof=1)),
            "ci_low": float(low[j]),
            "ci_high": float(high[j]),
            "includes_uniform": bool(low[j] <= uniform <= high[j]),
        }
        for j, name in enumerate(columns)
    }
    top = pd.Series(np.array(columns)[draws.argmax(axis=1)]).value_counts(normalize=True)
    return {
        "n_draws": int(len(draws)),
        "ci_level": ci_level,
        "uniform_weight": uniform,
        "scores": scores,
        "share_top_weight": {name: float(top.get(name, 0.0)) for name in columns},
    }


def dirichlet_weights(reference: np.ndarray, concentration: float, n: int, rng: np.random.Generator) -> np.ndarray:
    """Random weight vectors around ``reference`` (Dirichlet, mean = reference).

    Args:
        reference: Reference weights (sum 1).
        concentration: Larger values stay closer to ``reference``.
        n: Number of vectors.
        rng: Random generator (seeded by the caller).

    Returns:
        Array ``(n, len(reference))`` whose rows sum to one.
    """
    alpha = np.where(reference > 0, concentration * reference, 1e-9)
    return rng.dirichlet(alpha, size=n)


def index_ranks(scores: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Descending ranks (1 = highest) of the weighted base index.

    Args:
        scores: Matrix ``(n, s)`` of normalized scores.
        weights: Matrix ``(d, s)``, one weight vector per row.

    Returns:
        Matrix ``(n, d)`` of ranks, ties broken by position.
    """
    index = scores @ weights.T
    order = np.argsort(-index, axis=0, kind="stable")
    ranks = np.empty_like(order)
    np.put_along_axis(ranks, order, np.arange(1, index.shape[0] + 1)[:, None], axis=0)
    return ranks.astype(float)


def sensitivity_metrics(
    scores: np.ndarray,
    reference: np.ndarray,
    alternatives: np.ndarray,
    *,
    top_fraction: float,
    ci_level: float,
    stability_threshold: float,
    intervals: bool,
) -> dict[str, Any]:
    """How much the base-index ranking moves when the weights change.

    Args:
        scores: Matrix ``(n, s)`` of normalized scores of one year.
        reference: Reference weights, shape ``(s,)``.
        alternatives: Alternative weight vectors, shape ``(d, s)``.
        top_fraction: Share defining the top set.
        ci_level: Level of the summary interval (and of the rank interval).
        stability_threshold: Share of vectors in which a top member must stay on top.
        intervals: Also report per-parliamentarian rank intervals (needs ``d > 1``).

    Returns:
        Spearman, top-set Jaccard and mean absolute rank shift against the
        reference ranking (mean and interval over the vectors); optionally
        the rank-interval widths and the share of stable top members.
    """
    n = scores.shape[0]
    k = max(1, math.ceil(top_fraction * n))
    reference_rank = index_ranks(scores, reference[None, :])[:, 0]
    ranks = index_ranks(scores, alternatives)
    centered_ref = reference_rank - reference_rank.mean()
    centered = ranks - ranks.mean(axis=0)
    denominator = np.sqrt((centered_ref**2).sum()) * np.sqrt((centered**2).sum(axis=0))
    spearman_values = (centered_ref @ centered) / denominator
    reference_top = reference_rank <= k
    top = ranks <= k
    inter = (top & reference_top[:, None]).sum(axis=0)
    jaccard_values = inter / (2 * k - inter)
    shift_values = np.abs(ranks - reference_rank[:, None]).mean(axis=0)
    low_q, high_q = (1 - ci_level) / 2 * 100, (1 + ci_level) / 2 * 100

    def summary(values: np.ndarray) -> dict[str, float]:
        low, high = np.percentile(values, [low_q, high_q])
        return {"mean": float(values.mean()), "low": float(low), "high": float(high)}

    result: dict[str, Any] = {
        "n": int(n),
        "top_k": int(k),
        "n_weight_vectors": int(alternatives.shape[0]),
        "spearman": summary(spearman_values),
        "jaccard_top": summary(jaccard_values),
        "mean_rank_shift": summary(shift_values),
    }
    if intervals:
        rank_low, rank_high = np.percentile(ranks, [low_q, high_q], axis=1)
        widths = rank_high - rank_low
        stable = (top.mean(axis=1)[reference_top] >= stability_threshold).mean()
        result["rank_interval"] = {
            "median_width": float(np.median(widths)),
            "p95_width": float(np.percentile(widths, 95)),
            "median_width_share": float(np.median(widths) / n),
        }
        result["share_top_stable"] = float(stable)
    return result


def run_robustness(year_scores: Mapping[int, pd.DataFrame], settings: CalibrationSettings) -> dict[str, Any]:
    """Weight robustness and sensitivity of the base index (ADR-062 rule for ``V``).

    Args:
        year_scores: Normalized scores per year from :func:`build_year`.
        settings: Calibration settings.

    Returns:
        Weights under Min-Max and percentile-rank normalization, the cluster
        bootstrap of the weights, the agreement between the two normalizations
        and the sensitivity of each year's ranking to alternative weights.
    """
    cfg = settings.robustness
    # Row order must not matter: DuckDB does not guarantee it, and ties in the index are
    # broken by position.
    year_scores = {year: frame.sort_index() for year, frame in year_scores.items()}
    boot_seed, dirichlet_seed = np.random.SeedSequence(cfg.random_state).spawn(2)
    columns = list(SCORE_COLUMNS)
    stacked = stack_scores(year_scores)
    reference = critic_weights(stacked[columns])
    reference_array = reference.to_numpy()
    draws = bootstrap_critic_weights(stacked, cfg.bootstrap_samples, np.random.default_rng(boot_seed))

    rank_frames = {year: percentile_rank_scores(_ordered_scores(frame, "V")) for year, frame in year_scores.items()}
    rank_weights = critic_weights(pd.concat(list(rank_frames.values()), ignore_index=True)[columns])
    rank_array = rank_weights.reindex(columns).to_numpy()
    uniform = np.full((1, len(columns)), 1.0 / len(columns))
    dirichlet = dirichlet_weights(
        reference_array, cfg.dirichlet_concentration, cfg.dirichlet_samples, np.random.default_rng(dirichlet_seed)
    )

    common = {
        "top_fraction": settings.top_fraction,
        "ci_level": cfg.ci_level,
        "stability_threshold": cfg.stability_threshold,
    }
    sensitivity: dict[int, Any] = {}
    agreement: dict[int, Any] = {}
    for year, frame in year_scores.items():
        matrix = _ordered_scores(frame, "V").to_numpy(dtype=float)
        sensitivity[year] = {
            "uniform": sensitivity_metrics(matrix, reference_array, uniform, intervals=False, **common),
            "critic_rank_weights": sensitivity_metrics(
                matrix, reference_array, rank_array[None, :], intervals=False, **common
            ),
            "bootstrap_weights": sensitivity_metrics(matrix, reference_array, draws, intervals=True, **common),
            "dirichlet_weights": sensitivity_metrics(matrix, reference_array, dirichlet, intervals=True, **common),
        }
        minmax_index = pd.Series(matrix @ reference_array)
        rank_index = pd.Series(rank_frames[year].to_numpy(dtype=float) @ rank_array)
        agreement[year] = compare_rankings(minmax_index, rank_index, settings.top_fraction)
    difference = (reference - rank_weights).abs()
    return {
        "config": cfg.model_dump(),
        "weights": {
            "minmax_pooled": reference.to_dict(),
            "rank_pooled": rank_weights.to_dict(),
            "abs_diff": difference.to_dict(),
            "max_abs_diff": float(difference.max()),
        },
        "bootstrap": summarize_bootstrap(draws, reference, cfg.ci_level),
        "normalization_agreement": agreement,
        "sensitivity": sensitivity,
    }


def _ordered_scores(frame: pd.DataFrame, v_column: str) -> pd.DataFrame:
    """Scores in :data:`SCORE_COLUMNS` order, with ``v_column`` acting as ``V``."""
    others = [name for name in SCORE_COLUMNS if name != "V"]
    return frame[[*others, v_column]].rename(columns={v_column: "V"})[list(SCORE_COLUMNS)]


def calibrate_weights(
    year_scores: Mapping[int, pd.DataFrame], w_min_aviso: float, v_column: str = "V"
) -> dict[str, Any]:
    """CRITIC weights on the pooled window and per year.

    Args:
        year_scores: Normalized scores per year.
        w_min_aviso: Weights below this value are reported as warnings.
        v_column: Column used as the volume score (``V`` for the ADR-062
            rule, ``V_pooled`` for the ADR-063 rule).

    Returns:
        Pooled and per-year weights, warning counts, cross-year spread
        and the pooled Spearman matrix.
    """
    frames = {year: _ordered_scores(frame, v_column) for year, frame in year_scores.items()}
    pooled_frame = pd.concat(list(frames.values()), ignore_index=True)
    pooled = critic_weights(pooled_frame)
    by_year = {year: critic_weights(frame) for year, frame in frames.items()}
    table = pd.DataFrame(by_year)
    return {
        "pooled": pooled.to_dict(),
        "by_year": {year: weights.to_dict() for year, weights in by_year.items()},
        "below_w_min_aviso": {
            "pooled": [name for name, w in pooled.items() if w < w_min_aviso],
            "by_year": {
                year: [name for name, w in weights.items() if w < w_min_aviso]
                for year, weights in by_year.items()
            },
        },
        "cross_year_range": (table.max(axis=1) - table.min(axis=1)).to_dict(),
        "pooled_spearman_matrix": pooled_frame.rank().corr().to_dict(),
    }


def run_calibration(
    con: duckdb.DuckDBPyConnection,
    settings: CalibrationSettings,
    stage: Literal["baseline", "k_search", "full", "robustness"] = "baseline",
) -> dict[str, Any]:
    """Run the calibration and return the report.

    Stages:
        ``robustness``: score distributions, cluster bootstrap of the CRITIC
        weights, CRITIC on percentile ranks and the sensitivity of the
        base-index ranking to the weights (ADR-029); needs no ``pooling.k``.
        ``baseline`` (default): the ADR-062 diagnostics (CRITIC weights,
        dispersion, variance decomposition, ``n_min_pares`` sensitivity,
        old vs new supplier-dependency score); needs no ``pooling.k``.
        ``k_search``: leave-one-out search of the shrinkage ``k`` per house
        over ``pooling.k_grid``; needs no ``k`` in the configuration.
        ``full``: the ADR-062 diagnostics plus the pooled volume score, the
        acceptance criteria A1/A2 and pooled CRITIC weights; requires
        ``pooling.k`` filled for every house present in the data.

    Args:
        con: Open DuckDB connection (read-only recommended).
        settings: Calibration settings.
        stage: ``"baseline"``, ``"k_search"``, ``"full"`` or ``"robustness"``.

    Returns:
        JSON-friendly report.

    Raises:
        ConfigError: In the ``full`` stage when ``pooling.k`` is incomplete.
        ValueError: If a year has no data or too few scored parliamentarians.
    """
    run_id = str(uuid.uuid4())
    logger.info("risk_calibration.start", run_id=run_id, years=settings.window_years, stage=stage)
    totals = load_totals(con, settings)
    pairs = load_pairs(con, settings)
    groups = load_groups(con, settings)
    external = load_external_scores(con, settings)
    intervals = load_intervals(con, settings)
    months = months_in_office(intervals, settings.window_years, settings.days_per_month)

    volumes: dict[int, pd.DataFrame] = {}
    year_scores: dict[int, pd.DataFrame] = {}
    metas: dict[int, dict[str, Any]] = {}
    for year in settings.window_years:
        volume, scores, meta = build_year(year, totals, pairs, groups, months, external, settings)
        if len(scores) < 2:
            raise ValueError(f"year {year}: fewer than 2 parliamentarians have all scores")
        volumes[year], year_scores[year], metas[year] = volume, scores, meta

    meta = {
        "run_id": run_id,
        "stage": stage,
        "execution_timestamp": datetime.now(UTC).isoformat(),
        "window_years": settings.window_years,
        "n_min_pares": settings.n_min_pares,
        "meses_min": settings.meses_min,
        "w_min_aviso": settings.w_min_aviso,
        "data_fingerprint": data_fingerprint(
            totals,
            pairs,
            groups,
            external,
            intervals,
            settings.fingerprint_decimals,
            settings.fingerprint_money_decimals,
        ),
    }
    if stage == "baseline":
        return {
            "meta": meta,
            "years": {
                year: analyze_year(year, volumes[year], year_scores[year], metas[year], settings)
                for year in volumes
            },
            "weights": calibrate_weights(year_scores, settings.w_min_aviso),
        }

    if stage == "robustness":
        quantiles = settings.robustness.distribution_quantiles
        return {
            "meta": meta,
            "distributions": {
                "pooled": score_distribution(stack_scores(year_scores)[list(SCORE_COLUMNS)], quantiles),
                "by_year": {year: score_distribution(frame, quantiles) for year, frame in year_scores.items()},
            },
            "robustness": run_robustness(year_scores, settings),
        }

    grid = list(settings.pooling.k_grid)
    k_values = list(grid)
    k_by_casa: dict[str, float] = {}
    if stage == "full":
        casas = sorted({str(casa) for volume in volumes.values() for casa in volume["casa"].dropna().unique()})
        missing = [casa for casa in casas if settings.pooling.k.get(casa) is None]
        if missing:
            raise ConfigError(
                f"pooling.k is not set for {missing}; run --stage k_search and fill pooling.k (ADR-063, item 7)"
            )
        k_by_casa = {casa: float(settings.pooling.k[casa]) for casa in casas}  # type: ignore[arg-type]
        k_values = sorted(set(k_values) | set(k_by_casa.values()))

    components = {
        year: loo_components(volume[["total", "meses", "casa", "uf"]], settings.meses_min)
        for year, volume in volumes.items()
    }
    per_year_loo = {
        year: loo_error_sums(frame, k_values, settings.n_min_pares) for year, frame in components.items()
    }
    loo = aggregate_loo(per_year_loo)
    tolerance = settings.pooling.tolerance
    pooling: dict[str, Any] = {
        "k_grid": grid,
        "loo_mean": loo["mean"],
        "n_obs": loo["n_obs"],
        "loo_by_year": loo["by_year"],
        "k_argmin": {casa: select_k(errors, grid, tolerance) for casa, errors in loo["mean"].items()},
        "k_argmin_by_year": {
            year: {casa: select_k(errors, grid, tolerance) for casa, errors in per_casa.items()}
            for year, per_casa in loo["by_year"].items()
        },
    }
    if stage == "k_search":
        return {"meta": meta, "k_search": pooling}

    years: dict[int, Any] = {}
    pooled_scores: dict[int, pd.DataFrame] = {}
    for year, volume in volumes.items():
        volume_pooled, scores_pooled = attach_pooled(volume, year_scores[year], k_by_casa, settings.meses_min)
        section = analyze_year(year, volume, year_scores[year], metas[year], settings)
        section["pooling"] = analyze_pooling(
            volume_pooled, scores_pooled, settings, components[year], k_by_casa
        )
        years[year] = section
        pooled_scores[year] = scores_pooled
    pooling.update(
        {
            "k": k_by_casa,
            "k_matches_argmin": {
                casa: math.isclose(k_by_casa[casa], pooling["k_argmin"][casa]) for casa in pooling["k_argmin"]
            },
            "weights": calibrate_weights(pooled_scores, settings.w_min_aviso, v_column="V_pooled"),
            "acceptance": evaluate_acceptance(
                {year: section["pooling"]["uf_share_residual"] for year, section in years.items()},
                loo["mean"],
                k_by_casa,
                settings.pooling.strict_casas,
                tolerance,
                {year: section["pooling"]["uf_share_loo"] for year, section in years.items()},
            ),
        }
    )
    return {
        "meta": meta,
        "years": years,
        "weights": calibrate_weights(year_scores, settings.w_min_aviso),
        "pooling": pooling,
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _clean(value: Any) -> Any:
    """Make nested report data JSON-safe (NaN -> None, numpy -> python)."""
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def _fmt(value: Any) -> str:
    """Format a number for the Markdown report."""
    if value is None:
        return "n/a"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def _k_columns(errors: Mapping[str, Any]) -> list[str]:
    """Scheme names in display order: comparators first, then ``k=`` by value."""
    ks = sorted((name for name in errors if name.startswith("k=")), key=lambda name: float(name[2:]))
    return ["casa_only", "adr062_rule", *ks]


def _render_k_search(report: Mapping[str, Any]) -> str:
    """Markdown of the ``k_search`` stage (ADR-063, item 6)."""
    meta, search = report["meta"], report["k_search"]
    lines = [
        "# ADR-063 — k search (leave-one-out)",
        "",
        f"- run_id: `{meta['run_id']}` | stage: {meta['stage']}",
        f"- execution_timestamp: {meta['execution_timestamp']}",
        f"- window_years: {meta['window_years']} | n_min_pares (comparator): {meta['n_min_pares']}",
        f"- k_grid: {search['k_grid']}",
        _fingerprint_line(meta),
        "",
        "## Mean absolute LOO error (pooled over years)",
        "",
    ]
    casas = sorted(search["loo_mean"])
    columns = _k_columns(search["loo_mean"][casas[0]]) if casas else []
    lines += ["| casa | n | " + " | ".join(columns) + " |", "|---|---|" + "---|" * len(columns)]
    for casa in casas:
        errors = search["loo_mean"][casa]
        cells = " | ".join(_fmt(errors.get(name)) for name in columns)
        lines.append(f"| {casa} | {search['n_obs'][casa]} | {cells} |")
    lines += ["", "## Selected k (argmin, ties to larger k)", ""]
    for casa in casas:
        by_year = ", ".join(f"{year}: {_fmt(ks[casa])}" for year, ks in search["k_argmin_by_year"].items())
        lines.append(f"- {casa}: **k = {_fmt(search['k_argmin'][casa])}** (by year: {by_year})")
    lines += ["", "Fill `pooling.k` in the YAML with these values and run `--stage full`.", ""]
    return "\n".join(lines)


def _render_pooling(report: Mapping[str, Any]) -> list[str]:
    """Markdown lines of the ADR-063 section of the ``full`` report."""
    pooling = report["pooling"]
    acceptance = pooling["acceptance"]
    lines = ["## ADR-063 — partial pooling", ""]
    lines.append(
        "- k: " + ", ".join(f"{casa}={_fmt(k)}" for casa, k in pooling["k"].items())
        + " | LOO argmin: " + ", ".join(f"{casa}={_fmt(k)}" for casa, k in pooling["k_argmin"].items())
        + " | k equals argmin: " + str(pooling["k_matches_argmin"])
    )
    lines += ["", "### A1 — UF share of the residual z (R² on UF dummies)", ""]
    lines += ["| year | casa | ADR-062 rule | pooled | strict | pass |", "|---|---|---|---|---|---|"]
    for row in acceptance["a1"]["rows"]:
        lines.append(
            f"| {row['year']} | {row['casa']} | {_fmt(row['baseline'])} | {_fmt(row['pooled'])} "
            f"| {row['strict']} | {row['pass']} |"
        )
    lines += [
        "",
        "### A1-LOO — same comparison on out-of-sample residuals (informative, not part of the verdict)",
        "",
        "| year | casa | ADR-062 rule | pooled | casa_only | pass |",
        "|---|---|---|---|---|---|",
    ]
    for row in acceptance["a1_loo"]["rows"]:
        lines.append(
            f"| {row['year']} | {row['casa']} | {_fmt(row['baseline'])} | {_fmt(row['pooled'])} "
            f"| {_fmt(row['casa_only'])} | {row['pass']} |"
        )
    lines += ["", "### A2 — leave-one-out error (pooled over years)", ""]
    lines += ["| casa | k | error k | casa_only | ADR-062 rule | pass |", "|---|---|---|---|---|---|"]
    for row in acceptance["a2"]["rows"]:
        lines.append(
            f"| {row['casa']} | {_fmt(row['k'])} | {_fmt(row['error_k'])} | {_fmt(row['error_casa_only'])} "
            f"| {_fmt(row['error_adr062_rule'])} | {row['pass']} |"
        )
    verdict = "criteria met" if acceptance["all_pass"] else "criteria NOT met (ADR-063, item 9: rule of ADR-062 stands)"
    lines += [
        "",
        f"**A1: {'PASS' if acceptance['a1']['pass'] else 'FAIL'} · A2: {'PASS' if acceptance['a2']['pass'] else 'FAIL'}"
        f" → {verdict}**",
        "",
        "### CRITIC weights (pooled): ADR-062 V vs pooled V",
        "",
        "| score | ADR-062 V | pooled V |",
        "|---|---|---|",
    ]
    for name in SCORE_COLUMNS:
        baseline_w = _fmt(report["weights"]["pooled"][name])
        pooled_w = _fmt(pooling["weights"]["pooled"][name])
        lines.append(f"| {name} | {baseline_w} | {pooled_w} |")
    lines += ["", "### Per year", ""]
    for year, section in report["years"].items():
        block = section["pooling"]
        change = block["v_pooled_vs_v"]
        lines.append(
            f"- {year}: V pooled vs V — Spearman {_fmt(change['spearman'])}, "
            f"Jaccard top {_fmt(change['jaccard_top'])}, mean rank shift {_fmt(change['mean_rank_shift'])}; "
            f"lambda_u {block['lambda_u']}"
        )
    lines.append("")
    return lines


def _fingerprint_line(meta: Mapping[str, Any]) -> str:
    """One Markdown line with the short digests of the data inputs."""
    fingerprint = meta.get("data_fingerprint")
    if not fingerprint:
        return "- data_fingerprint: n/a"
    digests = " | ".join(f"{name} {digest[:12]}" for name, digest in fingerprint["hashes"].items())
    return f"- data_fingerprint: {digests}"


def _summary_cell(summary: Mapping[str, float]) -> str:
    """``mean (low–high)`` for a metric summary."""
    return f"{_fmt(summary['mean'])} ({_fmt(summary['low'])}–{_fmt(summary['high'])})"


def _render_robustness(report: Mapping[str, Any]) -> str:
    """Markdown of the ``robustness`` stage (ADR-029 criteria)."""
    meta, robustness = report["meta"], report["robustness"]
    weights, boot = robustness["weights"], robustness["bootstrap"]
    config = robustness["config"]
    lines = [
        "# ADR-029 — weight robustness and sensitivity (base index, ADR-062 rule for V)",
        "",
        f"- run_id: `{meta['run_id']}` | stage: {meta['stage']}",
        f"- execution_timestamp: {meta['execution_timestamp']}",
        f"- window_years: {meta['window_years']}",
        _fingerprint_line(meta),
        f"- bootstrap_samples: {config['bootstrap_samples']} | dirichlet_samples: {config['dirichlet_samples']} "
        f"| dirichlet_concentration: {config['dirichlet_concentration']} | random_state: {config['random_state']} "
        f"| ci_level: {config['ci_level']} | stability_threshold: {config['stability_threshold']}",
        "",
        "## Empirical distribution of each score",
        "",
    ]
    sections = {"pooled": report["distributions"]["pooled"], **report["distributions"]["by_year"]}
    for label, section in sections.items():
        names = list(next(iter(section.values()))["quantiles"])
        lines += [
            f"### {label}",
            "",
            "| score | n | mean | std | skew | share zero | " + " | ".join(names) + " |",
            "|---|---|---|---|---|---|" + "---|" * len(names),
        ]
        for score, stats in section.items():
            cells = " | ".join(_fmt(stats["quantiles"][name]) for name in names)
            lines.append(
                f"| {score} | {stats['n']} | {_fmt(stats['mean'])} | {_fmt(stats['std'])} | {_fmt(stats['skew'])} "
                f"| {_fmt(stats['share_zero'])} | {cells} |"
            )
        lines.append("")
    lines += [
        "## CRITIC weights: Min-Max vs percentile ranks (pooled)",
        "",
        "| score | Min-Max | percentile ranks | abs diff |",
        "|---|---|---|---|",
    ]
    for name in SCORE_COLUMNS:
        lines.append(
            f"| {name} | {_fmt(weights['minmax_pooled'][name])} | {_fmt(weights['rank_pooled'][name])} "
            f"| {_fmt(weights['abs_diff'][name])} |"
        )
    lines += [
        "",
        f"Largest absolute difference: {_fmt(weights['max_abs_diff'])}.",
        "",
        f"## Cluster bootstrap of the pooled weights ({boot['n_draws']} draws, {boot['ci_level']:.0%} interval)",
        "",
        f"Uniform weight = {_fmt(boot['uniform_weight'])}.",
        "",
        "| score | reference | mean | std | CI low | CI high | interval contains uniform | share with top weight |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in SCORE_COLUMNS:
        stats = boot["scores"][name]
        lines.append(
            f"| {name} | {_fmt(stats['reference'])} | {_fmt(stats['mean'])} | {_fmt(stats['std'])} "
            f"| {_fmt(stats['ci_low'])} | {_fmt(stats['ci_high'])} | {stats['includes_uniform']} "
            f"| {_fmt(boot['share_top_weight'][name])} |"
        )
    lines += ["", "## Agreement between the Min-Max and the percentile-rank indexes", ""]
    for year, values in robustness["normalization_agreement"].items():
        lines.append(
            f"- {year}: Spearman {_fmt(values['spearman'])}, Jaccard top {_fmt(values['jaccard_top'])}, "
            f"mean rank shift {_fmt(values['mean_rank_shift'])}"
        )
    lines += ["", "## Sensitivity of the base-index ranking to the weight vector", ""]
    for year, schemes in robustness["sensitivity"].items():
        lines += [
            f"### {year}",
            "",
            "| weights | vectors | Spearman | Jaccard top | mean rank shift "
            "| rank-interval median width | top members stable |",
            "|---|---|---|---|---|---|---|",
        ]
        for scheme, metrics in schemes.items():
            interval = metrics.get("rank_interval")
            width = "n/a"
            if interval:
                width = f"{_fmt(interval['median_width'])} ({_fmt(interval['median_width_share'])} of n)"
            stable = _fmt(metrics["share_top_stable"]) if "share_top_stable" in metrics else "n/a"
            lines.append(
                f"| {scheme} | {metrics['n_weight_vectors']} | {_summary_cell(metrics['spearman'])} "
                f"| {_summary_cell(metrics['jaccard_top'])} | {_summary_cell(metrics['mean_rank_shift'])} "
                f"| {width} | {stable} |"
            )
        lines.append("")
    return "\n".join(lines)


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the report as Markdown, ready to attach to ADR-062.

    Args:
        report: JSON-safe report from :func:`run_calibration`.

    Returns:
        Markdown text.
    """
    stage = report["meta"].get("stage")
    if stage == "robustness":
        return _render_robustness(report)
    if stage == "k_search":
        return _render_k_search(report)
    meta, weights = report["meta"], report["weights"]
    lines = [
        "# ADR-062 — calibration report",
        "",
        f"- run_id: `{meta['run_id']}`",
        f"- execution_timestamp: {meta['execution_timestamp']}",
        f"- window_years: {meta['window_years']} | n_min_pares: {meta['n_min_pares']} "
        f"| meses_min: {meta['meses_min']} | w_min_aviso: {meta['w_min_aviso']}",
        _fingerprint_line(meta),
        "",
        "## CRITIC weights",
        "",
        "| score | pooled | " + " | ".join(report["years"]) + " | range |",
        "|---|---|" + "---|" * len(report["years"]) + "---|",
    ]
    for name in SCORE_COLUMNS:
        per_year = " | ".join(_fmt(weights["by_year"][year][name]) for year in report["years"])
        lines.append(
            f"| {name} | {_fmt(weights['pooled'][name])} | {per_year} | {_fmt(weights['cross_year_range'][name])} |"
        )
    lines += ["", f"Below w_min_aviso (pooled): {weights['below_w_min_aviso']['pooled'] or 'none'}", ""]
    for year, section in report["years"].items():
        lines += [f"## {year}", ""]
        lines.append(
            f"- universe {section['n_universe']} | scored {section['n_scored']} | "
            f"null-supplier value share {_fmt(section['null_supplier_value_share'])}"
        )
        lines.append(f"- Spearman(C, D): {_fmt(section['spearman_cd'])}")
        lines.append("- Spearman(V, ·): " + ", ".join(f"{k}={_fmt(v)}" for k, v in section["spearman_v_vs"].items()))
        old_new = section["d_old_vs_new"]
        lines.append(
            f"- D old vs new: Spearman {_fmt(old_new['spearman'])}, Jaccard top {_fmt(old_new['jaccard_top'])}, "
            f"mean rank shift {_fmt(old_new['mean_rank_shift'])}, "
            f"mean {_fmt(old_new['mean_old'])} -> {_fmt(old_new['mean_new'])}"
        )
        variance = section["variance_decomposition"]
        lines.append(
            f"- R² ln(total): months {_fmt(variance['r2_meses'])} → +UF {_fmt(variance['r2_meses_uf'])} "
            f"→ +house {_fmt(variance['r2_meses_uf_casa'])}"
        )
        for key, ratios in section["dispersion"].items():
            lines.append(
                f"- {key}: raw {_fmt(ratios['raw_total'])} | monthly {_fmt(ratios['monthly'])} "
                f"| residual {_fmt(ratios['residual'])}"
            )
        groups = section["groups"]
        lines.append(
            f"- groups: {groups['n_groups']} total, {groups['n_groups_below_n_min']} below n_min "
            f"{groups['groups_below_n_min_by_casa']}; fallback share {_fmt(groups['share_fallback_casa'])}; "
            f"flags {groups['flags']}"
        )
        months = section["months"]
        lines.append(
            f"- months in office: partial-year share {_fmt(months['share_partial_year'])}, "
            f"below meses_min {_fmt(months['share_below_meses_min'])}, without interval {months['n_without_interval']}"
        )
        lines += ["", "| n_min | Spearman vs base | Jaccard top vs base | fallback share |", "|---|---|---|---|"]
        for row in section["sensitivity_n_min"]:
            lines.append(
                f"| {row['n_min']} | {_fmt(row['spearman_vs_base'])} | {_fmt(row['jaccard_top_vs_base'])} "
                f"| {_fmt(row['share_fallback_casa'])} |"
            )
        lines.append("")
    if "pooling" in report:
        lines += _render_pooling(report)
    return "\n".join(lines)


def write_report(report: Mapping[str, Any], output_dir: Path, config_sha256: str) -> tuple[Path, Path]:
    """Write the JSON and Markdown reports.

    Args:
        report: Report from :func:`run_calibration`.
        output_dir: Destination directory (created if missing).
        config_sha256: SHA-256 of the YAML used, stored for traceability.

    Returns:
        Paths of the JSON and Markdown files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = _clean(report)
    safe["meta"]["config_sha256"] = config_sha256
    prefix = {"k_search": "risk_k_search", "robustness": "risk_robustness"}.get(
        safe["meta"].get("stage"), "risk_calibration"
    )
    stem = f"{prefix}_{safe['meta']['run_id'][:8]}"
    json_path, md_path = output_dir / f"{stem}.json", output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(safe, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(safe), encoding="utf-8")
    logger.info("risk_calibration.report_written", json=str(json_path), markdown=str(md_path))
    return json_path, md_path


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entrypoint.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code: 0 on success, 2 on configuration errors,
        1 on database or data errors.
    """
    parser = argparse.ArgumentParser(description="ADR-062 risk index calibration")
    parser.add_argument("--config", type=Path, required=True, help="Path to risk_calibration.yaml")
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="DuckDB file (defaults to the DUCKDB_DATABASE_PATH environment variable)",
    )
    parser.add_argument(
        "--stage",
        choices=("baseline", "k_search", "full", "robustness"),
        default="baseline",
        help="baseline: ADR-062 diagnostics (default); robustness: ADR-029 weight robustness; "
        "k_search/full: ADR-063 pooling stages",
    )
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
        database = args.database or os.environ.get("DUCKDB_DATABASE_PATH")
        if not database:
            raise ConfigError("provide --database or set DUCKDB_DATABASE_PATH")
        config_sha256 = hashlib.sha256(args.config.read_bytes()).hexdigest()
    except (ConfigError, OSError) as exc:
        logger.error("risk_calibration.config_error", error=str(exc))
        return 2
    try:
        con = duckdb.connect(str(database), read_only=True)
        try:
            report = run_calibration(con, settings, stage=args.stage)
        finally:
            con.close()
    except ConfigError as exc:
        logger.error("risk_calibration.config_error", error=str(exc))
        return 2
    except (duckdb.Error, ValueError) as exc:
        logger.error("risk_calibration.failed", error=str(exc))
        return 1
    write_report(report, settings.output_dir, config_sha256)
    return 0


if __name__ == "__main__":
    sys.exit(main())
