"""Does our combined forecast beat the best single model? Out of sample (roadmap 6.4).

The forecast of ``meteoverdict.combine`` weights the models of an okres by their scores
of the last 90 days. Here it is rebuilt for past days from the stored D+N forecasts at
the stations (``fc-YYYY-MM.parquet``) with only what was known before, and scored like
the models:

1. **Training, strictly before the day.** For the forecast of day ``d`` at lead day
   ``N``, the okres scores of the ``window`` (90 days) ending on ``d - N``: the D+N
   forecast for ``d`` is made about N days before ``d``, and a day's scores are
   published the next morning. From those scores ``combine.weights`` (same
   inverse-error weights, bias corrections and shrinkage towards the plain mean as the
   live forecast) and the **best single model** of the okres (lowest MAE, i.e. rank 1
   of the ranking a user would have looked at). ``aggregate.aggregate`` builds those
   okres scores exactly as the daily run does (fair station-days, borrowed stations).
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
4. **Compared**, per okres, variable and lead day, on the station-days every model, the
   mean of all models and the combination have (``aggregate.common_days``), with:

   - ``best_oos``: on each day the model that was best in the okres in the training
     window (chosen out of sample, the honest competitor);
   - ``best_hindsight``: the one model with the lowest MAE over the whole test period
     (an upper bound: nobody could have known it in advance);
   - ``blend``: the plain mean of all models (``meteoverdict.blend``);
   - every single model (Czechia only).

   Czechia sums the okresy (a station borrowed by two okresy counts for both, with
   each okres's own weights). Intervals: ``ranking.bootstrap_group`` (whole days
   resampled) of the MAE difference to ``best_oos``; negative = better than the model
   a user of our ranking would have picked.

Output (``write``): ``site/data/blend-test.json``, see ``document``.
"""

from __future__ import annotations

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
COMBINED = "combined"
BEST_OOS = "best_oos"
BEST_HINDSIGHT = "best_hindsight"
#: model id prefix of the combination of one okres while it is scored
PREFIX = "combined@"
#: compared with ``best_oos`` in the published rows
COMPARED = (COMBINED, BEST_HINDSIGHT, blend.ID)

GROUP_COLUMNS = [
    "level", "region", "region_name", "variable", "lead_day", "days", "stations",
    "best_oos", "best_oos_models", "best_hindsight",
    "mae_combined", "mae_best_oos", "mae_best_hindsight", "mae_blend",
    "diff_combined", "low_combined", "high_combined",
    "diff_best_hindsight", "low_best_hindsight", "high_best_hindsight",
    "diff_blend", "low_blend", "high_blend",
]  # fmt: skip
MODEL_COLUMNS = ["variable", "lead_day", "model", "mae", "diff", "low", "high"]


def best_models(table: pl.DataFrame, window: str = combine.WINDOW) -> pl.DataFrame:
    """The best single model (lowest MAE) per okres, score variable and lead day of an
    aggregated table, among regions with enough stations: ``region``, ``variable``,
    ``lead_day``, ``model``, ``days``."""
    return (
        table.filter(
            pl.col("level") == "okres",
            pl.col("window") == window,
            pl.col("variable").is_in(list(SCORE_VARIABLES.values())),
            pl.col("model") != blend.ID,
            pl.col("enough_stations"),
            pl.col("mae").is_not_null(),
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
    and of ``best_models`` (score variable names), only for groups whose training had
    at least ``min_days`` scored days. With ``pairs`` (``mos.pairs``) and
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
    weights, best = [], []
    for as_of in as_of_days:
        part = scores.lazy().filter(pl.col("date") <= as_of)
        if length:  # only the window is needed
            part = part.filter(pl.col("date") > as_of - timedelta(days=length))
        if part.select(pl.len()).collect().item() == 0:
            continue
        table = aggregate.aggregate(part, stations, as_of, windows=(window,), levels=("okres",))
        stamp = pl.lit(as_of).alias("as_of")
        weights.append(combine.weights(table, window).with_columns(stamp))
        best.append(best_models(table, window).with_columns(stamp))
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
    b = (
        pl.concat(best)
        .with_columns(_target_date().alias("date"))
        .join(
            enough.with_columns(pl.col("variable").replace_strict(SCORE_VARIABLES)),
            on=["as_of", "region", "variable", "lead_day"],
            how="semi",
        )
    )
    return w, b


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


def daily_errors(
    scores: pl.DataFrame, combined_scores: pl.DataFrame, okres_pools: pl.DataFrame
) -> pl.DataFrame:
    """Day totals (``sum_abs_err``, ``n``, ``stations``) per okres, score variable, lead
    day, date and model (the models, ``blend`` and ``combined``) on the fair
    station-days of each okres, with the combination counting as one more model."""
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
    return (
        aggregate.common_days(rows, by="region")
        .group_by("region", "variable", "lead_day", "date", "model")
        .agg(
            metrics.total("sum_abs_err"),
            metrics.total("n"),
            pl.col("station_id").n_unique().alias("stations"),
        )
        .collect()
    )


def series(daily: pl.DataFrame, best: pl.DataFrame) -> pl.DataFrame:
    """Day totals per okres, variable, lead day, date and series on the days that have
    both the combination and the out-of-sample choice: the models, ``blend``,
    ``combined``, ``best_oos`` (the day's out-of-sample choice) and ``best_hindsight``
    (the okres's model with the lowest MAE over those days), with the model behind the
    last two in ``chosen``."""
    chosen = best.select("region", "variable", "lead_day", "date", pl.col("model").alias("chosen"))
    oos = daily.join(
        chosen, left_on=["region", "variable", "lead_day", "date", "model"],
        right_on=["region", "variable", "lead_day", "date", "chosen"],
    ).with_columns(pl.col("model").alias("chosen"), pl.lit(BEST_OOS).alias("model"))  # fmt: skip
    keys = ["region", "variable", "lead_day", "date"]
    tested = (
        pl.concat([daily.filter(pl.col("model") == COMBINED).select(keys), oos.select(keys)])
        .group_by(keys)
        .len()
        .filter(pl.col("len") == 2)
        .drop("len")
    )
    out = pl.concat([daily.with_columns(pl.lit(None, pl.String).alias("chosen")), oos])
    out = out.join(tested, on=keys, how="semi").filter(pl.col("n") > 0)
    group = ["region", "variable", "lead_day"]
    single = out.filter(~pl.col("model").is_in([COMBINED, BEST_OOS, blend.ID]))
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
    """Sum the okresy per variable, lead day, date and series; a model counts only if
    it is compared in every okres of that variable and lead day."""
    regions = days.group_by("variable", "lead_day").agg(pl.col("region").n_unique().alias("all"))
    everywhere = (
        days.group_by("variable", "lead_day", "model")
        .agg(pl.col("region").n_unique().alias("regions"))
        .join(regions, on=["variable", "lead_day"])
        .filter(pl.col("regions") == pl.col("all"))
        .select("variable", "lead_day", "model")
    )
    return (
        days.join(everywhere, on=["variable", "lead_day", "model"], how="semi")
        .group_by("variable", "lead_day", "date", "model")
        .agg(pl.col("sum_abs_err").sum(), pl.col("n").sum(), pl.col("stations").sum())
        .with_columns(pl.lit("cz").alias("region"), pl.lit(None, pl.String).alias("chosen"))
    )


def compare(
    days: pl.DataFrame, key: str, rng: np.random.Generator, resamples: int = ranking.RESAMPLES
) -> dict | None:
    """MAE of every series of one group and the bootstrap interval of its difference to
    ``best_oos``.

    ``days`` has ``date``, ``model``, ``sum_abs_err`` and ``n`` of one region,
    variable and lead day. Returns ``{"days", "series": {name: (mae, diff, low,
    high)}}`` or None without the combination or the choice.
    """
    abs_err = days.pivot(on="model", index="date", values="sum_abs_err").sort("date")
    n = days.pivot(on="model", index="date", values="n").sort("date")
    names = [c for c in abs_err.columns if c != "date"]
    if COMBINED not in names or BEST_OOS not in names:
        return None
    # every compared series must cover every day (the fair set makes the models do so)
    full = [c for c in names if n[c].null_count() == 0 and abs_err[c].null_count() == 0]
    if COMBINED not in full or BEST_OOS not in full:
        return None
    columns = full
    a = abs_err.select(full).to_numpy().astype(float)
    m = n.select(full).to_numpy().astype(float)
    ranked = np.array([c == BEST_OOS for c in columns])
    if a.shape[0] >= 2:
        _, diff, bounds = ranking.bootstrap_group(a, m, rng, resamples, ranked)
    else:
        mae_all = a.sum(axis=0) / m.sum(axis=0)
        diff = mae_all - mae_all[columns.index(BEST_OOS)]
        bounds = np.full((2, len(columns)), np.nan)
    totals = a.sum(axis=0) / m.sum(axis=0)
    out = {
        c: (float(totals[i]), float(diff[i]), float(bounds[0][i]), float(bounds[1][i]))
        for i, c in enumerate(columns)
    }
    return {"days": a.shape[0], "series": out}


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
    groups, model_rows = [], []
    frames = [("cz", czechia(days)), ("okres", days)]
    for level, frame in frames:
        for (region, variable, lead_day), part in sorted(
            frame.partition_by(["region", "variable", "lead_day"], as_dict=True).items()
        ):
            key = f"blendtest|{region}|{variable}|{lead_day}"
            result = compare(part, key, _seed(seed, key), resamples)
            if result is None or (level == "okres" and result["days"] < min_okres_days):
                continue
            s = result["series"]
            here = days.filter(pl.col("variable") == variable, pl.col("lead_day") == lead_day)
            if level == "okres":
                here = here.filter(pl.col("region") == region)
            chosen = here.filter(pl.col("model") == BEST_OOS)["chosen"]
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
            groups.append(row)
            if level == "cz":
                for model, (mae, diff, low, high) in s.items():
                    if model in (COMBINED, BEST_OOS, BEST_HINDSIGHT, blend.ID):
                        continue
                    model_rows.append(
                        [
                            variable,
                            lead_day,
                            model,
                            *(_nan_to_none(v) for v in (mae, diff, low, high)),
                        ]
                    )
    return groups, model_rows


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
) -> tuple[pl.DataFrame, list[list], list[list], dict]:
    """The whole test for the days ``first`` … ``last``: ``(days, groups, models,
    info)`` with the day totals (``series``), the rows of ``results`` and counts.
    ``regression``: temperature and wind with the regression blend (``mos``), as the
    live forecast; False: the inverse-error weights alone (the method before)."""
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
    daily = daily_errors(tested, combined_scores, okres_pools)
    days = series(daily, best)
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
    "of all models. Czechia sums all okresy. diff = MAE minus the MAE of best_oos "
    "(negative = better), with a 95 % interval from {resamples} bootstrap resamples of "
    "whole days."
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
    ``models`` (``MODEL_COLUMNS``): every single model in Czechia, same differences.
    """
    tested = sorted(days["date"].unique().to_list()) if days.height else []
    first_test = tested[0] if tested else None
    scored = info.get("scored_dates", [])
    warm_up = sum(1 for d in scored if first_test is None or d < first_test)
    return {
        "generated": generated.isoformat(timespec="seconds"),
        "method": METHOD.format(window=window, min_days=min_training_days, resamples=resamples),
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
        verdict = (
            "better" if high is not None and high < 0
            else "worse" if low is not None and low > 0
            else "no significant difference"
        )  # fmt: skip
        lines.append(
            f"{row[at['variable']]:<20} D+{row[at['lead_day']]}  {row[at['days']]:>3} days  "
            f"combined {row[at['mae_combined']]:.3f}  best (out of sample) "
            f"{row[at['mae_best_oos']]:.3f}  hindsight {row[at['mae_best_hindsight']] or 0:.3f}  "
            f"mean {row[at['mae_blend']] or 0:.3f}  diff {row[at['diff_combined']]:+.3f} "
            f"[{low if low is not None else float('nan'):+.3f}, "
            f"{high if high is not None else float('nan'):+.3f}]  {verdict}"
        )
    return lines
