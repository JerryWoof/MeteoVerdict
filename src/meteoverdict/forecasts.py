"""Forecasts from the Open-Meteo Previous Runs API at the stations.

For every model in models.yaml we ask for ``<variable>_previous_dayN`` (the value
forecast N*24 h before the valid hour) for its measured lead days, at each station's
latitude, longitude **and elevation** (Open-Meteo then corrects for elevation).

The free API counts weighted calls (open-meteo.com/en/pricing): per location
max(1, variables / 10 * max(1, days / 14)), and allows 600 a minute, 5,000 an hour,
10,000 a day and 300,000 a month. So we ask for each model's own lead days only, up
to 14 days per request and up to ``BATCH`` stations per request, keep a running total,
pace requests below the minute and hour limits, and stop before ``max_calls``.

One model per request, except where that would pay Open-Meteo's minimum of one call
per location for less: models with the same lead days whose request alone weighs less
than 1 (ICON-D2, GeoSphere, KNMI and DMI at D+1; the two ALADINs at D+1-2; the two
ARPEGEs at D+1-3) share a request (``groups``), which costs
``variables x models / 10`` per location instead of 1 per model. The answer has the
columns ``<variable>_previous_dayN_<model>`` with the same values as one-model requests
(checked live 2026-10-16); a model without data at a location is left out of that
location's answer, so such locations are asked again one model at a time.

The rain gauges only need precipitation: at most 5 lead days are 5 variables, so a
request of up to ``GAUGE_DAYS`` days still costs one call per location.
"""

from __future__ import annotations

import re
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
GAUGE_DAYS = 28  # precipitation only (<= 5 variables): 28 days cost one call per location
BATCH = 100  # stations per request
#: Weighted calls per location of a shared request at most (``groups``): with
#: ``BATCH`` stations a request stays at or below 500, under Open-Meteo's 600 a minute
MAX_GROUP_WEIGHT = 5.0
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


class NoDataError(ValueError):
    """Open-Meteo has no data of this model for (at least one of) the locations."""


class RunNotAvailableError(ValueError):
    """Single Runs API: one requested model has no such run (the whole request fails).

    ``model`` is the name Open-Meteo reports, which can differ from the requested id
    (``dwd_icon_eu_native`` for ``dwd_icon_eu``, ``ncep_gfs013`` for ``ncep_gfs_global``).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        match = re.search(r"Model: ([^,\s]+)", reason)
        self.model = match[1] if match else ""


class QuotaError(RuntimeError):
    """The call budget of this run, or Open-Meteo's daily limit, is used up.

    ``partial`` holds the rows fetched before stopping, so they can still be saved.
    """

    partial: pl.DataFrame = pl.DataFrame(schema=SCHEMA)


class UnavailableError(QuotaError):
    """Open-Meteo kept failing (server or network errors, unreadable answers) after retries.

    Handled like the daily limit: what was fetched is saved and the next run continues.
    """


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
        if weight > min(self.per_minute, self.per_hour):
            # no wait would ever make room; the caller must split the request
            raise ValueError(f"one request of {weight:g} calls is over the per-minute pace")
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


def windows(start: date, end: date, days: int = MAX_DAYS) -> Iterator[tuple[date, date]]:
    while start <= end:
        last = min(end, start + timedelta(days=days - 1))
        yield start, last
        start = last + timedelta(days=1)


def hourly_names(model: Model, variables: tuple[str, ...] = VARIABLES) -> list[str]:
    return [f"{var}_previous_day{n}" for n in model.lead_days for var in variables]


def parse(
    payload: list | dict,
    station_ids: list[str],
    model: Model,
    variables: tuple[str, ...] = VARIABLES,
) -> pl.DataFrame:
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
                        **{
                            var: hourly[f"{var}_previous_day{n}"] if var in variables else None
                            for var in VARIABLES
                        },
                    },
                    schema=SCHEMA,
                    strict=False,
                )
            )
    out = pl.concat(frames) if frames else pl.DataFrame(schema=SCHEMA)
    return out.filter(~pl.all_horizontal(pl.col(v).is_null() for v in VARIABLES))


def groups(
    models: list[Model], variables: tuple[str, ...] = VARIABLES, days: int = MAX_DAYS
) -> list[list[Model]]:
    """Models asked for in one request, in the order of ``models``: models with the
    same lead days that each weigh less than one call per location alone (Open-Meteo
    bills at least 1) share a request, up to ``MAX_GROUP_WEIGHT`` per location; every
    other model has a request of its own."""
    found: list[list[Model]] = []
    open_groups: dict[tuple[int, ...], list[Model]] = {}
    for model in models:
        alone = len(hourly_names(model, variables)) / 10 * max(1, days / MAX_DAYS)
        if alone >= 1:
            found.append([model])
            continue
        group = open_groups.get(model.lead_days)
        if group is not None and (len(group) + 1) * alone <= MAX_GROUP_WEIGHT:
            group.append(model)
            continue
        open_groups[model.lead_days] = [model]
        found.append(open_groups[model.lead_days])
    return found


def group_weight(
    locations: int, group: list[Model], variables: tuple[str, ...], days: int
) -> float:
    """Weighted calls of one request for ``group`` (models with the same lead days)."""
    return call_weight(locations, len(hourly_names(group[0], variables)) * len(group), days)


def parse_group(
    payload: list | dict,
    station_ids: list[str],
    models: list[Model],
    variables: tuple[str, ...] = VARIABLES,
) -> tuple[pl.DataFrame, dict[str, list[str]]]:
    """A several-model answer (columns ``<name>_<model>``) → ``(rows, missing)``.

    ``missing`` maps a model id to the stations whose answer has no columns of it:
    Open-Meteo leaves a model without data at a location out of that location's
    answer (and with one model left drops the suffix), so these are asked one by one.
    """
    results = payload if isinstance(payload, list) else [payload]
    if len(results) != len(station_ids):
        raise ValueError(f"asked for {len(station_ids)} locations, got {len(results)}")
    frames, missing = [pl.DataFrame(schema=SCHEMA)], {}
    for position, result in enumerate(results):
        station = station_ids[result.get("location_id", position)]
        hourly = result["hourly"]
        for model in models:
            names = hourly_names(model, variables)
            if not all(f"{name}_{model.id}" in hourly for name in names):
                missing.setdefault(model.id, []).append(station)
                continue
            own = {"time": hourly["time"], **{n: hourly[f"{n}_{model.id}"] for n in names}}
            frames.append(parse({"hourly": own}, [station], model, variables))
    return pl.concat(frames), missing


def request(
    client: httpx.Client, params: dict, sleep: Callable[[float], None], url: str = URL
) -> list | dict:
    """One Open-Meteo request (default: Previous Runs API); transient failures are
    retried after a pause.

    Retried: the per-minute/hour 429, server errors, network errors and an answer that is
    not JSON (seen once as an empty 200 in the middle of a backfill). If they persist,
    ``UnavailableError`` (a ``QuotaError``) stops the run cleanly so the next one resumes.
    """
    problem = ""
    for wait in (30, 60, 120, None):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError as exc:
            problem = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 429 and "daily" in response.text.lower():
                raise QuotaError(f"Open-Meteo: {_reason(response)}")
            if response.status_code == 400:
                reason = _reason(response)
                if "No data is available" in reason:
                    raise NoDataError(reason)
                if "model run is not available" in reason:
                    raise RunNotAvailableError(reason)
                raise ValueError(f"Open-Meteo: {reason}")
            if response.status_code == 429 or response.status_code >= 500:
                problem = f"HTTP {response.status_code} {_reason(response)}".strip()
            else:
                response.raise_for_status()
                try:
                    return response.json()
                except ValueError:
                    problem = f"HTTP {response.status_code} with a non-JSON answer: "
                    problem += repr(response.text[:80])
        if wait is None:
            break
        sleep(wait)
    raise UnavailableError(f"Open-Meteo unavailable after 4 attempts ({problem})")


def _reason(response: httpx.Response) -> str:
    try:
        return str(response.json().get("reason", response.text))
    except (ValueError, AttributeError):
        return response.text[:200]


def fetch_forecasts(
    client: httpx.Client,
    stations: pl.DataFrame,
    models: list[Model],
    start: date,
    end: date,
    budget: Budget,
    log: Callable[[str], None] = lambda _: None,
    uncovered: dict[str, set[str]] | None = None,
    variables: tuple[str, ...] = VARIABLES,
    max_days: int = MAX_DAYS,
) -> pl.DataFrame:
    """Forecasts for ``stations`` (id, lat, lon, elevation), ``start`` to ``end`` (UTC).

    ``variables`` not asked for are null; ``max_days`` is the longest request window.

    Stations a model has no data for (outside its real domain, e.g. ICON-D2 in the far
    east) are found by splitting the failing request, skipped, and added to
    ``uncovered[model id]``; stations already listed there are not asked for.
    """
    uncovered = {} if uncovered is None else uncovered
    frames = [pl.DataFrame(schema=SCHEMA)]
    rows = stations.select("id", "lat", "lon", "elevation").rows()
    first_hour = datetime.combine(start, datetime.min.time(), UTC)
    last_hour = datetime.combine(end, datetime.min.time(), UTC) + timedelta(hours=23)

    def collected() -> pl.DataFrame:
        return pl.concat(frames).filter(pl.col("time").is_between(first_hour, last_hour))

    try:
        ask = Ask(variables, max_days)
        _fetch_into(frames, client, rows, models, start, end, budget, log, uncovered, ask)
    except QuotaError as exc:
        exc.partial = collected()
        raise
    return collected()


@dataclass(frozen=True)
class Ask:
    variables: tuple[str, ...] = VARIABLES
    max_days: int = MAX_DAYS


def _fetch_into(frames, client, rows, models, start, end, budget, log, uncovered, ask) -> None:
    for group in groups(models, ask.variables, ask.max_days):
        if len(group) > 1:
            _fetch_group(frames, client, rows, group, start, end, budget, log, uncovered, ask)
            continue
        (model,) = group
        skip = uncovered.setdefault(model.id, set())
        first = max(start, model.archive_from)
        for window_start, window_end in windows(first, end, ask.max_days):
            todo = [r for r in rows if r[0] not in skip]
            for i in range(0, len(todo), BATCH):
                batch = todo[i : i + BATCH]
                frames.extend(
                    _fetch_batch(client, batch, model, window_start, window_end, budget, skip, ask)
                )
            log(f"{model.id} {window_start}..{window_end}: {budget.used:g} calls used")
            if skip:
                log(f"{model.id}: no data for {len(skip)} stations: {', '.join(sorted(skip))}")


def _fetch_group(frames, client, rows, group, start, end, budget, log, uncovered, ask) -> None:
    """Several models with the same lead days, one request per window and batch.

    Stations a model is known to have no data at, and stations whose answer lacks a
    model, are asked one model at a time (``_fetch_batch``, which records stations
    without data in ``uncovered``). Each model's rows start on its own first day, so
    the result is the same as asking every model alone."""
    skips = {m.id: uncovered.setdefault(m.id, set()) for m in group}
    starts = {m.id: max(start, m.archive_from) for m in group}
    for window_start, window_end in windows(min(starts.values()), end, ask.max_days):
        members = [m for m in group if starts[m.id] <= window_end]
        alone: dict[str, list] = {m.id: [] for m in members}
        shared = []
        for r in rows:
            if not any(r[0] in skips[m.id] for m in members):
                shared.append(r)
                continue
            for m in members:
                if r[0] not in skips[m.id]:
                    alone[m.id].append(r)
        for i in range(0, len(shared) if len(members) > 1 else 0, BATCH):
            batch = shared[i : i + BATCH]
            got, missing = _fetch_group_batch(
                client, batch, members, window_start, window_end, budget, ask
            )
            for m in members:
                first_hour = datetime.combine(starts[m.id], datetime.min.time(), UTC)
                frames.append(got.filter(pl.col("model") == m.id, pl.col("time") >= first_hour))
            by_id = {r[0]: r for r in batch}
            for model_id, stations in missing.items():
                alone[model_id] += [by_id[s] for s in stations]
        if len(members) == 1:
            alone[members[0].id] += shared
        for m in members:
            todo = alone[m.id]
            for i in range(0, len(todo), BATCH):
                batch = todo[i : i + BATCH]
                frames.extend(
                    _fetch_batch(
                        client,
                        batch,
                        m,
                        max(window_start, starts[m.id]),
                        window_end,
                        budget,
                        skips[m.id],
                        ask,
                    )
                )
        ids = ", ".join(m.id for m in members)
        log(f"{ids} {window_start}..{window_end}: {budget.used:g} calls used")
    for m in group:
        if skips[m.id]:
            log(
                f"{m.id}: no data for {len(skips[m.id])} stations: {', '.join(sorted(skips[m.id]))}"
            )


def _fetch_group_batch(client, batch, members, window_start, window_end, budget, ask):
    """One request for several models: ``(rows, missing)`` as from ``parse_group``. If
    Open-Meteo refuses it for missing data, all stations go to one-model requests."""
    days = (window_end - window_start).days + 1
    budget.spend(group_weight(len(batch), members, ask.variables, days))
    params = {
        **_location_params(batch),
        "hourly": ",".join(hourly_names(members[0], ask.variables)),
        "models": ",".join(m.id for m in members),
        "wind_speed_unit": "ms",
        "start_date": window_start.isoformat(),
        "end_date": window_end.isoformat(),
    }
    try:
        payload = request(client, params, budget.sleep)
    except NoDataError:
        return pl.DataFrame(schema=SCHEMA), {m.id: [r[0] for r in batch] for m in members}
    return parse_group(payload, [r[0] for r in batch], members, ask.variables)


def _location_params(batch) -> dict[str, str]:
    return {
        "latitude": ",".join(f"{r[1]:.5f}" for r in batch),
        "longitude": ",".join(f"{r[2]:.5f}" for r in batch),
        # "nan" makes Open-Meteo use its own terrain height (checked live)
        "elevation": ",".join("nan" if r[3] is None else f"{r[3]:.1f}" for r in batch),
    }


def _fetch_batch(client, batch, model, window_start, window_end, budget, skip, ask):
    days = (window_end - window_start).days + 1
    names = hourly_names(model, ask.variables)
    budget.spend(call_weight(len(batch), len(names), days))
    params = {
        **_location_params(batch),
        "hourly": ",".join(names),
        "models": model.id,
        "wind_speed_unit": "ms",
        "start_date": window_start.isoformat(),
        "end_date": window_end.isoformat(),
    }
    try:
        payload = request(client, params, budget.sleep)
    except NoDataError:
        if len(batch) == 1:
            skip.add(batch[0][0])
            return []
        half = len(batch) // 2
        return [
            *_fetch_batch(client, batch[:half], model, window_start, window_end, budget, skip, ask),
            *_fetch_batch(client, batch[half:], model, window_start, window_end, budget, skip, ask),
        ]
    return [parse(payload, [r[0] for r in batch], model, ask.variables)]


def estimate_calls(
    n_stations: int,
    models: list[Model],
    start: date,
    end: date,
    variables: tuple[str, ...] = VARIABLES,
    max_days: int = MAX_DAYS,
    grouped: bool = True,
) -> float:
    """Weighted Open-Meteo calls ``fetch_forecasts`` will use where every model has
    data at every station (``grouped=False``: one model per request, as before
    2026-10-16)."""
    total = 0.0
    for group in groups(models, variables, max_days) if grouped else [[m] for m in models]:
        starts = [max(start, m.archive_from) for m in group]
        for window_start, window_end in windows(min(starts), end, max_days):
            members = [m for m, s in zip(group, starts, strict=True) if s <= window_end]
            days = (window_end - window_start).days + 1
            if len(members) == 1:  # asked from its own first day, as in _fetch_group
                first = max(window_start, starts[group.index(members[0])])
                days = (window_end - first).days + 1
            for i in range(0, n_stations, BATCH):
                batch = min(BATCH, n_stations - i)
                total += group_weight(batch, members, variables, days)
    return total
