"""Rank models with bootstrap confidence intervals (roadmap 2.5).

For every level, region, window, variable and lead day (on the same fair station-days
as ``meteoverdict.aggregate``), models are ranked by MAE. To tell real differences from
luck we resample **whole days** with replacement (all stations and models of a day stay
together, because forecast errors on one day are correlated across stations) and
recompute every model's MAE. A model is ``tied_with_best`` when the 95 % interval of
its MAE minus the best model's MAE includes 0. The best model is a clear winner only
when no other model is tied with it.

Ranked variables: ``temperature_2m``, ``wind_speed_10m`` and ``precipitation_daily``
(hourly precipitation is left out because its periods differ between models).
"""

from __future__ import annotations

import zlib
from datetime import date

import numpy as np
import polars as pl

from meteoverdict import aggregate

RANKED_VARIABLES = ("temperature_2m", "wind_speed_10m", "precipitation_daily")
RESAMPLES = 1000
CONFIDENCE = 0.95
GROUP = ["level", "region", "window", "variable", "lead_day"]

RANK_SCHEMA = {
    "level": pl.String,
    "region": pl.String,
    "window": pl.String,
    "variable": pl.String,
    "lead_day": pl.Int8,
    "model": pl.String,
    "rank": pl.Int16,
    "diff_to_best": pl.Float64,
    "diff_ci_low": pl.Float64,
    "diff_ci_high": pl.Float64,
    "tied_with_best": pl.Boolean,
    "clear_winner": pl.Boolean,
}


def bootstrap_group(
    abs_err: np.ndarray, n: np.ndarray, rng: np.random.Generator, resamples: int = RESAMPLES
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MAE ranking with intervals for one group.

    ``abs_err`` and ``n`` are days x models (sums over the group's stations per day).
    Returns per model: the order (0 = best), the MAE difference to the best and the
    lower/upper bounds of its interval as a 2 x models array.
    """
    days = abs_err.shape[0]
    mae = abs_err.sum(axis=0) / n.sum(axis=0)
    order = np.argsort(mae, kind="stable")
    best = order[0]
    weights = rng.multinomial(days, np.full(days, 1 / days), size=resamples)  # resamples x days
    boot = (weights @ abs_err) / (weights @ n)  # resamples x models
    diffs = boot - boot[:, [best]]
    tail = (1 - CONFIDENCE) / 2
    bounds = np.quantile(diffs, [tail, 1 - tail], axis=0)
    return order, mae - mae[best], bounds


def rank(
    scores: pl.LazyFrame | pl.DataFrame,
    stations: pl.DataFrame,
    as_of: date | None = None,
    windows: tuple[str, ...] = aggregate.WINDOWS,
    resamples: int = RESAMPLES,
    seed: int = 0,
) -> pl.DataFrame:
    """One row per group and model with its rank and interval."""
    scores = scores.lazy().filter(pl.col("variable").is_in(RANKED_VARIABLES))
    first_day, last_day = aggregate.date_span(scores)
    as_of = as_of or last_day
    info = aggregate.station_info(stations)
    rows = []
    for window in windows:
        start = aggregate.window_start(window, as_of, first_day)
        fair = aggregate.common_days(scores.filter(pl.col("date").is_between(start, as_of)))
        fair = fair.join(info, on="station_id", how="inner")
        for level in aggregate.LEVELS:
            daily = (
                fair.with_columns(aggregate.region_columns(level))
                .group_by("region", "variable", "lead_day", "date", "model")
                .agg(pl.col("sum_abs_err").sum(), pl.col("n").sum())
                .collect()
            )
            for (region, variable, lead_day), part in daily.partition_by(
                ["region", "variable", "lead_day"], as_dict=True
            ).items():
                abs_err = part.pivot(on="model", index="date", values="sum_abs_err").sort("date")
                n = part.pivot(on="model", index="date", values="n").sort("date")
                models = [c for c in abs_err.columns if c != "date"]
                a = abs_err.select(models).to_numpy().astype(float)
                m = n.select(models).to_numpy().astype(float)
                if len(models) == 1:
                    order, diff, bounds = np.array([0]), np.array([0.0]), np.zeros((2, 1))
                else:
                    # a group's resamples depend only on the seed and the group itself
                    key = f"{level}|{region}|{window}|{variable}|{lead_day}".encode()
                    rng = np.random.default_rng([seed, zlib.crc32(key)])
                    order, diff, bounds = bootstrap_group(a, m, rng, resamples)
                # interval of (model - best) contains 0; the best model is not "tied"
                tied = (bounds[0] <= 0) & (bounds[1] >= 0) & (order.argsort() > 0)
                clear = len(models) > 1 and not tied.any()
                for position, index in enumerate(order):
                    rows.append(
                        (
                            level, region, window, variable, lead_day, models[index],
                            position + 1, float(diff[index]), float(bounds[0][index]),
                            float(bounds[1][index]), bool(tied[index]),
                            bool(position == 0 and clear),
                        )
                    )  # fmt: skip
    return pl.DataFrame(rows, schema=RANK_SCHEMA, orient="row").sort([*GROUP, "rank"])
