"""Verification metrics (roadmap 2.2).

Scores are kept as additive sums, so daily scores can be summed over any window,
station group or region before the final metric is computed:

* continuous (temperature, wind, precipitation amounts): ``n``, ``sum_err``,
  ``sum_abs_err``, ``sum_sq_err`` with error = forecast - observed →
  MAE = sum_abs_err / n, bias = sum_err / n, RMSE = sqrt(sum_sq_err / n);
* categorical (events "at least T": daily precipitation in mm, daily maximum
  temperature in °C): hits ``a``, false alarms ``b``,
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
#: Daily maximum temperature event thresholds in °C: a "tropický den" (tropical day,
#: ČHMÚ's term for a day reaching 30 °C), roadmap 5.2b.
HEAT_THRESHOLDS = (30.0,)
#: All event thresholds; their count columns share one namespace (``a_30`` etc.).
THRESHOLDS = PRECIPITATION_THRESHOLDS + HEAT_THRESHOLDS

SUMS = ("n", "sum_err", "sum_abs_err", "sum_sq_err")


def compact(columns: list[str]) -> dict[str, pl.DataType]:
    """Storage types of the score columns among ``columns`` (roadmap 3.5).

    One score row covers one station-day, so ``n`` is at most 24 and each count 0 or 1;
    float32 keeps about 7 significant digits of the sums. Aggregations sum them as
    ``total`` does, in 64 bits.
    """
    counts = {c for t in THRESHOLDS for c in counts_columns(t)}
    types: dict[str, pl.DataType] = {}
    for c in columns:
        if c == "n":
            types[c] = pl.UInt16
        elif c in SUMS:
            types[c] = pl.Float32
        elif c in counts:
            types[c] = pl.UInt8
    return types


def total(column: str) -> pl.Expr:
    """Sum of a stored score column, in 64 bits."""
    wide = pl.Float64 if column in SUMS[1:] else pl.Int64
    return pl.col(column).cast(wide).sum()


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
