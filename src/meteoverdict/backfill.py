"""Backfill history (roadmap 2.6): resumable, newest first, within the Open-Meteo quota.

Work is split into 14-day windows counted from the first day (a window costs the same
as a single day, so windows run across month boundaries). Only complete windows (all 14
days within the range) are processed, newest first; the newest, still incomplete window
is picked up once its last day has passed. For each window: observations of its months
(once per month), forecasts per model (``model|start|end`` is the unit of progress), then
the window's daily scores.
Progress is kept in a small JSON state file, so a run that stops at its call budget
(or Open-Meteo's daily limit) continues where it left off next time.

Rain gauges (roadmap 2.8) only need precipitation, which Open-Meteo bills by 28-day
requests, so their forecasts come per 28-day window (two 14-day windows, counted from
the same first day; ``gauges|model|start|end``). Their observations are fetched per
month from ``recent/`` (last 12 months; older ones are imported once with
``mvd fetch-gauges``) into ``gauges/``, and kept as final once the month ended
``GAUGE_DELAY_DAYS`` before the last day (manual readings arrive about a month late);
newer months are refreshed by the daily run.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

import httpx
import polars as pl

from meteoverdict import forecasts, gauges, observations, partitions, scoring
from meteoverdict.models import Model

GAUGE_DELAY_DAYS = 62


@dataclass
class State:
    path: Path
    obs_months: set[str] = field(default_factory=set)
    fc_done: set[str] = field(default_factory=set)
    scored: set[str] = field(default_factory=set)
    gauge_months: set[str] = field(default_factory=set)
    #: model id -> stations Open-Meteo has no data for (outside the model's real domain)
    uncovered: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> State:
        if not path.exists():
            return cls(path)
        doc = json.loads(path.read_text(encoding="utf-8"))
        uncovered = {m: set(ids) for m, ids in doc.get("uncovered", {}).items()}
        return cls(
            path,
            set(doc["obs_months"]),
            set(doc["fc_done"]),
            set(doc["scored"]),
            set(doc.get("gauge_months", [])),
            uncovered,
        )

    def save(self) -> None:
        doc = {
            "obs_months": sorted(self.obs_months),
            "fc_done": sorted(self.fc_done),
            "scored": sorted(self.scored),
            "gauge_months": sorted(self.gauge_months),
            "uncovered": {m: sorted(ids) for m, ids in sorted(self.uncovered.items()) if ids},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


class Sync(Protocol):
    """Keeps the local month files in step with a remote store (GitHub Releases)."""

    def pull(self, months: list[str]) -> None: ...

    def push(self, months: list[str]) -> None: ...


@dataclass
class Result:
    windows_done: int = 0
    stopped: str = ""  # why the run stopped early, if it did


def fc_key(model: Model, start: date, end: date) -> str:
    return f"{model.id}|{start}|{end}"


def window_key(start: date, end: date) -> str:
    return f"{start}|{end}"


def gauge_key(model: Model, start: date, end: date) -> str:
    return f"gauges|{model.id}|{start}|{end}"


def gauge_window(first: date, last: date, start: date) -> tuple[date, date] | None:
    """The complete 28-day window (counted from ``first``) holding the day ``start``."""
    for s, e in forecasts.windows(first, last, forecasts.GAUGE_DAYS):
        if s <= start <= e:
            return (s, e) if (e - s).days + 1 == forecasts.GAUGE_DAYS else None
    return None


def complete_windows(first: date, last: date) -> list[tuple[date, date]]:
    """14-day windows counted from ``first`` that end on or before ``last``."""
    return [
        (s, e) for s, e in forecasts.windows(first, last) if (e - s).days + 1 == forecasts.MAX_DAYS
    ]


def run(
    client: httpx.Client,
    points: pl.DataFrame,
    models: list[Model],
    first: date,
    last: date,
    data_dir: Path,
    budget: forecasts.Budget,
    sync: Sync | None = None,
    log: Callable[[str], None] = lambda _: None,
    gauge_points: pl.DataFrame | None = None,
) -> Result:
    """``gauge_points``: rain gauges that are not in ``points`` (precipitation only)."""
    state = State.load(data_dir / "backfill-state.json")
    result = Result()
    for start, end in reversed(complete_windows(first, last)):
        gauge_span = gauge_window(first, last, start) if gauge_points is not None else None
        # windows scored before the gauges were added get their gauge forecasts later
        if window_key(start, end) in state.scored and not (
            gauge_span and _gauges_pending(models, gauge_span, state)
        ):
            continue
        months = partitions.months(start, end)
        span = (min(start, gauge_span[0]), max(end, gauge_span[1])) if gauge_span else (start, end)
        # all months this window writes to; the last day's daily precipitation also
        # needs the next day's observations
        touched = partitions.months(*span)
        if sync:
            sync.pull(partitions.months(span[0], span[1] + timedelta(days=1)))
        for month in months:
            if month in state.obs_months:
                continue
            year, mon = map(int, month.split("-"))
            month_first = date(year, mon, 1)
            month_last = partitions.month_end(month_first)
            obs = observations.fetch_observations(
                client, points["id"], max(first, month_first), min(last, month_last)
            )
            if obs.height:
                partitions.write_monthly(obs, data_dir / "obs", ["station_id", "time", "variable"])
            # only a published month (recent/ or historical/) is final; data from now/
            # covers a few days and is replaced once ČHMÚ publishes the month
            if obs.height == 0 or "now" in set(obs["source"]):
                log(f"{month}: observations not published as a month yet")
                continue
            state.obs_months.add(month)
            state.save()
        if gauge_points is not None:
            _gauge_observations(client, gauge_points, months, first, last, data_dir, state)
        for model in models:
            model_start = max(start, model.archive_from)
            if model_start > end or fc_key(model, start, end) in state.fc_done:
                continue
            try:
                fc = forecasts.fetch_forecasts(
                    client, points, [model], model_start, end, budget, uncovered=state.uncovered
                )
            except forecasts.QuotaError as exc:
                partitions.write_monthly(exc.partial, data_dir / "fc", forecasts.KEYS)
                if sync:
                    sync.push(touched)
                result.stopped = str(exc)
                return result
            partitions.write_monthly(fc, data_dir / "fc", forecasts.KEYS)
            state.fc_done.add(fc_key(model, start, end))
            state.save()
        if gauge_span:
            stopped = _gauge_forecasts(
                client, gauge_points, models, gauge_span, data_dir, budget, state
            )
            if stopped:
                if sync:
                    sync.push(touched)
                result.stopped = stopped
                return result
        if all(m in state.obs_months for m in months):
            # the whole gauge window: its other half may have been scored without gauges
            first_day, last_day = span
            obs_scan = observations.scan(data_dir, first_day, last_day + timedelta(1))
            fc_scan = partitions.scan_months(data_dir / "fc", first_day, last_day + timedelta(1))
            if obs_scan is not None and fc_scan is not None:
                table = scoring.daily_scores(obs_scan, fc_scan, models, first_day, last_day)
                partitions.write_monthly(table, data_dir / "scores", scoring.KEYS, "date")
            state.scored.add(window_key(start, end))
            state.save()
        if sync:
            sync.push(touched)
        result.windows_done += 1
        log(f"window {start}..{end} done, {budget.used:g} calls used")
    return result


def _gauge_observations(client, gauge_points, months, first, last, data_dir, state) -> None:
    for month in months:
        if month in state.gauge_months:
            continue
        year, mon = map(int, month.split("-"))
        month_first = date(year, mon, 1)
        month_last = partitions.month_end(month_first)
        # recent/ only: older months come from a one-off `mvd fetch-gauges` import
        rows = gauges.fetch_gauge_precipitation(
            client,
            gauge_points["id"],
            max(first, month_first),
            min(last, month_last),
            historical=False,
        )
        if rows.height:
            observations.write_monthly(rows, data_dir / "gauges")
        if (last - month_last).days >= GAUGE_DELAY_DAYS:
            state.gauge_months.add(month)
            state.save()


def _gauges_pending(models: list[Model], span: tuple[date, date], state: State) -> bool:
    start, end = span
    return any(
        max(start, m.archive_from) <= end and gauge_key(m, start, end) not in state.fc_done
        for m in models
    )


def _gauge_forecasts(client, gauge_points, models, span, data_dir, budget, state) -> str:
    """Precipitation forecasts at the gauges for one 28-day window; why it stopped."""
    start, end = span
    for model in models:
        model_start = max(start, model.archive_from)
        if model_start > end or gauge_key(model, start, end) in state.fc_done:
            continue
        try:
            fc = forecasts.fetch_forecasts(
                client,
                gauge_points,
                [model],
                model_start,
                end,
                budget,
                uncovered=state.uncovered,
                variables=("precipitation",),
                max_days=forecasts.GAUGE_DAYS,
            )
        except forecasts.QuotaError as exc:
            partitions.write_monthly(exc.partial, data_dir / "fc", forecasts.KEYS)
            return str(exc)
        partitions.write_monthly(fc, data_dir / "fc", forecasts.KEYS)
        state.fc_done.add(gauge_key(model, start, end))
        state.save()
    return ""
