"""Daily pipeline (roadmap 3.2).

Forecasts come from the backfill (complete 14-day windows, newest first), so the daily
run needs no Open-Meteo calls:

1. Capture the last days' observations from ``now/``: the current month is published
   in ``recent/`` only after it ends, and ``now/`` keeps about three days.
2. Re-score the last ``RESCORE_DAYS`` days, so newly captured observations, forecast
   windows finished by the backfill, and checked observations replacing unchecked
   ones all reach the scores.
3. Aggregate and rank all scores, write the web map JSON and the README leaderboard
   (done by ``mvd daily`` with the functions of those steps).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import httpx
import polars as pl

from meteoverdict import observations, partitions, scoring
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
) -> list[str]:
    """Capture observations up to ``day`` and re-score; returns the months touched."""
    obs = observations.fetch_observations(
        client, points["id"], day - timedelta(days=CAPTURE_DAYS - 1), day
    )
    if obs.height:
        partitions.write_monthly(obs, data_dir / "obs", ["station_id", "time", "variable"])
    log(f"captured {obs.height} hourly observations up to {day}")
    first = day - timedelta(days=RESCORE_DAYS - 1)
    obs_scan = partitions.scan_months(data_dir / "obs", first, day + timedelta(days=1))
    fc_scan = partitions.scan_months(data_dir / "fc", first, day + timedelta(days=1))
    if obs_scan is None or fc_scan is None:
        log("nothing to score yet")
        return partitions.months(first, day)
    table = scoring.daily_scores(obs_scan, fc_scan, models, first, day)
    partitions.write_monthly(table, data_dir / "scores", scoring.KEYS, "date")
    log(f"re-scored {first}..{day}: {table.height} rows")
    return partitions.months(first, day)
