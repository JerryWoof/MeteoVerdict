"""Forecasts from the Open-Meteo Previous Runs API at the stations.

For every model in models.yaml we ask for ``<variable>_previous_dayN`` (the value
forecast N*24 h before the valid hour) for its measured lead days, at each station's
latitude, longitude **and elevation** (Open-Meteo then corrects for elevation).

The free API counts weighted calls (open-meteo.com/en/pricing): per location
max(1, variables / 10 * max(1, days / 14)), and allows 600 a minute, 5,000 an hour,
10,000 a day and 300,000 a month. So we ask one model at a time (its own lead days
only), up to 14 days per request and up to ``BATCH`` stations per request, keep a
running total, pace requests below the minute and hour limits, and stop before
``max_calls``.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import httpx
import polars as pl

from meteoverdict.models import VARIABLES, Model

URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
MAX_DAYS = 14  # longer windows cost more, shorter ones the same
BATCH = 100  # stations per request
KEYS = ["station_id", "time", "model", "lead_day"]
SCHEMA = {
    "station_id": pl.String,
    "time": pl.Datetime("us", "UTC"),
    "model": pl.String,
    "lead_day": pl.Int8,
    "temperature_2m": pl.Float32,
    "precipitation": pl.Float32,
    "wind_speed_10m": pl.Float32,
}


class QuotaError(RuntimeError):
    """The call budget of this run, or Open-Meteo's daily limit, is used up.

    ``partial`` holds the rows fetched before stopping, so they can still be saved.
    """

    partial: pl.DataFrame = pl.DataFrame(schema=SCHEMA)


def call_weight(locations: int, variables: int, days: int) -> float:
    """Open-Meteo's weighted call count for one request (formula from its pricing page)."""
    variables_weight = variables / 10
    return max(1.0, max(variables_weight, days / 14 * variables_weight)) * locations


@dataclass
class Budget:
    """Running total of weighted calls, paced below the per-minute and per-hour limits."""

    max_calls: float
    per_minute: float = 550  # Open-Meteo: 600
    per_hour: float = 4_800  # Open-Meteo: 5,000
    used: float = 0.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _recent: deque = field(default_factory=deque)

    def spend(self, weight: float) -> None:
        if self.used + weight > self.max_calls:
            raise QuotaError(f"budget of {self.max_calls:g} calls reached ({self.used:g} used)")
        for window, limit in ((60.0, self.per_minute), (3600.0, self.per_hour)):
            while True:
                now = self.clock()
                spent = sum(w for t, w in self._recent if now - t < window)
                if spent + weight <= limit:
                    break
                oldest = next(t for t, _ in self._recent if now - t < window)
                self.sleep(oldest + window - now + 0.5)
        now = self.clock()
        while self._recent and now - self._recent[0][0] >= 3600:
            self._recent.popleft()
        self._recent.append((now, weight))
        self.used += weight


def windows(start: date, end: date) -> Iterator[tuple[date, date]]:
    while start <= end:
        last = min(end, start + timedelta(days=MAX_DAYS - 1))
        yield start, last
        start = last + timedelta(days=1)


def hourly_names(model: Model) -> list[str]:
    return [f"{var}_previous_day{n}" for n in model.lead_days for var in VARIABLES]


def parse(payload: list | dict, station_ids: list[str], model: Model) -> pl.DataFrame:
    """One Open-Meteo response (a list for several locations) → rows per lead day."""
    results = payload if isinstance(payload, list) else [payload]
    if len(results) != len(station_ids):
        raise ValueError(f"asked for {len(station_ids)} locations, got {len(results)}")
    frames = []
    for position, result in enumerate(results):
        station = station_ids[result.get("location_id", position)]
        hourly = result["hourly"]
        times = pl.Series(hourly["time"]).str.to_datetime("%Y-%m-%dT%H:%M", time_zone="UTC")
        for n in model.lead_days:
            frames.append(
                pl.DataFrame(
                    {
                        "station_id": station,
                        "time": times,
                        "model": model.id,
                        "lead_day": n,
                        **{var: hourly[f"{var}_previous_day{n}"] for var in VARIABLES},
                    },
                    schema=SCHEMA,
                    strict=False,
                )
            )
    out = pl.concat(frames) if frames else pl.DataFrame(schema=SCHEMA)
    return out.filter(~pl.all_horizontal(pl.col(v).is_null() for v in VARIABLES))


def request(client: httpx.Client, params: dict, sleep: Callable[[float], None]) -> list | dict:
    for wait in (30, 60, 120, None):
        response = client.get(URL, params=params)
        if response.status_code == 429 and "daily" in response.text.lower():
            raise QuotaError(f"Open-Meteo: {response.json().get('reason', response.text)}")
        if response.status_code != 429 or wait is None:
            break
        sleep(wait)
    if response.status_code == 400:
        raise ValueError(f"Open-Meteo: {response.json().get('reason', response.text)}")
    response.raise_for_status()
    return response.json()


def fetch_forecasts(
    client: httpx.Client,
    stations: pl.DataFrame,
    models: list[Model],
    start: date,
    end: date,
    budget: Budget,
    log: Callable[[str], None] = lambda _: None,
) -> pl.DataFrame:
    """Forecasts for ``stations`` (id, lat, lon, elevation), ``start`` to ``end`` (UTC)."""
    frames = [pl.DataFrame(schema=SCHEMA)]
    rows = stations.select("id", "lat", "lon", "elevation").rows()
    first_hour = datetime.combine(start, datetime.min.time(), UTC)
    last_hour = datetime.combine(end, datetime.min.time(), UTC) + timedelta(hours=23)

    def collected() -> pl.DataFrame:
        return pl.concat(frames).filter(pl.col("time").is_between(first_hour, last_hour))

    try:
        _fetch_into(frames, client, rows, models, start, end, budget, log)
    except QuotaError as exc:
        exc.partial = collected()
        raise
    return collected()


def _fetch_into(frames, client, rows, models, start, end, budget, log) -> None:
    for model in models:
        first = max(start, model.archive_from)
        for window_start, window_end in windows(first, end):
            days = (window_end - window_start).days + 1
            for i in range(0, len(rows), BATCH):
                batch = rows[i : i + BATCH]
                names = hourly_names(model)
                budget.spend(call_weight(len(batch), len(names), days))
                params = {
                    "latitude": ",".join(f"{r[1]:.5f}" for r in batch),
                    "longitude": ",".join(f"{r[2]:.5f}" for r in batch),
                    # "nan" makes Open-Meteo use its own terrain height (checked live)
                    "elevation": ",".join("nan" if r[3] is None else f"{r[3]:.1f}" for r in batch),
                    "hourly": ",".join(names),
                    "models": model.id,
                    "wind_speed_unit": "ms",
                    "start_date": window_start.isoformat(),
                    "end_date": window_end.isoformat(),
                }
                payload = request(client, params, budget.sleep)
                frames.append(parse(payload, [r[0] for r in batch], model))
            log(f"{model.id} {window_start}..{window_end}: {budget.used:g} calls used")


def estimate_calls(n_stations: int, models: list[Model], start: date, end: date) -> float:
    """Weighted Open-Meteo calls ``fetch_forecasts`` will use."""
    total = 0.0
    for model in models:
        for window_start, window_end in windows(max(start, model.archive_from), end):
            days = (window_end - window_start).days + 1
            for i in range(0, n_stations, BATCH):
                batch = min(BATCH, n_stations - i)
                total += call_weight(batch, len(hourly_names(model)), days)
    return total
