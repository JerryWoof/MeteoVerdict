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

Priorities (docs/data-sources.md#open-meteo-budget): the outlook and the single runs'
API fallback (the newest runs come from Open-Meteo's bucket, ``bucket``) have budgets of
their own; a daily **shared** budget is spent on (3) the *current*
windows (``CURRENT_DAYS``: the ones the 90-day ranking and the combination weights read),
then (3b) the *priority* windows (ending on or after ``priority_from``, e.g. one full year
back, so every season is in the scores) at the station ``subset`` only (the ~100 stations
of the single runs, about a fifth of the calls), then (4a) the single runs' API history
(older than the bucket's three months, and the bucket's gaps) and
only then (4b) the *older* windows, and the rest of the stations of the priority
windows. So ``run`` takes older windows only when asked (``older``; ``mvd backfill
--older-windows after-runs-history`` asks once the single-runs history is complete), and
records how many calls it used today (``calls_on``, ``calls_used``). ``share_left``
tells ``mvd fetch-runs`` how much of the shared budget the backfill leaves today.

A priority window fetched at the subset has the keys ``model|start|end|subset``; when
the window is fetched for all stations later (as an older window), the subset's
stations are not asked again. Priority windows get no rain-gauge forecasts until then.

A model added to the catalogue is pending in every window of its archive; windows are
processed newest first, so it is fetched for the current windows first (also for windows
already scored, which are then scored again).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx
import polars as pl

from meteoverdict import forecasts, gauges, observations, partitions, scoring
from meteoverdict.models import Model

GAUGE_DELAY_DAYS = 62
#: Windows ending within this many days of the last day are "current": they feed the
#: 90-day ranking (aggregate window ``90d``) and the combination weights, so they come
#: before any history. Usually only the newest window is pending; after a model is added,
#: all of them are (for that model), and until they are fetched the fair comparison
#: would cut the 90-day ranking down to the days the new model has.
CURRENT_DAYS = 90


@dataclass
class State:
    path: Path
    obs_months: set[str] = field(default_factory=set)
    fc_done: set[str] = field(default_factory=set)
    scored: set[str] = field(default_factory=set)
    gauge_months: set[str] = field(default_factory=set)
    #: model id -> stations Open-Meteo has no data for (outside the model's real domain)
    uncovered: dict[str, set[str]] = field(default_factory=dict)
    #: UTC day (YYYY-MM-DD) the backfill last asked Open-Meteo for forecasts
    calls_on: str = ""
    #: weighted calls it used on that day (None: not recorded, by an older version)
    calls_used: float | None = None

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
            doc.get("calls_on", ""),
            doc.get("calls_used"),
        )

    def save(self) -> None:
        doc = {
            "obs_months": sorted(self.obs_months),
            "fc_done": sorted(self.fc_done),
            "scored": sorted(self.scored),
            "gauge_months": sorted(self.gauge_months),
            "uncovered": {m: sorted(ids) for m, ids in sorted(self.uncovered.items()) if ids},
        }
        if self.calls_on:
            doc["calls_on"] = self.calls_on
            if self.calls_used is not None:
                doc["calls_used"] = round(self.calls_used, 1)
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
    #: why older windows were left out (empty: they were allowed)
    held_back: str = ""
    #: complete older windows not looked at because of ``held_back``
    older_skipped: int = 0


def fc_key(model: Model, start: date, end: date) -> str:
    return f"{model.id}|{start}|{end}"


def subset_key(model: Model, start: date, end: date) -> str:
    """A window's forecasts of ``model`` at the station subset only (priority windows)."""
    return f"{model.id}|{start}|{end}|subset"


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


def is_current(end: date, last: date) -> bool:
    """A window ending on ``end`` is current (priority 3) when ``last`` is the last day."""
    return end > last - timedelta(days=CURRENT_DAYS)


def is_priority(end: date, last: date, priority_from: date | None) -> bool:
    """A window ending on ``end`` is a priority window (3b): not current, but ending on
    or after ``priority_from``."""
    return priority_from is not None and end >= priority_from and not is_current(end, last)


class _Calls:
    """Keeps ``calls_on``/``calls_used`` of the state up to date with the budget."""

    def __init__(self, state: State, day: str, budget: forecasts.Budget) -> None:
        self.state, self.day, self.budget = state, day, budget
        same_day = state.calls_on == day and state.calls_used is not None
        self.before = (state.calls_used or 0.0) if same_day else 0.0
        self.start = budget.used

    def note(self) -> None:
        self.state.calls_on = self.day
        self.state.calls_used = self.before + self.budget.used - self.start


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
    today: date | None = None,
    older: bool = True,
    held_back: str = "",
    priority_from: date | None = None,
    subset: set[str] | None = None,
) -> Result:
    """``gauge_points``: rain gauges that are not in ``points`` (precipitation only);
    ``today``: the UTC day recorded as ``calls_on`` (default: now); ``older``: also the
    windows that are neither current nor priority windows (else not, and ``held_back``
    says why); ``priority_from``: while older windows are held back, the windows ending
    on or after it are fetched too, at the stations of ``subset`` only (all stations
    without a subset); once older windows are allowed, they get the other stations."""
    state = State.load(data_dir / "backfill-state.json")
    calls = _Calls(state, str(today or datetime.now(UTC).date()), budget)
    result = Result()
    windows = list(reversed(complete_windows(first, last)))
    if not older:
        allowed = [
            (s, e) for s, e in windows if is_current(e, last) or is_priority(e, last, priority_from)
        ]
        result.older_skipped = len(windows) - len(allowed)
        result.held_back = held_back or "older windows not asked for"
        windows = allowed
    subset_ids = set(points["id"]) & subset if subset else set()
    for start, end in windows:
        # once older windows are allowed, priority windows get all their stations too
        thin = bool(subset_ids) and not older and is_priority(end, last, priority_from)
        gauge_span = (
            gauge_window(first, last, start) if gauge_points is not None and not thin else None
        )
        # windows scored before a model or the gauges were added are fetched again
        if (
            window_key(start, end) in state.scored
            and not _forecasts_pending(models, start, end, state, thin)
            and not (gauge_span and _gauges_pending(models, gauge_span, state))
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
            unreadable: list[str] = []
            obs = observations.fetch_observations(
                client,
                points["id"],
                max(first, month_first),
                min(last, month_last),
                unreadable=unreadable,
            )
            if obs.height:
                partitions.write_monthly(obs, data_dir / "obs", ["station_id", "time", "variable"])
            # only a whole month published (recent/ or historical/) and read for every
            # station is final; data from now/ covers a few days and is replaced once ČHMÚ
            # publishes the month
            if first > month_first or last < month_last:
                log(f"{month}: observations fetched for part of the month only")
                continue
            if unreadable:
                log(f"{month}: {len(unreadable)} monthly files unreadable, e.g. {unreadable[0]}")
                continue
            if obs.height == 0 or "now" in set(obs["source"]):
                log(f"{month}: observations not published as a month yet")
                continue
            state.obs_months.add(month)
            state.save()
        if gauge_points is not None:
            _gauge_observations(client, gauge_points, months, first, last, data_dir, state)
        for stations, group, keys in _requests(models, start, end, state, points, subset_ids, thin):
            calls.note()
            try:
                fc = forecasts.fetch_forecasts(
                    client,
                    stations,
                    group,
                    min(max(start, m.archive_from) for m in group),
                    end,
                    budget,
                    uncovered=state.uncovered,
                )
            except forecasts.QuotaError as exc:
                partitions.write_monthly(exc.partial, data_dir / "fc", forecasts.KEYS)
                calls.note()
                state.save()
                if sync:
                    sync.push(touched)
                result.stopped = str(exc)
                return result
            partitions.write_monthly(fc, data_dir / "fc", forecasts.KEYS)
            state.fc_done.update(keys)
            calls.note()
            state.save()
        if gauge_span:
            stopped = _gauge_forecasts(
                client, gauge_points, models, gauge_span, data_dir, budget, state, calls.note
            )
            if stopped:
                state.save()
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


def _requests(models, start, end, state, points, subset_ids, thin):
    """``(stations, models, state keys)`` to fetch for one window, models with the same
    lead days together where that is cheaper (``forecasts.groups``).

    ``thin`` (a priority window): the subset only. Otherwise all stations, except the
    subset's for models already fetched there."""
    pending = [
        m
        for m in models
        if max(start, m.archive_from) <= end
        and fc_key(m, start, end) not in state.fc_done
        and not (thin and subset_key(m, start, end) in state.fc_done)
    ]
    if thin:
        parts = [(points.filter(pl.col("id").is_in(list(subset_ids))), pending, subset_key)]
    else:
        done = [m for m in pending if subset_key(m, start, end) in state.fc_done]
        rest = points.filter(~pl.col("id").is_in(list(subset_ids)))
        parts = [
            (points, [m for m in pending if m not in done], fc_key),
            (rest, done, fc_key),
        ]
    for stations, todo, key in parts:
        for group in forecasts.groups(todo):
            yield stations, group, {key(m, start, end) for m in group}


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


def _gauge_forecasts(
    client, gauge_points, models, span, data_dir, budget, state, note=lambda: None
) -> str:
    """Precipitation forecasts at the gauges for one 28-day window; why it stopped.
    ``note`` records the calls of the day in the state."""
    start, end = span
    pending = [
        m
        for m in models
        if max(start, m.archive_from) <= end and gauge_key(m, start, end) not in state.fc_done
    ]
    precipitation = ("precipitation",)
    for group in forecasts.groups(pending, precipitation, forecasts.GAUGE_DAYS):
        note()
        try:
            fc = forecasts.fetch_forecasts(
                client,
                gauge_points,
                group,
                min(max(start, m.archive_from) for m in group),
                end,
                budget,
                uncovered=state.uncovered,
                variables=precipitation,
                max_days=forecasts.GAUGE_DAYS,
            )
        except forecasts.QuotaError as exc:
            partitions.write_monthly(exc.partial, data_dir / "fc", forecasts.KEYS)
            note()
            return str(exc)
        partitions.write_monthly(fc, data_dir / "fc", forecasts.KEYS)
        state.fc_done.update(gauge_key(m, start, end) for m in group)
        note()
        state.save()
    return ""


def _forecasts_pending(
    models: list[Model], start: date, end: date, state: State, thin: bool = False
) -> bool:
    """A model's forecasts of the window are still to fetch (``thin``: at the subset)."""
    return any(
        max(start, m.archive_from) <= end
        and fc_key(m, start, end) not in state.fc_done
        and not (thin and subset_key(m, start, end) in state.fc_done)
        for m in models
    )


def pending_windows(
    models: list[Model],
    first: date,
    last: date,
    state: State,
    gauges: bool = True,
    current_only: bool = False,
    priority_from: date | None = None,
) -> list[tuple[date, date]]:
    """Complete windows (newest first) for which ``run`` would still ask Open-Meteo:
    station forecasts of a model, or (``gauges``) the rain-gauge forecasts of the 28-day
    window the 14-day window completes; ``current_only``: only the current windows and,
    with ``priority_from``, the priority windows (at the station subset, no gauges). A
    window fetched but not scored yet (its observations not published as a month) needs
    only ČHMÚ downloads, so it is not pending here."""
    found = []
    for start, end in reversed(complete_windows(first, last)):
        thin = is_priority(end, last, priority_from)
        if current_only and not (is_current(end, last) or thin):
            break
        gauge_span = gauge_window(first, last, start) if gauges and not thin else None
        if _forecasts_pending(models, start, end, state, thin) or (
            gauge_span and _gauges_pending(models, gauge_span, state)
        ):
            found.append((start, end))
    return found


def share_left(
    models: list[Model],
    first: date,
    today: date,
    state: State,
    share: float,
    priority_from: date | None = None,
) -> tuple[float, str]:
    """How much of today's shared budget ``share`` the backfill (``--from first``,
    ``--to`` yesterday, ``--priority-from priority_from``) leaves for the single-runs
    history, and why (one line).

    - a current or priority window still pending (the backfill has not finished it, or
      not run yet today): nothing;
    - a current window becomes due tomorrow (one ending today): nothing, so the
      single-runs history and the backfill's next big day are always 24 hours apart;
    - the backfill asked Open-Meteo today (UTC): ``share`` minus what it used (nothing
      when it did not record how much);
    - otherwise: all of ``share``. Older windows do not count: they come after the
      single-runs history.
    """
    yesterday = today - timedelta(days=1)
    pending = pending_windows(
        models, first, yesterday, state, current_only=True, priority_from=priority_from
    )
    if pending:
        (start, end), n = pending[0], len(pending)
        kind = "current" if is_current(end, yesterday) else "priority"
        ran = " (it used Open-Meteo today)" if state.calls_on == str(today) else ""
        return 0.0, (
            f"{n} {kind} backfill window{'s' * (n > 1)} pending (newest {start}..{end}){ran}"
        )
    due = pending_windows(models, first, today, state, current_only=True)
    if due:
        return 0.0, f"backfill window {due[0][0]}..{due[0][1]} becomes due tomorrow"
    if state.calls_on == str(today):
        if state.calls_used is None:
            return 0.0, "the backfill used Open-Meteo today (amount not recorded)"
        left = max(0.0, share - state.calls_used)
        return left, (f"the backfill used {state.calls_used:g} of the {share:g} shared calls today")
    since = f" and its priority windows (since {priority_from})" if priority_from else ""
    return share, f"the backfill's current windows (last {CURRENT_DAYS} days){since} are done"


def summary(
    result: Result,
    calls: float,
    data_dir: Path,
    first: date,
    last: date,
    priority_from: date | None = None,
) -> str:
    """Markdown for the workflow's job summary: this run and the overall progress."""
    state = State.load(data_dir / "backfill-state.json")
    windows = complete_windows(first, last)
    scored = sum(window_key(s, e) in state.scored for s, e in windows)
    lines = [
        "## Backfill",
        "",
        f"- This run: {result.windows_done} windows, {calls:g} Open-Meteo calls",
        f"- Progress: {scored} of {len(windows)} 14-day windows scored since {first}",
        f"- Observation months final: {len(state.obs_months)}, rain-gauge months final: "
        f"{len(state.gauge_months)}",
    ]
    current = sum(is_current(e, last) for _, e in windows)
    priority = [(s, e) for s, e in windows if is_priority(e, last, priority_from)]
    if priority:
        done = sum(window_key(s, e) in state.scored for s, e in priority)
        then = (
            f"then the {len(priority)} priority windows ending since {priority_from} at the "
            f"station subset ({done} scored); "
        )
    else:
        then = ""
    lines.append(
        f"- Priority: the {current} current windows (last {CURRENT_DAYS} days) first; "
        + then
        + (
            f"older windows held back ({result.older_skipped} not looked at): {result.held_back}"
            if result.held_back
            else "older windows allowed"
        )
    )
    if state.calls_on and state.calls_used is not None:
        lines.append(f"- Calls on {state.calls_on} (UTC): {state.calls_used:g}")
    if result.stopped:
        lines.append(f"- Stopped: {result.stopped} (the next run continues)")
    return "\n".join(lines) + "\n"
