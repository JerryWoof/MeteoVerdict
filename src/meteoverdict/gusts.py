"""Wind gusts of the outlook per okres and part of day, from the stored single runs.

No Open-Meteo calls: the single runs (``runs``, release ``runs-YYYY-MM``) already hold
every model's hourly ``wind_gusts_10m`` (maximum of the preceding hour) at the ~100 run
stations, four runs a day, stored model by model as they reach Open-Meteo's bucket. The
outlook takes the newest stored run at least ``runs.MIN_AGE_H`` hours old (by then every
model has it; about 10-16 hours old):

1. **Stations of an okres** (``okres_stations``): the run stations in the okres at most
   ``sun_cloud_gust.LOWLAND_MAX_M`` high and at most ``frost.MAX_SITE_ABOVE_POINT`` above
   the okres's forecast point (summits such as Lysá hora are 3-6 m/s windier than the
   okres's fields); an okres without one takes the nearest such station within
   ``FALLBACK_KM`` of its point.
2. **Per station and part of day** (``station_parts``, Prague time, an hourly gust
   belongs to the part of the hour it ends): each model's largest gust in the part, then
   the mean over the models. A model counts where it has at least ``MIN_PART_VALUES``
   values in the part and reaches its end; a part needs ``MIN_MODELS`` models and must
   lie wholly after the run's start. Beyond that (the end of the run, about 5 days) the
   gust is null.
3. **Correction** (``sun_cloud_gust``, variable ``gust_part``): ``a + b·mean`` plus the
   station's mean remaining error, fitted on part-of-day maxima (the daily-maximum
   coefficients of ``gust`` make part-of-day maxima worse: docs/methodology.md). Applied
   only while its out-of-sample check beats the plain mean (``apply``).
4. **Okres**: the mean over its stations; the whole day the largest of its four parts.
   ``gust_warning`` when the corrected gust is at least ``WARNING_AT``.

The nightly fit pairs the same station parts with ČHMÚ gusts (hourly maxima of the
10-minute ``Fmax`` in ``obs``, at least ``MIN_OBS_HOURS`` hours of the part).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from meteoverdict import frost, sun_cloud_gust

VARIABLE = "gust_part"
#: as ``outlook.PARTS`` and ``outlook.TIME_ZONE`` (a test keeps them equal; outlook
#: imports this module)
TIME_ZONE = "Europe/Prague"
PRAGUE = ZoneInfo(TIME_ZONE)
PARTS = {"night": (0, 6), "morning": (6, 12), "afternoon": (12, 18), "evening": (18, 24)}
#: a model's part needs this many hourly values (3-hourly output gives 2 in 6 hours)
MIN_PART_VALUES = 2
#: a part needs this many models
MIN_MODELS = 3
#: the newest run is used only up to this age (hours); older: no gusts
MAX_RUN_AGE_H = 36
#: ... and from this age on (``runs.MIN_AGE_H``: every model has reached Open-Meteo)
MIN_RUN_AGE_H = 10
#: an okres without its own lowland station takes the nearest one this close
FALLBACK_KM = 30.0
#: observed part maximum: at least this many hourly gusts of the part
MIN_OBS_HOURS = 5
#: ``gust_warning``: the corrected part maximum at least this (m/s). Out of sample
#: (2026-09-06..10-14, 8 lowland stations, D+1) it gave the best ETS for observed gusts
#: of at least ``EVENT_AT`` among 12-15 m/s in steps of 0.5: 0.31, POD 0.47, FAR 0.50,
#: frequency bias 0.93 (15 events only; docs/methodology.md#gusts-in-the-outlook)
WARNING_AT = 13.5
EVENT_AT = 15.0
MAX_LEAD = sun_cloud_gust.MAX_LEAD

OKRES_SCHEMA = {
    "okres": pl.String,
    "day": pl.Date,
    "part": pl.String,
    "gust": pl.Float64,
    "gust_warning": pl.Boolean,
}


def local_part(time: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
    """``day`` and ``part`` (Prague time) of an instant."""
    local = time.dt.convert_time_zone(TIME_ZONE)
    part = pl.lit(None, pl.String)
    for name, (first, end) in PARTS.items():
        part = (
            pl.when(local.dt.hour().is_between(first, end - 1)).then(pl.lit(name)).otherwise(part)
        )
    return local.dt.date().alias("day"), part.alias("part")


def _km(lat1, lon1, lat2, lon2) -> float:
    dx = (lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * 110.57
    return math.hypot(dx, dy)


def okres_stations(
    run_stations: pl.DataFrame, points: pl.DataFrame, elevations: pl.DataFrame
) -> pl.DataFrame:
    """``okres``, ``station``: the lowland run stations of every okres (step 1).
    ``run_stations``: ``runs.load_stations()``; ``points``: ``code``, ``lat``, ``lon``;
    ``elevations``: ``code``, ``elevation`` of the okres points."""
    height = dict(elevations.select("code", "elevation").iter_rows())
    pool = run_stations.filter(pl.col("elevation") <= sun_cloud_gust.LOWLAND_MAX_M)
    sites = pool.select("id", "lat", "lon", "elevation", "okres_code").rows()
    rows = []
    for code, lat, lon in points.select("code", "lat", "lon").iter_rows():
        top = height.get(code)

        def ok(site, top=top) -> bool:
            return top is None or site[3] - top <= frost.MAX_SITE_ABOVE_POINT

        own = [s for s in sites if s[4] == code and ok(s)]
        if not own:
            near = sorted((_km(lat, lon, s[1], s[2]), s[0]) for s in sites if ok(s))
            own = [s for s in sites if near and near[0][0] <= FALLBACK_KM and s[0] == near[0][1]]
        rows += [(code, s[0]) for s in own]
    return pl.DataFrame(rows, schema={"okres": pl.String, "station": pl.String}, orient="row")


def newest_run(runs: pl.LazyFrame | pl.DataFrame, now: datetime) -> datetime | None:
    """The newest run with gusts of at least ``MIN_MODELS`` models, from
    ``MIN_RUN_AGE_H`` to ``MAX_RUN_AGE_H`` hours old (a younger run may still lack
    models: the bucket's runs are stored model by model as they arrive)."""
    found = (
        runs.lazy()
        .filter(
            pl.col("wind_gusts_10m").is_not_null(),
            pl.col("run") >= now - timedelta(hours=MAX_RUN_AGE_H),
            pl.col("run") <= now - timedelta(hours=MIN_RUN_AGE_H),
        )
        .group_by("run")
        .agg(pl.col("model").n_unique().alias("models"))
        .filter(pl.col("models") >= MIN_MODELS)
        .select(pl.col("run").max())
        .collect()
    )
    return found["run"][0] if found.height else None


def station_parts(runs: pl.LazyFrame | pl.DataFrame, stations) -> pl.DataFrame:
    """``station``, ``run``, ``day``, ``part``, ``lead_day``, ``forecast`` (mean over the
    models of each model's largest gust in the part), ``models`` (step 2). ``lead_day``:
    whole days from the run's start to the part's end, 1-``MAX_LEAD``."""
    day, part = local_part(pl.col("valid_time") - pl.duration(hours=1))
    rows = (
        runs.lazy()
        .filter(pl.col("station_id").is_in(list(stations)), pl.col("wind_gusts_10m").is_not_null())
        .with_columns(
            day, part, pl.col("valid_time").max().over("run", "model", "station_id").alias("_last")
        )
        .group_by("station_id", "run", "model", "day", "part")
        .agg(
            pl.col("wind_gusts_10m").max().cast(pl.Float64).alias("gust"),
            pl.len().alias("n"),
            pl.col("valid_time").min().alias("_first"),
            pl.col("_last").first(),
        )
        .collect()
    )
    if rows.is_empty():
        return pl.DataFrame(
            schema={
                "station": pl.String,
                "run": pl.Datetime("us", "UTC"),
                "day": pl.Date,
                "part": pl.String,
                "lead_day": pl.Int64,
                "forecast": pl.Float64,
                "models": pl.UInt32,
            }
        )
    keys = rows.select("day", "part").unique()
    first, end = _part_bounds(keys)
    bounds = keys.with_columns(
        pl.Series("_start", first, pl.Datetime("us", "UTC")),
        pl.Series("_end", end, pl.Datetime("us", "UTC")),
    )
    return (
        rows.join(bounds, on=["day", "part"])
        .filter(
            pl.col("n") >= MIN_PART_VALUES,
            pl.col("_last") >= pl.col("_end"),  # the model reaches the part's end
            pl.col("_start") >= pl.col("run"),  # wholly after the start
        )
        .group_by("station_id", "run", "day", "part", "_end")
        .agg(pl.col("gust").mean().alias("forecast"), pl.len().alias("models"))
        .filter(pl.col("models") >= MIN_MODELS)
        .with_columns(
            ((pl.col("_end") - pl.col("run")).dt.total_hours() / 24)
            .ceil()
            .clip(1, MAX_LEAD)
            .cast(pl.Int64)
            .alias("lead_day")
        )
        .select(
            pl.col("station_id").alias("station"),
            "run",
            "day",
            "part",
            "lead_day",
            "forecast",
            "models",
        )
        .sort("station", "run", "day", "part")
    )


def _part_bounds(keys: pl.DataFrame) -> tuple[list[datetime], list[datetime]]:
    """UTC start and end of each (``day``, ``part``) of ``keys``."""
    starts, ends = [], []
    for day, part in keys.iter_rows():
        first, last = PARTS[part]
        midnight = datetime(day.year, day.month, day.day, tzinfo=PRAGUE)
        starts.append(midnight.replace(hour=first).astimezone(UTC))
        stop = midnight + timedelta(days=1) if last == 24 else midnight.replace(hour=last)
        ends.append(stop.astimezone(UTC))
    return starts, ends


def correct(parts: pl.DataFrame, doc: dict) -> pl.DataFrame:
    """``station_parts`` with ``corrected`` (step 3; the plain mean when the correction is
    not to be applied)."""
    entry = doc.get(VARIABLE) or sun_cloud_gust.load(sun_cloud_gust.BOOTSTRAP)[VARIABLE]
    values = parts["forecast"].to_numpy().astype(float)
    out = values.copy()
    if entry.get("apply", True) and parts.height:
        leads = parts["lead_day"].to_numpy()
        stations = parts["station"].to_list()
        for lead in np.unique(leads):
            rows = leads == lead
            coef = sun_cloud_gust.coefficients({VARIABLE: entry}, VARIABLE, int(lead))
            out[rows] = sun_cloud_gust.predict_gust(
                coef, values[rows], [s for s, r in zip(stations, rows, strict=True) if r]
            )
    return parts.with_columns(pl.Series("corrected", out, pl.Float64))


def okres_gusts(
    runs: pl.LazyFrame | pl.DataFrame | None,
    mapping: pl.DataFrame,
    doc: dict,
    now: datetime,
) -> pl.DataFrame:
    """``okres``, ``day``, ``part`` (and "day"), ``gust``, ``gust_warning`` from the
    newest run (step 4); empty without a usable run. ``mapping``: ``okres_stations``."""
    empty = pl.DataFrame(schema=OKRES_SCHEMA)
    if runs is None or mapping.is_empty():
        return empty
    run = newest_run(runs, now)
    if run is None:
        return empty
    parts = station_parts(runs.lazy().filter(pl.col("run") == run), mapping["station"].unique())
    if parts.is_empty():
        return empty
    parts = correct(parts, doc)
    okres = (
        parts.join(mapping, on="station")
        .group_by("okres", "day", "part")
        .agg(pl.col("corrected").mean().alias("gust"))
    )
    days = (
        okres.group_by("okres", "day")
        .agg(pl.col("gust").max(), pl.len().alias("n"))
        .filter(pl.col("n") == len(PARTS))
        .select("okres", "day", pl.lit("day").alias("part"), "gust")
    )
    return (
        pl.concat([okres, days])
        .with_columns((pl.col("gust") >= WARNING_AT).alias("gust_warning"))
        .cast(OKRES_SCHEMA)
        .sort("okres", "day", "part")
    )


# --- the nightly fit -------------------------------------------------------------------
def observed_parts(observations: pl.LazyFrame | pl.DataFrame, stations) -> pl.DataFrame:
    """``station``, ``day``, ``part``, ``observed``: the largest hourly ČHMÚ gust
    (``obs``: ``wind_gusts_10m``, the hour ending at ``time``) of the part, with at least
    ``MIN_OBS_HOURS`` hours."""
    day, part = local_part(pl.col("time") - pl.duration(hours=1))
    return (
        observations.lazy()
        .filter(
            pl.col("variable") == "wind_gusts_10m",
            pl.col("station_id").is_in(list(stations)),
            pl.col("time").dt.minute() == 0,
            pl.col("value").is_not_null(),
        )
        .unique(["station_id", "time"], keep="first")
        .with_columns(day, part)
        .group_by("station_id", "day", "part")
        .agg(pl.col("value").max().cast(pl.Float64).alias("observed"), pl.len().alias("n"))
        .filter(pl.col("n") >= MIN_OBS_HOURS)
        .select(pl.col("station_id").alias("station"), "day", "part", "observed")
        .collect()
    )


def pairs(
    runs: pl.LazyFrame | pl.DataFrame | None,
    observations: pl.LazyFrame | pl.DataFrame | None,
    stations,
) -> pl.DataFrame | None:
    """Training pairs ``station``, ``day``, ``part``, ``lead_day``, ``forecast``,
    ``observed`` of all stored runs (None without runs or observations)."""
    if runs is None or observations is None:
        return None
    stations = list(stations)
    forecast = station_parts(runs, stations)
    observed = observed_parts(observations, stations)
    return forecast.join(observed, on=["station", "day", "part"]).select(
        "station", "day", "part", "lead_day", "forecast", "observed"
    )
