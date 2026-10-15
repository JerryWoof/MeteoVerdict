"""Daily pipeline (roadmap 3.2).

Forecasts come from the backfill (complete 14-day windows, newest first), so the daily
run needs no Open-Meteo calls:

1. Capture the last days' observations from ``now/``: the current month is published
   in ``recent/`` only after it ends, and ``now/`` keeps about three days.
2. Re-score the last ``RESCORE_DAYS`` days, so newly captured observations, forecast
   windows finished by the backfill, and checked observations replacing unchecked
   ones all reach the scores.
3. Aggregate and rank all scores, write the web map JSON and the "last updated" badge
   (done by ``mvd daily`` with the functions of those steps).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import httpx
import polars as pl

from meteoverdict import gauges, observations, partitions, scoring
from meteoverdict.backfill import GAUGE_DELAY_DAYS
from meteoverdict.models import Model

RESCORE_DAYS = 100  # covers the 90-day window and the publication delay of ČHMÚ data
CAPTURE_DAYS = 3  # what now/ still has


def run(
    client: httpx.Client,
    points: pl.DataFrame,
    models: list[Model],
    day: date,
    data_dir: Path,
    log: Callable[[str], None] = lambda _: None,
    gauge_points: pl.DataFrame | None = None,
) -> list[str]:
    """Capture observations up to ``day`` and re-score; returns the months touched.

    Rain-gauge months still within ``GAUGE_DELAY_DAYS`` are read again from ``recent/``
    every day, as ČHMÚ adds the manual readings.
    """
    obs = observations.fetch_observations(
        client, points["id"], day - timedelta(days=CAPTURE_DAYS - 1), day
    )
    if obs.height:
        partitions.write_monthly(obs, data_dir / "obs", ["station_id", "time", "variable"])
    log(f"captured {obs.height} hourly observations up to {day}")
    if gauge_points is not None:
        since = (day - timedelta(days=GAUGE_DELAY_DAYS)).replace(day=1)
        rows = gauges.fetch_gauge_precipitation(
            client, gauge_points["id"], since, day, historical=False
        )
        if rows.height:
            observations.write_monthly(rows, data_dir / "gauges")
        log(f"refreshed {rows.height} rain-gauge totals since {since}")
    first = day - timedelta(days=RESCORE_DAYS - 1)
    obs_scan = observations.scan(data_dir, first, day + timedelta(days=1))
    fc_scan = partitions.scan_months(data_dir / "fc", first, day + timedelta(days=1))
    if obs_scan is None or fc_scan is None:
        log("nothing to score yet")
        return partitions.months(first, day)
    table = scoring.daily_scores(obs_scan, fc_scan, models, first, day)
    partitions.write_monthly(table, data_dir / "scores", scoring.KEYS, "date")
    last_scored = table["date"].max() if table.height else None
    log(f"re-scored {first}..{day}: {table.height} rows, last scored day {last_scored}")
    if last_scored is None or last_scored < day:
        after = last_scored or first - timedelta(days=1)
        log(f"nothing scored after {after}: {coverage(obs_scan, fc_scan, after, day)}")
    return partitions.months(first, day)


def coverage(obs: pl.LazyFrame, fc: pl.LazyFrame, after: date, day: date) -> str:
    """Days after ``after`` up to ``day`` with forecasts and with observations: a day is
    scored only when it has both (forecasts come in complete 14-day backfill windows,
    observations of days ``now/`` no longer keeps only once ČHMÚ publishes the month)."""
    span = pl.col("time").dt.date().is_between(after + timedelta(days=1), day)

    def days(frame: pl.LazyFrame) -> str:
        found = frame.filter(span).select(pl.col("time").dt.date().unique().sort())
        return day_ranges(found.collect().to_series().to_list())

    return f"forecasts for {days(fc)}, observations for {days(obs)}"


def day_ranges(days: list[date]) -> str:
    """``2026-10-01..2026-10-04, 2026-10-10`` for sorted days; ``no day`` for none."""
    ranges: list[list[date]] = []
    for d in days:
        if ranges and d - ranges[-1][1] == timedelta(days=1):
            ranges[-1][1] = d
        else:
            ranges.append([d, d])
    return ", ".join(f"{a}..{b}" if a != b else str(a) for a, b in ranges) or "no day"
