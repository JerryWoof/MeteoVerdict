"""Pair forecasts with observations (roadmap 2.1).

Both sides are hourly and in UTC, with the same conventions (checked in Open-Meteo's
docs and against ČHMÚ's own hourly totals): temperature and wind are instantaneous
values at the hour, precipitation is the sum over the hour ending at ``time``.

Open-Meteo fills every hour, also where a model's output is 3- or 6-hourly
(Model.native_step); those in-between hours are interpolated. So for such a model and
lead day we keep temperature and wind only at its native hours, and compare
precipitation summed over its native periods (``period_h`` 3 or 6) instead of hourly.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl

from meteoverdict.models import VARIABLES, Model

INSTANT = ("temperature_2m", "wind_speed_10m")
PAIR_SCHEMA = {
    "station_id": pl.String,
    "time": pl.Datetime("us", "UTC"),
    "model": pl.String,
    "lead_day": pl.Int8,
    "variable": pl.String,
    "period_h": pl.Int8,  # 0 for instantaneous values, else the precipitation period
    "forecast": pl.Float32,
    "observed": pl.Float32,
    "quality": pl.UInt8,  # worst ČHMÚ quality code of the observations used
}


def _steps(models: list[Model]) -> pl.LazyFrame:
    rows = [(m.id, n, m.native_step(n)) for m in models for n in m.lead_days]
    return pl.LazyFrame(
        rows, schema={"model": pl.String, "lead_day": pl.Int8, "step": pl.Int8}, orient="row"
    )


def pairs(
    observations: pl.LazyFrame | pl.DataFrame,
    forecasts: pl.LazyFrame | pl.DataFrame,
    models: list[Model],
    exclude_estimated: bool = False,
) -> pl.LazyFrame:
    """Forecast-observation pairs at each model's native time resolution."""
    obs = observations.lazy()
    if exclude_estimated:
        obs = obs.filter(pl.col("quality") != 3)
    fc = (
        forecasts.lazy()
        .unpivot(
            index=["station_id", "time", "model", "lead_day"],
            on=list(VARIABLES),
            variable_name="variable",
            value_name="forecast",
        )
        .filter(pl.col("forecast").is_not_null())
    )
    hourly = fc.join(
        obs.select("station_id", "time", "variable", pl.col("value").alias("observed"), "quality"),
        on=["station_id", "time", "variable"],
        how="inner",
    ).join(_steps(models), on=["model", "lead_day"], how="inner")
    hour = pl.col("time").dt.hour()
    instant = hourly.filter(
        pl.col("variable").is_in(INSTANT), hour % pl.col("step") == 0
    ).with_columns(pl.lit(0, pl.Int8).alias("period_h"))
    precipitation = (
        hourly.filter(pl.col("variable") == "precipitation")
        # the hour ending at HH belongs to the native period ending at the next multiple
        # of the step (for a step of 6: 01:00 … 06:00 → 06:00)
        .with_columns(
            (
                pl.col("time")
                + pl.duration(hours=(pl.col("step") - hour % pl.col("step")) % pl.col("step"))
            ).alias("time")
        )
        .group_by("station_id", "time", "model", "lead_day", "variable", "step")
        .agg(
            pl.col("forecast").sum(),
            pl.col("observed").sum(),
            pl.col("quality").max(),
            pl.len().alias("n"),
        )
        .filter(pl.col("n") == pl.col("step"))
        .with_columns(pl.col("step").alias("period_h"))
    )
    return pl.concat(
        [instant.select(list(PAIR_SCHEMA)), precipitation.select(list(PAIR_SCHEMA))]
    ).cast(PAIR_SCHEMA)


def daily_precipitation(precipitation_pairs: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Daily sums (UTC day, 00:00-24:00) of precipitation pairs; only complete days."""
    one_hour = timedelta(hours=1)
    return (
        precipitation_pairs.lazy()
        .filter(pl.col("variable") == "precipitation")
        .with_columns((pl.col("time") - one_hour).dt.date().alias("date"))
        .group_by("station_id", "date", "model", "lead_day")
        .agg(
            pl.col("forecast").sum(),
            pl.col("observed").sum(),
            pl.col("quality").max(),
            pl.col("period_h").cast(pl.Int32).sum().alias("hours"),
        )
        .filter(pl.col("hours") == 24)
        .drop("hours")
    )
