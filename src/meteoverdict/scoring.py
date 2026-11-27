"""Daily scores table (roadmap 2.3).

One row per day, station, model, lead day and variable with the additive sums of
``meteoverdict.metrics``:

* ``temperature_2m`` and ``wind_speed_10m``: pairs at the synoptic hours 00, 06, 12
  and 18 UTC only (``period_h`` 0), where every model has native output, so all models
  are compared over the same hours of the day; the day is the UTC date of the hour.
  These are the ranked variables.
* ``temperature_2m_hourly`` and ``wind_speed_10m_hourly``: pairs at every native hour
  of the model (hourly for most), not ranked: their hours differ between models, and
  errors differ by time of day (by about 0.04 °C in MAE, September 2026).
* ``precipitation``: pairs over the model's native period (``period_h`` 1, 3 or 6); the
  day is the UTC date the period ends in (hours ending 01:00 … 24:00). MAEs of
  different periods are not comparable, so models are ranked on daily sums.
* ``precipitation_daily``: the UTC-day sum (``period_h`` 24), one value per day, with
  contingency counts for each event threshold.
* ``precipitation_24h``: the 06-06 UTC total (``period_h`` 24) of ČHMÚ's climatological
  day, from the manual rain gauges and the automatic stations; ``date`` is the day the
  window starts. Same sums and counts as ``precipitation_daily``.

* ``temperature_max``: the highest hourly temperature of the UTC day (``period_h`` 24),
  only for models with hourly output at that lead day, with counts for heat days
  (``metrics.HEAT_THRESHOLDS``).

* ``temperature_2m_00utc``, ``_06utc``, ``_12utc``, ``_18utc``: the temperature at
  one synoptic hour (``period_h`` 0), where every model has native output, to compare
  models by time of day (night inversions at 06 UTC, afternoon at 12 UTC).
* ``wind_speed_10m_00utc`` … ``_18utc``: the same for wind (since October 2026). Not
  aggregated or published on their own (``aggregate.SLOT_ONLY``): with the temperature
  ones they give each pair's error at a station and hour, from which
  ``aggregate.bias_corrected`` removes the model's usual bias there.

The mean of all models (``meteoverdict.blend``) is scored as one more model, ``blend``.

``source`` says where the forecasts came from: ``previous_runs`` here; ``fresh.mark``
sets ``single_runs`` for the recent days rebuilt from the single runs (score files
written before 2026-10-16 lack the column: Previous Runs).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import polars as pl

from meteoverdict import align, blend, metrics
from meteoverdict.models import Model

KEYS = ["date", "station_id", "model", "lead_day", "variable"]
#: ``source`` of a score row: D+N forecasts of the Previous Runs API (the backfill), or
#: rebuilt from the single runs for the days the backfill has not reached (``fresh``)
PREVIOUS_RUNS = "previous_runs"
SINGLE_RUNS = "single_runs"
#: Hours (UTC) at which every model, also the 6-hourly ones, has native output; the
#: temperature at each is scored separately (roadmap 5.1b), e.g. 06 UTC for inversions.
SYNOPTIC_HOURS = (0, 6, 12, 18)
#: Variables also scored at each synoptic hour on its own (``<variable>_HHutc``)
SLOT_VARIABLES = ("temperature_2m", "wind_speed_10m")


def slot_variable(variable: str, hour: int) -> str:
    """``temperature_2m``, 6 → ``temperature_2m_06utc``."""
    return f"{variable}_{hour:02d}utc"


#: Stations scored together by ``score_months``. The pairs of 100 days at ~300 stations
#: and ~30 models do not fit in memory at once (~19 GB; the 16 GB runner of the Daily
#: workflow ran out of it), so every month is scored in groups of stations.
STATION_CHUNK = 100


def month_spans(start: date, end: date) -> list[tuple[date, date]]:
    """The calendar months from ``start`` to ``end`` as ``(first day, last day)``, cut to
    that range."""
    spans = []
    first = start
    while first <= end:
        following = date(first.year + first.month // 12, first.month % 12 + 1, 1)
        last = min(end, following - timedelta(days=1))
        spans.append((first, last))
        first = following
    return spans


def score_months(
    observations: pl.LazyFrame | pl.DataFrame,
    forecasts: pl.LazyFrame | pl.DataFrame,
    models: list[Model],
    start: date,
    end: date,
    exclude_estimated: bool = False,
    with_blend: bool = True,
    chunk: int | None = STATION_CHUNK,
) -> Iterator[pl.DataFrame]:
    """The scores of ``daily_scores`` one calendar month at a time (each sorted by
    ``KEYS``, in date order), so the caller can write a month and drop it.

    A score row needs only the hours of its own day (the 06-06 UTC total and the hourly
    precipitation of 24:00 reach into the next one) and one station, so a month is scored
    from its hours (with a day of margin) in groups of ``chunk`` stations (None: all at
    once), and the rows are the same as when scoring everything at once.
    """
    obs, fc = observations.lazy(), forecasts.lazy()
    stations = fc.select("station_id").unique().sort("station_id").collect().to_series()
    size = chunk or max(stations.len(), 1)
    for first, last in month_spans(start, end):
        low = datetime.combine(first - timedelta(days=1), datetime.min.time(), UTC)
        high = datetime.combine(last + timedelta(days=2), datetime.min.time(), UTC)
        month_obs = obs.filter(pl.col("time").is_between(low, high))
        month_fc = fc.filter(pl.col("time").is_between(low, high))
        parts = []
        for i in range(0, max(stations.len(), 1), size):
            ids = stations.slice(i, size).to_list()
            parts.append(
                _daily_scores(
                    month_obs.filter(pl.col("station_id").is_in(ids)),
                    month_fc.filter(pl.col("station_id").is_in(ids)),
                    models,
                    first,
                    last,
                    exclude_estimated,
                    with_blend,
                )
            )
        table = pl.concat(parts, how="diagonal_relaxed").sort(KEYS)
        del parts
        yield table


def daily_scores(
    observations: pl.LazyFrame | pl.DataFrame,
    forecasts: pl.LazyFrame | pl.DataFrame,
    models: list[Model],
    start: date,
    end: date,
    exclude_estimated: bool = False,
    with_blend: bool = True,
    chunk: int | None = STATION_CHUNK,
) -> pl.DataFrame:
    """Scores of ``models`` and, with ``with_blend``, of their mean (``blend``), sorted
    by ``KEYS`` (``score_months`` puts them together)."""
    months = list(
        score_months(
            observations, forecasts, models, start, end, exclude_estimated, with_blend, chunk
        )
    )
    if not months:  # no days: the empty table
        return _daily_scores(
            observations.lazy(), forecasts.lazy(), models, start, end, exclude_estimated, with_blend
        )
    return pl.concat(months, how="diagonal_relaxed", rechunk=False)


def _daily_scores(
    observations: pl.LazyFrame,
    forecasts: pl.LazyFrame,
    models: list[Model],
    start: date,
    end: date,
    exclude_estimated: bool,
    with_blend: bool,
) -> pl.DataFrame:
    """Scores of the stations in ``observations`` and ``forecasts`` for ``start``..``end``."""
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
    hour = pl.col("time").dt.hour()
    instant = pl.col("variable").is_in(align.INSTANT)
    hourly = (
        pairs.with_columns(
            day.alias("date"),
            pl.when(instant)
            .then(pl.col("variable") + "_hourly")
            .otherwise(pl.col("variable"))
            .alias("variable"),
        )
        .group_by(*KEYS, "period_h")
        .agg(metrics.error_sums())
    )
    fair = (
        pairs.filter(instant, hour.is_in(SYNOPTIC_HOURS))
        .with_columns(day.alias("date"))
        .group_by(*KEYS, "period_h")
        .agg(metrics.error_sums())
    )
    synoptic = (
        pairs.filter(pl.col("variable").is_in(SLOT_VARIABLES), hour.is_in(SYNOPTIC_HOURS))
        .with_columns(
            pl.col("time").dt.date().alias("date"),
            pl.concat_str(
                pl.col("variable"), pl.lit("_"), pl.col("time").dt.strftime("%H"), pl.lit("utc")
            ).alias("variable"),
        )
        .group_by(*KEYS, "period_h")
        .agg(metrics.error_sums())
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
    heat = [e for t in metrics.HEAT_THRESHOLDS for e in metrics.contingency_counts(t)]
    maximum = (
        align.daily_maximum(observations, forecasts, models, exclude_estimated)
        .group_by("date", "station_id", "model", "lead_day")
        .agg(*metrics.error_sums(), *heat)
        .with_columns(
            pl.lit("temperature_max").alias("variable"), pl.lit(24, pl.Int8).alias("period_h")
        )
    )
    table = (
        pl.concat([hourly, fair, synoptic, daily, climatological, maximum], how="diagonal_relaxed")
        .filter(pl.col("date").is_between(start, end))
        .with_columns(pl.lit(PREVIOUS_RUNS).alias("source"))
        .collect()
    )
    return table.cast(metrics.compact(table.columns))
