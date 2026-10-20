"""Single model runs at a fixed station subset: from Open-Meteo's open-data bucket on AWS
(``bucket``), with Open-Meteo's Single Runs API as the fallback and for the history.

The D+N scores use the Previous Runs API (``forecasts``), which blends runs. To verify
every model run by run and lead hour by lead hour (``leads``), every 00, 06, 12 and 18
UTC run of every enabled model is stored at the ~100 stations of ``data/run-stations.csv``:
temperature, precipitation, wind and wind gusts, lead 1 to 120 hours, at the station's
elevation, **at the model's native output steps** (``native``); since 2026-10-19 also the
further variables of a full forecast (``EXTRA_VARIABLES``: humidity, dew point, pressure,
wind direction, radiation, cloud cover, sunshine, snow, surface temperature, CAPE,
visibility), from the bucket only.

**Sources** (``source`` column), in this order:

1. **the bucket** (``bucket.collect``, no API calls; ``mvd fetch-runs``): every run within
   the bucket's window (``BUCKET_DAYS``: it keeps per-run files for about three months),
   so each execution also catches up any run not stored yet before it ages out;
2. **the Single Runs API** (``collect``), within a call budget, newest first:

   - ``mvd fetch-runs``: a model-run the bucket does not have complete once it is
     ``BUCKET_FINAL_H`` old (``State.bucket_missing``: the fallback), and the runs older
     than the bucket's window but in the month it starts in (``history_edge``);
   - ``mvd backfill`` (``backfill.RunsHistory``): every older run, back to each model's
     start in the Single Runs archive (``Model.has_single_run``), together with the D+N
     window of the same days, newest first. The two never write the same month file.

The API asks ``run=YYYY-MM-DDTHH:00`` (the run's start) for all models still to fetch in
one request. Cost (Open-Meteo's weighted calls, ``forecasts.call_weight``): per station
max(1, variables x models / 10), e.g. 4 x 19 / 10 = 7.6, so about 760 calls a run of all
models (720 for the 06 and 18 UTC runs, which GEM Global does not have:
``Model.run_hours``), and 100 for one or two models (at least one call per station);
121 hours are less than 14 days, so the whole 5 days cost no more than one day. One
request stays at or below ``MAX_REQUEST`` calls (Open-Meteo allows 600 a minute), so the
stations of a run are split into equal batches. The API fills every hour (interpolated
between native steps); its rows are stored at the native steps too (``native``).

If one requested model does not have the run, Open-Meteo fails the whole request
(HTTP 400 "The requested model run is not available. Model: X"): X is dropped and the
rest asked again. A model missing from a run older than ``PENDING_H`` hours is recorded
as a gap.

Progress is kept in ``runs-state.json`` (per run: models fetched, models missing for
good, models missing in the bucket), so a model-run is stored once and a collection
stopped by the call budget or the time limit continues next time. Both workflows that
write it (``runs.yml`` and ``backfill.yml``) merge it with the released one before they
upload it (``RunsSync.push``), so neither loses what the other recorded meanwhile.

See docs/data-sources.md#single-runs-mvd-fetch-runs.
"""

from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files
from pathlib import Path

import httpx
import polars as pl

from meteoverdict import forecasts, partitions, store
from meteoverdict.models import RUNS_FROM, Model
from meteoverdict.models import VARIABLES as VERIFIED

URL = "https://single-runs-api.open-meteo.com/v1/forecast"
RUN_HOURS = (0, 6, 12, 18)
MAX_LEAD_H = 120  # 5 days
FORECAST_HOURS = MAX_LEAD_H + 1  # Open-Meteo's answer starts at the run's start (lead 0)
#: Every model of a run has reached Open-Meteo (API and bucket) when it is this old
#: (latest seen 2026-07..10: 13.4 h, JMA GSM; most within 10 h); the outlook's gusts
#: count on runs about this old
MIN_AGE_H = 10
#: Runs within this many days are read from the bucket (it keeps them ~93 days)
BUCKET_DAYS = 90
#: Runs younger than this are not looked for in the bucket (the first models arrive
#: after ~2 h)
BUCKET_MIN_AGE_H = 1
#: A model-run still incomplete in the bucket at this age is missing there for good and
#: asked from the API instead
BUCKET_FINAL_H = 24
#: A model missing from a run younger than this is asked again later, not a gap yet.
PENDING_H = 24
BATCH = 100  # stations per request at most
#: Weighted calls per request at most: below Open-Meteo's 600 a minute and the pace of
#: ``forecasts.Budget`` (550 a minute)
MAX_REQUEST = 500
#: The first run with ALADIN (both domains) in Open-Meteo's Single Runs archive
#: (models.yaml ``runs_from``): the default start of the lead-band ranking's "all"
#: window (``mvd leads``). Older runs lack ALADIN, which the 80 % coverage rule would
#: then leave out of that window.
ALADIN_FROM = date(2026, 6, 23)

#: Model names in Open-Meteo's "run is not available" errors that differ from our id
#: (checked live 2026-10-13).
ALIASES = {
    "dwd_icon_d2_native": "dwd_icon_d2",
    "dwd_icon_eu_native": "dwd_icon_eu",
    "ncep_gfs013": "ncep_gfs_global",
    "ncep_gfs025": "ncep_gfs_global",
    "cmc_gem_gdps_15km": "gem_global",  # checked live 2026-10-15
    "meteofrance_arpege_world025": "meteofrance_arpege_world",  # checked live 2026-10-15
}

#: Variables asked for: the verified ones (``models.VARIABLES``) plus the wind gusts for
#: the farmers' event scores (``farm``). Open-Meteo's hourly ``wind_gusts_10m`` is the
#: maximum gust in the preceding hour (Open-Meteo docs, "Preceding hour max"). Runs
#: fetched before the gusts were added have them null.
VARIABLES = (*VERIFIED, "wind_gusts_10m")
#: Further variables of a full forecast (since 2026-10-19), read from the bucket only
#: (``bucket.EXTRA``): the API fallback does not ask for them (its call weight grows with
#: the variables), so its rows have them null, as do rows stored before. Units as in
#: Open-Meteo's API: %, °C, hPa, ° (direction the wind comes from), W/m² (mean over the
#: preceding step), s (sunshine in the preceding step), cm (snowfall in the preceding
#: step), m (snow depth), mm (snow water equivalent), J/kg, m (visibility).
EXTRA_VARIABLES = (
    "relative_humidity_2m",
    "dew_point_2m",
    "pressure_msl",
    "wind_direction_10m",
    "shortwave_radiation",
    "cloud_cover",
    "cloud_cover_low",
    "sunshine_duration",
    "snowfall",
    "snow_depth",
    "snow_depth_water_equivalent",
    "surface_temperature",
    "cape",
    "visibility",
)

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
    **{v: pl.Float32 for v in EXTRA_VARIABLES},
    #: "bucket" (Open-Meteo's open-data bucket) or "api" (Single Runs API); null in rows
    #: stored before 2026-10-17 (API, every hour filled: ``native`` converts them)
    "source": pl.String,
}
SOURCES = ("bucket", "api")
#: An API answer before ``native`` (every hour filled, no source yet, no further variables)
HOURLY_SCHEMA = {k: v for k, v in SCHEMA.items() if k != "source" and k not in EXTRA_VARIABLES}

STATE_NAME = "runs-state.json"
STATE_TAG = "runs-state"
STATIONS_FILE = "run-stations.csv"

RELEASE_NOTES = (
    "Single model runs at about 100 ČHMÚ stations, one Parquet file per month of run "
    "start (runs-YYYY-MM.parquet), written by `mvd fetch-runs` at each model's native "
    "output steps: from Open-Meteo's open-data bucket on AWS (s3://openmeteo, AWS "
    "Registry of Open Data; column source = bucket) and, where the bucket lacks a run, "
    "from the Open-Meteo Single Runs API (free, non-commercial tier; source = api). "
    "Weather data by Open-Meteo.com, CC BY 4.0 "
    "(https://creativecommons.org/licenses/by/4.0/), from ČHMÚ, DWD, ECMWF, NOAA, "
    "Météo-France, GeoSphere Austria, KNMI, DMI, Environment and Climate Change Canada "
    "(Data Server End-use Licence), the Japan Meteorological Agency, the China "
    "Meteorological Administration and the UK Met Office (CC BY-SA 4.0); without "
    "warranty, Open-Meteo is not affiliated with these services. Format: "
    "docs/data-sources.md#single-runs-mvd-fetch-runs. These files are published under "
    "CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/); see "
    "docs/licensing.md."
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
       with 100 m of height counted as 10 km (spreads stations and elevations);
    4. beyond ``total``: every other active station that measures temperature (``T`` at
       10 minutes; ``temperature``, since 2026-10-20), so every temperature station has
       the single runs. Only steps 1-3 are asked from the API (``api_stations``); the
       bucket, which costs no quota, is read at all.

    Ties go to the lower id, so the same inputs always give the same subset.
    """
    elements = (
        meta2.filter(pl.col("OBS_TYPE") == "10M", pl.col("EG_EL_ABBREVIATION").is_in(ELEMENTS))
        .group_by("WSI")
        .agg(pl.col("EG_EL_ABBREVIATION").n_unique().alias("elements"))
        .rename({"WSI": "id"})
    )
    with_t = set(
        meta2.filter(pl.col("OBS_TYPE") == "10M", pl.col("EG_EL_ABBREVIATION") == "T")["WSI"]
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
    for r in rows.values():
        if r["id"] in with_t and r["id"] not in chosen:
            chosen[r["id"]] = "temperature"
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


def api_stations(stations: pl.DataFrame) -> pl.DataFrame:
    """The stations the Single Runs API is asked at: the rule's ``TOTAL_STATIONS`` (steps
    1-3 of ``select_stations``), not the further temperature stations, which come from
    the bucket only (a run of all models at all ~300 would cost three times the calls)."""
    if "reason" not in stations.columns:
        return stations
    return stations.filter(pl.col("reason") != "temperature")


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


#: a model is verified run by run (``leads``, ``farm``) when it has at least this share
#: of the runs in the period (as ``aggregate.MIN_COVERAGE`` for the D+N scores)
MIN_COVERAGE = 0.8


def coverage(forecasts: pl.LazyFrame | pl.DataFrame) -> pl.DataFrame:
    """``model``, ``runs`` (its runs with a value), ``of`` (runs of any model at the run
    hours this model has: GEM Global has no 06 and 18 UTC runs), ``coverage`` and
    ``covered`` (at least ``MIN_COVERAGE``, or no model reaches it).

    The run-by-run fair sets keep only the runs every model compared has; a model added
    recently (its single runs fetched only since) would otherwise cut them to its days."""
    frame = forecasts.lazy().select("model", "run").unique()
    hour = pl.col("run").dt.hour().alias("run_hour")
    per_hour = frame.group_by(hour).agg(pl.col("run").n_unique().alias("of"))
    return (
        frame.with_columns(hour)
        .group_by("model", "run_hour")
        .agg(pl.col("run").n_unique().alias("runs"))
        .join(per_hour, on="run_hour")
        .group_by("model")
        .agg(pl.col("runs").sum(), pl.col("of").sum())
        .with_columns((pl.col("runs") / pl.col("of")).alias("coverage"))
        .with_columns((pl.col("coverage") >= MIN_COVERAGE).alias("covered"))
        .with_columns(pl.col("covered") | ~pl.col("covered").any())
        .sort("model")
        .collect()
    )


def short_records(cover: pl.DataFrame) -> dict[str, dict]:
    """``{model: {"runs", "of", "coverage"}}`` of the models left out (``coverage``)."""
    return {
        r["model"]: {"runs": r["runs"], "of": r["of"], "coverage": round(r["coverage"], 3)}
        for r in cover.filter(~pl.col("covered")).iter_rows(named=True)
    }


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


def _runs_between(newest: datetime, oldest: datetime) -> list[datetime]:
    """Run times from ``newest`` back to ``oldest`` (both included), newest first."""
    found, run = [], newest
    while run >= oldest:
        found.append(run)
        run -= timedelta(hours=6)
    return found


def bucket_start(now: datetime) -> datetime:
    """The oldest run read from the bucket: ``BUCKET_DAYS`` back (rounded up to a run)."""
    edge = now - timedelta(days=BUCKET_DAYS)
    run = _latest_run(edge)
    return run if run == edge else run + timedelta(hours=6)


def bucket_runs(now: datetime) -> list[datetime]:
    """Runs to look for in the bucket: at least ``BUCKET_MIN_AGE_H`` old and from
    ``bucket_start`` on, newest first."""
    return _runs_between(_latest_run(now - timedelta(hours=BUCKET_MIN_AGE_H)), bucket_start(now))


def history_edge(now: datetime) -> datetime:
    """The first run of the month the bucket's window starts in. ``mvd fetch-runs`` asks
    the API for runs from here on (the bucket's gaps and the few runs between here and
    the bucket's window); every older run is the D+N backfill's (``backfill.RunsHistory``).
    So the two workflows never write the same month file."""
    start = bucket_start(now)
    return start.replace(day=1, hour=0)


def history_start(models: list[Model]) -> date:
    """The oldest day of any model's runs in the Single Runs archive."""
    return min((m.single_runs_from for m in models), default=RUNS_FROM)


def api_runs(now: datetime) -> list[datetime]:
    """Runs ``mvd fetch-runs`` may ask the Single Runs API for, newest first: at least
    ``BUCKET_FINAL_H`` old (younger ones may still reach the bucket), back to
    ``history_edge``. Within the bucket's window only for the models missing there
    (``State.api_todo``)."""
    return _runs_between(_latest_run(now - timedelta(hours=BUCKET_FINAL_H)), history_edge(now))


def day_runs(start: date, end: date) -> list[datetime]:
    """Every 00, 06, 12 and 18 UTC run of the days ``start`` … ``end``, newest first."""
    first = datetime.combine(start, datetime.min.time(), UTC)
    return _runs_between(datetime.combine(end, datetime.min.time(), UTC).replace(hour=18), first)


def wanted(models: list[Model], run: datetime) -> list[Model]:
    """Models whose Single Runs archive covers ``run`` (``Model.has_single_run``)."""
    return [m for m in models if m.has_single_run(run.date(), run.hour)]


# --- progress ------------------------------------------------------------------------


@dataclass
class State:
    path: Path
    #: run key (YYYYMMDDHH) -> model ids stored (from the bucket or the API)
    fetched: dict[str, set[str]] = field(default_factory=dict)
    #: run key -> model ids Open-Meteo's API does not have (gaps for good)
    missing: dict[str, set[str]] = field(default_factory=dict)
    #: run key -> model ids not complete in the bucket once ``BUCKET_FINAL_H`` old: the
    #: API is asked for them
    bucket_missing: dict[str, set[str]] = field(default_factory=dict)
    #: run key -> model ids whose further variables (``EXTRA_VARIABLES``) are settled:
    #: read from the bucket, or not to be had there any more. A stored model-run not
    #: in it is read from the bucket again while the bucket keeps it (``extra_todo``)
    extra: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> State:
        if not path.exists():
            return cls(path)
        doc = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            path,
            {k: set(v) for k, v in doc.get("fetched", {}).items()},
            {k: set(v) for k, v in doc.get("missing", {}).items()},
            {k: set(v) for k, v in doc.get("bucket_missing", {}).items()},
            {k: set(v) for k, v in doc.get("extra", {}).items()},
        )

    def save(self) -> None:
        doc = {
            "fetched": {k: sorted(v) for k, v in sorted(self.fetched.items())},
            "missing": {k: sorted(v) for k, v in sorted(self.missing.items()) if v},
            "bucket_missing": {k: sorted(v) for k, v in sorted(self.bucket_missing.items()) if v},
            "extra": {k: sorted(v) for k, v in sorted(self.extra.items()) if v},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(doc, indent=0) + "\n", encoding="utf-8")

    def merge(self, other: State) -> None:
        """Add what ``other`` recorded (another workflow's progress): nothing recorded
        is ever taken back, so the union is right."""
        for mine, theirs in (
            (self.fetched, other.fetched),
            (self.missing, other.missing),
            (self.bucket_missing, other.bucket_missing),
            (self.extra, other.extra),
        ):
            for k, ids in theirs.items():
                mine.setdefault(k, set()).update(ids)

    def todo(self, run: datetime, models: list[Model]) -> list[Model]:
        """Models of ``run`` not stored and not a gap for good."""
        done = self.fetched.get(key(run), set()) | self.missing.get(key(run), set())
        return [m for m in models if m.id not in done]

    def bucket_todo(self, run: datetime, models: list[Model]) -> list[Model]:
        """Models of ``run`` to look for in the bucket."""
        gone = self.bucket_missing.get(key(run), set())
        return [m for m in self.todo(run, models) if m.id not in gone]

    def extra_todo(self, run: datetime, models: list[Model]) -> list[Model]:
        """Models of ``run`` stored without their further variables settled: read from
        the bucket again (the whole model-run, which replaces the stored one)."""
        stored = self.fetched.get(key(run), set()) - self.extra.get(key(run), set())
        return [m for m in models if m.id in stored]

    def api_todo(self, run: datetime, models: list[Model], now: datetime) -> list[Model]:
        """Models of ``run`` to ask the API for: within the bucket's window only those
        missing there, older runs all not stored yet."""
        todo = self.todo(run, models)
        if run < bucket_start(now):
            return todo
        gone = self.bucket_missing.get(key(run), set())
        return [m for m in todo if m.id in gone]


# --- requests ------------------------------------------------------------------------


def request_weight(locations: int, models: int, variables: int = len(VARIABLES)) -> float:
    """Weighted calls of one request (121 hours count as 6 days, under 14)."""
    return forecasts.call_weight(locations, variables * models, math.ceil(FORECAST_HOURS / 24))


def batches(n_stations: int, n_models: int) -> list[int]:
    """Stations per request: equal parts of at most ``BATCH`` stations and
    ``MAX_REQUEST`` calls."""
    if n_stations <= 0:
        return []
    per_station = request_weight(1, n_models)
    size = max(1, min(BATCH, math.floor(MAX_REQUEST / per_station)))
    parts = math.ceil(n_stations / size)
    base, extra = divmod(n_stations, parts)
    return [base + 1] * extra + [base] * (parts - extra)


def run_cost(n_stations: int, n_models: int) -> float:
    """Weighted calls of one run for all stations (when every model has it)."""
    return sum(request_weight(n, n_models) for n in batches(n_stations, n_models))


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
                    schema=HOURLY_SCHEMA,
                    strict=False,
                )
            )
    if not frames:
        return pl.DataFrame(schema=HOURLY_SCHEMA)
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
    frames, i = [], 0
    for size in batches(len(rows), len(todo)):
        frames += _fetch_batch(client, rows[i : i + size], run, todo, budget, log)
        i += size
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
        table = pl.concat([pl.DataFrame(schema=HOURLY_SCHEMA), *frames])
        return table, {m.id for m in todo}, unavailable
    return pl.DataFrame(schema=HOURLY_SCHEMA), set(), unavailable


# --- release storage -----------------------------------------------------------------


def release_tag(month: str) -> str:
    return f"runs-{month}"


def asset_name(month: str) -> str:
    return f"runs-{month}.parquet"


class RunsSync:
    """Month files ``runs/YYYY-MM.parquet`` as ``runs-YYYY-MM.parquet`` in the releases
    ``runs-YYYY-MM``, the state as ``runs-state.json`` in ``runs-state``; each asset's
    label is the file's SHA-256, so unchanged files are skipped both ways. Two workflows
    write the state (``mvd fetch-runs`` and ``mvd backfill``, in different month files),
    so ``push`` first merges the released state into the local one (``State.merge``)."""

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
            self.merge_released(state)
            self.store.put(STATE_TAG, STATE_NAME, state, label=store.sha256(state))

    def merge_released(self, path: Path) -> None:
        """Merge the released state into ``path`` where they differ."""
        asset = self.store.assets(STATE_TAG).get(STATE_NAME)
        if asset is None or asset.get("label") == store.sha256(path):
            return
        with tempfile.TemporaryDirectory() as tmp:
            released = Path(tmp) / STATE_NAME
            self.store.download(STATE_TAG, STATE_NAME, released)
            theirs = State.load(released)
        mine = State.load(path)
        mine.merge(theirs)
        mine.save()


# --- native steps ----------------------------------------------------------------------


def native_steps(models: list[Model]) -> pl.LazyFrame:
    """``model``, ``lead_h`` (1-120), ``_step``: the output step at each lead hour."""
    return pl.LazyFrame(
        [(m.id, h, m.step_at(h)) for m in models for h in range(1, MAX_LEAD_H + 1)],
        schema={"model": pl.String, "lead_h": pl.Int16, "_step": pl.Int16},
        orient="row",
    )


def native(frame: pl.LazyFrame | pl.DataFrame, models: list[Model]) -> pl.LazyFrame:
    """The rows at each model's native output steps (``Model.step_at``), the stored
    convention: rows with a ``source`` are kept as they are; rows without one (the
    Single Runs API, stored before 2026-10-17 with every hour filled by Open-Meteo's
    interpolation) only at native hours, with the precipitation summed over the native
    period ending there (null unless every hour of it has a value). Models not in
    ``models`` count as hourly."""
    frame = frame.lazy()
    if "source" not in frame.collect_schema().names():
        frame = frame.with_columns(pl.lit(None, pl.String).alias("source"))
    columns = frame.collect_schema().names()
    kept = frame.filter(pl.col("source").is_not_null())
    old = (
        frame.filter(pl.col("source").is_null())
        .join(native_steps(models), on=["model", "lead_h"], how="left")
        .with_columns(pl.col("_step").fill_null(1))
    )
    lead, step = pl.col("lead_h"), pl.col("_step")
    sums = (
        old.with_columns((lead + (step - lead % step) % step).cast(pl.Int16).alias("lead_h"))
        .group_by("run", "model", "station_id", "lead_h")
        .agg(
            pl.col("precipitation").sum().alias("_sum"),
            pl.col("precipitation").count().alias("_n"),
        )
    )
    converted = (
        old.filter(lead % step == 0)
        .join(sums, on=["run", "model", "station_id", "lead_h"], how="left")
        .with_columns(
            pl.when(pl.col("_n") == step)
            .then(pl.col("_sum"))
            .otherwise(None)
            .cast(pl.Float32)
            .alias("precipitation")
        )
        .select(columns)
    )
    return pl.concat([kept, converted])


def from_api(table: pl.DataFrame, models: list[Model]) -> pl.DataFrame:
    """An API answer (``HOURLY_SCHEMA``) as stored: native steps, ``source`` "api", the
    further variables null (``EXTRA_VARIABLES``: bucket only)."""
    return (
        native(table, models)
        .with_columns(
            pl.lit("api").alias("source"),
            *(pl.lit(None, pl.Float32).alias(v) for v in EXTRA_VARIABLES),
        )
        .select(list(SCHEMA))
        .cast(SCHEMA)
        .collect()
    )


# --- the collection ------------------------------------------------------------------


@dataclass
class Result:
    runs: list[str] = field(default_factory=list)  # run keys fetched (fully or partly)
    gaps: dict[str, set[str]] = field(default_factory=dict)  # run key -> models missing
    failed: list[str] = field(default_factory=list)
    stopped: str = ""  # why the collection stopped early, if it did
    #: weighted calls per run key, as spent
    calls: dict[str, float] = field(default_factory=dict)


def affordable(n_stations: int, n_models: int, left: float) -> int:
    """How many of ``n_models`` one run can ask for within ``left`` calls (0: none)."""
    return max((k for k in range(n_models + 1) if run_cost(n_stations, k) <= left), default=0)


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
) -> Result:
    """Ask the Single Runs API, newest first, until done or the call budget is used up:
    ``runs`` if given (every model not stored yet), else ``api_runs``: "recent" (within
    the bucket's window: only the model-runs missing there, the fallback) and "history"
    (older runs back to ``history_edge``; the older ones are the D+N backfill's). When
    the budget left does not cover all models of a run, as many as it covers are asked
    (the rest wait for the next run)."""
    state = State.load(data_dir / STATE_NAME)
    explicit = runs is not None
    if runs is None:
        edge = bucket_start(now)
        runs = [
            r
            for r in api_runs(now)
            if ("recent" in modes and r >= edge) or ("history" in modes and r < edge)
        ]
    result, pulled = Result(), set()
    for run in runs:
        every = wanted(models, run)
        todo = state.todo(run, every) if explicit else state.api_todo(run, every, now)
        if not todo:
            continue
        fits = affordable(stations.height, len(todo), budget.max_calls - budget.used)
        if fits == 0:
            result.stopped = f"budget of {budget.max_calls:g} calls reached ({budget.used:g} used)"
            break
        todo = todo[:fits]
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
            partitions.write_monthly(
                from_api(table, models), data_dir / "runs", KEYS, "run", replace=["run", "model"]
            )
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
            f"run {run:%Y-%m-%d %H} UTC: {len(fetched)} models from the API, "
            f"{table.height:,} hourly rows, {result.calls[k]:g} calls"
            + (f"; not available: {', '.join(sorted(unavailable))}{later}" if unavailable else "")
        )
    return result


def all_runs(now: datetime, first: date) -> list[datetime]:
    """Every run from the newest one in the bucket's reach back to ``first``."""
    start = datetime.combine(first, datetime.min.time(), UTC)
    return _runs_between(_latest_run(now - timedelta(hours=BUCKET_MIN_AGE_H)), start)


def progress(data_dir: Path, models: list[Model], now: datetime) -> tuple[int, int]:
    """``(complete, all)`` runs from the oldest in the archive (``history_start``) to the
    newest one (every model it has stored or a gap for good)."""
    state = State.load(data_dir / STATE_NAME)
    every = [r for r in all_runs(now, history_start(models)) if wanted(models, r)]
    done = sum(not state.todo(r, wanted(models, r)) for r in every)
    return done, len(every)


def summary(
    result: Result,
    calls: float,
    data_dir: Path,
    models,
    now: datetime,
    budget_note: str = "",
    bucket_lines: str = "",
) -> str:
    """Markdown for the workflow's job summary."""
    done, every = progress(data_dir, models, now)
    state = State.load(data_dir / STATE_NAME)
    left = api_pending(state, models, now)
    older = backfill_pending(state, models, now)
    edge = history_edge(now)
    lines = [
        "## Single runs",
        "",
        *([bucket_lines.rstrip("\n")] if bucket_lines else []),
        f"- API: {len(result.runs)} runs asked, {calls:g} Open-Meteo calls; "
        f"{left} runs still to ask here (the bucket's gaps and the history since "
        f"{edge:%Y-%m-%d}); {older} older runs are left to the D+N backfill",
        f"- Progress: {done} of {every} runs complete since {history_start(models)}",
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


# --- what is left ------------------------------------------------------------------------


def api_pending(state: State, models: list[Model], now: datetime) -> int:
    """Runs ``mvd fetch-runs`` still has to ask the API for (``api_runs``,
    ``State.api_todo``): the bucket's gaps and the history back to ``history_edge``."""
    return sum(bool(state.api_todo(r, wanted(models, r), now)) for r in api_runs(now))


def backfill_pending(state: State, models: list[Model], now: datetime) -> int:
    """Runs older than ``history_edge`` still to fetch (the D+N backfill's part)."""
    start = datetime.combine(history_start(models), datetime.min.time(), UTC)
    older = _runs_between(history_edge(now) - timedelta(hours=6), start)
    return sum(bool(state.todo(r, wanted(models, r))) for r in older)
