"""Rank models with block-bootstrap confidence intervals (roadmap 2.5).

For every level, region, window, variable and lead day (on the same fair station-days
and okres pools as ``meteoverdict.aggregate``), models are ranked by MAE. Only the
models with scores on at least ``aggregate.MIN_COVERAGE`` of the window's scored days
are ranked (``aggregate.covered_only``); a newly added model joins once it has them. To tell real
differences from luck we resample **blocks of ``BLOCK_DAYS`` consecutive days** with
replacement (a moving-block bootstrap, circular so the first and last days are drawn as
often as the others). All stations and models of a day stay together, because forecast
errors on one day are correlated across stations; whole blocks stay together because
they are correlated from one day to the next as well (a weather regime lasts a few
days). On the 90 days to 18 October 2026 the daily MAE difference between a model and
the best one had a median lag-1 correlation of 0.11 (okres) to 0.21 (Czechia) for
temperature and 0.16 to 0.28 for wind, still 0.07 to 0.14 for wind at lag 2, and about
0 from lag 3 on (precipitation: about 0 at every lag). Resampling single days ignored
it and gave intervals that were too narrow; 4-day blocks cover it with a day to spare
and still leave 7 or more blocks in a 30-day sample.

For every model and the best one a **Diebold-Mariano** test checks the same difference
with a Newey-West (HAC) variance over ``DM_LAGS`` lags (Bartlett weights), on the daily
loss differential scaled so that its mean is the pooled MAE difference, with the
Harvey-Leybourne-Newbold small-sample factor and a normal p-value (``dm_p``, two-sided).
A model is ``tied_with_best`` unless **both** say it is worse: the 95 % interval of its
MAE minus the best model's excludes 0 **and** ``dm_p`` < 0.05. The best model is a clear
winner only when no other model is tied with it.

``p_best`` is the share of the bootstrap resamples in which a model has the lowest MAE
of the ranked models: how sure the top spot is, which a single winner hides. The map
shows a winner only with ``p_best`` of at least ``P_BEST_MIN``, "no clear winner"
otherwise. ``small_sample``: the comparison rests on fewer than ``SMALL_SAMPLE_DAYS``
days (fewer than 8 blocks), so its intervals and ``p_best`` are themselves rough.

The mean of all models (``blend``, roadmap 5.3) is not ranked (``rank`` null): its
difference and interval are relative to the best single model, so a ``diff_ci_high``
below 0 means the blend beats every model in that group.

Ranked variables: ``temperature_2m``, ``wind_speed_10m``, ``precipitation_daily``,
``precipitation_24h`` and ``temperature_max`` (hourly precipitation is left out
because its periods differ between models).
"""

from __future__ import annotations

import math
import zlib
from datetime import date

import numpy as np
import polars as pl

from meteoverdict import aggregate, blend, metrics

RANKED_VARIABLES = (
    "temperature_2m",
    "wind_speed_10m",
    "precipitation_daily",
    "precipitation_24h",
    "temperature_max",
)
RESAMPLES = 1000
CONFIDENCE = 0.95
#: length of the resampled blocks of consecutive days (see the module docstring)
BLOCK_DAYS = 4
#: Newey-West lags of the Diebold-Mariano variance: the dependence a block covers
DM_LAGS = BLOCK_DAYS - 1
#: a model is significantly worse than the best only below this Diebold-Mariano p-value
DM_ALPHA = 0.05
#: the map names a winner only when it is best in at least this share of the resamples:
#: more often than all the others together, with a margin for the resampling itself
P_BEST_MIN = 0.6
#: fewer scored days than this: ``small_sample`` (as the lead-band ranking's
#: "preliminary"); with ``BLOCK_DAYS`` 4 that is fewer than 8 blocks
SMALL_SAMPLE_DAYS = 30
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
    # added in October 2026 (the honest-scoring review): probability of being best,
    # Diebold-Mariano test against the best model, and the small-sample flag
    "p_best": pl.Float64,
    "dm_stat": pl.Float64,
    "dm_p": pl.Float64,
    "small_sample": pl.Boolean,
}


def block_weights(
    days: int, rng: np.random.Generator, resamples: int = RESAMPLES, block: int = BLOCK_DAYS
) -> np.ndarray:
    """How often each day is drawn in each resample (resamples x days): circular
    moving blocks of ``block`` consecutive days, as many as cover ``days``, cut to
    ``days``. The block is shortened to half the days for very short samples, so a
    resample is never the sample itself."""
    length = max(1, min(block, days // 2))
    count = -(-days // length)
    starts = rng.integers(0, days, size=(resamples, count))
    index = ((starts[:, :, None] + np.arange(length)) % days).reshape(resamples, -1)[:, :days]
    flat = (index + days * np.arange(resamples)[:, None]).ravel()
    return np.bincount(flat, minlength=resamples * days).reshape(resamples, days).astype(float)


def resampled_mae(
    abs_err: np.ndarray,
    n: np.ndarray,
    rng: np.random.Generator,
    resamples: int = RESAMPLES,
    block: int = BLOCK_DAYS,
) -> np.ndarray:
    """Every model's MAE in each block-bootstrap resample (resamples x models)."""
    weights = block_weights(abs_err.shape[0], rng, resamples, block)
    return (weights @ abs_err) / (weights @ n)


def bootstrap_best(
    abs_err: np.ndarray,
    n: np.ndarray,
    rng: np.random.Generator,
    resamples: int = RESAMPLES,
    ranked: np.ndarray | None = None,
    block: int = BLOCK_DAYS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """``bootstrap_group`` and ``p_best``: per model the share of the resamples in which
    it has the lowest MAE of the ranked models (0 for the columns not ranked; a resample
    with a tie counts for each tied model in equal parts)."""
    mae = abs_err.sum(axis=0) / n.sum(axis=0)
    ranked = np.ones(mae.shape, dtype=bool) if ranked is None else ranked
    order = np.argsort(np.where(ranked, mae, np.inf), kind="stable")
    best = order[0]
    boot = resampled_mae(abs_err, n, rng, resamples, block)
    diffs = boot - boot[:, [best]]
    tail = (1 - CONFIDENCE) / 2
    bounds = np.quantile(diffs, [tail, 1 - tail], axis=0)
    # a resample where several models share the lowest MAE counts for each in part
    candidates = np.where(ranked, boot, np.inf)
    lowest = np.isclose(candidates, candidates.min(axis=1, keepdims=True), rtol=0, atol=1e-12)
    p_best = (lowest / lowest.sum(axis=1, keepdims=True)).mean(axis=0)
    return order, mae - mae[best], bounds, p_best


def bootstrap_group(
    abs_err: np.ndarray,
    n: np.ndarray,
    rng: np.random.Generator,
    resamples: int = RESAMPLES,
    ranked: np.ndarray | None = None,
    block: int = BLOCK_DAYS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MAE ranking with intervals for one group.

    ``abs_err`` and ``n`` are days x models (sums over the group's stations per day),
    the days in date order (the blocks are consecutive rows). Returns per model: the
    order (0 = best), the MAE difference to the best and the lower/upper bounds of its
    interval as a 2 x models array. Columns where ``ranked`` is false (the blend) are
    compared with the best ranked model and ordered last.
    """
    order, diff, bounds, _ = bootstrap_best(abs_err, n, rng, resamples, ranked, block)
    return order, diff, bounds


def diebold_mariano(
    abs_err: np.ndarray, n: np.ndarray, reference: int, lags: int = DM_LAGS
) -> tuple[np.ndarray, np.ndarray]:
    """Diebold-Mariano statistic and two-sided p-value of every model against the
    column ``reference`` (``abs_err``, ``n``: days x models, in date order).

    The loss differential of day t is ``T · (a_t / N - a_ref,t / N_ref)`` (``N``: the
    model's total ``n``), whose mean is the pooled MAE difference; its long-run variance
    is Newey-West's with Bartlett weights over ``lags`` lags. The statistic gets the
    Harvey-Leybourne-Newbold factor sqrt((T - 1) / T) and a normal p-value. Infinite
    (p 0) for the same difference every day; NaN for the reference itself, with fewer
    than 3 days, or with no difference at all.
    """
    days = abs_err.shape[0]
    stat = np.full(abs_err.shape[1], np.nan)
    if days < 3:
        return stat, stat.copy()
    total = n.sum(axis=0)
    loss = days * abs_err / total
    d = loss - loss[:, [reference]]
    mean = d.mean(axis=0)
    centred = d - mean
    variance = (centred**2).mean(axis=0)
    for lag in range(1, min(lags, days - 1) + 1):
        weight = 1 - lag / (lags + 1)
        variance += 2 * weight * (centred[lag:] * centred[:-lag]).mean(axis=0) * (days - lag) / days
    ok = variance > 1e-12
    ok[reference] = False
    stat[ok] = mean[ok] / np.sqrt(variance[ok] / days) * math.sqrt((days - 1) / days)
    # the same difference every day: as significant as it gets
    constant = ~ok & (np.abs(mean) > 1e-12)
    constant[reference] = False
    stat[constant] = np.sign(mean[constant]) * np.inf
    p = np.array([np.nan if np.isnan(s) else math.erfc(abs(s) / math.sqrt(2)) for s in stat])
    return stat, p


def ties(
    abs_err: np.ndarray, n: np.ndarray, order: np.ndarray, bounds: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``tied`` (not shown to be worse than the best: the interval of model - best
    contains 0, or the Diebold-Mariano test against the best is not significant; never
    the best itself), with the Diebold-Mariano statistic and p-value per model."""
    stat, p_value = diebold_mariano(abs_err, n, int(order[0]))
    excludes = (bounds[0] > 0) | (bounds[1] < 0)
    worse = excludes & (np.nan_to_num(p_value, nan=1.0) < DM_ALPHA)
    return ~worse & (order.argsort() > 0), stat, p_value


def _finite(value: float) -> float | None:
    return None if np.isnan(value) else float(np.clip(value, -1e9, 1e9))


def rank(
    scores: pl.LazyFrame | pl.DataFrame,
    stations: pl.DataFrame,
    as_of: date | None = None,
    windows: tuple[str, ...] = aggregate.WINDOWS,
    resamples: int = RESAMPLES,
    seed: int = 0,
    levels: tuple[str, ...] = aggregate.LEVELS,
) -> pl.DataFrame:
    """One row per group and model with its rank and interval."""
    scores = scores.lazy().filter(pl.col("variable").is_in(RANKED_VARIABLES))
    first_day, last_day = aggregate.date_span(scores)
    as_of = as_of or last_day
    info = aggregate.station_info(stations)
    distance = aggregate.okres_distances(stations)
    rows = []
    for window in windows:
        _, days = aggregate.window_days(window, as_of, first_day)
        in_window = scores.filter(days).join(info, on="station_id", how="inner")
        in_window = aggregate.covered_only(in_window)
        for level in levels:
            regions = aggregate.with_regions(in_window, level, distance)
            daily = (
                aggregate.common_days(regions, by="region")
                .group_by("region", "variable", "lead_day", "date", "model")
                .agg(metrics.total("sum_abs_err"), metrics.total("n"))
                .collect()
            )
            for (region, variable, lead_day), part in daily.partition_by(
                ["region", "variable", "lead_day"], as_dict=True
            ).items():
                abs_err = part.pivot(on="model", index="date", values="sum_abs_err").sort("date")
                n = part.pivot(on="model", index="date", values="n").sort("date")
                models = [c for c in abs_err.columns if c != "date"]
                ranked = np.array([m != blend.ID for m in models])
                if not ranked.any():
                    continue
                a = abs_err.select(models).to_numpy().astype(float)
                m = n.select(models).to_numpy().astype(float)
                if len(models) == 1:
                    order, diff, bounds = np.array([0]), np.array([0.0]), np.zeros((2, 1))
                    p_best = np.ones(1)
                else:
                    # a group's resamples depend only on the seed and the group itself
                    key = f"{level}|{region}|{window}|{variable}|{lead_day}".encode()
                    rng = np.random.default_rng([seed, zlib.crc32(key)])
                    order, diff, bounds, p_best = bootstrap_best(a, m, rng, resamples, ranked)
                # worse than the best only when the interval of (model - best) excludes 0
                # and the Diebold-Mariano test agrees
                tied, stat, p_value = ties(a, m, order, bounds)
                clear = ranked.sum() > 1 and not (tied & ranked).any()
                small = a.shape[0] < SMALL_SAMPLE_DAYS
                for position, index in enumerate(order):
                    rows.append(
                        (
                            level, region, window, variable, lead_day, models[index],
                            position + 1 if ranked[index] else None, float(diff[index]),
                            float(bounds[0][index]), float(bounds[1][index]),
                            bool(tied[index]), bool(position == 0 and clear),
                            float(p_best[index]) if ranked[index] else None,
                            _finite(stat[index]), _finite(p_value[index]), small,
                        )
                    )  # fmt: skip
    table = pl.DataFrame(rows, schema=RANK_SCHEMA, orient="row")
    return table.sort([*GROUP, "rank"], nulls_last=True)
