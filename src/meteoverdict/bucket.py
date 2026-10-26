"""Single runs from Open-Meteo's open-data bucket on AWS, without API calls.

Open-Meteo publishes every model run it serves in the public S3 bucket ``s3://openmeteo``
(AWS Registry of Open Data, us-west-2, anonymous HTTPS, CC BY 4.0) as
``data_run/<model>/<YYYY>/<MM>/<DD>/<HHMM>Z/<variable>.om`` plus a ``meta.json``
(``valid_times``, the grid's ``crs_wkt``), and keeps these per-run files for about three
months. ``.om`` files are chunked (a strip of grid points x all lead times), so the ~100
stations of ``run-stations.csv`` are read by HTTP range requests (``omfiles``), a few
kB each, instead of downloading whole fields.

**Same values as the Single Runs API** (``runs``; checked on the runs of 2026-10-13 to
10-16, docs/data-sources.md#single-runs-from-the-bucket), because the reading follows
the API's conventions:

- the grid cell nearest to the station (``cells``: precomputed per station and bucket
  model, committed as ``data/bucket-cells.csv``, rebuilt by ``mvd bucket-cells``);
- temperature corrected to the station's elevation with 0.65 K per 100 m from the
  cell's model surface height (``HSURF.om``; AIFS uses the IFS 0.25° height, AIGFS the
  GFS 0.25° height, as the API does);
- wind speed from the native field or from the u and v components;
- each file's time steps on the run's ``valid_times`` (``file_times``): files of sums
  and maxima over the preceding step (precipitation for most models, the gusts of
  some) leave out the run's first step;
- model names: GFS from ``ncep_gfs013`` (gusts from ``ncep_gfs025``), GEM Global from
  ``cmc_gem_gdps_15km``, ARPEGE World from ``meteofrance_arpege_world025``;
- precipitation below 0 (a few packing artefacts) as 0.

**Further variables** (``EXTRA``, ``read_run(extra=True)``, since 2026-10-19): the files
the run's ``meta.json`` lists, derived where the API derives them; they never decide
whether a model-run is taken (docs/data-sources.md#further-variables).

Differences that remain: ECMWF IFS HRES (O1280 grid) where the API picks a neighbouring
cell (temperature 0.23 °C mean absolute difference) and DMI HARMONIE temperature
(0.13 °C) at a few cell edges; the rest is equal to rounding.

**Native steps only:** a run's rows are its own output times (e.g. ICON-EU hourly to
78 h, then 3-hourly; AIFS 6-hourly). The API interpolates the hours in between; those
are not invented here. Precipitation at a native time is the total since the previous
native time (as in the API's convention after ``runs.native``).

**Complete or not at all** (``read_run``): a model-run is taken only when its
``meta.json`` is there, its ``valid_times`` reach every native lead hour up to the
model's usual horizon (ECMWF writes IFS in stages: first to 72 h, later to the end),
every needed variable file is there with that many time steps, and every variable has
values at most stations. Otherwise it is tried again later and, once it is
``runs.BUCKET_FINAL_H`` old, recorded as missing in the bucket (``runs.State.bucket_missing``),
so that the Single Runs API is asked for just that model-run (``runs.collect``).
Dropped S3 connections are retried (``Bucket``).
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path

import httpx
import numpy as np
import polars as pl

from meteoverdict import partitions, runs
from meteoverdict.models import Model

BASE_URL = "https://openmeteo.s3.amazonaws.com"
#: Open-Meteo's elevation correction of temperature_2m (K per m)
LAPSE_RATE = 0.0065
#: A variable needs values at this share of the stations (ICON-D2 has none at one)
MIN_STATIONS = 0.5
#: Plausible values; anything else means a file read while it was being replaced
PLAUSIBLE = {
    "temperature_2m": (-70.0, 60.0),
    "precipitation": (-50.0, 500.0),
    "wind_speed_10m": (0.0, 150.0),
    "wind_gusts_10m": (0.0, 200.0),
}
#: Values are stored to this many decimals (the API rounds to 1; the elevation correction
#: and u/v → speed would otherwise leave noise digits that compress badly)
DECIMALS = 2
#: Model-runs failing in a row (after the retries) before a collection gives up
MAX_ERRORS = 20
CELLS_FILE = "bucket-cells.csv"
CELL_SCHEMA = {
    "bucket_model": pl.String,
    "station_id": pl.String,
    "y": pl.Int64,
    "x": pl.Int64,
    "ny": pl.Int64,
    "nx": pl.Int64,
    "grid_lat": pl.Float64,
    "grid_lon": pl.Float64,
    "grid_elevation": pl.Float64,
    "grid_distance_km": pl.Float64,
}


@dataclass(frozen=True)
class Source:
    """Where and how a project model is read from the bucket."""

    #: bucket model of temperature, precipitation and wind
    bucket: str
    #: "speed": ``wind_speed_10m`` itself; "uv": from the u and v components
    wind: str = "uv"
    #: bucket model of ``wind_gusts_10m``: "" = ``bucket``, None = not in the bucket
    gusts: str | None = ""
    #: last lead hour of a complete run, by run hour (default 120, the stored maximum)
    horizon_h: dict[int, int] = field(default_factory=dict)

    @property
    def gust_model(self) -> str | None:
        return self.bucket if self.gusts == "" else self.gusts

    def extra_files(
        self, listed: dict[str, set[str]], auxiliary: bool = False
    ) -> dict[str, tuple[str, Derived]]:
        """Further variable -> (bucket model, ``Derived``) for a run whose bucket models
        list ``listed`` variable files; variables none of them has are left out. With
        ``auxiliary`` also ``AUXILIARY``."""
        models = [self.bucket] + [m for m in (self.gust_model,) if m and m != self.bucket]
        found = {}
        for variable, choices in (EXTRA | AUXILIARY if auxiliary else EXTRA).items():
            for choice in choices:
                where = [m for m in models if set(choice.files) <= listed.get(m, set())]
                if where:
                    found[variable] = (where[0], choice)
                    break
        return found

    def horizon(self, run_hour: int) -> int:
        return min(self.horizon_h.get(run_hour, runs.MAX_LEAD_H), runs.MAX_LEAD_H)

    def files(self) -> dict[str, list[tuple[str, str]]]:
        """variable -> the (bucket model, file) it is made of."""
        wind = (
            [(self.bucket, "wind_speed_10m")]
            if self.wind == "speed"
            else [(self.bucket, "wind_u_component_10m"), (self.bucket, "wind_v_component_10m")]
        )
        found = {
            "temperature_2m": [(self.bucket, "temperature_2m")],
            "precipitation": [(self.bucket, "precipitation")],
            "wind_speed_10m": wind,
        }
        if self.gust_model:
            found["wind_gusts_10m"] = [(self.gust_model, "wind_gusts_10m")]
        return found


# --- the further variables --------------------------------------------------------------


def _magnus(t: np.ndarray) -> np.ndarray:
    """The exponent of Open-Meteo's Magnus formula (a = 17.625, b = 243.04 °C)."""
    return 17.625 * t / (243.04 + t)


def _relative_humidity(t: np.ndarray, td: np.ndarray) -> np.ndarray:
    return 100 * np.exp(_magnus(td) - _magnus(t))


def _dew_point(t: np.ndarray, rh: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        alpha = np.log(np.clip(rh, 0.01, None) / 100) + _magnus(t)
    return 243.04 * alpha / (17.625 - alpha)


def _hpa(pressure: np.ndarray) -> np.ndarray:
    """Pressure in hPa (ECMWF IFS HRES's file is in Pa, checked 2026-10-19)."""
    return np.where(pressure > 2000, pressure / 100, pressure)


def _direction(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Where the wind comes from, 0-360° (0 north, 90 east)."""
    return np.mod(270 - np.degrees(np.arctan2(v, u)), 360)


@dataclass(frozen=True)
class Derived:
    """A further variable from bucket files: one file as it is, or ``combine`` of
    several (each on the run's valid times)."""

    files: tuple[str, ...]
    combine: Callable[..., np.ndarray] | None = None


#: How each of ``runs.EXTRA_VARIABLES`` is read, in order of preference: the first whose
#: files a model's run lists (``meta.json`` "variables") is used; none: null. Which
#: model has which (runs of 2026-10-18, checked 2026-10-19) is in
#: docs/data-sources.md#further-variables; the derivations are Open-Meteo's.
EXTRA: dict[str, tuple[Derived, ...]] = {
    "relative_humidity_2m": (
        Derived(("relative_humidity_2m",)),
        Derived(("temperature_2m", "dew_point_2m"), _relative_humidity),  # IFS HRES
    ),
    "dew_point_2m": (
        Derived(("dew_point_2m",)),  # ALADIN, IFS HRES
        Derived(("temperature_2m", "relative_humidity_2m"), _dew_point),
    ),
    "pressure_msl": (Derived(("pressure_msl",), _hpa),),  # GFS: from ncep_gfs025
    "wind_direction_10m": (
        Derived(("wind_direction_10m",)),  # the models read with wind speed itself
        Derived(("wind_u_component_10m", "wind_v_component_10m"), _direction),
    ),
    "shortwave_radiation": (
        Derived(("shortwave_radiation",)),
        Derived(("direct_radiation", "diffuse_radiation"), np.add),  # ICON
    ),
    "cloud_cover": (Derived(("cloud_cover",)),),
    "cloud_cover_low": (Derived(("cloud_cover_low",)),),
    "sunshine_duration": (Derived(("sunshine_duration",)),),  # ALADIN, GeoSphere AROME
    # Open-Meteo: 7 cm of snow per 10 mm of water (CMA's own "snowfall" file is left
    # out: its unit is unverified)
    "snowfall": (Derived(("snowfall_water_equivalent",), lambda swe: swe * 0.7),),
    "snow_depth": (Derived(("snow_depth",)),),
    "snow_depth_water_equivalent": (Derived(("snow_depth_water_equivalent",)),),
    "surface_temperature": (
        Derived(("surface_temperature",)),
        Derived(("soil_temperature_0cm",)),  # ICON: the soil's surface
    ),
    "cape": (Derived(("cape",)),),  # GFS: from ncep_gfs025
    "visibility": (Derived(("visibility",)),),  # GFS: from ncep_gfs025
}
#: Radiation variables (W/m², means over the preceding step)
RADIATION = ("shortwave_radiation", "direct_radiation", "diffuse_radiation")
#: Météo-France keeps its radiation in the bucket with a conversion factor that the API's
#: readers undo (open-meteo ``MeteoFranceSurfaceVariable
#: .shortwaveRadiationArchiveCorrectionFactor``, 10^7 / 3600²): the bucket's ARPEGE values
#: are 1.296 times the API's (checked on the runs of 2026-10-19 12 and 10-20 00 UTC;
#: stored that way until 2026-10-20, then read again: ``runs.EXTRA_FIXES``)
RADIATION_SCALE = {
    "meteofrance_arpege_europe": 1e7 / 3600**2,
    "meteofrance_arpege_world025": 1e7 / 3600**2,
}
#: Files read only when asked for by name (``read_run(extra=[...])``: the outlook's
#: sunshine, as the API derives it from the direct radiation); not columns of the single
#: runs. Where a model has neither, the outlook splits the shortwave radiation itself.
AUXILIARY: dict[str, tuple[Derived, ...]] = {
    "direct_radiation": (Derived(("direct_radiation",)),),  # ICON, IFS HRES, UKMO, DMI
    "diffuse_radiation": (Derived(("diffuse_radiation",)),),  # ICON, GFS
}
#: Plausible further values; others (packing artefacts, a file being replaced) are
#: dropped (null), the model-run is still taken
EXTRA_PLAUSIBLE = {
    "relative_humidity_2m": (0.0, 105.0),
    "dew_point_2m": (-80.0, 45.0),
    "pressure_msl": (850.0, 1100.0),
    "wind_direction_10m": (0.0, 360.0),
    "shortwave_radiation": (-50.0, 1500.0),  # GEM Global: down to -11 at night
    "cloud_cover": (0.0, 100.5),
    "cloud_cover_low": (0.0, 100.5),
    "sunshine_duration": (-60.0, 6 * 3600.0),  # ALADIN: a few seconds below 0
    "snowfall": (-1.0, 300.0),
    "snow_depth": (0.0, 30.0),
    "snow_depth_water_equivalent": (0.0, 10_000.0),
    "surface_temperature": (-80.0, 80.0),
    "cape": (-1.0, 20_000.0),
    "visibility": (0.0, 1_000_000.0),
}
#: Clipped to these bounds after the plausibility check (rounding noise, packing)
EXTRA_CLIP = {
    "relative_humidity_2m": (0.0, 100.0),
    "shortwave_radiation": (0.0, None),
    "cloud_cover": (0.0, 100.0),
    "cloud_cover_low": (0.0, 100.0),
    "sunshine_duration": (0.0, None),
    "snowfall": (0.0, None),
    "cape": (0.0, None),
}
#: Decimals of the further variables (``DECIMALS`` otherwise)
EXTRA_DECIMALS = {
    "relative_humidity_2m": 0,
    "pressure_msl": 1,
    "wind_direction_10m": 0,
    "shortwave_radiation": 0,
    "cloud_cover": 0,
    "cloud_cover_low": 0,
    "sunshine_duration": 0,
    "snow_depth": 3,
    "dew_point_2m": 1,
    "surface_temperature": 1,
    "cape": 0,
    "visibility": 0,
}


def meta_variables(meta: dict) -> set[str]:
    """The variable files a run lists (``meta.json`` "variables": a list, or the text of
    a Python list as Open-Meteo writes it)."""
    found = meta.get("variables") or []
    if isinstance(found, str):
        found = re.findall(r"'([^']+)'", found)
    return set(found)


def _all(hours: int) -> dict[int, int]:
    """The same horizon for every run hour (also the 3-hourly runs in between that the
    outlook reads: ICON-D2, AROME AT, KNMI, DMI)."""
    return {h: hours for h in range(24)}


#: The 19 models (checked against the bucket and the API 2026-10-13..16).
SOURCES: dict[str, Source] = {
    "chmi_aladin_cz_1km": Source("chmi_aladin_cz_1km", "speed", horizon_h=_all(72)),
    "chmi_aladin_central_europe_2km": Source(
        "chmi_aladin_central_europe_2km", "speed", horizon_h=_all(72)
    ),
    "dwd_icon_d2": Source("dwd_icon_d2", horizon_h=_all(48)),
    # the runs in between (03, 09, 15, 21 UTC) reach 30 h (the outlook reads them)
    "dwd_icon_eu": Source("dwd_icon_eu", horizon_h={h: 30 for h in (3, 9, 15, 21)}),
    "ecmwf_ifs": Source("ecmwf_ifs"),
    "ecmwf_ifs025": Source("ecmwf_ifs025"),
    "ecmwf_aifs025_single": Source("ecmwf_aifs025_single", gusts=None),
    "ncep_gfs_global": Source("ncep_gfs013", gusts="ncep_gfs025"),
    "ukmo_global_deterministic_10km": Source(
        "ukmo_global_deterministic_10km", "speed", horizon_h={6: 60, 18: 60}
    ),
    "meteofrance_arpege_europe": Source("meteofrance_arpege_europe", horizon_h=_all(102)),
    "geosphere_arome_austria": Source("geosphere_arome_austria", "speed", horizon_h=_all(60)),
    "knmi_harmonie_arome_europe": Source("knmi_harmonie_arome_europe", "speed", horizon_h=_all(60)),
    "dmi_harmonie_arome_europe": Source("dmi_harmonie_arome_europe", "speed", horizon_h=_all(59)),
    "dwd_icon": Source("dwd_icon"),
    "gem_global": Source("cmc_gem_gdps_15km", "speed"),
    "jma_gsm": Source("jma_gsm", gusts=None),
    "cma_grapes_global": Source("cma_grapes_global"),
    "meteofrance_arpege_world": Source("meteofrance_arpege_world025", horizon_h=_all(102)),
    "ncep_aigfs025": Source("ncep_aigfs025", gusts=None),
}

#: Surface height for the temperature correction from another bucket model on the same
#: grid (the API's choice for AIFS; AIGFS has no HSURF.om of its own)
HSURF_FROM = {"ecmwf_aifs025_single": "ecmwf_ifs025", "ncep_aigfs025": "ncep_gfs025"}
#: Explicit PROJ for the rotated grid (KNMI), instead of parsing its WKT
PROJ = {
    "knmi_harmonie_arome_europe": (
        "+proj=ob_tran +o_proj=longlat +o_lon_p=0 +o_lat_p=35 +lon_0=-8.000001 "
        "+R=6371229 +to_meter=0.0174532925199433"
    )
}


def bucket_models() -> list[str]:
    """Every bucket model read (main and gust sources), sorted."""
    return sorted({b for s in SOURCES.values() for v in s.files().values() for b, _ in v})


def run_path(bucket_model: str, run: datetime) -> str:
    return f"data_run/{bucket_model}/{run:%Y/%m/%d/%H%M}Z"


def native_leads(model: Model, horizon: int) -> list[int]:
    """Lead hours 1…``horizon`` with the model's own output (``Model.native_hour``)."""
    return [h for h in range(1, horizon + 1) if model.native_hour(h)]


# --- HTTP ----------------------------------------------------------------------------


class Bucket:
    """Reads ``meta.json`` and ``.om`` files of the bucket over HTTPS with retries.

    It is also the file-system object ``omfiles.OmFileReader.from_fsspec`` reads through
    (``size`` and ``cat_file``), so range reads go through the same retries. S3 answers
    403 for a key that does not exist (no listing for anonymous users), like 404."""

    def __init__(
        self,
        client: httpx.Client,
        base: str = BASE_URL,
        tries: int = 6,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client, self.base, self.tries, self.sleep = client, base.rstrip("/"), tries, sleep
        self._sizes: dict[str, int] = {}
        self.requests = 0
        # what the run cost (``summary``): retries after a dropped connection, 429/5xx answer or
        # a 403/404 miss, bytes received, seconds spent in requests and asleep between retries
        self.retries = self.throttled = self.missing = self.bytes = 0
        self.request_s = self.sleep_s = 0.0
        self._stats_lock = threading.Lock()

    def summary(self) -> str:
        """One line: requests, retries, throttled answers, misses, MB, and the seconds all
        threads together spent waiting for answers and sleeping before retries."""
        return (
            f"bucket: {self.requests} requests, {self.retries} retries, {self.throttled} "
            f"throttled (429/5xx), {self.missing} missing, {self.bytes / 1e6:.1f} MB, "
            f"{self.request_s:.0f} s in requests (all threads), {self.sleep_s:.0f} s asleep"
        )

    def url(self, path: str) -> str:
        return f"{self.base}/{path}"

    def _request(self, method: str, url: str, headers: dict | None = None) -> httpx.Response:
        for attempt in range(self.tries):
            started = time.monotonic()
            try:
                response = self.client.request(method, url, headers=headers)
            except httpx.TransportError:  # dropped connections, timeouts
                self._count(time.monotonic() - started, retry=attempt < self.tries - 1)
                if attempt == self.tries - 1:
                    raise
            else:
                body = len(response.content) if response.status_code < 400 else 0
                miss = response.status_code in (403, 404)
                bad = response.status_code >= 500 or response.status_code == 429
                self._count(
                    time.monotonic() - started,
                    nbytes=body,
                    miss=miss,
                    throttled=bad,
                    retry=bad and attempt < self.tries - 1,
                )
                if miss:
                    raise FileNotFoundError(url)
                if response.status_code < 500 and response.status_code != 429:
                    response.raise_for_status()
                    return response
                if attempt == self.tries - 1:
                    response.raise_for_status()
            wait = min(30.0, 0.5 * 2**attempt)
            with self._stats_lock:
                self.sleep_s += wait
            self.sleep(wait)
        raise RuntimeError("unreachable")

    def _count(self, seconds: float, nbytes: int = 0, miss=False, throttled=False, retry=False) -> None:
        with self._stats_lock:
            self.requests += 1
            self.request_s += seconds
            self.bytes += nbytes
            self.missing += miss
            self.throttled += throttled
            self.retries += retry

    def meta(self, bucket_model: str, run: datetime) -> dict | None:
        """The run's ``meta.json``, or None when it is not there."""
        try:
            return self._request("GET", self.url(f"{run_path(bucket_model, run)}/meta.json")).json()
        except FileNotFoundError:
            return None

    # the fsspec-like interface of omfiles
    def size(self, path: str) -> int:
        if path not in self._sizes:
            response = self._request("HEAD", path)
            self._sizes[path] = int(response.headers["content-length"])
        return self._sizes[path]

    def cat_file(self, path: str, start: int | None = None, end: int | None = None, **_) -> bytes:
        last = "" if end is None else str(end - 1)
        return self._request("GET", path, {"Range": f"bytes={start or 0}-{last}"}).content

    def open(self, path: str):
        """An ``OmFileReader`` of ``path`` (relative to the bucket), None if absent."""
        from omfiles import OmFileReader

        url = self.url(path)
        try:
            self.size(url)
        except FileNotFoundError:
            return None
        return OmFileReader.from_fsspec(self, url)


# --- grid cells ----------------------------------------------------------------------

#: Points of ECMWF's O1280 reduced Gaussian grid (IFS HRES 9 km)
O1280_POINTS = 6_599_680


class _Identity:
    """``transform`` of a latitude/longitude grid: x is the longitude, y the latitude."""

    @staticmethod
    def transform(x: float, y: float) -> tuple[float, float]:
        return x, y


class Grid:
    """Maps a station to the array index of its nearest grid cell (``nearest``), from a
    run's ``meta.json`` (``crs_wkt`` with its ``BBOX``) and the file's shape. Regular
    lat/lon, Lambert conformal (ALADIN Central Europe, DMI) and rotated (KNMI) grids
    through pyproj; ECMWF's O1280 reduced Gaussian grid (shape (1, 6599680, t)) from its
    Gaussian latitudes with 4i + 16 points on ring i."""

    def __init__(self, bucket_model: str, wkt: str, shape: tuple[int, ...]) -> None:
        self.model = bucket_model
        if shape[0] == 1 and shape[1] == O1280_POINTS:
            self.kind = "o1280"
            n = 1280
            x, _ = np.polynomial.legendre.leggauss(2 * n)
            self.lats = np.degrees(np.arcsin(x))[::-1]  # north to south
            rings = np.array([4 * i + 16 for i in range(1, n + 1)])
            self.npts = np.concatenate([rings, rings[::-1]])
            self.offsets = np.concatenate([[0], np.cumsum(self.npts)[:-1]])
            return
        self.kind = "regular"
        self.ny, self.nx = shape[0], shape[1]
        box = [float(v) for v in re.search(r"BBOX\[([^\]]+)\]", wkt).group(1).split(",")]
        if wkt.lstrip().startswith("GEOGCRS") and bucket_model not in PROJ:
            # plain latitude/longitude: no projection (and no pyproj in the process:
            # loaded next to eccodes or OpenCV it crashed the interpreter at exit)
            self.fwd = self.inv = _Identity()
        else:
            from pyproj import CRS, Transformer

            crs = CRS.from_proj4(PROJ[bucket_model]) if bucket_model in PROJ else CRS.from_wkt(wkt)
            self.fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
            self.inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        self.x0, self.y0 = self.fwd.transform(box[1], box[0])
        x1, y1 = self.fwd.transform(box[3], box[2])
        self.dx = (x1 - self.x0) / (self.nx - 1)
        self.dy = (y1 - self.y0) / (self.ny - 1)

    def nearest(self, lat: float, lon: float) -> tuple[int, int]:
        """``(y, x)``: the array index (for O1280 ``(0, point)``)."""
        if self.kind == "o1280":
            ring = int(np.argmin(abs(self.lats - lat)))
            n = int(self.npts[ring])
            i = round((lon % 360) / (360 / n)) % n
            return 0, int(self.offsets[ring] + i)
        x, y = self.fwd.transform(lon, lat)
        return round((y - self.y0) / self.dy), round((x - self.x0) / self.dx)

    def around(self, index: tuple[int, int]) -> list[tuple[int, int]]:
        """The 3 x 3 cells around ``index`` within the grid (regular grids)."""
        y, x = index
        return [
            (y + a, x + b)
            for a in (-1, 0, 1)
            for b in (-1, 0, 1)
            if 0 <= y + a < self.ny and 0 <= x + b < self.nx
        ]

    def latlon(self, index: tuple[int, int]) -> tuple[float, float]:
        if self.kind == "o1280":
            ring = int(np.searchsorted(self.offsets, index[1], side="right") - 1)
            lon = (index[1] - self.offsets[ring]) * 360 / self.npts[ring]
            return float(self.lats[ring]), float(lon - 360 if lon > 180 else lon)
        lon, lat = self.inv.transform(self.x0 + index[1] * self.dx, self.y0 + index[0] * self.dy)
        return float(lat), float(lon)


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    a = (
        math.sin((lat2 - lat1) * p / 2) ** 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    )
    return 12742 * math.asin(math.sqrt(a))


def _water(height: float) -> bool:
    """No usable surface height: water (-999 in HSURF.om) or none at all."""
    return math.isnan(height) or height <= -999


def _read_heights(reader, cells: list[tuple[int, int]], pool) -> list[float]:
    """The model surface height of every cell, read by row ``segments``."""
    parts = segments(cells)

    def read(segment):
        y, first, last = segment
        return np.asarray(reader[y, first : last + 1], dtype=np.float64).ravel()

    found = {}
    for (y, first, last), block in zip(parts, pool.map(read, parts), strict=True):
        for x in range(first, last + 1):
            found[(y, x)] = float(block[x - first])
    return [found[cell] for cell in cells]


def _read_point(reader, index: tuple[int, int]) -> np.ndarray:
    return np.asarray(reader[index[0], index[1], :], dtype=np.float32).ravel()


#: points of one grid row at most this many cells apart are read in one request (with the
#: cells between): many points (the obce) cost a few hundred reads instead of thousands
SEGMENT_GAP = 64


def segments(
    indices: Iterable[tuple[int, int]], gap: int = SEGMENT_GAP
) -> list[tuple[int, int, int]]:
    """``(row, first, last)`` column ranges covering ``indices``, near points merged."""
    rows: dict[int, list[int]] = {}
    for y, x in set(indices):
        rows.setdefault(y, []).append(x)
    out = []
    for y, xs in sorted(rows.items()):
        xs.sort()
        start = previous = xs[0]
        for x in xs[1:]:
            if x - previous > gap:
                out.append((y, start, previous))
                start = x
            previous = x
        out.append((y, start, previous))
    return out


def _read_segment(reader, segment: tuple[int, int, int]) -> np.ndarray:
    """The values of ``segment`` as an array (cells, times)."""
    y, first, last = segment
    block = np.asarray(reader[y, first : last + 1, :], dtype=np.float32)
    return block.reshape(last - first + 1, -1)


def build_cells(
    bucket: Bucket,
    stations: pl.DataFrame,
    run: datetime,
    models: Iterable[str] | None = None,
    threads: int = 32,
    log: Callable[[str], None] = lambda _: None,
) -> pl.DataFrame:
    """``CELL_SCHEMA`` rows: per bucket model and station the nearest cell, its position,
    distance and model surface height (``HSURF_FROM``), from the run ``run`` (its
    ``meta.json`` and the shape of a variable file). Network: a few hundred requests."""
    rows = []
    with ThreadPoolExecutor(threads) as pool:
        for bucket_model in models or bucket_models():
            meta = bucket.meta(bucket_model, run)
            if meta is None:
                raise FileNotFoundError(f"{bucket_model}: no meta.json for {run:%Y-%m-%d %H} UTC")
            variable = "wind_gusts_10m" if bucket_model == "ncep_gfs025" else "temperature_2m"
            reader = bucket.open(f"{run_path(bucket_model, run)}/{variable}.om")
            if reader is None:
                raise FileNotFoundError(f"{bucket_model}: no {variable}.om")
            shape = tuple(reader.shape)
            reader.close()
            grid = Grid(bucket_model, meta["crs_wkt"], shape)
            hsurf_model = HSURF_FROM.get(bucket_model, bucket_model)
            hsurf = bucket.open(f"data/{hsurf_model}/static/HSURF.om")
            if hsurf is not None and tuple(hsurf.shape[:2]) != shape[:2]:
                raise ValueError(f"{hsurf_model}: HSURF {hsurf.shape} is not on {shape}")
            points = [
                (sid, lat, lon, grid.nearest(lat, lon))
                for sid, lat, lon in stations.select("id", "lat", "lon").rows()
            ]
            elevations: dict[tuple[int, int], float] = {}
            if hsurf is not None:
                unique = sorted({p[3] for p in points})
                heights = _read_heights(hsurf, unique, pool)
                elevations = dict(zip(unique, heights, strict=True))
                # a water cell (HSURF -999): the nearest land cell of the 3 x 3 around it,
                # as the API does (checked: DMI at Rozkoš, 2026-10-15)
                wet = [p for p in points if _water(elevations[p[3]]) and grid.kind == "regular"]
                around = sorted({c for p in wet for c in grid.around(p[3])} - set(elevations))
                heights = _read_heights(hsurf, around, pool)
                elevations |= dict(zip(around, heights, strict=True))
                for i, (sid, lat, lon, index) in enumerate(points):
                    if (sid, lat, lon, index) not in wet:
                        continue
                    land = [c for c in grid.around(index) if not _water(elevations[c])]
                    if land:
                        best = min(land, key=lambda c: distance_km(lat, lon, *grid.latlon(c)))
                        points[i] = (sid, lat, lon, best)
            if hsurf is not None:
                hsurf.close()
            for sid, lat, lon, index in points:
                glat, glon = grid.latlon(index)
                elevation = elevations.get(index, math.nan)
                rows.append(
                    (
                        bucket_model,
                        sid,
                        index[0],
                        index[1],
                        shape[0],
                        shape[1],
                        glat,
                        glon,
                        None if _water(elevation) else elevation,
                        distance_km(lat, lon, glat, glon),
                    )
                )
            log(f"{bucket_model}: {grid.kind} grid {shape[:2]}, {len(points)} stations")
    return pl.DataFrame(rows, schema=CELL_SCHEMA, orient="row")


def write_cells(cells: pl.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cells.sort("bucket_model", "station_id").with_columns(
        pl.col("grid_lat", "grid_lon").round(5),
        pl.col("grid_elevation").round(1),
        pl.col("grid_distance_km").round(3),
    ).write_csv(path)
    return path


def load_cells(path: Path | None = None) -> pl.DataFrame:
    """The committed cells (``src/meteoverdict/data/bucket-cells.csv``)."""
    source = path or files("meteoverdict").joinpath("data", CELLS_FILE)
    with source.open("rb") as f:
        return pl.read_csv(f.read(), schema=CELL_SCHEMA)


# --- one model-run -------------------------------------------------------------------


@dataclass
class Fetched:
    """A model-run from the bucket: ``rows`` (``runs.SCHEMA``) when complete, else None
    and ``reason`` why not."""

    rows: pl.DataFrame | None
    reason: str = ""
    #: every further variable file the run lists was there (else read it again later)
    extra_complete: bool = True


def _valid_times(meta: dict) -> list[datetime]:
    return [
        datetime.strptime(v, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC) for v in meta["valid_times"]
    ]


def file_times(times: list[datetime], steps: int) -> list[datetime]:
    """The valid times of a file with ``steps`` time steps in a run with ``times``: all
    of them, or, when the file is shorter, from the second on. Sums and maxima over the
    preceding step (precipitation for most models, the gusts of some) have no value at
    the run's start, and their files leave that step out (checked 2026-08-01 and
    2026-10-15: one step shorter, values at the following steps equal to the API's)."""
    return times[:steps] if steps >= len(times) else times[1 : 1 + steps]


def read_run(
    bucket: Bucket,
    model: Model,
    run: datetime,
    stations: pl.DataFrame,
    cells: pl.DataFrame,
    pool: ThreadPoolExecutor,
    extra: bool | Iterable[str] = False,
    max_lead_h: int = runs.MAX_LEAD_H,
) -> Fetched:
    """One model-run at ``stations`` (``id``, ``elevation``), complete or not at all
    (module docstring); with ``extra`` also the further variables (``EXTRA``; all, or
    those named) the run lists, as far as their files are written
    (``Fetched.extra_complete``). Rows up to ``max_lead_h`` (the outlook reads past
    ``runs.MAX_LEAD_H``; completeness is judged up to the usual horizon all the same).
    Network errors other than missing files propagate."""
    readers: dict = {}
    if extra is not True and extra:
        extra = frozenset(extra)
    try:
        return _read_run(bucket, model, run, stations, cells, pool, readers, extra, max_lead_h)
    finally:  # close the readers here, not at interpreter exit (omfiles holds callbacks)
        for reader in readers.values():
            reader.close()


def _read_run(bucket, model, run, stations, cells, pool, readers, extra, max_lead_h) -> Fetched:
    source = SOURCES.get(model.id)
    if source is None:
        return Fetched(None, "not in the bucket")
    files_ = source.files()
    metas = {}
    for bucket_model in sorted({b for parts in files_.values() for b, _ in parts}):
        meta = bucket.meta(bucket_model, run)
        if meta is None:
            return Fetched(None, f"no meta.json ({bucket_model})")
        metas[bucket_model] = meta
    times = {b: _valid_times(m) for b, m in metas.items()}
    need = native_leads(model, source.horizon(run.hour))

    def leads(found: list[datetime]) -> set[int]:
        return {int((t - run).total_seconds() // 3600) for t in found}

    have = leads(times[source.bucket])
    if not set(need) <= have:
        return Fetched(None, f"{len(set(need) & have)} of {len(need)} lead hours written")
    axes, indices, grids = {}, {}, {}
    for variable, parts in files_.items():
        for bucket_model, name in parts:
            reader = bucket.open(f"{run_path(bucket_model, run)}/{name}.om")
            if reader is None:
                return Fetched(None, f"{name}.om missing ({bucket_model})")
            readers[(bucket_model, name)] = reader
            shape = tuple(reader.shape)
            mine = cells.filter(pl.col("bucket_model") == bucket_model)
            if mine.height == 0 or (mine["ny"][0], mine["nx"][0]) != shape[:2]:
                return Fetched(None, f"{bucket_model}: grid {shape[:2]} not in the cells file")
            grids[bucket_model] = shape[:2]
            axis = file_times(times[bucket_model], shape[-1])
            # a total over the preceding step has none at the run's first time (AIGFS:
            # its 6 h); the gusts may end before the horizon (IFS 0.25°: 90 h)
            due = set(need) - leads(times[bucket_model][:1])
            if variable != "wind_gusts_10m" and not due <= leads(axis):
                return Fetched(None, f"{name}.om: {shape[-1]} time steps")
            readers[(bucket_model, name)] = reader
            axes[(bucket_model, name)] = axis
            rows = mine.select("station_id", "y", "x").rows()
            indices[bucket_model] = {sid: (y, x) for sid, y, x in rows}
    chosen, extra_complete = {}, True
    if extra:
        listed = {b: meta_variables(m) for b, m in metas.items()}
        named = extra is not True
        for variable, (bucket_model, derived) in source.extra_files(listed, named).items():
            if extra is not True and variable not in extra:
                continue
            usable = True
            for name in derived.files:
                if (bucket_model, name) in readers:
                    continue
                reader = bucket.open(f"{run_path(bucket_model, run)}/{name}.om")
                if reader is None:  # listed, not written yet
                    usable = extra_complete = False
                    break
                readers[(bucket_model, name)] = reader
                if tuple(reader.shape)[:2] != grids[bucket_model]:
                    usable = False  # not on the grid of the cells: left out
                    break
                # some end before the run does (ARPEGE Europe's CAPE, the UK Met
                # Office's radiation): the hours after are null
                axes[(bucket_model, name)] = file_times(times[bucket_model], reader.shape[-1])
            if usable:
                chosen[variable] = (bucket_model, derived)
    wanted = stations["id"].to_list()
    jobs = []
    for key in axes:
        mine = [indices[key[0]][sid] for sid in wanted if sid in indices[key[0]]]
        jobs += [(key, segment) for segment in segments(mine)]
    blocks = dict(
        zip(jobs, pool.map(lambda job: _read_segment(readers[job[0]], job[1]), jobs), strict=True)
    )
    found = {}
    for (key, (y, first, last)), block in blocks.items():
        for x in range(first, last + 1):
            found[(key, y, x)] = block[x - first]
    values = {
        (key, sid): found[(key, *indices[key[0]][sid])]
        for key in axes
        for sid in wanted
        if sid in indices[key[0]]
    }
    rows, reason = _assemble(
        model, source, run, stations, cells, times, axes, values, need, chosen, max_lead_h
    )
    return Fetched(rows, reason, extra_complete)


def _on_times(axis: list[datetime], value: np.ndarray, times: list[datetime]) -> np.ndarray:
    """``value`` (on ``axis``) at ``times``, NaN where the file has none."""
    lookup = dict(zip(axis, value[: len(axis)].tolist(), strict=True))
    return np.array([lookup.get(t, np.nan) for t in times], dtype=np.float32)


#: Files moved to the station's elevation like temperature_2m (the API does so for the
#: dew point and the surface temperature too, and derives humidity and dew point from
#: the moved values; checked against the Single Runs API 2026-10-19)
LAPSE_FILES = ("temperature_2m", "dew_point_2m", "surface_temperature", "soil_temperature_0cm")


def _extras(chosen, sid, axes, values, main, shift: float) -> dict[str, np.ndarray]:
    """The further variables of one station on the run's times ``main``; ``shift``: the
    elevation correction (K) of ``LAPSE_FILES``."""
    found = {}
    for variable, (bucket_model, derived) in chosen.items():
        keys = [(bucket_model, name) for name in derived.files]
        arrays = [values.get((key, sid)) for key in keys]
        if any(a is None for a in arrays):
            continue
        arrays = [
            _on_times(axes[k], a, main) + np.float32(shift if k[1] in LAPSE_FILES else 0)
            for k, a in zip(keys, arrays, strict=True)
        ]
        with np.errstate(invalid="ignore", over="ignore"):
            value = derived.combine(*arrays) if derived.combine else arrays[0]
        if variable in RADIATION:
            value = value * np.float32(RADIATION_SCALE.get(bucket_model, 1.0))
        found[variable] = np.asarray(value, dtype=np.float32)
    return found


def _assemble(
    model,
    source,
    run,
    stations,
    cells,
    times,
    axes,
    values,
    need,
    chosen=None,
    max_lead_h=runs.MAX_LEAD_H,
):
    """Rows from the point values; ``(rows, "")`` or ``(None, reason)``. ``chosen``: the
    further variables read (``Source.extra_files``); the others are null; the
    ``AUXILIARY`` ones read become columns after ``runs.SCHEMA``'s."""
    auxiliary = [v for v in AUXILIARY if v in (chosen or {})]
    main = times[source.bucket]
    elevation = dict(
        cells.filter(pl.col("bucket_model") == source.bucket)
        .select("station_id", "grid_elevation")
        .rows()
    )
    nan = np.full(len(main), np.nan, dtype=np.float32)
    frames = []
    for sid, height in stations.select("id", "elevation").rows():
        series = {}
        for variable, parts in source.files().items():
            arrays = [values.get((key, sid)) for key in parts]
            if any(a is None for a in arrays):
                series[variable] = nan
                continue
            axis = axes[parts[0]]  # u and v share their axis
            arrays = [a[: len(axis)] for a in arrays]
            value = np.hypot(*arrays) if len(arrays) == 2 else arrays[0]
            lookup = dict(zip(axis, value.tolist(), strict=True))
            series[variable] = np.array([lookup.get(t, np.nan) for t in main], dtype=np.float32)
        grid_height = elevation.get(sid)
        temperature = series["temperature_2m"]
        shift = 0.0
        if grid_height is not None and height is not None and not math.isnan(height):
            shift = (grid_height - height) * LAPSE_RATE
            temperature = temperature + np.float32(shift)
        extras = _extras(chosen or {}, sid, axes, values, main, shift)
        frames.append(
            pl.DataFrame(
                {
                    "run": [run] * len(main),
                    "model": model.id,
                    "station_id": sid,
                    "lead_h": [int((t - run).total_seconds() // 3600) for t in main],
                    "valid_time": main,
                    "temperature_2m": temperature,
                    "precipitation": series["precipitation"],
                    "wind_speed_10m": series["wind_speed_10m"],
                    "wind_gusts_10m": series.get("wind_gusts_10m", nan),
                    **{v: extras.get(v, nan) for v in runs.EXTRA_VARIABLES},
                    **{v: extras.get(v, nan) for v in auxiliary},
                },
                schema={
                    **runs.HOURLY_SCHEMA,
                    **{v: pl.Float32 for v in (*runs.EXTRA_VARIABLES, *auxiliary)},
                },
            )
        )
    table = (
        pl.concat(frames)
        .filter(pl.col("lead_h").is_between(1, max_lead_h))
        .with_columns(pl.col(v).fill_nan(None) for v in runs.VARIABLES)
        # a station outside the model's domain (ICON-D2 in the far east): no rows, as
        # in the API's answers
        .filter(~pl.all_horizontal(pl.col(v).is_null() for v in runs.VARIABLES))
    )
    for variable, (low, high) in PLAUSIBLE.items():
        bad = table.filter(~pl.col(variable).is_between(low, high)).height
        if bad:
            return None, f"{bad} implausible {variable} values"
    reason = _coverage_gap(table, source, need, stations.height)
    if reason:
        return None, reason
    table = table.with_columns(
        pl.col("precipitation").clip(lower_bound=0.0), pl.lit("bucket").alias("source")
    ).with_columns(pl.col(v).round(DECIMALS) for v in runs.VARIABLES)
    tidy = tidy_extras(table).with_columns(
        pl.col(v).fill_nan(None).round(DECIMALS) for v in auxiliary
    )
    return tidy.select(*runs.SCHEMA, *auxiliary), ""


def tidy_extras(table: pl.DataFrame) -> pl.DataFrame:
    """The further variables NaN-free, implausible values null (``EXTRA_PLAUSIBLE``),
    clipped (``EXTRA_CLIP``) and rounded (``EXTRA_DECIMALS``)."""
    columns = []
    for v in runs.EXTRA_VARIABLES:
        low, high = EXTRA_PLAUSIBLE[v]
        value = pl.col(v).fill_nan(None)
        value = pl.when(value.is_between(low, high)).then(value).otherwise(None)
        if v in EXTRA_CLIP:
            value = value.clip(*EXTRA_CLIP[v])
        columns.append(value.round(EXTRA_DECIMALS.get(v, DECIMALS)).cast(pl.Float32).alias(v))
    return table.with_columns(columns)


def _coverage_gap(table: pl.DataFrame, source: Source, need: list[int], n_stations: int) -> str:
    """Why the values do not cover the run ("" if they do): every variable needs values
    at ``MIN_STATIONS`` of the stations, temperature at every needed lead hour."""
    for variable in source.files():
        stations = table.filter(pl.col(variable).is_not_null())["station_id"].n_unique()
        if stations < MIN_STATIONS * n_stations:
            return f"{variable} at {stations} of {n_stations} stations"
    leads = set(table.filter(pl.col("temperature_2m").is_not_null())["lead_h"].to_list())
    if not set(need) <= leads:
        return f"temperature at {len(set(need) & leads)} of {len(need)} lead hours"
    return ""


# --- the collection ------------------------------------------------------------------


@dataclass
class Result:
    #: run key -> models stored from the bucket
    stored: dict[str, set[str]] = field(default_factory=dict)
    #: run key -> {model: why not} (still young: tried again later)
    waiting: dict[str, dict[str, str]] = field(default_factory=dict)
    #: run key -> {model: why not} recorded as missing in the bucket (API fallback)
    missing: dict[str, dict[str, str]] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)  # "run model" -> error
    #: run key -> models stored before, read again for their further variables
    refilled: dict[str, set[str]] = field(default_factory=dict)
    rows: int = 0
    stopped: str = ""


def collect(
    bucket: Bucket,
    stations: pl.DataFrame,
    models: list[Model],
    data_dir: Path,
    now: datetime,
    cells: pl.DataFrame | None = None,
    runs_: list[datetime] | None = None,
    sync: runs.RunsSync | None = None,
    max_minutes: float = 40,
    threads: int = 48,
    parallel_models: int = 4,
    log: Callable[[str], None] = lambda _: None,
    clock: Callable[[], float] = time.monotonic,
) -> Result:
    """Store every model-run of the bucket window (``runs.bucket_runs``, newest first)
    not stored yet; record those still incomplete at ``runs.BUCKET_FINAL_H`` as missing in the
    bucket. Model-runs stored without their further variables (``runs.State.extra_todo``:
    stored before 2026-10-19, from the API, or read while a file was still being
    written) are read again and replace the stored rows; once ``runs.BUCKET_FINAL_H``
    old they are settled either way. Month files and the state are pushed once at the end
    (the bucket costs no quota, so a run cut short is simply read again)."""
    cells = load_cells() if cells is None else cells
    state = runs.State.load(data_dir / runs.STATE_NAME)
    result, touched, start, errors = Result(), set(), clock(), 0
    todo = runs_ if runs_ is not None else runs.bucket_runs(now)
    with ThreadPoolExecutor(threads) as pool, ThreadPoolExecutor(parallel_models) as outer:
        for run in todo:
            k = runs.key(run)
            every = runs.wanted(models, run)
            new = state.bucket_todo(run, every)
            again = {m.id for m in state.extra_todo(run, every)}
            pending = new + [m for m in every if m.id in again]
            if not pending:
                continue
            if clock() - start > max_minutes * 60:
                result.stopped = f"time limit of {max_minutes:g} minutes reached"
                break
            if errors >= MAX_ERRORS:
                last = list(result.failed.values())[-1]
                result.stopped = f"the bucket keeps failing ({errors} model-runs in a row: {last})"
                break
            month = f"{run:%Y-%m}"
            if sync and month not in touched:
                sync.pull([month])
            jobs = {
                model.id: outer.submit(
                    read_run, bucket, model, run, stations, cells, pool, extra=True
                )
                for model in pending
            }
            frames = []
            for model in pending:
                try:
                    fetched = jobs[model.id].result()
                except Exception as exc:  # network trouble after the retries: next time
                    result.failed[f"{k} {model.id}"] = f"{type(exc).__name__}: {exc}"[:300]
                    errors += 1
                    continue
                errors = 0
                final = now - run >= timedelta(hours=runs.BUCKET_FINAL_H)
                if fetched.rows is not None:
                    frames.append(fetched.rows)
                    state.fetched.setdefault(k, set()).add(model.id)
                    if model.id in again:
                        result.refilled.setdefault(k, set()).add(model.id)
                    else:
                        result.stored.setdefault(k, set()).add(model.id)
                    if fetched.extra_complete or final:
                        state.settle(k, model.id)
                elif model.id in again:  # the stored rows stay
                    if final:
                        state.settle(k, model.id)
                elif final:
                    state.bucket_missing.setdefault(k, set()).add(model.id)
                    result.missing.setdefault(k, {})[model.id] = fetched.reason
                else:
                    result.waiting.setdefault(k, {})[model.id] = fetched.reason
            if frames:
                table = pl.concat(frames)
                partitions.write_monthly(
                    table, data_dir / "runs", runs.KEYS, "run", replace=["run", "model"]
                )
                result.rows += table.height
                touched.add(month)
            state.save()
            if k in result.stored or k in result.missing or k in result.refilled:
                log(
                    f"run {run:%Y-%m-%d %H} UTC: {len(result.stored.get(k, ()))} models from "
                    "the bucket"
                    + (
                        f", {len(result.refilled[k])} read again for the further variables"
                        if k in result.refilled
                        else ""
                    )
                    + (
                        f"; missing there: {', '.join(sorted(result.missing[k]))}"
                        if k in result.missing
                        else ""
                    )
                )
    if sync:
        sync.push(sorted(touched))
    return result


@dataclass
class Added:
    """What ``add_stations`` did: per month the model-runs filled in, rows and the
    model-runs the bucket no longer has (or not complete) at the added stations."""

    filled: dict[str, int] = field(default_factory=dict)
    rows: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    stopped: str = ""


def _present(path: Path) -> pl.DataFrame:
    """``run``, ``model``, ``source``, the ``stations`` of every stored model-run and the
    stations among them with any further variable (``with_extras``)."""
    frame = pl.scan_parquet(path)
    names = frame.collect_schema().names()
    extras = [v for v in runs.EXTRA_VARIABLES if v in names]
    has = pl.any_horizontal(pl.col(v).is_not_null() for v in extras) if extras else pl.lit(False)
    return (
        frame.group_by("run", "model")
        .agg(
            pl.col("source").first(),
            pl.col("station_id").unique().alias("stations"),
            pl.col("station_id").filter(has).unique().alias("with_extras"),
        )
        .collect()
    )


def _spill(frames: list[pl.DataFrame], spool: Path, parts: list[Path]) -> None:
    """Write ``frames`` to the next part file in ``spool`` and empty the list."""
    if frames:
        part = spool / f"{len(parts):04d}.parquet"
        pl.concat(frames, how="diagonal_relaxed").write_parquet(part)
        parts.append(part)
        frames.clear()


def add_stations(
    bucket: Bucket,
    stations: pl.DataFrame,
    models: list[Model],
    data_dir: Path,
    now: datetime,
    cells: pl.DataFrame | None = None,
    sync: runs.RunsSync | None = None,
    first: datetime | None = None,
    max_minutes: float = 330,
    threads: int = 96,
    parallel_models: int = 8,
    extra: bool = False,
    extras_only: bool = False,
    flush_every: int = 200,
    log: Callable[[str], None] = lambda _: None,
    clock: Callable[[], float] = time.monotonic,
) -> Added:
    """Fill in the stations of ``stations`` that stored model-runs lack, after the
    station subset grew (2026-10-20: every temperature station): every model-run of the
    bucket's window (from ``first`` if later) that was stored from the bucket is read
    again at its missing stations only and merged by run, model and station, so the
    stored stations' rows stay as they are. Newest month first, newest run first; each
    month file is pulled again just before it is written and pushed, so a schedule of
    ``runs.yml`` that wrote it meanwhile is kept (the workflow shares its concurrency
    group anyway). Model-runs from the API are not in the bucket and stay without the
    added stations. Without ``extra`` only the four main variables are read (the
    further ones, four times the requests, come with the new runs). The rows read are
    kept on disk every ``flush_every`` model-runs (a month at ~200 stations is tens of
    millions of rows; on 2026-10-20 a runner holding them in memory was lost) and
    merged into the month file once. Resumable: a month already complete costs one
    scan.

    With ``extras_only`` the stations are the stored ones whose rows lack the further
    variables while other stations of the same model-run have them (2026-08-28 to
    2026-10-19 the added stations were filled in with the four main variables only):
    they are read again with the further variables and their rows replaced. A
    model-run without further variables at any station (the bucket had none) is left."""
    extra = extra or extras_only
    cells = load_cells() if cells is None else cells
    catalogue = {m.id: m for m in models}
    wanted = set(stations["id"])
    window = [r for r in runs.bucket_runs(now) if first is None or r >= first]
    months = sorted({f"{r:%Y-%m}" for r in window}, reverse=True)
    result, start = Added(), clock()
    with ThreadPoolExecutor(threads) as pool, ThreadPoolExecutor(parallel_models) as outer:
        for month in months:
            if sync:
                sync.pull([month])
            path = data_dir / "runs" / f"{month}.parquet"
            if not path.exists():
                continue
            present = _present(path)
            todo = []
            for run, model_id, source, have, full in present.sort("run", descending=True).rows():
                if source != "bucket" or model_id not in catalogue:
                    continue
                if run < window[-1] or run > window[0]:
                    continue
                if extras_only:
                    missing = sorted((wanted & set(have)) - set(full)) if full else []
                else:
                    missing = sorted(wanted - set(have))
                if missing:
                    todo.append((run, model_id, missing))
            log(
                f"{month}: {len(todo)} model-runs lack some of the {len(wanted)} stations"
                + (" (further variables)" if extras_only else "")
            )
            frames, done, parts = [], 0, []
            spool = data_dir / "runs" / f".{month}.added"
            spool.mkdir(parents=True, exist_ok=True)

            for i in range(0, len(todo), parallel_models * 4):
                if clock() - start > max_minutes * 60:
                    result.stopped = f"time limit of {max_minutes:g} minutes reached"
                    break
                chunk = todo[i : i + parallel_models * 4]
                jobs = [
                    (
                        run,
                        model_id,
                        outer.submit(
                            read_run,
                            bucket,
                            catalogue[model_id],
                            run,
                            stations.filter(pl.col("id").is_in(missing)),
                            cells,
                            pool,
                            extra=extra,
                        ),
                    )
                    for run, model_id, missing in chunk
                ]
                for run, model_id, job in jobs:
                    try:
                        fetched = job.result()
                    except Exception as exc:  # network trouble after the retries: next time
                        result.failed[f"{runs.key(run)} {model_id}"] = (
                            f"{type(exc).__name__}: {exc}"[:300]
                        )
                        continue
                    if fetched.rows is None:
                        result.skipped[month] = result.skipped.get(month, 0) + 1
                    else:
                        frames.append(fetched.rows)
                        done += 1
                if sum(f.height > 0 for f in frames) >= flush_every:
                    _spill(frames, spool, parts)
                if (i // (parallel_models * 4)) % 25 == 0:
                    log(f"{month}: {done} of {len(todo)} model-runs read")
            _spill(frames, spool, parts)
            if parts:
                table = pl.read_parquet(parts)
                if sync:
                    sync.pull([month])  # the newest release, if a schedule wrote it meanwhile
                partitions.write_monthly(
                    table,
                    data_dir / "runs",
                    runs.KEYS,
                    "run",
                    replace=["run", "model", "station_id"],
                )
                if sync:
                    sync.push([month])
                result.filled[month], result.rows[month] = done, table.height
                log(f"{month}: {done} model-runs filled in, {table.height:,} rows")
                del table
            for part in parts:
                part.unlink()
            spool.rmdir()
            if result.stopped:
                break
    return result


def summary(result: Result) -> str:
    """Markdown lines for the job summary."""
    stored = sum(len(v) for v in result.stored.values())
    refilled = sum(len(v) for v in result.refilled.values())
    lines = [
        f"- Bucket: {stored} model-runs stored ({result.rows:,} rows) from "
        f"s3://openmeteo, no API calls"
        + (f"; {refilled} stored ones read again for the further variables" if refilled else "")
    ]
    waiting = sum(len(v) for v in result.waiting.values())
    if waiting:
        newest = max(result.waiting)
        why = "; ".join(f"{m}: {r}" for m, r in sorted(result.waiting[newest].items()))
        lines.append(f"- Not complete in the bucket yet: {waiting} model-runs ({newest}: {why})")
    if result.missing:
        gaps = "; ".join(f"{k}: {', '.join(sorted(v))}" for k, v in sorted(result.missing.items()))
        lines.append(f"- Missing in the bucket (asked from the API instead): {gaps}")
    if result.failed:
        lines.append(f"- Bucket errors (tried again next time): {len(result.failed)}")
    if result.stopped:
        lines.append(f"- Bucket: stopped, {result.stopped} (the next run continues)")
    return "\n".join(lines) + "\n"


# --- the one-off import of a harvest ---------------------------------------------------


#: Models whose precipitation the one-off harvest of 2026-10-16 (``from_harvest``) put
#: one native step early: their precipitation files leave out the run's first step
#: (``file_times``), which the harvest did not allow for (its gusts it did shift)
HARVEST_PRECIPITATION_EARLY = frozenset(SOURCES) - {
    "chmi_aladin_cz_1km",
    "chmi_aladin_central_europe_2km",
    "geosphere_arome_austria",
}


def from_harvest(frame: pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame:
    """Rows of the one-off harvest (``om-runs-archive/runs-YYYY-MM.parquet``: the same
    reading, extra columns, lead 0 kept) in ``runs.SCHEMA``, with its precipitation
    moved to the right step (``HARVEST_PRECIPITATION_EARLY``)."""
    early = pl.col("model").is_in(list(HARVEST_PRECIPITATION_EARLY))
    by_run = ["run", "model", "station_id"]
    return (
        frame.lazy()
        .sort([*by_run, "lead_h"])
        .with_columns(
            pl.when(early)
            .then(pl.col("precipitation").shift(1).over(by_run))
            .otherwise(pl.col("precipitation"))
            .alias("precipitation")
        )
        .filter(
            pl.col("lead_h").is_between(1, runs.MAX_LEAD_H),
            ~pl.all_horizontal(pl.col(v).is_null() for v in runs.VARIABLES),
        )
        .with_columns(
            pl.col("precipitation").clip(lower_bound=0.0), pl.lit("bucket").alias("source")
        )
        .with_columns(pl.col(v).round(DECIMALS) for v in runs.VARIABLES)
        .with_columns(pl.lit(None, pl.Float32).alias(v) for v in runs.EXTRA_VARIABLES)
        .select(list(runs.SCHEMA))
        .cast(runs.SCHEMA)
    )


def refresh_moved_cells(
    raw: pl.DataFrame,
    rows: pl.DataFrame,
    cells: pl.DataFrame,
    bucket: Bucket,
    models: list[Model],
    stations: pl.DataFrame,
    log: Callable[[str], None] = lambda _: None,
) -> tuple[pl.DataFrame, dict[str, dict[str, int]]]:
    """``rows`` (from ``from_harvest(raw)``) with the stations whose harvested grid cell
    (``raw``: ``om_model``, ``grid_lat``, ``grid_lon``) is not the committed one read
    again from the bucket, run by run; where the bucket no longer has the run, that
    station's rows of the model-run are dropped. Returns the rows and, per "model
    station", how many model-runs were read again and dropped."""
    harvested = raw.group_by("model", "station_id").agg(
        pl.col("om_model").first(), pl.col("grid_lat").first(), pl.col("grid_lon").first()
    )
    committed = cells.select(
        pl.col("bucket_model").alias("om_model"),
        "station_id",
        pl.col("grid_lat").alias("lat"),
        pl.col("grid_lon").alias("lon"),
    )
    moved = (
        harvested.join(committed, on=["om_model", "station_id"], how="left")
        .filter(
            ((pl.col("grid_lat") - pl.col("lat")).abs() > 1e-3)
            | ((pl.col("grid_lon") - pl.col("lon")).abs() > 1e-3)
        )
        .select("model", "station_id")
        .rows()
    )
    catalogue = {m.id: m for m in models}
    report: dict[str, dict[str, int]] = {}
    with ThreadPoolExecutor(16) as pool:
        for model_id, sid in moved:
            mine = rows.filter(pl.col("model") == model_id, pl.col("station_id") == sid)
            fresh, done = [], {"reread": 0, "dropped": 0}
            for run in sorted(mine["run"].unique().to_list()):
                fetched = read_run(
                    bucket,
                    catalogue[model_id],
                    run,
                    stations.filter(pl.col("id") == sid),
                    cells,
                    pool,
                )
                if fetched.rows is not None:
                    fresh.append(fetched.rows)
                    done["reread"] += 1
                else:
                    done["dropped"] += 1
            rows = pl.concat(
                [
                    rows.filter(~((pl.col("model") == model_id) & (pl.col("station_id") == sid))),
                    *fresh,
                ]
            )
            report[f"{model_id} {sid}"] = done
            log(f"{model_id} at {sid}: grid cell moved, {done}")
    return rows.sort(runs.KEYS), report


def complete_runs(frame: pl.DataFrame, models: list[Model], n_stations: int) -> pl.DataFrame:
    """``run``, ``model``, ``complete`` and ``reason`` per model-run of ``frame``
    (``runs.SCHEMA``), by the same rule as ``read_run``."""
    catalogue = {m.id: m for m in models}
    rows = []
    for (run, model_id), part in frame.group_by("run", "model"):
        model, source = catalogue.get(model_id), SOURCES.get(model_id)
        if model is None or source is None:
            rows.append((run, model_id, False, "not a bucket model"))
            continue
        need = native_leads(model, source.horizon(run.hour))
        reason = _coverage_gap(part, source, need, n_stations)
        rows.append((run, model_id, not reason, reason))
    return pl.DataFrame(
        rows,
        schema={
            "run": pl.Datetime("us", "UTC"),
            "model": pl.String,
            "complete": pl.Boolean,
            "reason": pl.String,
        },
        orient="row",
    ).sort("run", "model")


def merge(stored: pl.DataFrame | None, imported: pl.DataFrame) -> pl.DataFrame:
    """A month file with ``imported`` added: a model-run in ``imported`` replaces every
    stored row of that model-run (the bucket is preferred for all models)."""
    if stored is None or stored.height == 0:
        return imported.sort(runs.KEYS)
    kept = stored.join(imported.select("run", "model").unique(), on=["run", "model"], how="anti")
    return pl.concat([kept, imported], how="diagonal_relaxed").sort(runs.KEYS)
