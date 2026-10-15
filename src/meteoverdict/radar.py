"""Archive ČHMÚ weather radar composites before the open-data files expire, and keep
the frames the radar page shows.

opendata.chmi.cz/meteorology/weather/radar/composite/ keeps every product for only
about seven days. Once a UTC day is complete, ``archive`` packs all files of that day
of each product into one uncompressed tar (``maxz-hdf5-20261014.tar``, …), as assets of
the monthly GitHub release ``radar-YYYY-MM``, plus derived files:

* ``merge1h-hourly-YYYYMMDD.npz``: the 24 hourly MERGE precipitation grids (radar and
  rain gauges, mm in the hour ending at the time) as raw codes with gain and offset;
* ``merge1h-stations-YYYYMMDD.parquet``: that precipitation at every ČHMÚ station;
* ``web-YYYYMMDD.tar``: the frames of the radar page for that day (max reflectivity
  every 5 minutes, MERGE every 10 minutes), cropped to the data area and transparent.

``update_live`` keeps the frames of the last hours plus the newest nowcast in a folder
that the radar workflow pushes to the branch ``radar-live``.

Licence: ČHMÚ, CC BY 4.0 (National Open Data Catalogue, e.g. "Sloučená informace
maximální radarové odrazivosti MAX_Z pro území Česka"). Changes we make: packing per
day; for the page, cropping the PNG to the data area and making its frame, labels and
background transparent; for the station values, the grid cell containing the station.
See docs/data-sources.md#radar-archive.
"""

from __future__ import annotations

import io
import json
import math
import re
import shutil
import tarfile
import tempfile
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import h5py
import httpx
import numpy as np
import polars as pl
from PIL import Image

BASE_URL = "https://opendata.chmi.cz/meteorology/weather/radar/composite"
#: a day is archived once its last file is this old (MERGE appears up to ~1.5 h late)
COMPLETE_AFTER = timedelta(hours=3)
EARTH_RADIUS = 6378137.0  # m, spherical Web Mercator (EPSG:3857)

#: The composite grid (HDF5 ``/where`` of every product, checked 2026-10-15): Web
#: Mercator, 598 x 378 cells of 1555.7 m (about 1 km at 50° N), outer edges below.
GRID_WEST, GRID_SOUTH, GRID_EAST, GRID_NORTH = 11.266869, 48.047275, 19.623974, 51.458369
GRID_COLS, GRID_ROWS = 598, 378
#: The PNGs are 680 x 460: the grid at the bottom left, side views above and to the right.
PNG_TOP = 82  # first row of the grid in the PNG
PNG_FRAME = 145  # palette index of the black frame, grid lines and the title
PNG_NO_COVERAGE = 242  # palette index of the grey outside the radar coverage
NO_COVERAGE_ALPHA = 64
#: per layer: the grey of MERGE (outside its domain) and of the nowcast (no forecast
#: there) is hidden, as their titles lie on it and would show as gaps
LAYER_NO_COVERAGE_ALPHA = {"maxz": NO_COVERAGE_ALPHA, "merge1h": 0, "nowcast": 0}


@dataclass(frozen=True)
class Product:
    key: str  # asset name prefix
    folder: str  # under BASE_URL
    pattern: str  # file name; groups: date (YYYYMMDD) and time (hhmm), UTC
    step_min: int  # one file every … minutes
    forecast: bool = False

    def regex(self) -> re.Pattern[str]:
        return re.compile(self.pattern)


_PNG = r"pacz2gmaps3\.{}\.(\d{{8}})\.(\d{{4}})\.{}"
PRODUCTS = (
    Product("maxz-hdf5", "maxz/hdf5", r"T_PABV23_C_OKPR_(\d{8})(\d{4})00\.hdf", 5),
    Product("maxz-png", "maxz/png", _PNG.format("z_max3d", r"0\.png"), 5),
    Product("maxz-png_masked", "maxz/png_masked", _PNG.format("z_max3d", r"0\.png"), 5),
    Product("cappi2km-hdf5", "pseudocappi2km/hdf5", r"T_PANV23_C_OKPR_(\d{8})(\d{4})00\.hdf", 5),
    Product("cappi2km-png", "pseudocappi2km/png", _PNG.format("z_cappi020", r"0\.png"), 5),
    Product("echotop-hdf5", "echotop/hdf5", r"T_PADV23_C_OKPR_(\d{8})(\d{4})00\.hdf", 5),
    Product("merge1h-hdf5", "merge1h/hdf5", r"T_PASV23_C_OKPR_(\d{8})(\d{4})00\.hdf", 10),
    Product("merge1h-png", "merge1h/png", _PNG.format("merge", r"60\.png"), 10),
    Product(
        "fct_maxz-hdf5", "fct_maxz/hdf5", r"T_PABV23_C_OKPR_(\d{8})\.(\d{4})\.ft60s10\.tar", 5, True
    ),
    Product("fct_maxz-png", "fct_maxz/png", _PNG.format("fct_z_max", r"ft60s10\.tar"), 5, True),
    Product(
        "fct_maxz-png_masked",
        "fct_maxz/png_masked",
        _PNG.format("fct_z_max", r"ft60s10\.tar"),
        5,
        True,
    ),
    Product(
        "fct_cappi2km-hdf5",
        "fct_pseudocappi2km/hdf5",
        r"T_PANV23_C_OKPR_(\d{8})\.(\d{4})\.ft60s10\.tar",
        5,
        True,
    ),
    Product(
        "fct_cappi2km-png",
        "fct_pseudocappi2km/png",
        _PNG.format("fct_z_cappi020", r"ft60s10\.tar"),
        5,
        True,
    ),
)
BY_KEY = {p.key: p for p in PRODUCTS}
#: ``--products`` presets. The GitHub archive keeps "observed" (about 12 GB a year);
#: the nowcasts (about 50 GB a year) are meant for a local disk (docs/data-sources.md).
PRESETS = {
    "observed": tuple(p.key for p in PRODUCTS if not p.forecast),
    "forecast": tuple(p.key for p in PRODUCTS if p.forecast),
    "all": tuple(p.key for p in PRODUCTS),
}

#: derived asset → the products it is made from
DERIVED = {
    "merge1h-hourly": ("merge1h-hdf5",),
    "merge1h-stations": ("merge1h-hdf5",),
    "web": ("maxz-png_masked", "merge1h-png"),
}
DERIVED_SUFFIX = {"merge1h-hourly": "npz", "merge1h-stations": "parquet", "web": "tar"}
#: what the page shows: layer → product of its frames
WEB_LAYERS = {"maxz": "maxz-png_masked", "merge1h": "merge1h-png"}
NOWCAST = "fct_maxz-png_masked"

ATTRIBUTION = (
    "Radar data: Czech Hydrometeorological Institute (ČHMÚ / CHMI), opendata.chmi.cz, "
    "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). PNG frames cropped to the "
    "data area, with the frame, labels and background made transparent, by MeteoVerdict."
)


def parse_products(spec: str) -> tuple[str, ...]:
    """``observed``, ``forecast``, ``all`` or a comma-separated list of product keys."""
    if spec in PRESETS:
        return PRESETS[spec]
    keys = tuple(k.strip() for k in spec.split(",") if k.strip())
    unknown = [k for k in keys if k not in BY_KEY]
    if unknown or not keys:
        raise ValueError(
            f"unknown products {unknown}; use {', '.join(PRESETS)} or keys from {', '.join(BY_KEY)}"
        )
    return keys


def stamp(when: datetime) -> str:
    """``YYYYMMDDhhmm`` (UTC), the frame names of the page."""
    return f"{when:%Y%m%d%H%M}"


def parse_stamp(text: str) -> datetime:
    return datetime.strptime(text, "%Y%m%d%H%M").replace(tzinfo=UTC)


def release_tag(day: date) -> str:
    return f"radar-{day:%Y-%m}"


def asset_name(key: str, day: date) -> str:
    """``maxz-hdf5-20261014.tar``; derived assets have their own suffix."""
    return f"{key}-{day:%Y%m%d}.{DERIVED_SUFFIX.get(key, 'tar')}"


def file_url(product: Product, name: str) -> str:
    return f"{BASE_URL}/{product.folder}/{name}"


def parse_listing(product: Product, html: str) -> dict[datetime, str]:
    """File time (UTC) → file name, from an nginx directory listing."""
    regex = product.regex()
    found: dict[datetime, str] = {}
    for name in re.findall(r'href="([^"/?]+)"', html):
        match = regex.fullmatch(name)
        if match:
            when = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M").replace(tzinfo=UTC)
            found[when] = name
    return dict(sorted(found.items()))


def list_files(client: httpx.Client, product: Product) -> dict[datetime, str]:
    response = client.get(f"{BASE_URL}/{product.folder}/")
    response.raise_for_status()
    return parse_listing(product, response.text)


def complete_days(times: Iterable[datetime], now: datetime) -> list[date]:
    """UTC days with files whose end is at least ``COMPLETE_AFTER`` ago, oldest first."""
    days = {t.date() for t in times}
    return sorted(
        d
        for d in days
        if datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(days=1) <= now - COMPLETE_AFTER
    )


def download(client: httpx.Client, url: str) -> bytes:
    response = client.get(url)
    response.raise_for_status()
    return response.content


def fetch_all(
    client: httpx.Client, product: Product, names: list[str], workers: int = 8
) -> list[bytes]:
    """Download the files in parallel (the server answers small files quickly)."""
    urls = [file_url(product, n) for n in names]
    if workers <= 1 or len(urls) <= 1:
        return [download(client, u) for u in urls]
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(lambda u: download(client, u), urls))


def write_tar(path: Path, members: Iterable[tuple[str, bytes, datetime]]) -> int:
    """An uncompressed tar of ``(name, content, time)``, in the given order."""
    n = 0
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as tar:
        for name, content, when in members:
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(content), int(when.timestamp()), 0o644
            tar.addfile(info, io.BytesIO(content))
            n += 1
    return n


# --- frames of the page --------------------------------------------------------------


def web_frame(png: bytes, no_coverage_alpha: int = NO_COVERAGE_ALPHA) -> bytes:
    """A ČHMÚ composite PNG cropped to the grid, frame and labels transparent.

    Keeps the palette (and so ČHMÚ's colour scale); the grey outside the radar coverage
    gets ``no_coverage_alpha`` (faint by default). The result covers exactly
    ``GRID_WEST … GRID_NORTH``.
    """
    image = Image.open(io.BytesIO(png))
    if image.mode != "P" or image.size != (680, 460):
        raise ValueError(f"unexpected PNG {image.mode} {image.size}")
    cropped = image.crop((0, PNG_TOP, GRID_COLS, PNG_TOP + GRID_ROWS))
    alpha = bytearray([255] * 256)
    alpha[0] = alpha[PNG_FRAME] = 0
    alpha[PNG_NO_COVERAGE] = no_coverage_alpha
    out = io.BytesIO()
    cropped.save(out, format="PNG", optimize=True, transparency=bytes(alpha))
    return out.getvalue()


_NOWCAST_MEMBER = re.compile(r"\.(\d{8})\.(\d{4})\.(\d+)\.png$")


def nowcast_frames(tar_bytes: bytes) -> list[tuple[datetime, int, bytes]]:
    """``(valid time, lead in minutes, PNG)`` of a nowcast tar, by lead."""
    frames = []
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        for member in tar.getmembers():
            match = _NOWCAST_MEMBER.search(member.name)
            if not member.isfile() or not match:
                continue
            when = datetime.strptime(match[1] + match[2], "%Y%m%d%H%M").replace(tzinfo=UTC)
            content = tar.extractfile(member)
            if content is not None:
                frames.append((when, int(match[3]), content.read()))
    return sorted(frames, key=lambda f: f[1])


def frame_index(root: Path, nowcast: dict | None = None, now: datetime | None = None) -> dict:
    """``index.json`` of a frame folder: the frame times of every layer."""
    index: dict = {
        "version": 1,
        "bounds": [[GRID_WEST, GRID_SOUTH], [GRID_EAST, GRID_NORTH]],
        "attribution": ATTRIBUTION,
    }
    if now is not None:
        index["generated"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    for layer in WEB_LAYERS:
        folder = root / layer
        index[layer] = sorted(p.stem for p in folder.glob("*.png")) if folder.exists() else []
    if nowcast is not None:
        index["nowcast"] = nowcast
    return index


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")


def update_live(
    client: httpx.Client,
    root: Path,
    now: datetime,
    hours: float = 24,
    log: Callable[[str], None] = print,
) -> dict:
    """Bring the live folder up to date: frames of the last ``hours`` and the newest nowcast.

    Downloads only frames that are missing, deletes the older ones, rewrites
    ``index.json``. Layout as in ``web-YYYYMMDD.tar``: ``maxz/<stamp>.png``,
    ``merge1h/<stamp>.png`` and ``nowcast/<stamp>.png`` (valid time).
    """
    cutoff = now - timedelta(hours=hours)
    for layer, key in WEB_LAYERS.items():
        product = BY_KEY[key]
        folder = root / layer
        folder.mkdir(parents=True, exist_ok=True)
        wanted = {stamp(t): n for t, n in list_files(client, product).items() if t >= cutoff}
        have = {p.stem for p in folder.glob("*.png")}
        missing = sorted(set(wanted) - have)
        for name, content in zip(
            missing, fetch_all(client, product, [wanted[s] for s in missing]), strict=True
        ):
            frame = web_frame(content, LAYER_NO_COVERAGE_ALPHA[layer])
            (folder / f"{name}.png").write_bytes(frame)
        for old in have - set(wanted):
            if parse_stamp(old) < cutoff:
                (folder / f"{old}.png").unlink()
        log(f"live {layer}: {len(missing)} new, {len(wanted)} in the last {hours:g} h")

    nowcast = None
    runs = list_files(client, BY_KEY[NOWCAST])
    old_index = root / "index.json"
    previous = json.loads(old_index.read_text()).get("nowcast") if old_index.exists() else None
    if runs:
        base, name = max(runs.items())
        folder = root / "nowcast"
        if previous and previous.get("base") == stamp(base) and folder.exists():
            nowcast = previous
        else:
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True)
            frames = nowcast_frames(download(client, file_url(BY_KEY[NOWCAST], name)))
            for when, _, content in frames:
                frame = web_frame(content, LAYER_NO_COVERAGE_ALPHA["nowcast"])
                (folder / f"{stamp(when)}.png").write_bytes(frame)
            nowcast = {
                "base": stamp(base),
                "frames": [{"time": stamp(w), "lead": lead} for w, lead, _ in frames],
            }
            log(f"live nowcast from {stamp(base)}: {len(frames)} frames")
    index = frame_index(root, nowcast, now)
    write_json(root / "index.json", index)
    (root / "README.md").write_text(
        "# MeteoVerdict radar, live\n\nThe radar frames of the last hours and the newest "
        "nowcast for https://jerrywoof.github.io/MeteoVerdict/radar.html, replaced every "
        "few minutes by the Radar workflow (this branch has a single commit).\n\n"
        f"{ATTRIBUTION}\n",
        encoding="utf-8",
    )
    return index


# --- derived data from MERGE ----------------------------------------------------------


@dataclass
class MergeField:
    time: datetime  # end of the hour
    codes: np.ndarray  # uint16, rows north → south
    gain: float
    offset: float
    nodata: float
    undetect: float
    where: dict

    def mm(self) -> np.ndarray:
        """Precipitation in mm (float32): undetect → 0, nodata → NaN."""
        values = self.codes.astype(np.float32) * self.gain + self.offset
        values[self.codes == self.undetect] = 0.0
        values[self.codes == self.nodata] = np.nan
        return values


def _attrs(group) -> dict:
    return {k: v.decode() if isinstance(v, bytes) else v for k, v in group.attrs.items()}


def read_merge(content: bytes) -> MergeField:
    with h5py.File(io.BytesIO(content), "r") as f:
        what, data_what = _attrs(f["dataset1/what"]), _attrs(f["dataset1/data1/what"])
        if data_what.get("quantity") != "ACRR":
            raise ValueError(f"not a precipitation sum: {data_what.get('quantity')}")
        when = datetime.strptime(what["enddate"] + what["endtime"], "%Y%m%d%H%M%S")
        return MergeField(
            when.replace(tzinfo=UTC),
            f["dataset1/data1/data"][()],
            float(data_what["gain"]),
            float(data_what["offset"]),
            float(data_what["nodata"]),
            float(data_what["undetect"]),
            _attrs(f["where"]),
        )


def mercator(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lon, lat = np.asarray(lon, dtype=float), np.asarray(lat, dtype=float)
    x = EARTH_RADIUS * np.radians(lon)
    y = EARTH_RADIUS * np.log(np.tan(math.pi / 4 + np.radians(lat) / 2))
    return x, y


def grid_cells(where: dict, lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Row (from the north) and column of the grid cell containing each point; -1 outside."""
    x, y = mercator(lon, lat)
    west, north = mercator(np.array([where["UL_lon"]]), np.array([where["UL_lat"]]))
    col = np.floor((x - west[0]) / float(where["xscale"])).astype(np.int64)
    row = np.floor((north[0] - y) / float(where["yscale"])).astype(np.int64)
    inside = (col >= 0) & (col < int(where["xsize"])) & (row >= 0) & (row < int(where["ysize"]))
    return np.where(inside, row, -1), np.where(inside, col, -1)


def hourly(fields: list[MergeField]) -> list[MergeField]:
    """The fields at full hours (the sums of whole clock hours), by time."""
    return sorted((f for f in fields if f.time.minute == 0), key=lambda f: f.time)


def write_hourly_grids(path: Path, fields: list[MergeField]) -> None:
    first = fields[0]
    np.savez_compressed(
        path,
        acrr=np.stack([f.codes for f in fields]).astype(np.uint16),
        time=np.array([stamp(f.time) for f in fields]),
        gain=first.gain,
        offset=first.offset,
        nodata=first.nodata,
        undetect=first.undetect,
        west=first.where["UL_lon"],
        north=first.where["UL_lat"],
        east=first.where["LR_lon"],
        south=first.where["LR_lat"],
        xscale=first.where["xscale"],
        yscale=first.where["yscale"],
        projdef=first.where["projdef"],
    )


def station_values(fields: list[MergeField], stations: pl.DataFrame) -> pl.DataFrame:
    """Hourly MERGE precipitation (mm) in the grid cell of each station inside the grid."""
    rows, cols = grid_cells(fields[0].where, stations["lon"].to_numpy(), stations["lat"].to_numpy())
    inside = rows >= 0
    ids, rows, cols = stations["id"].to_numpy()[inside], rows[inside], cols[inside]
    n = len(ids)
    values = np.concatenate([f.mm()[rows, cols] for f in fields]) if fields else np.array([])
    return pl.DataFrame(
        {
            "station_id": np.tile(ids, len(fields)),
            "time": pl.Series([f.time for f in fields for _ in range(n)]).cast(
                pl.Datetime("us", "UTC")
            ),
            "precipitation": values.astype(np.float32),
            "grid_row": np.tile(rows, len(fields)).astype(np.int16),
            "grid_col": np.tile(cols, len(fields)).astype(np.int16),
        }
    ).with_columns(pl.col("precipitation").fill_nan(None))


# --- the archive ----------------------------------------------------------------------


class Store(Protocol):
    def names(self, tag: str) -> set[str]: ...

    def put(self, tag: str, name: str, path: Path, label: str = "") -> None: ...


class LocalStore:
    """Files under ``root/<tag>/<name>``, the same layout as a mirror of the releases."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def names(self, tag: str) -> set[str]:
        folder = self.root / tag
        return {p.name for p in folder.iterdir() if p.is_file()} if folder.exists() else set()

    def put(self, tag: str, name: str, path: Path, label: str = "") -> None:
        (self.root / tag).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, self.root / tag / name)


@dataclass
class ArchiveResult:
    archived: list[str] = field(default_factory=list)
    skipped: int = 0
    failed: list[str] = field(default_factory=list)
    sizes: dict[str, int] = field(default_factory=dict)  # asset name → bytes


def _derived_wanted(stations: pl.DataFrame | None) -> list[str]:
    return [k for k in DERIVED if k != "merge1h-stations" or stations is not None]


def archive(
    client: httpx.Client,
    store: Store,
    products: tuple[str, ...],
    now: datetime,
    stations: pl.DataFrame | None = None,
    days: list[date] | None = None,
    derived: bool = True,
    log: Callable[[str], None] = print,
) -> ArchiveResult:
    """Archive every complete day on the server that is not in ``store`` yet, oldest first.

    ``days`` restricts the run to those days (they must still be on the server).
    Derived assets are made when their source products are listed on the server.
    """
    result = ArchiveResult()
    wanted_derived = _derived_wanted(stations) if derived else []
    sources = set(products) | {s for k in wanted_derived for s in DERIVED[k]}
    listings: dict[str, dict[datetime, str]] = {}
    for key in sorted(sources):
        try:
            listings[key] = list_files(client, BY_KEY[key])
        except httpx.HTTPError as exc:  # the other products may still work
            log(f"failed to list {key}: {exc}")
            if key in products:
                result.failed.append(f"{key} listing")
            listings[key] = {}
    all_times = [t for listing in listings.values() for t in listing]
    todo = complete_days(all_times, now) if days is None else sorted(days)
    have: dict[str, set[str]] = {}

    for day in todo:
        tag = release_tag(day)
        if tag not in have:
            have[tag] = store.names(tag)
        by_day = {k: {t: n for t, n in v.items() if t.date() == day} for k, v in listings.items()}
        missing = [k for k in products if asset_name(k, day) not in have[tag] and by_day[k]]
        result.skipped += sum(asset_name(k, day) in have[tag] for k in products)
        missing_derived = [
            k
            for k in wanted_derived
            if asset_name(k, day) not in have[tag] and all(by_day[s] for s in DERIVED[k])
        ]
        need = set(missing) | {s for k in missing_derived for s in DERIVED[k]}
        if not need:
            continue
        files: dict[str, list[tuple[str, bytes, datetime]]] = {}
        with tempfile.TemporaryDirectory() as tmp:
            for key in sorted(need):
                names = by_day[key]
                try:
                    contents = fetch_all(client, BY_KEY[key], list(names.values()))
                except httpx.HTTPError as exc:
                    log(f"failed to download {key} {day}: {exc}")
                    result.failed.append(asset_name(key, day))
                    continue
                files[key] = [(n, c, t) for (t, n), c in zip(names.items(), contents, strict=True)]
            for key in missing:
                if key not in files:
                    continue
                name = asset_name(key, day)
                path = Path(tmp) / name
                count = write_tar(path, files[key])
                _put(store, tag, name, path, f"files={count}", result, log)
            for key in missing_derived:
                if not all(s in files for s in DERIVED[key]):
                    continue
                name = asset_name(key, day)
                path = Path(tmp) / name
                try:
                    label = _derive(key, files, stations, path)
                except Exception as exc:  # keep going: the raw files are archived
                    log(f"failed {name}: {exc}")
                    result.failed.append(name)
                    continue
                _put(store, tag, name, path, label, result, log)
    return result


def _put(store: Store, tag: str, name: str, path: Path, label: str, result, log) -> None:
    try:
        store.put(tag, name, path, label=label)
    except Exception as exc:  # e.g. an upload error: the next run tries again
        log(f"failed to store {name}: {exc}")
        result.failed.append(name)
        return
    size = path.stat().st_size
    result.archived.append(name)
    result.sizes[name] = size
    log(f"archived {name} ({label}, {size / 1e6:.1f} MB)")


def _derive(
    key: str,
    files: dict[str, list[tuple[str, bytes, datetime]]],
    stations: pl.DataFrame | None,
    path: Path,
) -> str:
    if key == "web":
        members = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for layer, source in WEB_LAYERS.items():
                (root / layer).mkdir()
                for _, content, when in files[source]:
                    frame = web_frame(content, LAYER_NO_COVERAGE_ALPHA[layer])
                    (root / layer / f"{stamp(when)}.png").write_bytes(frame)
                    members.append((f"{layer}/{stamp(when)}.png", frame, when))
            index = json.dumps(frame_index(root), separators=(",", ":")).encode()
        last = max(m[2] for m in members)
        count = write_tar(path, [("index.json", index, last), *members])
        return f"files={count}"
    fields = hourly([read_merge(c) for _, c, _ in files["merge1h-hdf5"]])
    if not fields:
        raise ValueError("no MERGE field at a full hour")
    if key == "merge1h-hourly":
        write_hourly_grids(path, fields)
        return f"hours={len(fields)}"
    assert stations is not None
    table = station_values(fields, stations)
    table.write_parquet(path, compression="zstd")
    return f"hours={len(fields)}"


# --- local mirror ---------------------------------------------------------------------


def mirror(store, out_dir: Path, since: str = "", log: Callable[[str], None] = print) -> int:
    """Copy every ``radar-YYYY-MM`` release asset to ``out_dir/<tag>/<name>`` (resumable:
    files already there with the same size are skipped). ``since``: first month."""
    count = 0
    for tag in store.tags("radar-"):
        if since and tag < f"radar-{since}":
            continue
        for name, asset in sorted(store.assets(tag).items()):
            dest = out_dir / tag / name
            if dest.exists() and dest.stat().st_size == asset.get("size"):
                continue
            store.download(tag, name, dest)
            log(f"downloaded {tag}/{name}")
            count += 1
    return count
