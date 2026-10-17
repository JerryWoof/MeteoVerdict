"""Archive of all ČHMÚ climatological open data: every element of every station.

ČHMÚ publishes station data at opendata.chmi.cz/meteorology/climate/ in several
resolutions (10 min, 1 hour, daily, pentadic, monthly, yearly, phenomena) and folders
(``now/`` for the last ~3 days, ``recent/`` for the last 12 months, ``historical/`` for
closed years). The inventory with sizes is in docs/chmi-data.md, the archive format in
docs/data-sources.md#chmi-archive.

Everything is stored in one long Parquet schema (``SCHEMA``), one row per station,
time, element (and, for aggregates, time function and statistic), sorted by station
and time, which compresses ČHMÚ's JSON about 40 times. Files ("assets") are grouped
into GitHub releases; the same ``<tag>/<name>`` layout is used on a local disk
(``LocalStore``), so a mirror is a plain copy.

Work comes in units (one asset each), done in order of urgency, newest first, under a
time budget, and remembered in a small state file, so the backfill resumes where it
stopped:

1. ``day``: one UTC day of 10-minute and hourly data of all stations from ``now/``
   (kept ~3 days; falls back to the current month's day files in ``recent/``), plus
   that day's metadata snapshot.
2. ``recent``: one month of one resolution from ``recent/`` (re-done when ČHMÚ changes
   the files, e.g. after their checks on the 3rd of the month).
3. ``history``: all closed years of one station from ``historical/`` (daily, monthly,
   pentadic, yearly and phenomena in one file).
4. ``month``: one closed month of 10-minute or hourly data of all stations from
   ``historical/`` (2018 onwards).

Licence: ČHMÚ, CC BY 4.0. We change only the layout (JSON → Parquet, types).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

import httpx
import polars as pl

from meteoverdict.chmi import BASE_URL, parse_collection
from meteoverdict.observations import RETRY_WAITS
from meteoverdict.observations import _get as get_json

#: resolution → ČHMÚ file name prefix
PREFIX = {
    "10min": "10m",
    "1hour": "1h",
    "daily": "dly",
    "pentadic": "5d",
    "monthly": "mly",
    "yearly": "yrs",
    "phenomena": "ph",
}
RESOLUTION = {prefix: res for res, prefix in PREFIX.items()}
#: whole-history files per station in historical/data/<resolution>/
HISTORY_RESOLUTIONS = ("daily", "monthly", "pentadic", "yearly", "phenomena")
#: one file per station and month in historical/data/<resolution>/<YYYY>/
MONTH_RESOLUTIONS = ("10min", "1hour")
#: month folders recent/data/<resolution>/<MM>/ (yearly has none)
RECENT_RESOLUTIONS = ("10min", "1hour", "daily", "monthly", "pentadic", "phenomena")
#: the current month's per-station files lie in recent/data/<resolution>/ itself
RECENT_ROOT_MONTHLY = ("daily", "phenomena")

SCHEMA = {
    "station": pl.String,  # WIGOS station identifier (WSI)
    "resolution": pl.String,  # a key of PREFIX
    "time": pl.Datetime("ms", "UTC"),  # ČHMÚ's DT; start of the period for aggregates
    "element": pl.String,  # ELEMENT, or PHENOMENON for phenomena
    "vtype": pl.String,  # daily VTYPE (e.g. AVG, 06:00); TIMEFUNCTION of aggregates
    "func": pl.String,  # MDFUNCTION of aggregates (AVG, MAX, SUM, GE(10), …)
    "value": pl.Float32,  # null when ČHMÚ sends "" (missing)
    "flag": pl.String,  # FLAG (meta3), or FLAG_REPEAT of aggregates
    "flag2": pl.String,  # FLAG_INTERRUPTED of aggregates
    "quality": pl.UInt8,  # QUALITY (meta4): 0 good … 4 missing, 5 unknown
}
SORT = ["station", "resolution", "time", "element", "vtype", "func"]

STATE_TAG = "chmi-state"
STATE_NAME = "chmi-archive-state.json"
#: download threads towards opendata.chmi.cz: be gentle
WORKERS = 4
#: first year of 10-minute and hourly data in historical/
FIRST_MONTH_YEAR = 2018

RELEASE_NOTES = (
    "Archive of all ČHMÚ climatological station data (every element, every station; "
    "10-minute, hourly, daily, pentadic, monthly, yearly and phenomena) as Parquet, "
    "written by `mvd chmi-archive`. Source: Czech Hydrometeorological Institute (ČHMÚ), "
    "opendata.chmi.cz, licensed under CC BY 4.0 "
    "(https://creativecommons.org/licenses/by/4.0/). Changes: JSON converted to one long "
    "Parquet table with typed columns; values are unchanged. "
    "Format: docs/data-sources.md#chmi-archive."
)


# --- names --------------------------------------------------------------------------
def day_asset(day: date) -> tuple[str, str]:
    """10-minute and hourly data of all stations for one UTC day (from now/)."""
    return f"chmi-now-{day.year}", f"chmi-now-{day:%Y-%m-%d}.parquet"


def meta_asset(day: date) -> tuple[str, str]:
    """The day's metadata snapshot (meta1…meta4 JSON, zipped)."""
    return f"chmi-now-{day.year}", f"chmi-meta-{day:%Y-%m-%d}.zip"


def month_asset(resolution: str, year: int, month: int) -> tuple[str, str]:
    """One month of one resolution for all stations."""
    return f"chmi-{year}", f"chmi-{resolution}-{year}-{month:02d}.parquet"


def history_asset(wsi: str) -> tuple[str, str]:
    """All closed years of one station (daily, monthly, pentadic, yearly, phenomena).

    Ten releases by the last digit of the WSI keep each under GitHub's 1000 assets.
    """
    return f"chmi-history-{wsi[-1]}", f"chmi-history-{wsi}.parquet"


_NAME_RE = re.compile(r"^(10m|1h|dly|5d|mly|yrs|ph)-(\d+-\d+-\d+-\d+?)(?:-(\d{6}|\d{8}))?\.json$")


@dataclass(frozen=True)
class FileName:
    resolution: str
    wsi: str
    stamp: str | None  # YYYYMM or YYYYMMDD; None for whole-history files


def parse_name(name: str) -> FileName | None:
    """``10m-0-20000-0-11520-20261014.json`` → (10min, WSI, 20261014)."""
    m = _NAME_RE.match(name)
    if not m:
        return None
    return FileName(RESOLUTION[m.group(1)], m.group(2), m.group(3))


# --- directory listings ----------------------------------------------------------------
_LISTING_RE = re.compile(
    r'<a href="([^"?][^"]*)">[^<]*</a>\s+(\d\d-\w{3}-\d{4} \d\d:\d\d)\s+(-|\d+)'
)


@dataclass(frozen=True)
class Entry:
    name: str  # a folder ends with "/"
    modified: str  # as listed, e.g. "15-Oct-2026 00:02"
    size: int  # bytes; -1 for folders


def parse_listing(html: str) -> list[Entry]:
    """Files and folders of an nginx directory listing (opendata.chmi.cz)."""
    return [
        Entry(name, modified, -1 if size == "-" else int(size))
        for name, modified, size in _LISTING_RE.findall(html)
        if name != "../"
    ]


def list_dir(
    client: httpx.Client, path: str, sleep: Callable[[float], None] = time.sleep
) -> list[Entry]:
    """Listing of ``BASE_URL/path`` (path ends with "/"); [] when it does not exist.

    Network and server errors are retried like single files (``observations._get``).
    """
    for wait in (*RETRY_WAITS, None):
        try:
            response = client.get(f"{BASE_URL}/{path}")
        except httpx.TransportError:
            if wait is None:
                raise
        else:
            if response.status_code == 404:
                return []
            if response.status_code < 500 and response.status_code != 429:
                response.raise_for_status()
                return parse_listing(response.text)
            if wait is None:
                response.raise_for_status()
        sleep(wait)
    return []


def signature(entries: Iterable[Entry]) -> str:
    """Short fingerprint of a set of files: changes when ČHMÚ rewrites any of them."""
    text = "\n".join(
        f"{e.name} {e.modified} {e.size}" for e in sorted(entries, key=lambda e: e.name)
    )
    return hashlib.sha1(text.encode()).hexdigest()[:16]


# --- normalising one ČHMÚ file --------------------------------------------------------
def _text(raw: pl.DataFrame, *names: str) -> pl.Expr:
    """First existing column as a string with "" as null; null if none exists."""
    for name in names:
        if name in raw.columns:
            return pl.col(name).cast(pl.String).replace("", None)
    return pl.lit(None, pl.String)


def _int(raw: pl.DataFrame, name: str, default: int | None) -> pl.Expr:
    if name in raw.columns:
        return pl.col(name).cast(pl.String).cast(pl.Float64, strict=False).cast(pl.Int32)
    return pl.lit(default, pl.Int32)


def normalize(raw: pl.DataFrame, resolution: str, stamp: str | None = None) -> pl.DataFrame:
    """One ČHMÚ table (any resolution) → rows of ``SCHEMA``, sorted.

    Recent monthly and pentadic files have no YEAR/MONTH columns: they come from the
    file name (``stamp``, YYYYMM).
    """
    if raw.height == 0:
        return pl.DataFrame(schema=SCHEMA)
    if "DT" in raw.columns:
        dt = pl.col("DT").cast(pl.String)
        dt = pl.when(dt.str.len_chars() == 10).then(dt + "T00:00:00Z").otherwise(dt)
        when = dt.str.to_datetime("%Y-%m-%dT%H:%M:%SZ", time_unit="ms", time_zone="UTC")
    else:
        year = _int(raw, "YEAR", int(stamp[:4]) if stamp else None)
        month = _int(raw, "MONTH", int(stamp[4:6]) if stamp and len(stamp) >= 6 else 1)
        pentade = _int(raw, "PENTADE", 1)
        when = pl.datetime(year, month, (pentade - 1) * 5 + 1, time_unit="ms", time_zone="UTC")
    out = raw.select(
        _text(raw, "STATION").alias("station"),
        pl.lit(resolution).alias("resolution"),
        when.alias("time"),
        _text(raw, "ELEMENT", "PHENOMENON").alias("element"),
        _text(raw, "VTYPE", "TIMEFUNCTION").alias("vtype"),
        _text(raw, "MDFUNCTION").alias("func"),
        _text(raw, "VAL", "VALUE").cast(pl.Float32, strict=False).alias("value"),
        _text(raw, "FLAG", "FLAG_REPEAT").alias("flag"),
        _text(raw, "FLAG_INTERRUPTED").alias("flag2"),
        _text(raw, "QUALITY").cast(pl.Float32, strict=False).cast(pl.UInt8).alias("quality"),
    )
    return out.cast(SCHEMA).sort(SORT, nulls_last=False)


def write(table: pl.DataFrame, path: Path) -> Path:
    """Parquet as stored in the archive (zstd, statistics for filtering by station/time)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table.select(list(SCHEMA)).write_parquet(
        path, compression="zstd", compression_level=10, statistics=True, row_group_size=1 << 20
    )
    return path


# --- units of work -------------------------------------------------------------------
@dataclass(frozen=True)
class Source:
    path: str  # relative to BASE_URL
    resolution: str
    stamp: str | None


@dataclass
class Unit:
    kind: str  # day | recent | history | month
    key: str  # in the state file
    tag: str
    name: str
    sources: list[Source]
    signature: str
    meta: list[str] = field(default_factory=list)  # day units: metadata files to zip


@dataclass
class State:
    """``units``: unit key → signature of the ČHMÚ files it was built from."""

    units: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_json(cls, text: str) -> State:
        return cls(dict(json.loads(text).get("units", {})))

    def to_json(self) -> str:
        return json.dumps({"units": dict(sorted(self.units.items()))}, indent=1) + "\n"


def _sources(folder: str, entries: list[Entry]) -> list[Source]:
    found = []
    for e in sorted(entries, key=lambda e: e.name):
        if (parsed := parse_name(e.name)) is not None:
            found.append(Source(folder + e.name, parsed.resolution, parsed.stamp))
    return found


def _day_files(entries: list[Entry]) -> dict[str, list[Entry]]:
    """10-minute and hourly day files (``…-YYYYMMDD.json``) by day."""
    by_day: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        p = parse_name(e.name)
        if p and p.stamp and len(p.stamp) == 8 and p.resolution in MONTH_RESOLUTIONS:
            by_day[p.stamp].append(e)
    return by_day


def plan_days(client: httpx.Client, today: date, have: Callable[[str, str], bool]) -> list[Unit]:
    """Complete UTC days not archived yet, newest first: from now/ (unchecked, ~3 days),
    or, for days that already fell out of now/, from the current month's day files in
    recent/ (partly checked; there until the month is published as a whole)."""
    now = _day_files(list_dir(client, "now/data/"))
    meta = {e.name for e in list_dir(client, "now/metadata/")}
    recent: dict[str, list[tuple[str, Entry]]] = defaultdict(list)
    for res in MONTH_RESOLUTIONS:
        folder = f"recent/data/{res}/"
        for stamp, entries in _day_files(list_dir(client, folder)).items():
            recent[stamp] += [(folder, e) for e in entries]
    units = []
    for stamp in sorted(set(now) | set(recent), reverse=True):
        day = datetime.strptime(stamp, "%Y%m%d").date()
        tag, name = day_asset(day)
        if day >= today or have(tag, name):
            continue
        if stamp in now:
            sources = _sources("now/data/", now[stamp])
            meta_files = [f"now/metadata/meta{n}-{stamp}.json" for n in range(1, 5)]
            meta_files = [m for m in meta_files if m.rsplit("/", 1)[1] in meta]
            sig = "now:" + signature(now[stamp])
        else:
            sources = [s for folder, e in recent[stamp] for s in _sources(folder, [e])]
            meta_files, sig = [], "recent:" + signature(e for _, e in recent[stamp])
        units.append(Unit("day", f"day|{day}", tag, name, sources, sig, meta_files))
    return units


def last_closed_year(client: httpx.Client) -> int:
    """The newest year with a folder in historical/data/10min/ (ČHMÚ adds one each
    February)."""
    years = [
        int(e.name[:4]) for e in list_dir(client, "historical/data/10min/") if e.name[:4].isdigit()
    ]
    return max(years, default=FIRST_MONTH_YEAR - 1)


def plan_recent(client: httpx.Client, state: State, closed: int) -> list[Unit]:
    """Months in recent/ that changed since they were archived, newest first.

    Months of closed years are skipped where historical/ has them (10 min and 1 h: the
    month units; the rest: the station history files).
    """
    units = []
    for res in RECENT_RESOLUTIONS:
        groups: dict[str, list[tuple[str, Entry]]] = defaultdict(list)
        folders = [f"recent/data/{res}/{mm:02d}/" for mm in range(1, 13)]
        if res in RECENT_ROOT_MONTHLY:
            folders.append(f"recent/data/{res}/")
        for folder in folders:
            for e in list_dir(client, folder):
                p = parse_name(e.name)
                if p and p.stamp and len(p.stamp) == 6:
                    groups[p.stamp].append((folder, e))
        for stamp, found in groups.items():
            year, month = int(stamp[:4]), int(stamp[4:])
            if year <= closed:
                continue
            key = f"{res}|{year}-{month:02d}"
            sig = "recent:" + signature(e for _, e in found)
            if state.units.get(key) == sig:
                continue
            tag, name = month_asset(res, year, month)
            sources = [
                Source(folder + e.name, res, stamp)
                for folder, e in sorted(found, key=lambda f: f[1].name)
            ]
            units.append(Unit("recent", key, tag, name, sources, sig))
    return sorted(units, key=lambda u: (u.key.split("|")[1], u.key), reverse=True)


def plan_history(client: httpx.Client, state: State) -> list[Unit]:
    """Stations whose history files changed (or were never archived)."""
    by_station: dict[str, list[tuple[str, Entry]]] = defaultdict(list)
    for res in HISTORY_RESOLUTIONS:
        folder = f"historical/data/{res}/"
        for e in list_dir(client, folder):
            p = parse_name(e.name)
            if p and p.stamp is None:
                by_station[p.wsi].append((folder, e))
    units = []
    for wsi in sorted(by_station):
        found = by_station[wsi]
        key, sig = f"history|{wsi}", "historical:" + signature(e for _, e in found)
        if state.units.get(key) == sig:
            continue
        tag, name = history_asset(wsi)
        sources = [_sources(folder, [e])[0] for folder, e in found]
        units.append(Unit("history", key, tag, name, sources, sig))
    return units


def plan_months(
    client: httpx.Client, state: State, first_year: int = FIRST_MONTH_YEAR
) -> list[Unit]:
    """Closed months of 10-minute and hourly data, newest first (hourly first: smaller)."""
    units = []
    for res in MONTH_RESOLUTIONS:
        years = [
            int(e.name[:4])
            for e in list_dir(client, f"historical/data/{res}/")
            if e.name[:4].isdigit() and int(e.name[:4]) >= first_year
        ]
        for year in sorted(years, reverse=True):
            folder = f"historical/data/{res}/{year}/"
            groups: dict[str, list[Entry]] = defaultdict(list)
            for e in list_dir(client, folder):
                p = parse_name(e.name)
                if p and p.stamp and len(p.stamp) == 6:
                    groups[p.stamp].append(e)
            for stamp in sorted(groups, reverse=True):
                y, m = int(stamp[:4]), int(stamp[4:])
                key, sig = f"{res}|{y}-{m:02d}", "historical:" + signature(groups[stamp])
                if state.units.get(key) == sig:
                    continue
                tag, name = month_asset(res, y, m)
                units.append(Unit("month", key, tag, name, _sources(folder, groups[stamp]), sig))
    return units


# --- doing the work -------------------------------------------------------------------
def fetch_to_parquet(
    client: httpx.Client,
    sources: list[Source],
    dest: Path,
    workers: int = WORKERS,
    sleep: Callable[[float], None] | None = None,
) -> tuple[int, list[str]]:
    """Download and normalise the files into one sorted Parquet file ``dest``.

    Each file is written to a temporary part first and the parts are joined on disk,
    so a month of 10-minute data (about 45 million rows) never sits in memory at once.
    Returns the number of rows and the files that could not be read even after
    retries (gone since the listing, or an empty body as ČHMÚ sometimes serves): they
    are left out, like a missing station-day in ``observations``, and reported.
    """
    wait = sleep or (lambda s: time.sleep(s))
    parts_dir = dest.parent / f"{dest.name}.parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    def one(item: tuple[int, Source]) -> tuple[Path, int] | None:
        i, source = item
        doc = get_json(client, f"{BASE_URL}/{source.path}", wait)
        if doc is None:
            return None
        table = normalize(parse_collection(doc), source.resolution, source.stamp)
        part = parts_dir / f"{i:05d}.parquet"
        table.write_parquet(part, compression="lz4")
        return part, table.height

    # every file is one station and resolution, sorted: in this order the whole table is
    ordered = sorted(sources, key=lambda s: (_wsi(s.path), s.resolution))
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, enumerate(ordered)))
        missing = [s.path for s, r in zip(ordered, results, strict=True) if r is None]
        done = [r for r in results if r is not None]
        rows = sum(n for _, n in done)
        if rows:
            dest.parent.mkdir(parents=True, exist_ok=True)
            pl.scan_parquet([p for p, _ in done]).select(list(SCHEMA)).sink_parquet(
                dest,
                compression="zstd",
                compression_level=10,
                statistics=True,
                row_group_size=1 << 20,
            )
    finally:
        for part in parts_dir.glob("*.parquet"):
            part.unlink()
        parts_dir.rmdir()
    return rows, missing


def _wsi(path: str) -> str:
    parsed = parse_name(path.rsplit("/", 1)[-1])
    return parsed.wsi if parsed else path


def fetch_meta_zip(client: httpx.Client, paths: list[str], dest: Path) -> Path | None:
    """The metadata JSON files as they are, in one zip (None if none could be read)."""
    buffer = io.BytesIO()
    written = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            doc = get_json(client, f"{BASE_URL}/{path}")
            if doc is not None:
                archive.writestr(Path(path).name, json.dumps(doc, ensure_ascii=False))
                written += 1
    if not written:
        return None
    dest.write_bytes(buffer.getvalue())
    return dest


class Store(Protocol):
    def names(self, tag: str) -> set[str]: ...

    def put(self, tag: str, name: str, path: Path) -> None: ...

    def get(self, tag: str, name: str, dest: Path) -> Path | None: ...


class LocalStore:
    """Archive files under ``root/<tag>/<name>`` (the same layout as a mirror)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def names(self, tag: str) -> set[str]:
        folder = self.root / tag
        return {p.name for p in folder.iterdir() if p.is_file()} if folder.exists() else set()

    def put(self, tag: str, name: str, path: Path) -> None:
        (self.root / tag).mkdir(parents=True, exist_ok=True)
        target = self.root / tag / name
        if path.resolve() != target.resolve():
            target.write_bytes(path.read_bytes())

    def get(self, tag: str, name: str, dest: Path) -> Path | None:
        source = self.root / tag / name
        if not source.exists():
            return None
        if source.resolve() != dest.resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(source.read_bytes())
        return dest


class ReleaseStore:
    """GitHub releases (``releases.GitHubReleaseStore``), asset labels = SHA-256."""

    def __init__(self, releases) -> None:
        self.releases = releases
        self._names: dict[str, set[str]] = {}

    def names(self, tag: str) -> set[str]:
        if tag not in self._names:
            self._names[tag] = self.releases.names(tag)
        return self._names[tag]

    def put(self, tag: str, name: str, path: Path) -> None:
        self.releases.put(tag, name, path, label=sha256(path))
        self.names(tag).add(name)

    def get(self, tag: str, name: str, dest: Path) -> Path | None:
        if name not in self.names(tag):
            return None
        return self.releases.download(tag, name, dest)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_state(store: Store, workdir: Path) -> State:
    path = store.get(STATE_TAG, STATE_NAME, workdir / STATE_NAME)
    return State.from_json(path.read_text(encoding="utf-8")) if path else State()


def save_state(store: Store, state: State, workdir: Path) -> None:
    path = workdir / STATE_NAME
    path.write_text(state.to_json(), encoding="utf-8")
    store.put(STATE_TAG, STATE_NAME, path)


@dataclass
class Result:
    done: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    pending: int = 0  # units left when the time budget ran out
    unreadable: int = 0  # listed files left out because they could not be read
    rows: int = 0
    bytes: int = 0


def run_units(
    client: httpx.Client,
    store: Store,
    state: State,
    units: list[Unit],
    workdir: Path,
    deadline: float | None = None,
    log: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
    save: bool = True,
) -> Result:
    """Build and store each unit in order until ``deadline`` (``clock`` seconds).

    The state is saved after every unit (unless ``save`` is false), so an interrupted
    run loses at most one.
    """
    result = Result()
    for i, unit in enumerate(units):
        if deadline is not None and clock() >= deadline:
            result.pending = len(units) - i
            log(f"time budget used up; {result.pending} units left for the next run")
            break
        try:
            path = workdir / unit.name
            rows, missing = fetch_to_parquet(client, unit.sources, path)
            if missing:
                log(f"{unit.name}: left out {len(missing)} unreadable files, e.g. {missing[0]}")
                result.unreadable += len(missing)
            if rows == 0:
                log(f"skipped {unit.name}: no rows")
                state.units[unit.key] = unit.signature
                if save:
                    save_state(store, state, workdir)
                continue
            store.put(unit.tag, unit.name, path)
            if unit.meta:
                zipped = fetch_meta_zip(client, unit.meta, workdir / meta_asset(_day(unit))[1])
                if zipped:
                    store.put(*meta_asset(_day(unit)), zipped)
                    zipped.unlink()
            size = path.stat().st_size
            path.unlink()
        except Exception as exc:  # keep going: the next unit may still work
            (workdir / unit.name).unlink(missing_ok=True)
            log(f"failed {unit.name}: {exc}")
            result.failed.append(unit.name)
            continue
        if unit.kind != "day" and save:  # day units are recognised by their asset
            state.units[unit.key] = unit.signature
            save_state(store, state, workdir)
        result.done.append(unit.name)
        result.rows += rows
        result.bytes += size
        log(
            f"archived {unit.name}: {rows:,} rows, {size / 1e6:.1f} MB "
            f"from {len(unit.sources)} files"
        )
    return result


def _day(unit: Unit) -> date:
    return date.fromisoformat(unit.key.removeprefix("day|"))


PARTS = ("days", "recent", "history", "months")


def archive(
    client: httpx.Client,
    store: Store,
    workdir: Path,
    parts: Iterable[str] = PARTS,
    today: date | None = None,
    max_minutes: float | None = None,
    first_year: int = FIRST_MONTH_YEAR,
    stations: set[str] | None = None,
    log: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
) -> Result:
    """Plan and run the archive. ``stations`` limits the history part (for trials)."""
    today = today or datetime.now(UTC).date()
    workdir.mkdir(parents=True, exist_ok=True)
    deadline = clock() + max_minutes * 60 if max_minutes is not None else None
    state = load_state(store, workdir)
    parts = set(parts)
    units: list[Unit] = []
    if "days" in parts:
        units += plan_days(client, today, lambda tag, name: name in store.names(tag))
    if "recent" in parts:
        units += plan_recent(client, state, last_closed_year(client))
    if "history" in parts:
        units += plan_history(client, state)
    if "months" in parts:
        units += plan_months(client, state, first_year)
    if stations is not None:  # a trial: partial files, so the state is not kept
        for unit in units:
            if unit.kind != "day":
                unit.sources = [s for s in unit.sources if _wsi(s.path) in stations]
        units = [u for u in units if u.sources]
    log(
        f"{len(units)} units to do: "
        + ", ".join(
            f"{n} {kind}"
            for kind in ("day", "recent", "history", "month")
            if (n := sum(u.kind == kind for u in units))
        )
    )
    return run_units(
        client, store, state, units, workdir, deadline, log, clock, save=stations is None
    )


# --- mirror ----------------------------------------------------------------------------
def mirror(
    releases, dest: Path, prefix: str = "chmi-", log: Callable[[str], None] = print
) -> list[str]:
    """Copy every asset of the releases ``prefix*`` to ``dest/<tag>/<name>``, skipping
    files whose SHA-256 equals the asset label (unchanged)."""
    copied = []
    for tag in releases.tags(prefix):
        for name, asset in sorted(releases.assets(tag).items()):
            path = dest / tag / name
            if path.exists() and asset.get("label") and sha256(path) == asset["label"]:
                continue
            releases.download(tag, name, path)
            copied.append(f"{tag}/{name}")
            log(f"copied {tag}/{name} ({asset.get('size', 0) / 1e6:.1f} MB)")
    return copied


# --- reading the archive back ------------------------------------------------------------
def scan(root: Path, pattern: str) -> pl.LazyFrame | None:
    """All archive files ``root/*/<pattern>`` as one lazy table (None when there are none)."""
    files = sorted(root.glob(f"*/{pattern}"))
    return pl.scan_parquet(files) if files else None


#: parallel downloads from GitHub's storage host (not the API) in ``sync``
SYNC_WORKERS = 8


def sync(
    releases, root: Path, wanted: Iterable[tuple[str, str]], log=print, workers: int = SYNC_WORKERS
) -> int:
    """Download the wanted ``(tag, name)`` assets that exist and differ from the local
    copy under ``root/<tag>/<name>`` (read only towards GitHub). One asset listing per
    release; the files themselves come in parallel. Returns the count."""
    by_tag: dict[str, list[str]] = defaultdict(list)
    for tag, name in wanted:
        by_tag[tag].append(name)
    todo: list[tuple[str, str, Path, int]] = []
    for tag, names in sorted(by_tag.items()):
        assets = releases.assets(tag)
        for name in sorted(set(names)):
            asset = assets.get(name)
            if asset is None:
                continue
            path = root / tag / name
            if path.exists() and asset.get("label") and sha256(path) == asset["label"]:
                continue
            todo.append((tag, name, path, asset.get("size") or 0))
    started = time.monotonic()
    with ThreadPoolExecutor(max(workers, 1)) as pool:
        list(pool.map(lambda job: releases.download(job[0], job[1], job[2]), todo))
    size = sum(job[3] for job in todo)
    log(
        f"downloaded {len(todo)} archive files ({size / 1e6:.0f} MB) to {root} "
        f"in {time.monotonic() - started:.0f} s"
    )
    return len(todo)
