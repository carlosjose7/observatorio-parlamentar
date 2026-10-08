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
* old (simple mean) vs new (value-weighted) supplier-dependency score.

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


def calibrate_weights(
    year_scores: Mapping[int, pd.DataFrame], w_min_aviso: float
) -> dict[str, Any]:
    """CRITIC weights on the pooled window and per year.

    Args:
        year_scores: Normalized scores per year.
        w_min_aviso: Weights below this value are reported as warnings.

    Returns:
        Pooled and per-year weights, warning counts, cross-year spread
        and the pooled Spearman matrix.
    """
    columns = list(SCORE_COLUMNS)
    pooled_frame = pd.concat([frame[columns] for frame in year_scores.values()], ignore_index=True)
    pooled = critic_weights(pooled_frame)
    by_year = {year: critic_weights(frame[columns]) for year, frame in year_scores.items()}
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


def run_calibration(con: duckdb.DuckDBPyConnection, settings: CalibrationSettings) -> dict[str, Any]:
    """Run the full calibration and return the report.

    Args:
        con: Open DuckDB connection (read-only recommended).
        settings: Calibration settings.

    Returns:
        JSON-friendly report with metadata, per-year sections and weights.
    """
    run_id = str(uuid.uuid4())
    logger.info("risk_calibration.start", run_id=run_id, years=settings.window_years)
    totals = load_totals(con, settings)
    pairs = load_pairs(con, settings)
    groups = load_groups(con, settings)
    external = load_external_scores(con, settings)
    months = months_in_office(load_intervals(con, settings), settings.window_years, settings.days_per_month)

    years: dict[int, Any] = {}
    year_scores: dict[int, pd.DataFrame] = {}
    for year in settings.window_years:
        volume, scores, meta = build_year(year, totals, pairs, groups, months, external, settings)
        if len(scores) < 2:
            raise ValueError(f"year {year}: fewer than 2 parliamentarians have all scores")
        years[year] = analyze_year(year, volume, scores, meta, settings)
        year_scores[year] = scores
    return {
        "meta": {
            "run_id": run_id,
            "execution_timestamp": datetime.now(UTC).isoformat(),
            "window_years": settings.window_years,
            "n_min_pares": settings.n_min_pares,
            "meses_min": settings.meses_min,
            "w_min_aviso": settings.w_min_aviso,
        },
        "years": years,
        "weights": calibrate_weights(year_scores, settings.w_min_aviso),
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


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the report as Markdown, ready to attach to ADR-062.

    Args:
        report: JSON-safe report from :func:`run_calibration`.

    Returns:
        Markdown text.
    """
    meta, weights = report["meta"], report["weights"]
    lines = [
        "# ADR-062 — calibration report",
        "",
        f"- run_id: `{meta['run_id']}`",
        f"- execution_timestamp: {meta['execution_timestamp']}",
        f"- window_years: {meta['window_years']} | n_min_pares: {meta['n_min_pares']} "
        f"| meses_min: {meta['meses_min']} | w_min_aviso: {meta['w_min_aviso']}",
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
    stem = f"risk_calibration_{safe['meta']['run_id'][:8]}"
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
            report = run_calibration(con, settings)
        finally:
            con.close()
    except (duckdb.Error, ValueError) as exc:
        logger.error("risk_calibration.failed", error=str(exc))
        return 1
    write_report(report, settings.output_dir, config_sha256)
    return 0


if __name__ == "__main__":
    sys.exit(main())
