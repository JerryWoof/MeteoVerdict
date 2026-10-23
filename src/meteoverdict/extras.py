"""Scores of the further variables the combined forecast weighs (humidity, dew point,
gusts, sea-level pressure, wind direction).

Temperature, precipitation and wind are scored from the Previous Runs archive
(``meteoverdict.scoring``). The further variables exist only in the single runs, from the
bucket (``runs.EXTRA_VARIABLES``; gusts are in the Previous Runs too but only from
October 2026), so they are scored from there: the D+N forecasts rebuilt as ``fresh`` does
(``fresh.previous_days`` with ``variables``) against the stations that measure them
(``obs/`` and ``obs-extra/``). Same score rows as ``scoring`` (additive error sums per
day, station, model, lead day and variable), kept in their own monthly files
``data/scores-extra/`` so that nothing reading ``scores/`` changes, and aggregated at the
okres level only (``meteoverdict.aggregate``), which gives ``combine.weights`` the rows for
the variables of ``combine.EXTRA_VARIABLES``.

At the synoptic hours 00, 06, 12 and 18 UTC only, where every model has native output
(as ``scoring``). Wind direction is scored with the circular error
``((forecast - observed + 180) mod 360) - 180``, only where the station's wind is at
least ``MIN_WIND_FOR_DIRECTION`` m/s (the direction of a calm is noise); the bias is then
the mean of those angles, the MAE their mean absolute value.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import polars as pl

from meteoverdict import aggregate, combine, fresh, metrics, partitions, scoring
from meteoverdict.models import Model

UTC = UTC
#: the variables scored here (their names are the Open-Meteo and the observation names)
VARIABLES = tuple(combine.EXTRA_VARIABLES)
#: wind direction is only scored where the observed wind is at least this strong (m/s)
MIN_WIND_FOR_DIRECTION = 1.0
#: variables with too few stations for okres weights (about 25 measure sea-level pressure):
#: every okres gets the weights of all stations, which suits a smooth field
NATIONAL = ("pressure_msl",)
#: monthly score files, next to ``scores/``
FOLDER = "scores-extra"
#: days of single runs re-scored by ``mvd daily`` (the 90-day window is kept in the files)
RESCORE_DAYS = fresh.DAYS


def wrap(angle: pl.Expr) -> pl.Expr:
    """An angle difference in degrees, wrapped to [-180, 180)."""
    return (angle + 180.0) % 360.0 - 180.0


def forecasts(
    single_runs: pl.LazyFrame | pl.DataFrame, models: list[Model], first: date, last: date
) -> pl.LazyFrame:
    """D+N rows of the further variables for valid hours of ``first`` to ``last`` (UTC)."""
    start = datetime.combine(first, time(0), UTC)
    end = datetime.combine(last, time(23), UTC)
    columns = single_runs.lazy().collect_schema().names()
    have = tuple(v for v in VARIABLES if v in columns)
    return fresh.previous_days(single_runs, models, start, end, have).filter(
        pl.any_horizontal(pl.col(v).is_not_null() for v in have)
    )


def daily_scores(
    observations_: pl.LazyFrame | pl.DataFrame,
    fc: pl.LazyFrame | pl.DataFrame,
    models: list[Model],
    start: date,
    end: date,
) -> pl.DataFrame:
    """Score rows (``scoring.KEYS`` and the sums of ``metrics.error_sums``) of the
    further variables, one per day, station, model, lead day and variable."""
    obs = observations_.lazy()
    columns = fc.lazy().collect_schema().names()
    present = [v for v in VARIABLES if v in columns]
    long = (
        fc.lazy()
        .unpivot(
            index=["station_id", "time", "model", "lead_day"],
            on=present,
            variable_name="variable",
            value_name="forecast",
        )
        .filter(pl.col("forecast").is_not_null())
    )
    speed = obs.filter(pl.col("variable") == "wind_speed_10m").select(
        "station_id", "time", pl.col("value").alias("_speed")
    )
    seen = obs.filter(pl.col("variable").is_in(present)).select(
        "station_id", "time", "variable", pl.col("value").alias("observed")
    )
    steps = pl.LazyFrame(
        [(m.id, n, m.native_step(n)) for m in models for n in m.lead_days],
        schema={"model": pl.String, "lead_day": pl.Int8, "step": pl.Int8},
        orient="row",
    )
    hour = pl.col("time").dt.hour()
    direction = pl.col("variable") == "wind_direction_10m"
    pairs = (
        long.join(seen, on=["station_id", "time", "variable"], how="inner")
        .join(steps, on=["model", "lead_day"], how="inner")
        .filter(hour.is_in(scoring.SYNOPTIC_HOURS), hour % pl.col("step") == 0)
        .join(speed, on=["station_id", "time"], how="left")
        .filter(~direction | (pl.col("_speed") >= MIN_WIND_FOR_DIRECTION))
        .with_columns(
            pl.when(direction)
            .then(wrap(pl.col("forecast").cast(pl.Float64) - pl.col("observed")))
            .otherwise(pl.col("forecast").cast(pl.Float64))
            .alias("forecast"),
            pl.when(direction).then(0.0).otherwise(pl.col("observed")).alias("observed"),
        )
    )
    table = (
        pairs.with_columns(pl.col("time").dt.date().alias("date"))
        .group_by(*scoring.KEYS)
        .agg(metrics.error_sums())
        .with_columns(pl.lit(0, pl.Int8).alias("period_h"))
        .filter(pl.col("date").is_between(start, end))
        .sort(scoring.KEYS)
        .collect()
    )
    return table.cast(metrics.compact(table.columns))


def scan_observations(data_dir: Path, first: date, last: date) -> pl.LazyFrame | None:
    """The hourly observations ``daily_scores`` needs: ``obs/`` (wind, gusts) and
    ``obs-extra/`` (humidity, dew point, direction, pressure)."""
    scans = [partitions.scan_months(data_dir / kind, first, last) for kind in ("obs", "obs-extra")]
    found = [s for s in scans if s is not None]
    return pl.concat(found, how="diagonal_relaxed") if found else None


def update(
    data_dir: Path, models: list[Model], day: date, days: int = RESCORE_DAYS
) -> pl.DataFrame | None:
    """Score the last ``days`` days up to ``day`` from ``data_dir/runs`` and the
    observations, and merge them into ``data_dir/scores-extra``; the scored rows, or None
    where there are no runs or observations."""
    first = day - timedelta(days=days - 1)
    runs = partitions.scan_months(data_dir / "runs", first - timedelta(days=7), day)
    obs = scan_observations(data_dir, first, day + timedelta(days=1))
    if runs is None or obs is None:
        return None
    runs = runs.filter(pl.col("valid_time") >= datetime.combine(first, time(0), UTC))
    table = daily_scores(obs, forecasts(runs, models, first, day), models, first, day)
    if table.height:
        partitions.write_monthly(table, data_dir / FOLDER, scoring.KEYS, "date")
    return table


def okres_table(
    data_dir: Path, stations: pl.DataFrame, as_of: date | None = None
) -> pl.DataFrame | None:
    """The 90-day okres scores of the further variables (``aggregate.aggregate`` rows of
    ``combine.WINDOW``, ``okres`` level) from ``data_dir/scores-extra``, for
    ``combine.weights``; None where there are no score files."""
    files = sorted((data_dir / FOLDER).glob("*.parquet"))
    if not files:
        return None
    scores = pl.concat([pl.scan_parquet(f) for f in files], how="diagonal_relaxed")
    table = aggregate.aggregate(
        scores, stations, as_of, windows=(combine.WINDOW,), levels=("okres", "cz"), corrected=False
    )
    okresy = (
        stations.select(pl.col("okres_code").alias("region"), pl.col("okres").alias("region_name"))
        .drop_nulls("region")
        .unique("region")
    )
    local = table.filter(pl.col("level") == "okres", ~pl.col("variable").is_in(NATIONAL))
    national = (
        table.filter(pl.col("level") == "cz", pl.col("variable").is_in(NATIONAL))
        .drop("region", "region_name", "level")
        .join(okresy, how="cross")
        .with_columns(pl.lit("okres").alias("level"))
        .select(local.columns)
    )
    table = pl.concat([local, national])
    return table if table.height else None
