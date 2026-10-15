"""Single model runs at a fixed station subset, from Open-Meteo's Single Runs API.

The D+N scores use the Previous Runs API (``forecasts``), which blends runs. To verify
every model run by run and lead hour by lead hour (``leads``), ``mvd fetch-runs`` asks
the Single Runs API (``run=YYYY-MM-DDTHH:00``, the run's start) for each 00, 06, 12 and
18 UTC run: all enabled models in one request, temperature, precipitation, wind and
wind gusts at the ~100 stations of ``data/run-stations.csv`` (with their elevation), 121 hours from
the run's start (lead 0 to 120; lead 0 is not stored).

Cost (Open-Meteo's weighted calls, ``forecasts.call_weight``): per station
4 variables x 11 models / 10 = 4.4, so about 440 calls a run (330 before the gusts were
added on 2026-10-15); 121 hours are less than
14 days, so asking for the whole 5 days costs no more than one day.

If one requested model does not have the run, Open-Meteo fails the whole request
(HTTP 400 "The requested model run is not available. Model: X"): X is dropped and the
rest asked again. A model missing from a run older than ``PENDING_H`` hours is recorded
as a gap; a younger run is asked again for it later (models arrive at different times).

Progress is kept in ``runs-state.json`` (per run: models fetched and models missing),
so runs are fetched once and a run stopped by the call budget continues next time.
"Recent" runs (the last ``RECENT_H`` hours, at least ``MIN_AGE_H`` old) come first,
then "history" newest first back to ``HISTORY_FROM`` (not to the archive start
``models.RUNS_FROM``; see ``HISTORY_FROM``).

The call budget of a scheduled run can grow by the backfill's share when the backfill
has nothing to do (``handover_budget``).

See docs/data-sources.md#single-runs-mvd-fetch-runs.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files
from pathlib import Path

import httpx
import polars as pl

from meteoverdict import backfill, forecasts, partitions, store
from meteoverdict.models import VARIABLES as VERIFIED
from meteoverdict.models import Model

URL = "https://single-runs-api.open-meteo.com/v1/forecast"
RUN_HOURS = (0, 6, 12, 18)
MAX_LEAD_H = 120  # 5 days
FORECAST_HOURS = MAX_LEAD_H + 1  # Open-Meteo's answer starts at the run's start (lead 0)
#: A run is fetched once it is this old: every model has reached Open-Meteo by then
#: (checked 2026-10-13: at 8.4 h the 06 UTC run was complete for all 11 models).
MIN_AGE_H = 10
#: "Recent" runs: up to this old (missed schedules catch up), newer than history.
RECENT_H = 48
#: A model missing from a run younger than this is asked again later, not a gap yet.
PENDING_H = 24
BATCH = 100  # stations per request
#: Oldest run the history goes back to by default: the first run with ALADIN (both
#: domains) in Open-Meteo's Single Runs archive (models.yaml ``runs_from``). The archive
#: itself starts on ``models.RUNS_FROM`` (2026-04-02), but earlier runs lack the two
#: ALADIN models, so they barely enter the fair comparison (all models on a common set)
#: and would cost about 330 more runs (~89,000 calls). ``mvd fetch-runs --history-from``.
HISTORY_FROM = date(2026, 6, 23)

#: Model names in Open-Meteo's "run is not available" errors that differ from our id
#: (checked live 2026-10-13).
ALIASES = {
    "dwd_icon_d2_native": "dwd_icon_d2",
    "dwd_icon_eu_native": "dwd_icon_eu",
    "ncep_gfs013": "ncep_gfs_global",
    "ncep_gfs025": "ncep_gfs_global",
}

#: Variables asked for: the verified ones (``models.VARIABLES``) plus the wind gusts for
#: the farmers' event scores (``farm``). Open-Meteo's hourly ``wind_gusts_10m`` is the
#: maximum gust in the preceding hour (Open-Meteo docs, "Preceding hour max"). Runs
#: fetched before the gusts were added have them null.
VARIABLES = (*VERIFIED, "wind_gusts_10m")

KEYS = ["run", "model", "station_id", "lead_h"]  # sorted by run first: cheap run filters
SCHEMA = {
    "run": pl.Datetime("us", "UTC"),
    "model": pl.String,
    "station_id": pl.String,
    "lead_h": pl.Int16,
    "valid_time": pl.Datetime("us", "UTC"),
    "temperature_2m": pl.Float32,
    "precipitation": pl.Float32,
    "wind_speed_10m": pl.Float32,
    "wind_gusts_10m": pl.Float32,
}

STATE_NAME = "runs-state.json"
STATE_TAG = "runs-state"
STATIONS_FILE = "run-stations.csv"

RELEASE_NOTES = (
    "Single model runs at about 100 ČHMÚ stations, one Parquet file per month of run "
    "start (runs-YYYY-MM.parquet), written by `mvd fetch-runs` from the Open-Meteo "
    "Single Runs API (free, non-commercial tier). Forecasts: Open-Meteo.com, CC BY 4.0, "
    "from DWD, ECMWF, NOAA, Météo-France, GeoSphere Austria, ČHMÚ and the UK Met Office "
    "(CC BY-SA 4.0). Format: docs/data-sources.md#single-runs-mvd-fetch-runs. "
    "These files are published under CC BY-SA 4.0 "
    "(https://creativecommons.org/licenses/by-sa/4.0/); see docs/licensing.md."
)

# --- the station subset --------------------------------------------------------------

#: ČHMÚ elements (10-minute) behind our three variables: T, wind F, precipitation SRA10M.
ELEMENTS = ("T", "F", "SRA10M")
TOTAL_STATIONS = 100
MOUNTAIN_M = 800  # the "mountain" elevation class of `mvd stations`
#: Elevation weight in the spreading distance: 100 m height difference counts as 10 km.
KM_PER_M = 0.1


def _km(lat1, lon1, lat2, lon2) -> float:
    dx = (lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * 110.57
    return math.hypot(dx, dy)


def select_stations(
    stations: pl.DataFrame,
    meta2: pl.DataFrame,
    points: pl.DataFrame,
    total: int = TOTAL_STATIONS,
) -> pl.DataFrame:
    """The station subset, by a fixed rule (docs/data-sources.md#the-station-subset):

    1. every okres (by code): of its active stations with the most of ``ELEMENTS`` at
       10 minutes, the one closest to the okres's forecast point (``points``);
    2. every other full station (all three elements) above ``MOUNTAIN_M``;
    3. until ``total``: the full station farthest from all chosen ones, by distance
       with 100 m of height counted as 10 km (spreads stations and elevations).

    Ties go to the lower id, so the same inputs always give the same subset.
    """
    elements = (
        meta2.filter(pl.col("OBS_TYPE") == "10M", pl.col("EG_EL_ABBREVIATION").is_in(ELEMENTS))
        .group_by("WSI")
        .agg(pl.col("EG_EL_ABBREVIATION").n_unique().alias("elements"))
        .rename({"WSI": "id"})
    )
    candidates = (
        stations.filter(pl.col("active"), pl.col("okres_code").is_not_null())
        .join(elements, on="id")
        .sort("id")
    )
    rows = {r["id"]: r for r in candidates.iter_rows(named=True)}
    chosen: dict[str, str] = {}  # id -> reason, in selection order
    for code, _name, lat, lon in points.sort("code").select("code", "name", "lat", "lon").rows():
        here = [r for r in rows.values() if r["okres_code"] == code]
        if not here:
            continue
        best = min(here, key=lambda r: (-r["elements"], _km(lat, lon, r["lat"], r["lon"]), r["id"]))
        chosen[best["id"]] = "okres"
    full = [r for r in rows.values() if r["elements"] == len(ELEMENTS)]
    mountains = sorted(
        (r for r in full if (r["elevation"] or 0) > MOUNTAIN_M and r["id"] not in chosen),
        key=lambda r: (-r["elevation"], r["id"]),
    )
    for r in mountains:
        if len(chosen) >= total:
            break
        chosen[r["id"]] = "mountain"

    def distance(a: dict, b: dict) -> float:
        dz = ((a["elevation"] or 0) - (b["elevation"] or 0)) * KM_PER_M
        return math.hypot(_km(a["lat"], a["lon"], b["lat"], b["lon"]), dz)

    nearest = {
        r["id"]: min((distance(r, rows[c]) for c in chosen), default=math.inf)
        for r in full
        if r["id"] not in chosen
    }
    while len(chosen) < total and nearest:
        pick = min(nearest, key=lambda i: (-nearest[i], i))
        chosen[pick] = "spread"
        del nearest[pick]
        for i in nearest:
            nearest[i] = min(nearest[i], distance(rows[i], rows[pick]))
    order = {station: n for n, station in enumerate(chosen)}
    columns = ["id", "name", "lat", "lon", "elevation", "okres_code", "okres", "kraj_code"]
    return (
        candidates.filter(pl.col("id").is_in(list(chosen)))
        .with_columns(
            pl.col("id").replace_strict(chosen).alias("reason"),
            pl.col("id").replace_strict(order, return_dtype=pl.Int32).alias("_order"),
        )
        .sort("_order")
        .select(*columns, "elevation_class", "elements", "reason")
    )


def load_stations(path: Path | None = None) -> pl.DataFrame:
    """The committed station subset (``src/meteoverdict/data/run-stations.csv``)."""
    source = path or files("meteoverdict").joinpath("data", STATIONS_FILE)
    with source.open("rb") as f:
        return pl.read_csv(
            f.read(),
            schema_overrides={
                "id": pl.String,
                "lat": pl.Float64,
                "lon": pl.Float64,
                "elevation": pl.Float64,
            },
        )


# --- which runs ----------------------------------------------------------------------


def key(run: datetime) -> str:
    return f"{run:%Y%m%d%H}"


def parse_run(text: str) -> datetime:
    """``YYYY-MM-DDTHH`` (or ``YYYYMMDDHH``) → the run time in UTC; only 00/06/12/18."""
    for pattern in ("%Y-%m-%dT%H", "%Y-%m-%dT%H:%M", "%Y%m%d%H"):
        try:
            run = datetime.strptime(text, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
        if run.hour in RUN_HOURS and run.minute == 0:
            return run
        break
    raise ValueError(f"not a run time (YYYY-MM-DDTHH with HH 00, 06, 12 or 18): {text}")


def _latest_run(time: datetime) -> datetime:
    return time.replace(hour=time.hour // 6 * 6, minute=0, second=0, microsecond=0)


def recent_runs(now: datetime) -> list[datetime]:
    """Runs from ``RECENT_H`` to ``MIN_AGE_H`` hours ago, newest first."""
    run = _latest_run(now - timedelta(hours=MIN_AGE_H))
    found = []
    while now - run <= timedelta(hours=RECENT_H):
        found.append(run)
        run -= timedelta(hours=6)
    return found


def history_runs(now: datetime, first: date = HISTORY_FROM) -> list[datetime]:
    """Runs older than the recent ones, newest first, back to ``first`` 00 UTC."""
    recent = recent_runs(now)
    run = (recent[-1] if recent else _latest_run(now)) - timedelta(hours=6)
    start = datetime.combine(first, datetime.min.time(), UTC)
    found = []
    while run >= start:
        found.append(run)
        run -= timedelta(hours=6)
    return found


def wanted(models: list[Model], run: datetime) -> list[Model]:
    """Models whose Single Runs archive covers ``run`` (``runs_from``)."""
    return [m for m in models if m.single_runs_from <= run.date()]


# --- progress ------------------------------------------------------------------------


@dataclass
class State:
    path: Path
    #: run key (YYYYMMDDHH) -> model ids fetched / missing at Open-Meteo for good
    fetched: dict[str, set[str]] = field(default_factory=dict)
    missing: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> State:
        if not path.exists():
            return cls(path)
        doc = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            path,
            {k: set(v) for k, v in doc.get("fetched", {}).items()},
            {k: set(v) for k, v in doc.get("missing", {}).items()},
        )

    def save(self) -> None:
        doc = {
            "fetched": {k: sorted(v) for k, v in sorted(self.fetched.items())},
            "missing": {k: sorted(v) for k, v in sorted(self.missing.items()) if v},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(doc, indent=0) + "\n", encoding="utf-8")

    def todo(self, run: datetime, models: list[Model]) -> list[Model]:
        done = self.fetched.get(key(run), set()) | self.missing.get(key(run), set())
        return [m for m in models if m.id not in done]


# --- requests ------------------------------------------------------------------------


def request_weight(locations: int, models: int, variables: int = len(VARIABLES)) -> float:
    """Weighted calls of one request (121 hours count as 6 days, under 14)."""
    return forecasts.call_weight(locations, variables * models, math.ceil(FORECAST_HOURS / 24))


def run_cost(n_stations: int, n_models: int) -> float:
    """Weighted calls of one run for all stations (when every model has it)."""
    return sum(
        request_weight(min(BATCH, n_stations - i), n_models) for i in range(0, n_stations, BATCH)
    )


def parse(payload: list | dict, station_ids: list[str], models: list[Model], run: datetime):
    """One Single Runs answer → rows per model, station and lead hour 1…``MAX_LEAD_H``.

    Columns are ``<variable>_<model>``. A model without data at a location is left out
    of that location's answer (checked: ICON-D2 in the far east); with one model left
    the names lose their suffix, so they are read only when one model was asked for.
    """
    results = payload if isinstance(payload, list) else [payload]
    if len(results) != len(station_ids):
        raise ValueError(f"asked for {len(station_ids)} locations, got {len(results)}")
    frames = []
    for position, result in enumerate(results):
        station = station_ids[result.get("location_id", position)]
        hourly = result["hourly"]
        times = pl.Series(hourly["time"]).str.to_datetime("%Y-%m-%dT%H:%M", time_zone="UTC")
        for model in models:
            values = {var: hourly.get(f"{var}_{model.id}") for var in VARIABLES}
            if len(models) == 1 and all(v is None for v in values.values()):
                values = {var: hourly.get(var) for var in VARIABLES}
            if all(v is None for v in values.values()):
                continue
            frames.append(
                pl.DataFrame(
                    {
                        "run": [run] * len(times),
                        "model": model.id,
                        "station_id": station,
                        "lead_h": ((times - run).dt.total_hours()).cast(pl.Int16),
                        "valid_time": times,
                        **{
                            var: v if v is not None else [None] * len(times)
                            for var, v in values.items()
                        },
                    },
                    schema=SCHEMA,
                    strict=False,
                )
            )
    if not frames:
        return pl.DataFrame(schema=SCHEMA)
    return pl.concat(frames).filter(
        pl.col("lead_h").is_between(1, MAX_LEAD_H),
        ~pl.all_horizontal(pl.col(v).is_null() for v in VARIABLES),
    )


def _match(reported: str, todo: list[Model]) -> Model | None:
    name = ALIASES.get(reported, reported)
    for model in todo:
        if model.id == name:
            return model
    found = [m for m in todo if name.startswith(m.id) or m.id.startswith(name)]
    return found[0] if len(found) == 1 else None


def _fetch(client, rows, run, todo, budget, log) -> list[pl.DataFrame]:
    frames = []
    for i in range(0, len(rows), BATCH):
        frames += _fetch_batch(client, rows[i : i + BATCH], run, todo, budget, log)
    return frames


def _fetch_batch(client, batch, run, todo, budget, log) -> list[pl.DataFrame]:
    budget.spend(request_weight(len(batch), len(todo)))
    params = {
        "latitude": ",".join(f"{r[1]:.5f}" for r in batch),
        "longitude": ",".join(f"{r[2]:.5f}" for r in batch),
        # "nan" makes Open-Meteo use its own terrain height
        "elevation": ",".join("nan" if r[3] is None else f"{r[3]:.1f}" for r in batch),
        "hourly": ",".join(VARIABLES),
        "models": ",".join(m.id for m in todo),
        "run": f"{run:%Y-%m-%dT%H:%M}",
        "forecast_hours": FORECAST_HOURS,
        "wind_speed_unit": "ms",
    }
    try:
        payload = forecasts.request(client, params, budget.sleep, url=URL)
    except forecasts.NoDataError:
        # only a one-model request fails like this (several models: the model is left
        # out of that location's answer); find the stations by splitting
        if len(batch) == 1:
            log(f"{todo[0].id}: no data at {batch[0][0]}")
            return []
        half = len(batch) // 2
        return [
            *_fetch_batch(client, batch[:half], run, todo, budget, log),
            *_fetch_batch(client, batch[half:], run, todo, budget, log),
        ]
    return [parse(payload, [r[0] for r in batch], todo, run)]


def fetch_run(
    client: httpx.Client,
    stations: pl.DataFrame,
    run: datetime,
    models: list[Model],
    budget: forecasts.Budget,
    log: Callable[[str], None] = lambda _: None,
) -> tuple[pl.DataFrame, set[str], set[str]]:
    """One run of ``models`` at ``stations`` (id, lat, lon, elevation).

    Returns the rows, the models fetched and the models Open-Meteo does not have for
    this run. Raises ``QuotaError`` (nothing of the run kept) and ``ValueError`` for an
    error that names no model we asked for.
    """
    rows = stations.select("id", "lat", "lon", "elevation").rows()
    todo, unavailable = list(models), set()
    while todo:
        try:
            frames = _fetch(client, rows, run, todo, budget, log)
        except forecasts.RunNotAvailableError as exc:
            model = _match(exc.model, todo)
            if model is None:
                raise ValueError(f"cannot tell which model is meant: {exc}") from exc
            todo.remove(model)
            unavailable.add(model.id)
            continue
        table = pl.concat([pl.DataFrame(schema=SCHEMA), *frames])
        return table, {m.id for m in todo}, unavailable
    return pl.DataFrame(schema=SCHEMA), set(), unavailable


# --- release storage -----------------------------------------------------------------


def release_tag(month: str) -> str:
    return f"runs-{month}"


def asset_name(month: str) -> str:
    return f"runs-{month}.parquet"


class RunsSync:
    """Month files ``runs/YYYY-MM.parquet`` as ``runs-YYYY-MM.parquet`` in the releases
    ``runs-YYYY-MM``, the state as ``runs-state.json`` in ``runs-state``; each asset's
    label is the file's SHA-256, so unchanged files are skipped both ways."""

    def __init__(self, releases, data_dir: Path, log=lambda _: None) -> None:
        self.store, self.data_dir, self.log = releases, data_dir, log

    def pull_state(self) -> None:
        if STATE_NAME in self.store.assets(STATE_TAG):
            self.store.download(STATE_TAG, STATE_NAME, self.data_dir / STATE_NAME)

    def pull(self, months: list[str]) -> list[str]:
        done = []
        for month in months:
            asset = self.store.assets(release_tag(month)).get(asset_name(month))
            path = self.data_dir / "runs" / f"{month}.parquet"
            if asset is None or (path.exists() and store.sha256(path) == asset.get("label")):
                continue
            self.store.download(release_tag(month), asset_name(month), path)
            self.log(f"downloaded {asset_name(month)}")
            done.append(month)
        return done

    def push(self, months: list[str]) -> None:
        for month in months:
            path = self.data_dir / "runs" / f"{month}.parquet"
            if not path.exists():
                continue
            digest = store.sha256(path)
            tag, name = release_tag(month), asset_name(month)
            if self.store.assets(tag).get(name, {}).get("label") != digest:
                self.store.put(tag, name, path, label=digest)
                self.log(f"uploaded {name} ({path.stat().st_size // 1024} KB)")
        state = self.data_dir / STATE_NAME
        if state.exists():
            self.store.put(STATE_TAG, STATE_NAME, state, label=store.sha256(state))


# --- the collection ------------------------------------------------------------------


@dataclass
class Result:
    runs: list[str] = field(default_factory=list)  # run keys fetched (fully or partly)
    gaps: dict[str, set[str]] = field(default_factory=dict)  # run key -> models missing
    failed: list[str] = field(default_factory=list)
    stopped: str = ""  # why the collection stopped early, if it did
    #: weighted calls per run key, as spent
    calls: dict[str, float] = field(default_factory=dict)


def collect(
    client: httpx.Client,
    stations: pl.DataFrame,
    models: list[Model],
    data_dir: Path,
    budget: forecasts.Budget,
    now: datetime,
    runs: list[datetime] | None = None,
    modes: tuple[str, ...] = ("recent", "history"),
    sync: RunsSync | None = None,
    log: Callable[[str], None] = lambda _: None,
    first: date = HISTORY_FROM,
) -> Result:
    """Fetch the runs not done yet: ``runs`` if given, else the recent ones, then the
    history (newest first), until done or the call budget is used up."""
    state = State.load(data_dir / STATE_NAME)
    if runs is None:
        runs = [
            *(recent_runs(now) if "recent" in modes else []),
            *(history_runs(now, first) if "history" in modes else []),
        ]
    result, pulled = Result(), set()
    for run in runs:
        todo = state.todo(run, wanted(models, run))
        if not todo:
            continue
        month = f"{run:%Y-%m}"
        if sync and month not in pulled:  # merge into the stored month, not over it
            sync.pull([month])
            pulled.add(month)
        before = budget.used
        try:
            table, fetched, unavailable = fetch_run(client, stations, run, todo, budget, log)
        except forecasts.QuotaError as exc:
            result.stopped = str(exc)
            break
        except ValueError as exc:
            log(f"run {run:%Y-%m-%d %H} UTC failed: {exc}")
            result.failed.append(key(run))
            continue
        finally:
            result.calls[key(run)] = result.calls.get(key(run), 0) + budget.used - before
        if table.height:
            partitions.write_monthly(table, data_dir / "runs", KEYS, "run")
        k = key(run)
        state.fetched.setdefault(k, set()).update(fetched)
        if unavailable and now - run >= timedelta(hours=PENDING_H):
            state.missing.setdefault(k, set()).update(unavailable)
        state.save()
        if sync:
            sync.push([month])
        result.runs.append(k)
        if unavailable:
            result.gaps[k] = unavailable
        later = "" if now - run >= timedelta(hours=PENDING_H) else " (asked again later)"
        log(
            f"run {run:%Y-%m-%d %H} UTC: {len(fetched)} models, {table.height:,} rows, "
            f"{result.calls[k]:g} calls"
            + (f"; not available: {', '.join(sorted(unavailable))}{later}" if unavailable else "")
        )
    return result


def progress(data_dir: Path, models: list[Model], now: datetime, first: date = HISTORY_FROM):
    """``(complete, all)`` runs from ``first`` to the newest recent run."""
    state = State.load(data_dir / STATE_NAME)
    every = [*recent_runs(now), *history_runs(now, first)]
    done = sum(not state.todo(r, wanted(models, r)) for r in every)
    return done, len(every)


def summary(
    result: Result,
    calls: float,
    data_dir: Path,
    models,
    now: datetime,
    first: date = HISTORY_FROM,
    budget_note: str = "",
) -> str:
    """Markdown for the workflow's job summary."""
    done, every = progress(data_dir, models, now, first)
    lines = [
        "## Single runs",
        "",
        f"- This run: {len(result.runs)} model runs fetched, {calls:g} Open-Meteo calls",
        f"- Progress: {done} of {every} runs complete since {first}",
    ]
    if budget_note:
        lines.append(f"- Budget: {budget_note}")
    if result.gaps:
        gaps = "; ".join(f"{k}: {', '.join(sorted(v))}" for k, v in sorted(result.gaps.items()))
        lines.append(f"- Not available at Open-Meteo: {gaps}")
    if result.failed:
        lines.append(f"- Failed: {', '.join(result.failed)}")
    if result.stopped:
        lines.append(f"- Stopped: {result.stopped} (the next run continues)")
    return "\n".join(lines) + "\n"


# --- the budget ----------------------------------------------------------------------


def handover_budget(
    base: float,
    extra: float,
    read_state: Callable[[], backfill.State],
    models: list[Model],
    backfill_from: date,
    today: date,
) -> tuple[float, str]:
    """``(calls, why)``: ``base`` plus ``extra`` when the D+N backfill is idle
    (``backfill.handover``), else ``base``; also ``base`` when its state cannot be read.

    ``read_state`` gives the backfill's state (from the release ``data-state``).
    """
    if extra <= 0:
        return base, f"{base:g} calls (normal)"
    normal = f"{base:g} calls (normal; extra {extra:g} not used"
    try:
        state = read_state()
        idle, why = backfill.handover(models, backfill_from, today, state)
    except Exception as exc:  # anything: the normal budget is always safe
        return base, f"{normal}: backfill state not readable: {exc})"
    if not idle:
        return base, f"{normal}: {why})"
    return base + extra, f"{base + extra:g} calls ({base:g} normal + {extra:g} extra: {why})"
