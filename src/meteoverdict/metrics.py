"""Verification metrics (roadmap 2.2).

Scores are kept as additive sums, so daily scores can be summed over any window,
station group or region before the final metric is computed:

* continuous (temperature, wind, precipitation amounts): ``n``, ``sum_err``,
  ``sum_abs_err``, ``sum_sq_err`` with error = forecast - observed →
  MAE = sum_abs_err / n, bias = sum_err / n, RMSE = sqrt(sum_sq_err / n);
* categorical (precipitation events "at least T mm"): hits ``a``, false alarms ``b``,
  misses ``c`` and correct negatives ``d`` →
  POD = a / (a + c), FAR = b / (a + b),
  ETS = (a - a_r) / (a + b + c - a_r) with a_r = (a + b)(a + c) / (a + b + c + d).

A metric whose denominator is zero is null.
"""

from __future__ import annotations

import polars as pl

#: Daily precipitation event thresholds in mm: 0.1 and 5 (ROADMAP "Scope v1") and 20 for
#: heavy precipitation (the ETCCDI climate index R20mm, roadmap 5.2).
PRECIPITATION_THRESHOLDS = (0.1, 5.0, 20.0)

SUMS = ("n", "sum_err", "sum_abs_err", "sum_sq_err")


def label(threshold: float) -> str:
    """Column suffix for a threshold: 0.1 → "0p1", 5.0 → "5"."""
    return f"{threshold:g}".replace(".", "p")


def counts_columns(threshold: float) -> list[str]:
    return [f"{k}_{label(threshold)}" for k in ("a", "b", "c", "d")]


def error_sums(forecast: str = "forecast", observed: str = "observed") -> list[pl.Expr]:
    """Aggregations for ``group_by(...).agg(...)``: the continuous sums."""
    error = pl.col(forecast).cast(pl.Float64) - pl.col(observed).cast(pl.Float64)
    return [
        error.count().alias("n"),
        error.sum().alias("sum_err"),
        error.abs().sum().alias("sum_abs_err"),
        (error * error).sum().alias("sum_sq_err"),
    ]


def contingency_counts(
    threshold: float, forecast: str = "forecast", observed: str = "observed"
) -> list[pl.Expr]:
    """Aggregations: hits, false alarms, misses and correct negatives for ``>= threshold``."""
    f = pl.col(forecast) >= threshold
    o = pl.col(observed) >= threshold
    a, b, c, d = counts_columns(threshold)
    return [
        (f & o).sum().cast(pl.Int64).alias(a),
        (f & ~o).sum().cast(pl.Int64).alias(b),
        (~f & o).sum().cast(pl.Int64).alias(c),
        (~f & ~o).sum().cast(pl.Int64).alias(d),
    ]


def _ratio(numerator: pl.Expr, denominator: pl.Expr) -> pl.Expr:
    return pl.when(denominator > 0).then(numerator / denominator).otherwise(None)


def continuous_scores(sums: pl.DataFrame | pl.LazyFrame) -> pl.DataFrame | pl.LazyFrame:
    """Add ``mae``, ``bias`` and ``rmse`` to a frame with the continuous sums."""
    n = pl.col("n").cast(pl.Float64)
    return sums.with_columns(
        _ratio(pl.col("sum_abs_err"), n).alias("mae"),
        _ratio(pl.col("sum_err"), n).alias("bias"),
        _ratio(pl.col("sum_sq_err"), n).sqrt().alias("rmse"),
    )


def categorical_scores(
    counts: pl.DataFrame | pl.LazyFrame, threshold: float
) -> pl.DataFrame | pl.LazyFrame:
    """Add ``pod_*``, ``far_*`` and ``ets_*`` for ``threshold`` to a frame with its counts."""
    a, b, c, d = (pl.col(name).cast(pl.Float64) for name in counts_columns(threshold))
    random_hits = _ratio((a + b) * (a + c), a + b + c + d)
    suffix = label(threshold)
    return counts.with_columns(
        _ratio(a, a + c).alias(f"pod_{suffix}"),
        _ratio(b, a + b).alias(f"far_{suffix}"),
        _ratio(a - random_hits, a + b + c - random_hits).alias(f"ets_{suffix}"),
    )
