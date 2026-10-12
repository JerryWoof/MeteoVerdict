"""Archive ČHMÚ ALADIN forecasts at the stations before the open-data files expire.

opendata.chmi.cz/meteorology/weather/nwp_aladin/ keeps only the last three days of
runs (00, 06, 12 and 18 UTC). For every run still there and not yet archived, we
download 2 m temperature, 10 m wind speed and total precipitation (GRIB1, hourly
steps 0-72 h), take the value at the grid point nearest to each station, and store
one small Parquet file per run. The raw GRIB files are discarded.

Licence: ČHMÚ, CC BY 4.0 (National Open Data Catalogue). Changes we make: nearest
grid point extraction, K → °C. See docs/data-sources.md#aladin-archive.
"""

from __future__ import annotations

import bz2
import math
import re
import tempfile
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import eccodes
import httpx
import numpy as np
import polars as pl

BASE_URL = "https://opendata.chmi.cz/meteorology/weather/nwp_aladin"
RUN_HOURS = (0, 6, 12, 18)
GRAVITY = 9.80665
MAX_DISTANCE_KM = 3.0  # a station further from every grid point is outside the domain

#: ČHMÚ field name → our column (units after conversion).
FIELDS = {
    "CLSTEMPERATURE": "temperature_2m",  # °C (file: K)
    "CLSWIND_SPEED": "wind_speed_10m",  # m/s
    "SURFPREC_TOTAL": "precipitation_accum",  # mm since the run started (file: kg/m²)
}
OROGRAPHY = "SURFGEOPOTENTIEL"  # m²/s², divided by g for the grid elevation


@dataclass(frozen=True)
class Domain:
    model: str  # id in models.yaml
    folder: str
    prefix: str


DOMAINS = (
    Domain("chmi_aladin_cz_1km", "CZ_1km", "ALADCZ1K4opendata"),
    Domain("chmi_aladin_central_europe_2km", "Lambert_2.3km", "ALADLAMB4opendata"),
)

_FILE_RE = re.compile(r'href="[A-Z0-9]+opendata_(\d{10})_([A-Z_]+)\.grb\.bz2"')


def file_url(domain: Domain, run: datetime, field: str) -> str:
    return f"{BASE_URL}/{domain.folder}/{run:%H}/{domain.prefix}_{run:%Y%m%d%H}_{field}.grb.bz2"


def archive_name(domain: Domain, run: datetime) -> str:
    return f"{domain.model}_{run:%Y%m%d%H}.parquet"


def release_tag(run: datetime) -> str:
    return f"aladin-{run:%Y-%m}"


def available_runs(client: httpx.Client, domain: Domain) -> list[datetime]:
    """Runs on the server that have every field we need, oldest first."""
    fields: dict[str, set[str]] = defaultdict(set)
    for hour in RUN_HOURS:
        response = client.get(f"{BASE_URL}/{domain.folder}/{hour:02d}/")
        response.raise_for_status()
        for stamp, field in _FILE_RE.findall(response.text):
            fields[stamp].add(field)
    needed = {*FIELDS, OROGRAPHY}
    return sorted(
        datetime.strptime(stamp, "%Y%m%d%H").replace(tzinfo=UTC)
        for stamp, have in fields.items()
        if needed <= have
    )


def download_bz2(client: httpx.Client, url: str, dest: Path) -> Path:
    """Stream a .bz2 file to ``dest`` decompressed (handles multi-stream bz2)."""
    decompressor = bz2.BZ2Decompressor()
    with client.stream("GET", url) as response, dest.open("wb") as out:
        response.raise_for_status()
        for chunk in response.iter_bytes(1 << 20):
            while chunk:
                out.write(decompressor.decompress(chunk))
                chunk = b""
                if decompressor.eof:
                    chunk = decompressor.unused_data
                    decompressor = bz2.BZ2Decompressor()
    return dest


def grib_messages(path: Path) -> Iterator[tuple[int, np.ndarray]]:
    """Yield ``(step_hours, values)`` for every GRIB message in the file."""
    with path.open("rb") as f:
        while (gid := eccodes.codes_grib_new_from_file(f)) is not None:
            try:
                if eccodes.codes_get(gid, "stepUnits") != 1:
                    raise ValueError(f"{path.name}: step units are not hours")
                yield int(eccodes.codes_get(gid, "endStep")), eccodes.codes_get_values(gid)
            finally:
                eccodes.codes_release(gid)


def grid_coordinates(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Latitudes, longitudes (-180 to 180) and values of the first message."""
    with path.open("rb") as f:
        gid = eccodes.codes_grib_new_from_file(f)
        if gid is None:
            raise ValueError(f"{path.name}: no GRIB message")
        try:
            lats = eccodes.codes_get_array(gid, "latitudes")
            lons = eccodes.codes_get_array(gid, "longitudes")
            values = eccodes.codes_get_values(gid)
        finally:
            eccodes.codes_release(gid)
    return lats, np.where(lons > 180, lons - 360, lons), values


def nearest_grid_points(
    lats: np.ndarray, lons: np.ndarray, st_lats: np.ndarray, st_lons: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Index of the nearest grid point and its distance (km) for every station."""
    box = (
        (lats > st_lats.min() - 0.5)
        & (lats < st_lats.max() + 0.5)
        & (lons > st_lons.min() - 0.5)
        & (lons < st_lons.max() + 0.5)
    )
    candidates = np.flatnonzero(box)
    index = np.zeros(len(st_lats), dtype=np.int64)
    distance = np.full(len(st_lats), np.inf)
    if candidates.size == 0:
        return index, distance
    c_lat, c_lon = lats[candidates], lons[candidates]
    for i, (lat, lon) in enumerate(zip(st_lats, st_lons, strict=True)):
        dx = (c_lon - lon) * 111.32 * math.cos(math.radians(lat))
        dy = (c_lat - lat) * 110.57
        d2 = dx * dx + dy * dy
        j = int(np.argmin(d2))
        index[i], distance[i] = candidates[j], math.sqrt(d2[j])
    return index, distance


def extract_run(
    client: httpx.Client, domain: Domain, run: datetime, stations: pl.DataFrame, workdir: Path
) -> pl.DataFrame:
    """Values of one run at the stations: one row per station and lead hour."""
    oro = download_bz2(client, file_url(domain, run, OROGRAPHY), workdir / "oro.grb")
    lats, lons, geopotential = grid_coordinates(oro)
    oro.unlink()
    st_lats, st_lons = stations["lat"].to_numpy(), stations["lon"].to_numpy()
    index, distance = nearest_grid_points(lats, lons, st_lats, st_lons)
    inside = distance <= MAX_DISTANCE_KM
    ids, index, distance = stations["id"].to_numpy()[inside], index[inside], distance[inside]

    columns: dict[str, dict[int, np.ndarray]] = {}
    for field, column in FIELDS.items():
        path = download_bz2(client, file_url(domain, run, field), workdir / f"{field}.grb")
        columns[column] = {step: values[index] for step, values in grib_messages(path)}
        path.unlink()
    steps = sorted(set().union(*columns.values()))

    def stacked(column: str, offset: float = 0.0) -> np.ndarray:
        by_step = columns[column]
        empty = np.full(len(ids), np.nan)
        return np.concatenate([by_step.get(s, empty) + offset for s in steps]).astype(np.float32)

    n = len(steps)
    return pl.DataFrame(
        {
            "model": domain.model,
            "run": [run] * (n * len(ids)),
            "lead_h": np.repeat(np.array(steps, dtype=np.int16), len(ids)),
            "station_id": np.tile(ids, n),
            "temperature_2m": stacked("temperature_2m", -273.15),
            "wind_speed_10m": stacked("wind_speed_10m"),
            "precipitation_accum": stacked("precipitation_accum"),
            "grid_lat": np.tile(lats[index], n).astype(np.float32),
            "grid_lon": np.tile(lons[index], n).astype(np.float32),
            "grid_elevation": np.tile(geopotential[index] / GRAVITY, n).astype(np.float32),
            "grid_distance_km": np.tile(distance, n).astype(np.float32),
        }
    ).with_columns(
        pl.col("run").dt.replace_time_zone("UTC"),
        (pl.col("run").dt.replace_time_zone("UTC") + pl.duration(hours=pl.col("lead_h"))).alias(
            "valid_time"
        ),
        pl.selectors.float().fill_nan(None),
    )


class Store(Protocol):
    def names(self, tag: str) -> set[str]: ...

    def put(self, tag: str, name: str, path: Path) -> None: ...


class LocalStore:
    """Archive files under ``root/<tag>/<name>``."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def names(self, tag: str) -> set[str]:
        folder = self.root / tag
        return {p.name for p in folder.glob("*.parquet")} if folder.exists() else set()

    def put(self, tag: str, name: str, path: Path) -> None:
        (self.root / tag).mkdir(parents=True, exist_ok=True)
        path.replace(self.root / tag / name)


@dataclass
class ArchiveResult:
    archived: list[str]
    skipped: int
    failed: list[str]


def archive(
    client: httpx.Client,
    store: Store,
    stations: pl.DataFrame,
    domains: tuple[Domain, ...] = DOMAINS,
    log=print,
) -> ArchiveResult:
    """Archive every run on the server that is not in ``store`` yet, oldest first."""
    result = ArchiveResult([], 0, [])
    for domain in domains:
        try:
            runs = available_runs(client, domain)
        except httpx.HTTPError as exc:  # the other domain may still work
            log(f"failed to list {domain.model} runs: {exc}")
            result.failed.append(f"{domain.model} listing")
            continue
        for run in runs:
            tag, name = release_tag(run), archive_name(domain, run)
            if name in store.names(tag):
                result.skipped += 1
                continue
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    table = extract_run(client, domain, run, stations, Path(tmp))
                    out = Path(tmp) / name
                    table.write_parquet(out, compression="zstd")
                    store.put(tag, name, out)
            except Exception as exc:  # keep going: other runs may still be saved
                log(f"failed {name}: {exc}")
                result.failed.append(name)
                continue
            log(f"archived {name} ({table.height} rows)")
            result.archived.append(name)
    return result
