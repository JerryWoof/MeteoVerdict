"""Daily scores table (roadmap 2.3).

One row per day, station, model, lead day and variable with the additive sums of
``meteoverdict.metrics``:

* ``temperature_2m`` and ``wind_speed_10m``: hourly pairs at native hours
  (``period_h`` 0); the day is the UTC date of the hour.
* ``precipitation``: pairs over the model's native period (``period_h`` 1, 3 or 6); the
  day is the UTC date the period ends in (hours ending 01:00 … 24:00). MAEs of
  different periods are not comparable, so models are ranked on daily sums.
* ``precipitation_daily``: the UTC-day sum (``period_h`` 24), one value per day, with
  contingency counts for each event threshold.
* ``precipitation_24h``: the 06-06 UTC total (``period_h`` 24) of ČHMÚ's climatological
  day, from the manual rain gauges and the automatic stations; ``date`` is the day the
  window starts. Same sums and counts as ``precipitation_daily``.

The mean of all models (``meteoverdict.blend``) is scored as one more model, ``blend``.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from meteoverdict import align, blend, metrics
from meteoverdict.models import Model

KEYS = ["date", "station_id", "model", "lead_day", "variable"]


def daily_scores(
    observations: pl.LazyFrame | pl.DataFrame,
    forecasts: pl.LazyFrame | pl.DataFrame,
    models: list[Model],
    start: date,
    end: date,
    exclude_estimated: bool = False,
    with_blend: bool = True,
) -> pl.DataFrame:
    """Scores of ``models`` and, with ``with_blend``, of their mean (``blend``)."""
    if with_blend:
        forecasts = pl.concat([forecasts.lazy(), blend.forecasts(forecasts, models)])
        models = [*models, blend.MODEL]
    pairs = align.pairs(observations, forecasts, models, exclude_estimated)
    one_hour = timedelta(hours=1)
    day = (
        pl.when(pl.col("variable") == "precipitation")
        .then((pl.col("time") - one_hour).dt.date())
        .otherwise(pl.col("time").dt.date())
    )
    hourly = (
        pairs.with_columns(day.alias("date")).group_by(*KEYS, "period_h").agg(metrics.error_sums())
    )
    counts = [e for t in metrics.PRECIPITATION_THRESHOLDS for e in metrics.contingency_counts(t)]
    daily = (
        align.daily_precipitation(pairs)
        .group_by("date", "station_id", "model", "lead_day")
        .agg(*metrics.error_sums(), *counts)
        .with_columns(
            pl.lit("precipitation_daily").alias("variable"), pl.lit(24, pl.Int8).alias("period_h")
        )
    )
    climatological = (
        align.precipitation_24h(observations, forecasts, models, exclude_estimated)
        .group_by("date", "station_id", "model", "lead_day")
        .agg(*metrics.error_sums(), *counts)
        .with_columns(
            pl.lit("precipitation_24h").alias("variable"), pl.lit(24, pl.Int8).alias("period_h")
        )
    )
    return (
        pl.concat([hourly, daily, climatological], how="diagonal_relaxed")
        .filter(pl.col("date").is_between(start, end))
        .sort(KEYS)
        .collect()
    )
