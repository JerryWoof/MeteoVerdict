"""Does our combined forecast beat the single models? Out of sample (roadmap 6.4).

The forecast of ``meteoverdict.combine`` weights the models of an okres by their scores
of the last 90 days. Here it is rebuilt for past days from the stored D+N forecasts at
the stations (``fc-YYYY-MM.parquet``) with only what was known before, and scored like
the models:

1. **Training, strictly before the day.** For the forecast of day ``d`` at lead day
   ``N``, the okres scores of the ``window`` (90 days) ending on ``d - N``: the D+N
   forecast for ``d`` is made about N days before ``d``, and a day's scores are
   published the next morning. From those scores ``combine.weights`` (same
   inverse-error weights, bias corrections and shrinkage towards the plain mean as the
   live forecast), the **best single model** of the okres (lowest MAE, i.e. rank 1
   of the ranking a user would have looked at) and the best single model for the
   whole of Czechia. ``aggregate.aggregate`` builds those scores exactly as the daily
   run does (fair station-days, borrowed stations), from the models with scores on at
   least ``MIN_MODEL_COVERAGE`` of the window's scored days: a model the backfill has
   delivered only its newest 14-day window of would otherwise cut every model's fair
   station-days, and with them the training, down to that window.
   For temperature and wind also the regression blend of ``meteoverdict.mos``, fitted
   on the station pairs (00/06/12/18 UTC) of the same window and okres pools, with its
   corrections taken at each test station's own elevation.
2. **Warm-up.** An okres, variable and lead day is tested on ``d`` only when its
   training had at least ``MIN_TRAINING_DAYS`` scored days; earlier days are left out.
3. **The combined forecast** applies those weights (``combine.combine_values``) to the
   models' forecasts of day ``d`` at each station of the okres (its own stations and
   the borrowed ones, ``aggregate.with_regions``), hour by hour, and is scored by
   ``scoring.daily_scores`` like the mean of all models (a 6-hourly model:
   temperature and wind at 00, 06, 12 and 18 UTC, precipitation as daily totals).
   Variables: ``temperature_2m``, ``wind_speed_10m``, ``precipitation_daily`` (the
   weights of hourly precipitation come from daily totals, as in the live forecast).
4. **Compared**, per okres, variable and lead day, on the station-days every model of
   that day, the mean of all models and the combination have (``aggregate.common_days``
   day by day, so a model with scores on part of the test period only, or the fresh
   days rebuilt from the single runs of fewer models, does not drop the other days),
   with:

   - ``best_cz_oos``: on each day the model that was best in the whole of Czechia in
     the training window, used at every station (one model everywhere, what most
     people do; the headline comparison);
   - ``best_oos``: on each day the model that was best in the okres in the training
     window (chosen out of sample; a harder competitor than any one model);
   - ``best_hindsight``: the one model with the lowest MAE over the whole test period
     (an upper bound: nobody could have known it in advance);
   - ``blend``: the plain mean of all models (``meteoverdict.blend``);
   - every single model (Czechia only), each on the days it has.

   Czechia sums the okresy (a station borrowed by two okresy counts for both, with
   each okres's own weights); a series counts on a day only if it is compared in every
   okres tested that day. Intervals: ``ranking.bootstrap_group`` (whole days
   resampled) of the MAE difference to ``best_oos`` and to ``best_cz_oos``, and of
   ours minus each single model; negative = ours (or the series) better.

Output (``write``): ``site/data/blend-test.json``, see ``document``.
"""

from __future__ import annotations

import copy
import json
import zlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from meteoverdict import aggregate, blend, combine, forecasts, metrics, mos, ranking, scoring

#: Open-Meteo variable → score variable it is tested on (as ``combine.VARIABLES``)
SCORE_VARIABLES = {name: score for name, (score, _) in combine.VARIABLES.items()}
UNITS = {"temperature_2m": "°C", "wind_speed_10m": "m/s", "precipitation_daily": "mm"}
#: an okres, variable and lead day needs this many scored training days to be tested
MIN_TRAINING_DAYS = 14
#: results of an okres are published with at least this many test days
MIN_OKRES_DAYS = 10
#: a model is trained on only when it has scores on this share of the window's scored
#: days (``aggregate.MIN_COVERAGE``, as the live ranking): a model the backfill has
#: delivered only a few days of would otherwise shrink the fair station-days of every
#: model to those few days
MIN_MODEL_COVERAGE = aggregate.MIN_COVERAGE
COMBINED = "combined"
BEST_OOS = "best_oos"
BEST_CZ_OOS = "best_cz_oos"
BEST_HINDSIGHT = "best_hindsight"
#: model id prefix of the combination of one okres while it is scored
PREFIX = "combined@"
#: compared with ``best_oos`` in the published rows
COMPARED = (COMBINED, BEST_HINDSIGHT, blend.ID)
#: compared with ``best_cz_oos`` (one model everywhere) in the published rows
COMPARED_CZ = (COMBINED, BEST_OOS, BEST_HINDSIGHT, blend.ID)
#: the series that are not single models
SERIES = (COMBINED, BEST_OOS, BEST_CZ_OOS, BEST_HINDSIGHT, blend.ID)

GROUP_COLUMNS = [
    "level", "region", "region_name", "variable", "lead_day", "days", "stations",
    "best_oos", "best_oos_models", "best_hindsight",
    "mae_combined", "mae_best_oos", "mae_best_hindsight", "mae_blend",
    "diff_combined", "low_combined", "high_combined",
    "diff_best_hindsight", "low_best_hindsight", "high_best_hindsight",
    "diff_blend", "low_blend", "high_blend",
    # added later: one model for the whole of Czechia (``best_cz_oos``) as the reference
    "best_cz_oos", "best_cz_oos_models", "mae_best_cz_oos",
    *(f"{k}_{c}_vs_cz" for c in COMPARED_CZ for k in ("diff", "low", "high")),
]  # fmt: skip
#: ``diff`` = the model's MAE minus ``best_oos``'s; ``diff_combined`` = ours minus the
#: model's (negative = ours better), both on the ``days`` both series have
MODEL_COLUMNS = [
    "variable", "lead_day", "model", "mae", "diff", "low", "high",
    "days", "mae_combined", "diff_combined", "low_combined", "high_combined",
]  # fmt: skip


def best_models(
    table: pl.DataFrame, window: str = combine.WINDOW, level: str = "okres"
) -> pl.DataFrame:
    """The best single model (lowest MAE) per okres (``level="cz"``: for Czechia),
    score variable and lead day of an aggregated table, among regions with enough
    stations: ``region``, ``variable``, ``lead_day``, ``model``, ``days``."""
    return (
        table.filter(
            pl.col("level") == level,
            pl.col("window") == window,
            pl.col("variable").is_in(list(SCORE_VARIABLES.values())),
            pl.col("model") != blend.ID,
            pl.col("enough_stations"),
            pl.col("mae").is_not_null(),
            ~pl.col("short_record").fill_null(False),
        )
        .sort("region", "variable", "lead_day", "mae", "model")
        .group_by("region", "variable", "lead_day", maintain_order=True)
        .first()
        .select("region", "variable", "lead_day", "model", "days")
    )


def _target_date() -> pl.Expr:
    """The day a training ``as_of`` is used for at its lead day: ``as_of + lead_day``."""
    return (pl.col("as_of") + pl.duration(days=pl.col("lead_day").cast(pl.Int64))).cast(pl.Date)


def training(
    scores: pl.DataFrame,
    stations: pl.DataFrame,
    as_of_days: list[date],
    window: str = combine.WINDOW,
    min_days: int = MIN_TRAINING_DAYS,
    pairs: pl.DataFrame | None = None,
    okres_pools: pl.DataFrame | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Weights and best models for every ``as_of`` day, from the scores up to it.

    Returns ``(weights, best)`` with ``date`` = the day they are used for
    (``as_of + lead_day``): the rows of ``combine.weights`` (Open-Meteo variable names)
    and of ``best_models`` (score variable names; the okresy and, with ``region`` =
    ``cz``, the best model for the whole of Czechia), only for groups whose training had
    at least ``min_days`` scored days. Only the models with scores on at least
    ``MIN_MODEL_COVERAGE`` of the window's scored days are trained on
    (``covered_models``). With ``pairs`` (``mos.pairs``) and
    ``okres_pools``, also the regression coefficients of temperature and wind fitted
    on the window ending on ``as_of`` (``combine.with_mos``), as the live forecast.
    """
    w, b = _score_training(scores, stations, as_of_days, window, min_days)
    if pairs is None or okres_pools is None or w.is_empty():
        return combine.with_mos(w, None) if not w.is_empty() else w, b
    length = int(window.removesuffix("d"))
    allowed = w.select("variable", "lead_day", "model").unique()
    coefficients = mos.coefficients(
        pairs, okres_pools, stations, as_of_days, length, allowed=allowed, min_days=min_days
    )
    return combine.with_mos(w, coefficients, keys=("as_of", "region")), b


def _score_training(
    scores: pl.DataFrame,
    stations: pl.DataFrame,
    as_of_days: list[date],
    window: str,
    min_days: int,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    length = int(window.removesuffix("d")) if window.endswith("d") else None
    weights, best, best_cz = [], [], []
    for as_of in as_of_days:
        part = scores.lazy().filter(pl.col("date") <= as_of)
        if length:  # only the window is needed
            part = part.filter(pl.col("date") > as_of - timedelta(days=length))
        if part.select(pl.len()).collect().item() == 0:
            continue
        part = part.join(covered_models(part).lazy(), on=["variable", "lead_day", "model"])
        # the weights and the best models need the MAE only, not the bias-corrected one
        table = aggregate.aggregate(
            part, stations, as_of, windows=(window,), levels=("okres", "cz"), corrected=False
        )
        stamp = pl.lit(as_of).alias("as_of")
        weights.append(combine.weights(table, window).with_columns(stamp))
        best.append(best_models(table, window).with_columns(stamp))
        best_cz.append(best_models(table, window, level="cz").with_columns(stamp))
    if not weights:
        return pl.DataFrame(), pl.DataFrame()
    w = pl.concat(weights).with_columns(_target_date().alias("date"))
    enough = (
        w.group_by("as_of", "region", "variable", "lead_day")
        .agg(pl.col("days").max())
        .filter(pl.col("days") >= min_days)
        .drop("days")
    )
    w = w.join(enough, on=["as_of", "region", "variable", "lead_day"], how="semi")
    b = pl.concat(best).join(
        enough.with_columns(pl.col("variable").replace_strict(SCORE_VARIABLES)),
        on=["as_of", "region", "variable", "lead_day"],
        how="semi",
    )
    cz = pl.concat(best_cz).filter(pl.col("days") >= min_days)
    b = pl.concat([b, cz.select(b.columns)]).with_columns(_target_date().alias("date"))
    return w, b


def covered_models(scores: pl.LazyFrame | pl.DataFrame) -> pl.DataFrame:
    """``variable``, ``lead_day`` and ``model`` of the models with scores on at least
    ``MIN_MODEL_COVERAGE`` of the days that variable and lead day has scores on
    (``aggregate.coverage``, the rule of the live ranking and weights).

    The fair comparison (``aggregate.common_days``) keeps only the station-days every
    model of the period has; a model the backfill has delivered for its newest window
    only (it fetches newest first, so a newly added model starts with a 14-day block)
    would cut every model's training down to that block, and with it the warm-up."""
    cover = aggregate.coverage(scores)
    return cover.filter("covered").select(aggregate.COVERAGE_KEYS)


def pools(scores: pl.LazyFrame | pl.DataFrame, stations: pl.DataFrame) -> pl.DataFrame:
    """The stations each okres is tested on, per score variable (``variable``,
    ``region``, ``region_name``, ``station_id``): its own and, where it has fewer than
    ``aggregate.MIN_STATIONS``, borrowed ones, as in the ranking."""
    return mos.pools(scores, stations)


def combined_forecasts(
    fc: pl.LazyFrame | pl.DataFrame,
    okres_pools: pl.DataFrame,
    weights: pl.DataFrame,
    stations: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """The combined forecast of every okres at its stations, in the forecast table's
    layout (``forecasts.SCHEMA``) with ``model`` = ``combined@<okres>``.

    Each hour takes the weights of the day it is scored on: the UTC day of the hour for
    temperature and wind, the day the hour ends in for precipitation (as ``scoring``).
    With the regression coefficients in ``weights`` (``combine.with_mos``) the slot
    corrections are taken at each station's elevation (from ``stations``).
    """
    keys = ["region", "station_id", "time", "lead_day"]
    raw = fc.lazy().filter(pl.col("model") != blend.ID)
    regression = "mos_weight" in weights.columns
    elevation = (
        stations.select(pl.col("id").alias("station_id"), pl.col("elevation").alias("_elevation"))
        if stations is not None and regression and "elevation" in stations.columns
        else None
    )
    parts = []
    for name, score in SCORE_VARIABLES.items():
        start = pl.col("time") - timedelta(hours=1) if name == "precipitation" else pl.col("time")
        extra = list(mos.COEFFICIENT_COLUMNS) if regression else []
        w = weights.filter(pl.col("variable") == name).select(
            "date", "region", "lead_day", "model", "weight", "correction", *extra
        )
        members = okres_pools.filter(pl.col("variable") == score).select("region", "station_id")
        rows = (
            raw.select("station_id", "time", "lead_day", "model", name)
            .with_columns(start.dt.date().alias("date"))
            .join(members.lazy(), on="station_id")
            .join(w.lazy(), on=["date", "region", "lead_day", "model"])
        )
        if regression:
            at = pl.col("_elevation") if elevation is not None else pl.lit(None, pl.Float64)
            if elevation is not None:
                rows = rows.join(elevation.lazy(), on="station_id", how="left")
            rows = rows.with_columns(combine.slot_corrections(at))
        parts.append(combine.combine_values(rows, name, keys))
    out = parts[0]
    for part in parts[1:]:
        out = out.join(part, on=keys, how="full", coalesce=True)
    return (
        out.with_columns((pl.lit(PREFIX) + pl.col("region")).alias("model"))
        .select(list(forecasts.SCHEMA))
        .cast(forecasts.SCHEMA)
        .sort(forecasts.KEYS)
        .collect()
    )


def score_combined(
    observations: pl.LazyFrame | pl.DataFrame, combined: pl.DataFrame, start: date, end: date
) -> pl.DataFrame:
    """Daily scores of the combinations, scored like the blend (a 6-hourly model), with
    ``region`` = the okres and ``model`` = ``combined``."""
    regions = sorted(combined["model"].unique().to_list())
    models = [replace(blend.MODEL, id=r, name="Combined forecast") for r in regions]
    table = scoring.daily_scores(observations, combined, models, start, end, with_blend=False)
    return table.filter(pl.col("variable").is_in(list(SCORE_VARIABLES.values()))).with_columns(
        pl.col("model").str.strip_prefix(PREFIX).alias("region"), pl.lit(COMBINED).alias("model")
    )


def score_candidates(
    observations: pl.LazyFrame | pl.DataFrame, candidates: pl.DataFrame, start: date, end: date
) -> pl.DataFrame:
    """Daily scores of experimental forecasts, scored like the blend (a 6-hourly model)."""
    ids = sorted(candidates["model"].unique().to_list())
    models = [replace(blend.MODEL, id=i, name=i) for i in ids]
    table = scoring.daily_scores(observations, candidates, models, start, end, with_blend=False)
    return table.filter(pl.col("variable").is_in(list(SCORE_VARIABLES.values())))


def daily_errors(
    scores: pl.DataFrame, combined_scores: pl.DataFrame, okres_pools: pl.DataFrame
) -> pl.DataFrame:
    """Day totals (``sum_abs_err``, ``n``, ``stations``) per okres, score variable, lead
    day, date and model (the models, ``blend`` and ``combined``) on the fair
    station-days of each okres, with the combination counting as one more model.

    Fair day by day: on each day the models compared are those with a score in the
    okres that day, so a model that has scores on part of the test period only (a newly
    added model the backfill has delivered one window of; the fresh days, rebuilt from
    the single runs of fewer models) does not drop the other days."""
    members = okres_pools.select("variable", "region", "station_id")
    columns = ["date", "station_id", "model", "lead_day", "variable", "region", "sum_abs_err", "n"]
    rows = pl.concat(
        [
            scores.lazy().join(members.lazy(), on=["variable", "station_id"]).select(columns),
            combined_scores.lazy()
            .join(members.lazy(), on=["variable", "region", "station_id"], how="semi")
            .select(columns),
        ]
    )
    day = pl.concat_str(pl.col("region"), pl.col("date").cast(pl.String), separator="|")
    return (
        aggregate.common_days(rows.with_columns(day.alias("_region_day")), by="_region_day")
        .group_by("region", "variable", "lead_day", "date", "model")
        .agg(
            metrics.total("sum_abs_err"),
            metrics.total("n"),
            pl.col("station_id").n_unique().alias("stations"),
        )
        .collect()
    )


def series(
    daily: pl.DataFrame, best: pl.DataFrame, exclude: set[str] = frozenset()
) -> pl.DataFrame:
    """Day totals per okres, variable, lead day, date and series on the days that have
    the combination and both out-of-sample choices: the models, ``blend``,
    ``combined``, ``best_oos`` (the day's out-of-sample choice in the okres),
    ``best_cz_oos`` (the day's out-of-sample choice for the whole of Czechia, ``best``
    rows with ``region`` = ``cz``, the same model in every okres) and ``best_hindsight``
    (the okres's model with the lowest MAE over those days), with the model behind the
    last three in ``chosen``."""
    keys = ["region", "variable", "lead_day", "date"]
    chosen = best.select(*keys, pl.col("model").alias("chosen"))
    oos = daily.join(
        chosen.filter(pl.col("region") != "cz"), left_on=[*keys, "model"],
        right_on=[*keys, "chosen"],
    ).with_columns(pl.col("model").alias("chosen"), pl.lit(BEST_OOS).alias("model"))  # fmt: skip
    oos_cz = daily.join(
        chosen.filter(pl.col("region") == "cz").drop("region"),
        left_on=["variable", "lead_day", "date", "model"],
        right_on=["variable", "lead_day", "date", "chosen"],
    ).with_columns(pl.col("model").alias("chosen"), pl.lit(BEST_CZ_OOS).alias("model"))
    tested = (
        pl.concat(
            [
                daily.filter(pl.col("model") == COMBINED).select(keys),
                oos.select(keys),
                oos_cz.select(keys),
            ]
        )
        .group_by(keys)
        .len()
        .filter(pl.col("len") == 3)
        .drop("len")
    )
    out = pl.concat([daily.with_columns(pl.lit(None, pl.String).alias("chosen")), oos, oos_cz])
    out = out.join(tested, on=keys, how="semi").filter(pl.col("n") > 0)
    group = ["region", "variable", "lead_day"]
    # experimental candidates are compared, never picked as the best in hindsight
    single = out.filter(~pl.col("model").is_in([*SERIES, *exclude]))
    hindsight = (
        single.group_by(*group, "model")
        .agg((pl.col("sum_abs_err").sum() / pl.col("n").sum()).alias("mae"), pl.len().alias("d"))
        # a model must cover all the group's days (the fair set makes them do so)
        .filter(pl.col("d") == pl.col("d").max().over(group))
        .sort(*group, "mae", "model")
        .group_by(group, maintain_order=True)
        .first()
        .select(*group, pl.col("model").alias("chosen"))
    )
    best_rows = (
        single.drop("chosen")
        .join(hindsight, left_on=[*group, "model"], right_on=[*group, "chosen"])
        .with_columns(pl.col("model").alias("chosen"), pl.lit(BEST_HINDSIGHT).alias("model"))
    )
    return pl.concat([out, best_rows.select(out.columns)])


def czechia(days: pl.DataFrame) -> pl.DataFrame:
    """Sum the okresy per variable, lead day, date and series; a series counts on a day
    only if it is compared in every okres tested that day (so that all series of a day
    cover the same station-days)."""
    day = ["variable", "lead_day", "date"]
    regions = days.group_by(day).agg(pl.col("region").n_unique().alias("all"))
    everywhere = (
        days.group_by(*day, "model")
        .agg(pl.col("region").n_unique().alias("regions"))
        .join(regions, on=day)
        .filter(pl.col("regions") == pl.col("all"))
        .select(*day, "model")
    )
    return (
        days.join(everywhere, on=[*day, "model"], how="semi")
        .group_by(*day, "model")
        .agg(pl.col("sum_abs_err").sum(), pl.col("n").sum(), pl.col("stations").sum())
        .with_columns(pl.lit("cz").alias("region"), pl.lit(None, pl.String).alias("chosen"))
    )


def _differences(
    a: np.ndarray,
    m: np.ndarray,
    rng: np.random.Generator,
    resamples: int,
    columns: list[str],
    reference: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MAE difference of every column to ``reference`` with its 95 % interval
    (``ranking.bootstrap_group``, whole days resampled); no interval with one day. The
    generator is copied, so every reference sees the same resamples."""
    if a.shape[0] >= 2:
        ranked = np.array([c == reference for c in columns])
        _, diff, bounds = ranking.bootstrap_group(a, m, copy.deepcopy(rng), resamples, ranked)
        return diff, bounds[0], bounds[1]
    mae = a.sum(axis=0) / m.sum(axis=0)
    nan = np.full(len(columns), np.nan)
    return mae - mae[columns.index(reference)], nan, nan


def _matrices(days: pl.DataFrame) -> tuple[list[str], pl.DataFrame, pl.DataFrame]:
    abs_err = days.pivot(on="model", index="date", values="sum_abs_err").sort("date")
    n = days.pivot(on="model", index="date", values="n").sort("date")
    return [c for c in abs_err.columns if c != "date"], abs_err, n


def compare(
    days: pl.DataFrame, key: str, rng: np.random.Generator, resamples: int = ranking.RESAMPLES
) -> dict | None:
    """MAE of every series of one group and the bootstrap interval of its difference to
    ``best_oos`` and to ``best_cz_oos``.

    ``days`` has ``date``, ``model``, ``sum_abs_err`` and ``n`` of one region,
    variable and lead day. Returns ``{"days", "series": {name: (mae, diff, low,
    high)}, "vs_cz": {name: (diff, low, high)}}`` (``vs_cz`` empty without
    ``best_cz_oos``) or None without the combination or the choice. Only the series
    with every day are compared (single models with fewer days: ``model_rows``).
    """
    names, abs_err, n = _matrices(days)
    if COMBINED not in names or BEST_OOS not in names:
        return None
    # every compared series must cover every day (the fair set makes the models do so)
    full = [c for c in names if n[c].null_count() == 0 and abs_err[c].null_count() == 0]
    if COMBINED not in full or BEST_OOS not in full:
        return None
    a = abs_err.select(full).to_numpy().astype(float)
    m = n.select(full).to_numpy().astype(float)
    totals = a.sum(axis=0) / m.sum(axis=0)
    diff, low, high = _differences(a, m, rng, resamples, full, BEST_OOS)
    out = {
        c: (float(totals[i]), float(diff[i]), float(low[i]), float(high[i]))
        for i, c in enumerate(full)
    }
    vs_cz = {}
    if BEST_CZ_OOS in full:
        diff, low, high = _differences(a, m, rng, resamples, full, BEST_CZ_OOS)
        vs_cz = {c: (float(diff[i]), float(low[i]), float(high[i])) for i, c in enumerate(full)}
    return {"days": a.shape[0], "series": out, "vs_cz": vs_cz}


def model_rows(
    days: pl.DataFrame,
    variable: str,
    lead_day: int,
    key: str,
    seed: int = 0,
    resamples: int = ranking.RESAMPLES,
) -> list[list]:
    """``MODEL_COLUMNS`` rows of every single model of one group (Czechia): its MAE and
    the difference to ``best_oos`` (model minus it), and ours minus the model, each
    with its 95 % interval, on the days the model, ``combined`` and ``best_oos`` all
    have (a model with scores on part of the test period only is compared on those)."""
    names, abs_err, n = _matrices(days)
    if COMBINED not in names or BEST_OOS not in names:
        return []
    rows = []
    for model in sorted(c for c in names if c not in SERIES):
        columns = [model, COMBINED, BEST_OOS]
        have = pl.all_horizontal(pl.col(c).is_not_null() for c in columns)
        a = abs_err.select(columns).filter(have.alias("_have")).to_numpy().astype(float)
        m = n.select(columns).filter(have.alias("_have")).to_numpy().astype(float)
        if a.shape[0] == 0 or (m.sum(axis=0) == 0).any():
            continue
        rng = _seed(seed, f"{key}|{model}")
        mae = a.sum(axis=0) / m.sum(axis=0)
        diff, low, high = _differences(a, m, rng, resamples, columns, BEST_OOS)
        ours, ours_low, ours_high = _differences(a, m, rng, resamples, columns, model)
        rows.append(
            [
                variable, lead_day, model,
                *(_nan_to_none(v) for v in (mae[0], diff[0], low[0], high[0])),
                a.shape[0],
                *(_nan_to_none(v) for v in (mae[1], ours[1], ours_low[1], ours_high[1])),
            ]
        )  # fmt: skip
    return rows


def _most(chosen: pl.Series) -> str | None:
    """The most frequent value (ties: the first in alphabetical order)."""
    counts = chosen.drop_nulls().value_counts()
    if counts.is_empty():
        return None
    return counts.sort(["count", chosen.name], descending=[True, False])[chosen.name][0]


def _seed(seed: int, key: str) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(key.encode())])


def _nan_to_none(value: float | None) -> float | None:
    return None if value is None or np.isnan(value) else round(value, 3)


def results(
    days: pl.DataFrame,
    okres_names: dict[str, str],
    resamples: int = ranking.RESAMPLES,
    seed: int = 0,
    min_okres_days: int = MIN_OKRES_DAYS,
) -> tuple[list[list], list[list]]:
    """Rows of the published tables (``GROUP_COLUMNS``, ``MODEL_COLUMNS``): Czechia
    and every okres with at least ``min_okres_days`` test days; the single models for
    Czechia only."""
    groups, models = [], []
    frames = [("cz", czechia(days)), ("okres", days)]
    for level, frame in frames:
        for (region, variable, lead_day), part in sorted(
            frame.partition_by(["region", "variable", "lead_day"], as_dict=True).items()
        ):
            key = f"blendtest|{region}|{variable}|{lead_day}"
            result = compare(part, key, _seed(seed, key), resamples)
            if result is None or (level == "okres" and result["days"] < min_okres_days):
                continue
            s, vs_cz = result["series"], result["vs_cz"]
            here = days.filter(pl.col("variable") == variable, pl.col("lead_day") == lead_day)
            if level == "okres":
                here = here.filter(pl.col("region") == region)
            chosen = here.filter(pl.col("model") == BEST_OOS)["chosen"]
            chosen_cz = here.filter(pl.col("model") == BEST_CZ_OOS).unique("date")["chosen"]
            stations = part.group_by("date").agg(pl.col("stations").max())["stations"].max()
            row = [
                level, region, "Česko" if level == "cz" else okres_names.get(region, region),
                variable, lead_day, result["days"], stations,
                _most(chosen), chosen.n_unique(),
                _most(here.filter(pl.col("model") == BEST_HINDSIGHT)["chosen"]),
            ]  # fmt: skip
            row += [_nan_to_none(s.get(c, (None,))[0]) for c in (COMBINED, BEST_OOS)]
            row += [_nan_to_none(s.get(c, (None,))[0]) for c in (BEST_HINDSIGHT, blend.ID)]
            for c in COMPARED:
                row += [_nan_to_none(v) for v in s.get(c, (None, None, None, None))[1:]]
            row += [
                _most(chosen_cz),
                chosen_cz.n_unique() if chosen_cz.len() else None,
                _nan_to_none(s.get(BEST_CZ_OOS, (None,))[0]),
            ]
            for c in COMPARED_CZ:
                row += [_nan_to_none(v) for v in vs_cz.get(c, (None, None, None))]
            groups.append(row)
            if level == "cz":
                models += model_rows(part, variable, lead_day, key, seed, resamples)
    return groups, models


def run(
    scores: pl.DataFrame,
    fc: pl.LazyFrame | pl.DataFrame,
    observations: pl.LazyFrame | pl.DataFrame,
    stations: pl.DataFrame,
    first: date,
    last: date,
    window: str = combine.WINDOW,
    min_training_days: int = MIN_TRAINING_DAYS,
    resamples: int = ranking.RESAMPLES,
    seed: int = 0,
    log=lambda _: None,
    regression: bool = True,
    candidates: pl.DataFrame | None = None,
) -> tuple[pl.DataFrame, list[list], list[list], dict]:
    """The whole test for the days ``first`` … ``last``: ``(days, groups, models,
    info)`` with the day totals (``series``), the rows of ``results`` and counts.
    ``regression``: temperature and wind with the regression blend (``mos``), as the
    live forecast; False: the inverse-error weights alone (the method before).
    ``candidates``: experimental forecasts (``forecasts.SCHEMA``, one ``model`` id each,
    e.g. MeteoVerdict AI from ``ai/``), scored like the combination and compared as single
    models; they never enter the training, ``best_oos`` or ``best_hindsight``."""
    scores = scores.filter(pl.col("variable").is_in(list(SCORE_VARIABLES.values())))
    lead_days = sorted(scores["lead_day"].unique().to_list())
    max_lead = max(lead_days) if lead_days else 1
    as_of_days = [first - timedelta(days=k) for k in range(max_lead, 0, -1)]
    as_of_days += [first + timedelta(days=k) for k in range((last - first).days)]
    tested = scores.filter(pl.col("date").is_between(first, last))
    info = {"scored_dates": sorted(scores["date"].unique().to_list())}
    if tested.is_empty():
        return pl.DataFrame(), [], [], info
    okres_pools = pools(tested, stations)
    pairs = None
    if regression:
        length = int(window.removesuffix("d")) if window.endswith("d") else mos.WINDOW_DAYS
        start = as_of_days[0] - timedelta(days=length - 1)
        pairs = mos.pairs(observations, fc, start, last)
        log(f"regression: {pairs.height} temperature and wind pairs from {start}")
    weights, best = training(
        scores, stations, as_of_days, window, min_training_days, pairs, okres_pools
    )
    log(f"training: {len(as_of_days)} days, {weights.height} weight rows")
    if weights.is_empty():
        return pl.DataFrame(), [], [], info
    # day by day, which keeps the memory small: the hours scored on day d (00:00 …
    # 24:00, precipitation up to the hour ending at 24:00)
    members = okres_pools["station_id"].unique().to_list()
    fc = fc.lazy().filter(pl.col("station_id").is_in(members))
    parts = []
    for day in sorted(weights.filter(pl.col("date").is_between(first, last))["date"].unique()):
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        hours = pl.col("time").is_between(start, start + timedelta(days=1))
        today = weights.filter(pl.col("date") == day)
        parts.append(combined_forecasts(fc.filter(hours), okres_pools, today, stations))
    combined = pl.concat(parts) if parts else pl.DataFrame(schema=forecasts.SCHEMA)
    log(f"combined forecasts: {combined.height} rows")
    if combined.is_empty():
        return pl.DataFrame(), [], [], info
    combined_scores = score_combined(observations, combined, first, last)
    if candidates is not None and not candidates.is_empty():
        tested = pl.concat(
            [tested, score_candidates(observations, candidates, first, last)],
            how="diagonal_relaxed",
        )
        log(f"candidates: {', '.join(sorted(candidates['model'].unique()))}")
    daily = daily_errors(tested, combined_scores, okres_pools)
    exclude = set(candidates["model"].unique()) if candidates is not None else set()
    days = series(daily, best, exclude)
    names = dict(okres_pools.select("region", "region_name").unique().iter_rows())
    groups, models = results(days, names, resamples, seed)
    return days, groups, models, info


METHOD = (
    "For every day d and lead day N, the combination's weights and bias corrections and "
    "the best single model of each okres come only from the okres scores of the {window} "
    "window ending on d - N (what the daily run had published when the D+N forecast was "
    "made), with the same shrinkage towards the plain mean as the live forecast; for "
    "temperature and wind, as live, the regression blend (hour-of-day and elevation "
    "corrections, ridge-regression weights) fitted on the station pairs of that window, "
    "with the corrections taken at each station's elevation. The "
    "combination is applied to the models' stored D+N forecasts at the okres's stations "
    "(borrowed ones included) and scored like the mean of all models: temperature and "
    "wind at 00, 06, 12 and 18 UTC, precipitation as UTC-day totals, on the station-days "
    "every model has. An okres, variable and lead day is tested only after {min_days} "
    "scored training days (warm-up). best_oos: the model that was best in the okres in "
    "the training window, chosen anew every day (what a user following the ranking would "
    "have used); best_hindsight: the single model with the lowest MAE over the test "
    "period (an upper bound nobody could have picked in advance); blend: the plain mean "
    "of all models; best_cz_oos: the model that was best in the whole of Czechia in the "
    "training window, used everywhere (one model for the whole country). Only models "
    "with scores on at least {coverage:.0%} of a training window's scored days are "
    "trained on; on each test day the models compared are those with scores that day. "
    "Czechia sums all okresy. diff = MAE minus the MAE of best_oos, *_vs_cz = MAE minus "
    "the MAE of best_cz_oos, single models: diff_combined = our MAE minus the model's "
    "(negative = better), each with a 95 % interval from {resamples} bootstrap resamples "
    "of whole days."
)


def document(
    days: pl.DataFrame,
    groups: list[list],
    models: list[list],
    info: dict,
    names: dict[str, str],
    generated: datetime,
    window: str = combine.WINDOW,
    min_training_days: int = MIN_TRAINING_DAYS,
    resamples: int = ranking.RESAMPLES,
) -> dict:
    """The published JSON: method, period, warm-up and the two tables.

    ``groups`` (``GROUP_COLUMNS``): one row per level (``cz``, ``okres``), region,
    variable and lead day with the MAE of the combination, the out-of-sample best
    model, the best model in hindsight and the mean of all models, and the difference
    of each to the out-of-sample best with its 95 % interval (``low``, ``high``).
    ``models`` (``MODEL_COLUMNS``): every single model in Czechia, its difference to
    the out-of-sample best and ours minus it, with intervals. The ``*_vs_cz`` columns
    compare with ``best_cz_oos``, the best model for the whole of Czechia.
    """
    tested = sorted(days["date"].unique().to_list()) if days.height else []
    first_test = tested[0] if tested else None
    scored = info.get("scored_dates", [])
    warm_up = sum(1 for d in scored if first_test is None or d < first_test)
    return {
        "generated": generated.isoformat(timespec="seconds"),
        "method": METHOD.format(
            window=window,
            min_days=min_training_days,
            resamples=resamples,
            coverage=MIN_MODEL_COVERAGE,
        ),
        "min_model_coverage": MIN_MODEL_COVERAGE,
        "training_window": window,
        "shrink_days": combine.SHRINK_DAYS,
        "bias_shrink_days": combine.BIAS_SHRINK_DAYS,
        "regression": {
            "variables": list(mos.VARIABLES),
            "slot_shrink_days": mos.SLOT_SHRINK_DAYS,
            "national_ridge": mos.NATIONAL_RIDGE,
            "okres_ridge": mos.OKRES_RIDGE,
            "min_coverage": mos.MIN_COVERAGE,
            "min_days": mos.MIN_DAYS,
        },
        "min_training_days": min_training_days,
        "min_okres_days": MIN_OKRES_DAYS,
        "first_scored": str(scored[0]) if scored else None,
        "from": str(first_test) if first_test else None,
        "to": str(tested[-1]) if tested else None,
        "test_days": len(tested),
        "warm_up_days": warm_up,
        "units": UNITS,
        "models": names,
        "groups": {"columns": GROUP_COLUMNS, "rows": groups},
        "single_models": {"columns": MODEL_COLUMNS, "rows": models},
    }


def write(doc: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path


def summary(groups: list[list]) -> list[str]:
    """Czechia, one line per variable and lead day, for the command's output."""
    at = {c: i for i, c in enumerate(GROUP_COLUMNS)}
    lines = []
    for row in groups:
        if row[at["level"]] != "cz":
            continue
        low, high = row[at["low_combined"]], row[at["high_combined"]]
        verdict = _verdict(low, high)
        cz_low, cz_high = row[at["low_combined_vs_cz"]], row[at["high_combined_vs_cz"]]
        cz_diff = row[at["diff_combined_vs_cz"]]
        lines.append(
            f"{row[at['variable']]:<20} D+{row[at['lead_day']]}  {row[at['days']]:>3} days  "
            f"vs one model everywhere ({row[at['best_cz_oos']]}) "
            f"{row[at['mae_best_cz_oos']] or float('nan'):.3f}: "
            f"{cz_diff if cz_diff is not None else float('nan'):+.3f} "
            f"[{cz_low if cz_low is not None else float('nan'):+.3f}, "
            f"{cz_high if cz_high is not None else float('nan'):+.3f}] "
            f"{_verdict(cz_low, cz_high)}  |  "
            f"combined {row[at['mae_combined']]:.3f}  best per okres "
            f"{row[at['mae_best_oos']]:.3f}  hindsight {row[at['mae_best_hindsight']] or 0:.3f}  "
            f"mean {row[at['mae_blend']] or 0:.3f}  diff {row[at['diff_combined']]:+.3f} "
            f"[{low if low is not None else float('nan'):+.3f}, "
            f"{high if high is not None else float('nan'):+.3f}]  {verdict}"
        )
    return lines


def _verdict(low: float | None, high: float | None) -> str:
    if high is not None and high < 0:
        return "better"
    if low is not None and low > 0:
        return "worse"
    return "no significant difference"
