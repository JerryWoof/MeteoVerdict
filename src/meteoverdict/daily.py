"""Daily pipeline (roadmap 3.2).

Forecasts come from the backfill (complete 14-day windows, newest first) and, for the
days it has not reached yet, from the single runs (``fresh``), so the daily run needs
no Open-Meteo calls:

1. Capture the last days' observations from ``now/``: the current month is published
   in ``recent/`` only after it ends, and ``now/`` keeps about three days.
2. Rebuild D+N forecasts of the last ``fresh.DAYS`` days from the single runs
   (``runs/``, the ~100 stations of ``runs.yml``) for the hours the backfill's windows
   do not cover yet, and log how both sources agree where they overlap.
3. Re-score the last ``RESCORE_DAYS`` days, so newly captured observations, forecast
   windows finished by the backfill (replacing the rebuilt forecasts), and checked
   observations replacing unchecked ones all reach the scores; ``source`` says which
   days were scored from the single runs.
4. Aggregate and rank all scores, write the web map JSON and the "last updated" badge
   (done by ``mvd daily`` with the functions of those steps).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import httpx
import polars as pl

from meteoverdict import fresh, gauges, observations, partitions, scoring
from meteoverdict.backfill import GAUGE_DELAY_DAYS
from meteoverdict.models import MAX_LEAD_DAY, Model

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
    fc_scan, added = add_fresh(data_dir, models, day, obs_scan, fc_scan, log)
    if obs_scan is None or fc_scan is None:
        log("nothing to score yet")
        return partitions.months(first, day)
    table = scoring.daily_scores(obs_scan, fc_scan, models, first, day)
    if added is not None:
        table = fresh.mark(table, added)
    partitions.write_monthly(table, data_dir / "scores", scoring.KEYS, "date")
    last_scored = table["date"].max() if table.height else None
    log(f"re-scored {first}..{day}: {table.height} rows, last scored day {last_scored}")
    if last_scored is None or last_scored < day:
        after = last_scored or first - timedelta(days=1)
        log(f"nothing scored after {after}: {coverage(obs_scan, fc_scan, after, day)}")
    return partitions.months(first, day)


def add_fresh(
    data_dir: Path,
    models: list[Model],
    day: date,
    obs: pl.LazyFrame | None,
    fc: pl.LazyFrame | None,
    log: Callable[[str], None] = lambda _: None,
) -> tuple[pl.LazyFrame | None, pl.DataFrame | None]:
    """``(forecasts, rebuilt rows added)``: the Previous Runs forecasts ``fc`` plus the
    D+N rebuilt from the single runs in ``data_dir/runs`` (``fresh.previous_days``) for
    the hours of the last ``fresh.DAYS`` days that ``fc`` lacks; ``None`` added when
    there are no single runs. Logs how both sources agree where both exist."""
    start, end = fresh.window(day)
    # the oldest run that can make a D+N of the first hour
    since = start.date() - timedelta(days=MAX_LEAD_DAY + 1)
    single = partitions.scan_months(data_dir / "runs", since, end.date())
    if single is None:
        log("no single runs to rebuild the recent days from")
        return fc, None
    derived = fresh.previous_days(single, models, start, end).collect()
    if derived.height == 0:
        log("no D+N could be rebuilt from the single runs")
        return fc, None
    if fc is None:
        added = derived
        fc = derived.lazy()
    else:
        in_window = fc.filter(pl.col("time").is_between(start, end))
        log(fresh.summary(fresh.compare(in_window, derived, obs, models)))
        fc, added = fresh.fill(fc, derived)
    if added.height:
        log(
            f"rebuilt D+N from the single runs for {added['station_id'].n_unique()} stations "
            f"and {day_ranges(sorted(set(added['time'].dt.date())))}"
        )
    return fc, added


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
