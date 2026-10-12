"""Pair forecasts with observations (roadmap 2.1).

Both sides are hourly and in UTC, with the same conventions (checked in Open-Meteo's
docs and against ČHMÚ's own hourly totals): temperature and wind are instantaneous
values at the hour, precipitation is the sum over the hour ending at ``time``.

Open-Meteo fills every hour, also where a model's output is 3- or 6-hourly
(Model.native_step); those in-between hours are interpolated. So for such a model and
lead day we keep temperature and wind only at its native hours, and compare
precipitation summed over its native periods (``period_h`` 3 or 6) instead of hourly.

``precipitation_24h`` compares 24-hour totals over ČHMÚ's climatological day, 06:00 to
06:00 UTC, which is the window of the manual rain gauges. Every native period of 3 or
6 hours fits into it, so hourly forecasts can be summed for any model.
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


#: ČHMÚ's climatological day starts at 06:00 UTC; an hour ending at ``time`` belongs to
#: the window of the date of ``time - 7 h`` (07:00 … 06:00 next day).
WINDOW_OFFSET = timedelta(hours=7)


def precipitation_24h(
    observations: pl.LazyFrame | pl.DataFrame,
    forecasts: pl.LazyFrame | pl.DataFrame,
    models: list[Model],
    exclude_estimated: bool = False,
) -> pl.LazyFrame:
    """06-06 UTC precipitation pairs; ``date`` is the day the window starts.

    Observed totals come from the rain gauges (``precipitation_24h``, stamped at the
    window's end) and, where a station has no gauge value, from 24 complete hourly
    sums. Forecasts are hourly sums over the same 24 hours, each hour from its own lead
    day (as for the UTC-day totals).
    """
    obs = observations.lazy()
    if exclude_estimated:
        obs = obs.filter(pl.col("quality") != 3)
    window = (pl.col("time") - WINDOW_OFFSET).dt.date().alias("date")
    gauges = obs.filter(pl.col("variable") == "precipitation_24h").select(
        "station_id",
        (pl.col("time") - timedelta(days=1)).dt.date().alias("date"),
        pl.col("value").alias("observed"),
        "quality",
    )
    hourly = (
        obs.filter(pl.col("variable") == "precipitation")
        .group_by("station_id", window)
        .agg(pl.col("value").sum().alias("observed"), pl.col("quality").max(), pl.len())
        .filter(pl.col("len") == 24)
        .drop("len")
        .join(gauges, on=["station_id", "date"], how="anti")
    )
    fc = (
        forecasts.lazy()
        .filter(pl.col("precipitation").is_not_null())
        .join(_steps(models).select("model", "lead_day"), on=["model", "lead_day"], how="inner")
        .group_by("station_id", window, "model", "lead_day")
        .agg(pl.col("precipitation").sum().alias("forecast"), pl.len())
        .filter(pl.col("len") == 24)
        .drop("len")
    )
    return fc.join(pl.concat([gauges, hourly]), on=["station_id", "date"], how="inner").select(
        "station_id",
        "date",
        "model",
        pl.col("lead_day").cast(pl.Int8),
        pl.col("forecast").cast(pl.Float32),
        pl.col("observed").cast(pl.Float32),
        pl.col("quality").cast(pl.UInt8),
    )


def daily_maximum(
    observations: pl.LazyFrame | pl.DataFrame,
    forecasts: pl.LazyFrame | pl.DataFrame,
    models: list[Model],
    exclude_estimated: bool = False,
) -> pl.LazyFrame:
    """Highest hourly temperature of each UTC day (00:00 … 23:00), forecast and observed.

    Only for models with hourly output at that lead day: the maximum of interpolated
    hours would hide the peak. Both sides use the values at the full hour, so the
    observed maximum is the highest hourly reading, not ČHMÚ's ``TMA``.
    """
    obs = observations.lazy().filter(pl.col("variable") == "temperature_2m")
    if exclude_estimated:
        obs = obs.filter(pl.col("quality") != 3)
    day = pl.col("time").dt.date().alias("date")
    observed = (
        obs.group_by("station_id", day)
        .agg(pl.col("value").max().alias("observed"), pl.col("quality").max(), pl.len())
        .filter(pl.col("len") == 24)
        .drop("len")
    )
    hourly = _steps(models).filter(pl.col("step") == 1).select("model", "lead_day")
    forecast = (
        forecasts.lazy()
        .filter(pl.col("temperature_2m").is_not_null())
        .join(hourly, on=["model", "lead_day"], how="inner")
        .group_by("station_id", day, "model", "lead_day")
        .agg(pl.col("temperature_2m").max().alias("forecast"), pl.len())
        .filter(pl.col("len") == 24)
        .drop("len")
    )
    return forecast.join(observed, on=["station_id", "date"], how="inner").select(
        "station_id",
        "date",
        "model",
        pl.col("lead_day").cast(pl.Int8),
        pl.col("forecast").cast(pl.Float32),
        pl.col("observed").cast(pl.Float32),
        pl.col("quality").cast(pl.UInt8),
    )
