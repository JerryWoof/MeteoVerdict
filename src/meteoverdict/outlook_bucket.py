"""The outlook's model forecasts from Open-Meteo's open-data bucket, without API calls.

Since 2026-10-20 ``mvd outlook`` reads every model's forecast at the 77 okres points
from the bucket (``meteoverdict.bucket``, as the single runs and the obce do) instead of
asking the Forecast API (~3,400 weighted calls a day). It gives the same table as
``outlook.parse`` (okres, time, model and ``outlook.VARIABLES``, hourly, 00 UTC today
to ``outlook.DAYS`` days on), built the way the API builds its answer:

- **The grid cell** of each okres point (``CELLS_FILE``, committed like
  ``bucket-cells.csv``, rebuilt by ``mvd bucket-cells --okres``), the temperature moved
  from the cell's surface height to the point's (``combine.point_elevations``: the
  elevation the API answered with) by 0.65 K per 100 m.
- **Several runs stitched** like the API's time series: each hour and variable from the
  newest complete run that has it (``bucket.read_run``: complete or not at all), older
  runs for the hours before the newest one starts (back to 00 UTC today) and past its
  end (UKMO's 06 and 18 UTC runs end at 60 h, its 00 and 12 UTC ones at 168 h). The
  3-hourly runs of ICON-D2, ICON-EU (30 h), AROME AT, KNMI and DMI are read too
  (``RUN_STEP_H``).
- **Hourly as the API interpolates** a model's coarser steps (open-meteo
  ``Interpolation.swift``): temperature and wind by Hermite (Catmull-Rom) splines,
  cloud cover linearly, precipitation spread evenly over the hours of its step
  (backwards sum), shortwave radiation through the clearness index of the solar
  factor of each step (``solar_backwards``).
- **Sunshine** from the model's own file where the bucket has one (ALADIN, AROME AT),
  else from the hourly radiation as the API derives it (``Zensun.swift``): the diffuse
  part by Open-Meteo's polynomial in the clearness index and the sun's angle, the
  direct normal irradiance from the rest, sunshine for the share of the hour between
  60 and 180 W/m² (``sunshine``).

A model none of whose runs of the last ``MAX_RUN_AGE_H`` hours is complete in the
bucket is asked from the API instead (``outlook.fetch``, only those models; the
answer's rows replace nothing). Validation against the API:
docs/data-sources.md#outlook-from-the-bucket.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path

import numpy as np
import polars as pl

from meteoverdict import bucket, combine, sun
from meteoverdict.models import Model

#: committed: per bucket model and okres point (``station_id`` = okres code) the cell
CELLS_FILE = "okres-cells.csv"
#: hours after the newest run to look back for runs (the API's series of today
#: reaches back to 00 UTC; 18 UTC of the day before covers it)
LOOKBACK_H = 36
#: the model's newest complete run in the bucket older than this: asked from the API
MAX_RUN_AGE_H = 24
#: the API's answer reaches this far after its start (00 UTC today), so the runs are
#: read to this lead
MAX_LEAD_H = 168
#: models whose bucket has runs every 3 hours (the API serves the newest of them)
RUN_STEP_H = {
    "dwd_icon_d2": 3,
    "dwd_icon_eu": 3,
    "geosphere_arome_austria": 3,
    "knmi_harmonie_arome_europe": 3,
    "dmi_harmonie_arome_europe": 3,
}
#: the bucket's further variables the outlook needs (``bucket.EXTRA``)
EXTRA = (
    "cloud_cover",
    "shortwave_radiation",
    "sunshine_duration",
    "direct_radiation",
    "diffuse_radiation",
)
VARIABLES = (
    "temperature_2m",
    "precipitation",
    "wind_speed_10m",
    "cloud_cover",
    "sunshine_duration",
)
#: Météo-France's radiation is stored with a conversion factor the API's readers undo
#: (open-meteo ``MeteoFranceSurfaceVariable.shortwaveRadiationArchiveCorrectionFactor``,
#: 10^7 / 3600²): the bucket's ARPEGE values are 1.296 times the API's (checked on the
#: runs of 2026-10-19 12 and 10-20 00 UTC)
MEAN_RADIATION_SCALE = {
    "meteofrance_arpege_europe": 1e7 / 3600**2,
    "meteofrance_arpege_world025": 1e7 / 3600**2,
}
#: W/m² (Open-Meteo's ``Zensun.solarConstant``)
SOLAR_CONSTANT = 1367.7


def load_cells(path: Path | None = None) -> pl.DataFrame:
    """The committed cells of the okres points (``src/meteoverdict/data/okres-cells.csv``)."""
    return bucket.load_cells(path or Path(str(files("meteoverdict").joinpath("data", CELLS_FILE))))


def point_table(points: pl.DataFrame) -> pl.DataFrame:
    """``id`` (okres code), ``lat``, ``lon``, ``elevation`` of the okres points: the
    stations ``bucket.read_run`` reads."""
    heights = combine.point_elevations().rename({"code": "id"})
    return (
        points.select(pl.col("code").alias("id"), "lat", "lon")
        .join(heights, on="id", how="left")
        .with_columns(pl.col("elevation").cast(pl.Float64))
    )


# --- the sun (open-meteo Zensun.swift) --------------------------------------------------


def _sun(stamp: float) -> tuple[float, float, float]:
    """Declination (°), equation of time (h) and earth-sun distance (AU) at the unix
    time ``stamp``."""
    declination, equation = sun._position(stamp / 86400 + sun.UNIX_JD)
    seconds = stamp % 31_557_600
    day = seconds / 86400 - 4 + 1
    radius = 1 - 0.01672 * math.cos(math.radians((360 / 365.256363) * day))
    return math.degrees(declination), equation / 60, radius


def _arc(stamp: float, dt: float, lat: float, lon: float):
    """The sun's path over the ``dt`` seconds before ``stamp`` at ``lat``/``lon``:
    ``(p1, p10, p0, t0, t1, sunrise, sunset)`` as Zensun names them (radians)."""
    decang, eqtime, _ = _sun(stamp)
    ut = (stamp % 86400) / 3600
    t1 = math.radians(90 - decang)
    p1 = math.radians(-15.0 * (ut - 12.0 + eqtime))
    p10 = math.radians(-15.0 * (ut - dt / 3600 - 12.0 + eqtime))
    t0 = math.radians(90 - lat)
    p0 = math.radians(lon)
    if p0 < p1 - math.pi:
        p0 += 2 * math.pi
    if p0 > p1 + math.pi:
        p0 -= 2 * math.pi
    arg = -(math.cos(t0) * math.cos(t1)) / (math.sin(t0) * math.sin(t1))
    carg = math.pi if arg > 1 or arg < -1 else math.acos(arg)
    return p1, p10, p0, t0, t1, p0 + carg, p0 - carg


def _integral(p1_l, p10_l, p0, t0, t1) -> float:
    left = math.sin(t0) * math.sin(t1) * math.sin(p1_l - p0) + p1_l * math.cos(t0) * math.cos(t1)
    right = math.sin(t0) * math.sin(t1) * math.sin(p10_l - p0) + p10_l * math.cos(t0) * math.cos(t1)
    return left - right


def solar_factor(stamp: float, dt: float, lat: float, lon: float) -> float:
    """The sun's elevation (sine) averaged over the ``dt`` seconds before ``stamp``,
    night counting as 0, over the squared earth-sun distance
    (``calculateRadiationBackwardsAveraged``)."""
    p1, p10, p0, t0, t1, sunrise, sunset = _arc(stamp, dt, lat, lon)
    if p10 < sunset or p1 > sunrise:
        return 0.0
    radius = _sun(stamp)[2]
    value = _integral(min(sunrise, p10), max(sunset, p1), p0, t0, t1) / (p10 - p1)
    return value / (radius * radius)


def _elevation(stamp: float, dt: float, lat: float, lon: float) -> float:
    """The sun's elevation (sine) averaged over its daylight within the ``dt`` seconds
    before ``stamp`` (``calculateSunElevationBackwards``)."""
    p1, p10, p0, t0, t1, sunrise, sunset = _arc(stamp, dt, lat, lon)
    p1_l, p10_l = min(sunrise, p10), max(sunset, p1)
    delta = p1_l - p10_l
    return _integral(p1_l, p10_l, p0, t0, t1) / (
        min(-0.001, delta) if delta < 0 else max(0.001, delta)
    )


def diffuse(ghi: float, stamp: float, lat: float, lon: float) -> float:
    """The diffuse part of the hour's mean shortwave radiation
    (``calculateDiffuseRadiationBackwards``)."""
    sin_alpha = _elevation(stamp, 3600, lat, lon)
    if sin_alpha <= 5 / SOLAR_CONSTANT:
        return ghi
    kt = ghi / min(sin_alpha * SOLAR_CONSTANT, 0.95 * SOLAR_CONSTANT)
    aoi = math.acos(min(1.0, sin_alpha))
    kd = (
        1.58 * kt
        + 0.991 * aoi
        - 5.084 * kt**2
        - 2.11 * kt * aoi
        - 1.16 * aoi**2
        + 2.918 * kt**3
        + 1.307 * kt**2 * aoi
        + 0.762 * kt * aoi**2
        + 0.432 * aoi**3
        + 0.718
    )
    return min(kd * ghi, ghi)


def sunshine(direct: float, stamp: float, lat: float, lon: float, dt: float = 3600) -> float:
    """Seconds of sunshine in the ``dt`` before ``stamp`` from the mean direct radiation
    (``calculateBackwardsSunshineDuration``: DNI from 60 to 180 W/m² counts linearly)."""
    if math.isnan(direct):
        return math.nan
    if direct <= 0:
        return 0.0
    p1, p10, p0, t0, t1, sunrise, sunset = _arc(stamp, dt, lat, lon)
    if p10 < sunset or p1 > sunrise:
        return 0.0
    p1_l, p10_l = min(sunrise, p10), max(sunset, p1)
    bound = dt * abs((p1_l - p10_l) / (p10 - p1))
    delta = p1_l - p10_l
    zz = _integral(p1_l, p10_l, p0, t0, t1) / (
        min(-0.001, delta) if delta < 0 else max(0.001, delta)
    )
    dni = direct if zz <= 0.0001 else direct / zz
    return min(max(dni - 60, 0) / (180 - 60) * bound, bound)


# --- hourly from a run's native steps (open-meteo Interpolation.swift) -----------------


def hermite(leads: np.ndarray, values: np.ndarray, hours: np.ndarray, low: float | None = None):
    """Catmull-Rom between the native ``leads`` (Open-Meteo's ``interpolateHermite``)
    at ``hours`` within them; ``low``: a lower bound."""
    out = np.full(len(hours), np.nan)
    n = len(leads)
    for i, h in enumerate(hours):
        k = int(np.searchsorted(leads, h, side="right") - 1)
        if k < 0 or h > leads[-1]:
            continue
        b = values[k]
        if k == n - 1:
            out[i] = b
            continue
        fraction = (h - leads[k]) / (leads[k + 1] - leads[k])
        a = b if k - 1 < 0 or np.isnan(values[k - 1]) else values[k - 1]
        c = b if np.isnan(values[k + 1]) else values[k + 1]
        d = c if k + 2 >= n else (b if np.isnan(values[k + 2]) else values[k + 2])
        out[i] = (
            (-a / 2 + 3 * b / 2 - 3 * c / 2 + d / 2) * fraction**3
            + (a - 5 * b / 2 + 2 * c - d / 2) * fraction**2
            + (-a / 2 + c / 2) * fraction
            + b
        )
    if low is not None:
        out = np.where(np.isnan(out), out, np.maximum(out, low))
    return out


def linear(leads: np.ndarray, values: np.ndarray, hours: np.ndarray) -> np.ndarray:
    inside = (hours >= leads[0]) & (hours <= leads[-1])
    return np.where(inside, np.interp(hours, leads, values), np.nan)


def backwards_sum(leads: np.ndarray, values: np.ndarray, hours: np.ndarray) -> np.ndarray:
    """A total over each native step (since the previous lead, the first since the
    run's start) spread evenly over its hours."""
    out = np.full(len(hours), np.nan)
    starts = np.concatenate([[0], leads[:-1]])
    for i, h in enumerate(hours):
        k = int(np.searchsorted(leads, h, side="left"))
        if k < len(leads) and starts[k] < h <= leads[k]:
            out[i] = values[k] / (leads[k] - starts[k])
    return out


def solar_backwards(
    leads: np.ndarray, values: np.ndarray, hours: np.ndarray, run: datetime, lat: float, lon: float
) -> np.ndarray:
    """Mean radiation over each native step → hourly means through the clearness index
    (value over the step's solar factor), Catmull-Rom between the steps' middles
    (``interpolateSolarBackwards``); hours of an hourly step as they are."""
    start = run.timestamp()
    steps = np.diff(np.concatenate([[0], leads]))
    centres = leads - steps / 2
    low = np.array(
        [
            solar_factor(start + 3600 * lead, 3600 * s, lat, lon)
            for lead, s in zip(leads, steps, strict=True)
        ]
    )
    limit, minimum = 0.95 * SOLAR_CONSTANT, 5 / SOLAR_CONSTANT
    kt = np.where(low <= minimum, np.nan, np.minimum(values / np.where(low > 0, low, 1), limit))
    out = np.full(len(hours), np.nan)
    n = len(leads)
    hourly_steps = {lead: v for lead, s, v in zip(leads, steps, values, strict=True) if s == 1}
    for i, h in enumerate(hours):
        if h in hourly_steps:  # an hourly mean already: as it is
            out[i] = hourly_steps[h]
            continue
        centre = h - 0.5
        k = int(np.searchsorted(centres, centre, side="right") - 1)
        if k < 0 or h > leads[-1] or np.isnan(values[k]):
            continue
        factor = solar_factor(start + 3600 * h, 3600, lat, lon)
        if factor == 0:
            out[i] = 0.0
            continue
        ia, ib, ic, id_ = max(k - 1, 0), k, min(k + 1, n - 1), min(k + 2, n - 1)
        a, b, c, d = kt[ia], kt[ib], kt[ic], kt[id_]
        if np.isnan(a):
            a = b if not np.isnan(b) else c if not np.isnan(c) else d
        if np.isnan(b):
            b = a if not np.isnan(a) else c if not np.isnan(c) else d
        if np.isnan(c):
            c = b if not np.isnan(b) else d if not np.isnan(d) else a
        if np.isnan(d):
            d = c if not np.isnan(c) else b if not np.isnan(b) else a
        fraction = 0.0 if ic == ib else (centre - centres[ib]) / (centres[ic] - centres[ib])
        fraction = min(max(fraction, 0.0), 1.0)
        value = (
            (-a / 2 + 3 * b / 2 - 3 * c / 2 + d / 2) * fraction**3
            + (a - 5 * b / 2 + 2 * c - d / 2) * fraction**2
            + (-a / 2 + c / 2) * fraction
            + b
        ) * factor
        if value < 0 and values[ib] >= 0 and values[ic] >= 0:
            value = (b * (1 - fraction) + c * fraction) * factor
        out[i] = value
    return out


def _native(part: pl.DataFrame, column: str) -> tuple[np.ndarray, np.ndarray]:
    """The leads and values of ``column`` where it has one."""
    own = part.select("lead_h", column).drop_nulls()
    return own["lead_h"].to_numpy().astype(float), own[column].to_numpy().astype(float)


def hourly(
    rows: pl.DataFrame, cells: pl.DataFrame, source: bucket.Source, model_id: str
) -> pl.DataFrame:
    """One model-run's rows (``runs.SCHEMA`` with ``EXTRA``) → hourly rows (okres,
    time, model, ``VARIABLES``) from its first to its last native lead."""
    where = {
        sid: (lat, lon)
        for sid, lat, lon in cells.filter(pl.col("bucket_model") == source.bucket)
        .select("station_id", "grid_lat", "grid_lon")
        .rows()
    }
    frames = []
    for (sid,), part in rows.sort("lead_h").partition_by("station_id", as_dict=True).items():
        run = part["run"][0]
        hours = np.arange(1, int(part["lead_h"].max()) + 1)
        lat, lon = where.get(sid, (math.nan, math.nan))

        series: dict[str, np.ndarray] = {}
        scale = MEAN_RADIATION_SCALE.get(source.bucket, 1.0)
        for column, how in (
            ("temperature_2m", "hermite"),
            ("wind_speed_10m", "hermite0"),
            ("cloud_cover", "linear"),
            ("precipitation", "sum"),
            ("sunshine_duration", "sum"),
            ("shortwave_radiation", "solar"),
            ("direct_radiation", "solar"),
            ("diffuse_radiation", "solar"),
        ):
            if column not in part.columns:
                series[column] = np.full(len(hours), np.nan)
                continue
            leads, values = _native(part, column)
            if how == "solar":
                values = values * scale
            if len(leads) == 0:
                series[column] = np.full(len(hours), np.nan)
            elif how == "hermite":
                series[column] = hermite(leads, values, hours)
            elif how == "hermite0":
                series[column] = hermite(leads, values, hours, low=0.0)
            elif how == "linear":
                series[column] = linear(leads, values, hours)
            elif how == "sum":
                series[column] = backwards_sum(leads, values, hours)
            elif math.isnan(lat):
                series[column] = np.full(len(hours), np.nan)
            else:
                series[column] = solar_backwards(leads, values, hours, run, lat, lon)
        if np.isnan(series["sunshine_duration"]).all() and not math.isnan(lat):
            series["sunshine_duration"] = _sunshine(series, hours, run.timestamp(), lat, lon)
        frames.append(
            pl.DataFrame(
                {
                    "okres": sid,
                    "time": [run + timedelta(hours=int(h)) for h in hours],
                    "model": model_id,
                    **{v: series[v] for v in VARIABLES},
                },
                schema={
                    "okres": pl.String,
                    "time": pl.Datetime("us", "UTC"),
                    "model": pl.String,
                    **{v: pl.Float64 for v in VARIABLES},
                },
            ).with_columns(pl.col(v).fill_nan(None) for v in VARIABLES)
        )
    return pl.concat(frames) if frames else pl.DataFrame()


def _sunshine(series: dict, hours: np.ndarray, start: float, lat: float, lon: float):
    """Hourly sunshine from the direct radiation: the model's own, else its shortwave
    minus its own diffuse radiation (GFS), else minus ``diffuse`` (as the API)."""
    direct = series["direct_radiation"]
    if np.isnan(direct).all():
        ghi, own = series["shortwave_radiation"], series["diffuse_radiation"]
        if np.isnan(own).all():
            own = np.array(
                [
                    math.nan if math.isnan(g) else diffuse(g, start + 3600 * h, lat, lon)
                    for h, g in zip(hours, ghi, strict=True)
                ]
            )
        direct = np.maximum(ghi - own, 0.0)
    return np.array(
        [sunshine(d, start + 3600 * h, lat, lon) for h, d in zip(hours, direct, strict=True)]
    )


# --- the runs of one model --------------------------------------------------------------


def candidate_runs(model: Model, now: datetime) -> list[datetime]:
    """The model's runs from an hour before ``now`` back ``LOOKBACK_H`` hours, newest
    first (every 3 hours for ``RUN_STEP_H``, else at ``model.run_hours``)."""
    step = RUN_STEP_H.get(model.id)
    top = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    out = []
    for back in range(LOOKBACK_H + 1):
        run = top - timedelta(hours=back)
        if (run.hour % step == 0) if step else (run.hour in model.run_hours):
            out.append(run)
    return out


def stitch(frames: list[pl.DataFrame]) -> pl.DataFrame:
    """Hourly frames of one model's runs, newest first → one series: each hour and
    variable from the newest run that has it."""
    ranked = pl.concat(
        [f.with_columns(pl.lit(i).alias("_rank")) for i, f in enumerate(frames)],
        how="vertical_relaxed",
    )
    return (
        ranked.sort("_rank")
        .group_by("okres", "time", "model", maintain_order=True)
        .agg(pl.col(v).drop_nulls().first() for v in VARIABLES)
        .sort("okres", "time")
    )


@dataclass
class ModelRead:
    """One model from the bucket: ``fc`` (hourly) and the runs read, newest first."""

    model: str
    fc: pl.DataFrame | None
    runs: list[datetime] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


def read_model(
    store: bucket.Bucket,
    model: Model,
    points: pl.DataFrame,
    cells: pl.DataFrame,
    now: datetime,
    start: datetime,
    pool: ThreadPoolExecutor,
    end: datetime | None = None,
) -> ModelRead:
    """The model's stitched hourly series at ``points`` (``point_table``): its newest
    complete run in the bucket and older ones until 00 UTC today (``start``) is covered
    and, where the newer runs end sooner (UKMO's and JMA's 06 and 18 UTC runs), the
    older ones that reach further towards ``end`` (their ``meta.json`` tells); ``fc``
    None when it has no complete run of the last ``MAX_RUN_AGE_H`` hours."""
    end = end or start + timedelta(days=6)
    source = bucket.SOURCES.get(model.id)
    result = ModelRead(model.id, None)
    if source is None:
        result.skipped["-"] = "not in the bucket"
        return result
    frames, covered, last = [], False, None
    for run in candidate_runs(model, now):
        if not result.runs and now - run > timedelta(hours=MAX_RUN_AGE_H):
            break
        meta = store.meta(source.bucket, run)
        if meta is None:
            continue
        if covered:
            reach = max(bucket._valid_times(meta), default=run)
            if last is not None and reach <= last:
                continue  # ends before what the newer runs give
        fetched = bucket.read_run(
            store, model, run, points, cells, pool, extra=EXTRA, max_lead_h=MAX_LEAD_H
        )
        if fetched.rows is None:
            result.skipped[f"{run:%Y-%m-%d %H}"] = fetched.reason
            continue
        frames.append(hourly(fetched.rows, cells, source, model.id))
        result.runs.append(run)
        reached = frames[-1].drop_nulls("temperature_2m")["time"].max()
        last = reached if last is None or (reached is not None and reached > last) else last
        covered = covered or run < start  # this one covers 00 UTC today
        if covered and last is not None and last >= end - timedelta(hours=1):
            break
    if frames:
        result.fc = stitch(frames)
    return result


def from_bucket(
    store: bucket.Bucket,
    models: list[Model],
    points: pl.DataFrame,
    now: datetime,
    cells: pl.DataFrame | None = None,
    days: int = 6,
    threads: int = 32,
    parallel_models: int = 4,
    log: Callable[[str], None] = lambda _: None,
) -> tuple[pl.DataFrame, list[ModelRead]]:
    """Every model of ``models`` at ``points`` (code, lat, lon) as ``outlook.parse``
    gives it, from 00 UTC today for ``days`` days; and per model what was read (those
    with ``fc`` None are left for the API)."""
    cells = load_cells() if cells is None else cells
    table = point_table(points)
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    with ThreadPoolExecutor(threads) as pool, ThreadPoolExecutor(parallel_models) as outer:
        jobs = [
            outer.submit(read_model, store, m, table, cells, now, start, pool, end) for m in models
        ]
        reads = [job.result() for job in jobs]
    frames = []
    for read in reads:
        if read.fc is None:
            log(f"{read.model}: no complete run in the bucket ({read.skipped}); from the API")
            continue
        log(f"{read.model}: runs {', '.join(f'{r:%d %H}' for r in read.runs)} UTC")
        frames.append(read.fc.filter(pl.col("time") >= start, pl.col("time") < end))
    fc = pl.concat(frames) if frames else pl.DataFrame(schema=EMPTY_SCHEMA)
    return fc.filter(~pl.all_horizontal(pl.col(v).is_null() for v in VARIABLES)), reads


EMPTY_SCHEMA = {
    "okres": pl.String,
    "time": pl.Datetime("us", "UTC"),
    "model": pl.String,
    **{v: pl.Float64 for v in VARIABLES},
}
