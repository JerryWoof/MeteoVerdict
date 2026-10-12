"""Backfill history (roadmap 2.6): resumable, newest first, within the Open-Meteo quota.

Work is split into 14-day windows counted from the first day (a window costs the same
as a single day, so windows run across month boundaries). Windows are processed newest
first. For each window: observations of its months (once per month), forecasts per
model (``model|window start`` is the unit of progress), then the window's daily scores.
Progress is kept in a small JSON state file, so a run that stops at its call budget
(or Open-Meteo's daily limit) continues where it left off next time.
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

from meteoverdict import forecasts, observations, partitions, scoring
from meteoverdict.models import Model


@dataclass
class State:
    path: Path
    obs_months: set[str] = field(default_factory=set)
    fc_done: set[str] = field(default_factory=set)
    scored: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> State:
        if not path.exists():
            return cls(path)
        doc = json.loads(path.read_text(encoding="utf-8"))
        return cls(path, set(doc["obs_months"]), set(doc["fc_done"]), set(doc["scored"]))

    def save(self) -> None:
        doc = {
            "obs_months": sorted(self.obs_months),
            "fc_done": sorted(self.fc_done),
            "scored": sorted(self.scored),
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


def fc_key(model: Model, start: date) -> str:
    return f"{model.id}|{start}"


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
) -> Result:
    state = State.load(data_dir / "backfill-state.json")
    result = Result()
    for start, end in reversed(list(forecasts.windows(first, last))):
        if str(start) in state.scored:
            continue
        months = partitions.months(start, end)
        # the last day's daily precipitation also needs the next day's observations
        nearby = partitions.months(start, end + timedelta(days=1))
        if sync:
            sync.pull(nearby)
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
        for model in models:
            model_start = max(start, model.archive_from)
            if model_start > end or fc_key(model, start) in state.fc_done:
                continue
            try:
                fc = forecasts.fetch_forecasts(client, points, [model], model_start, end, budget)
            except forecasts.QuotaError as exc:
                partitions.write_monthly(exc.partial, data_dir / "fc", forecasts.KEYS)
                if sync:
                    sync.push(months)
                result.stopped = str(exc)
                return result
            partitions.write_monthly(fc, data_dir / "fc", forecasts.KEYS)
            state.fc_done.add(fc_key(model, start))
            state.save()
        if all(m in state.obs_months for m in months):
            obs_scan = partitions.scan_months(data_dir / "obs", start, end + timedelta(days=1))
            fc_scan = partitions.scan_months(data_dir / "fc", start, end + timedelta(days=1))
            if obs_scan is not None and fc_scan is not None:
                table = scoring.daily_scores(obs_scan, fc_scan, models, start, end)
                partitions.write_monthly(table, data_dir / "scores", scoring.KEYS, "date")
            state.scored.add(str(start))
            state.save()
        if sync:
            sync.push(months)
        result.windows_done += 1
        log(f"window {start}..{end} done, {budget.used:g} calls used")
    return result
