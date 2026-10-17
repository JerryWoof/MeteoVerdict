"""Sunshine, cloud cover and gusts corrected against ČHMÚ observations.

The plain mean of the models over-forecasts sunshine by about 2.8 hours a day (August to
October 2026, 10 ČHMÚ stations, docs/methodology.md#sunshine-cloud-and-gusts), cloud
cover a little too low and too spread, gusts too weak. Three small statistical
corrections, fitted by least squares on the recent past and refitted every night:

**Sunshine** (per okres and UTC day). ``L`` is the astronomical day length at the okres
point (``day_length``), ``rel`` the models' mean sunshine as a share of it and ``c`` the
models' mean cloud cover 06-16 UTC (0-1). Then

    sunshine = clip((a + b·rel + d·(1 - c)) · L, 0, L)

Fractions of the day, not hours: a plain additive correction (about -3.7 h) would go
negative in December. The hourly values are scaled so that they add up to the corrected
day (``scale_to``: proportionally, no hour above 3,600 s), so hours, parts of day and
days agree.

**Cloud cover** (every hour): ``clip(a + b·mean, 0, 100)``, fitted on the hours 06-16
UTC.

**Gusts** (daily maximum): ``a + b·mean`` plus the mean remaining error of the okres's
representative station (``okres_gust_stations``: a lowland or upland station, never a
summit such as Milešovka or Lysá hora, where the models are 3-6 m/s too weak).

**Gusts per part of day** (``gust_part``, the outlook's ``gust``, ``meteoverdict.gusts``):
the same form fitted on the largest gust of each part of day (Prague time) at the
lowland run stations, from all stored single runs against the hourly ČHMÚ gusts. The
daily coefficients would add about 0.6 m/s too much to a part (out of sample, docs/
methodology.md). ``check`` holds the plain mean's and the correction's mean absolute
error on the last ``CHECK_DAYS`` days, fitted on the days before; ``apply`` is false when
the correction does not beat the plain mean there (the outlook then shows the plain
mean).

Coefficients may differ by lead day (``by_lead``, where a lead day has ``MIN_DAYS`` days
of pairs) and fall back to ``default`` (all lead days pooled). They live in
``sun-cloud-gust.json``: the bootstrap fitted on the research sample ships with the
package (``BOOTSTRAP``); ``fit`` replaces each variable once ``MIN_DAYS`` days of pairs
exist in the last ``WINDOW_DAYS`` days.

Training data cost no Open-Meteo calls: the outlook archives the plain model means of
cloud and sunshine it fetches anyway (``archive_rows``, release ``outlook-archive``),
paired with ČHMÚ daily sunshine ``SSV`` and hourly cloud ``N`` at the nearest lowland
station of each okres point; gusts come from the single runs (``runs-YYYY-MM``) and
ČHMÚ daily ``Fmax``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from meteoverdict import chmi_archive

#: the coefficients fitted on the research sample, used until observations exist
BOOTSTRAP = Path(__file__).parent / "data" / "sun-cloud-gust.json"
#: name of the published coefficients (release data-latest)
NAME = "sun-cloud-gust.json"
ARCHIVE_TAG = "outlook-archive"
ARCHIVE_NOTES = (
    "The outlook's plain model means of cloud cover (%) and sunshine (s in the hour "
    "ending at the time) for every okres point, one month per file "
    "(outlook-archive-YYYY-MM.parquet: okres, issued, time, cloud_cover, "
    "sunshine_duration), kept to fit the sunshine and cloud corrections "
    "(meteoverdict.sun_cloud_gust, docs/methodology.md). Forecasts: Open-Meteo.com, "
    "CC BY 4.0, from the weather services listed in docs/licensing.md. Published under "
    "CC BY-SA 4.0."
)
VARIABLES = ("sunshine", "cloud", "gust", "gust_part")
#: ``gust_part``: the out-of-sample check holds out this many most recent days
CHECK_DAYS = 10
#: days with pairs needed before a fit replaces the bootstrap (research: >= 21)
MIN_DAYS = 21
#: the fit uses the pairs of this many days before today (rolling: the biases change
#: with the season, autumn inversions are expected to make sunshine worse)
WINDOW_DAYS = 60
MAX_LEAD = 5
#: daytime hours (UTC, instants) of the cloud fit and of ``c`` in the sunshine formula
DAYTIME_UTC = (6, 16)
#: a day needs this many hourly sunshine values and daytime cloud values
MIN_SUN_HOURS = 20
MIN_DAYTIME_HOURS = 9
#: stations above this elevation never stand for an okres (summits: Milešovka 830 m,
#: Lysá hora 1,322 m; Polom 747 m, on a ridge, behaves like the lowland stations)
LOWLAND_MAX_M = 750.0
#: the observing station must lie this close to the okres point (ČHMÚ: ~160 stations
#: measure sunshine, ~30 report cloud cover)
SUN_MAX_KM = 40.0
CLOUD_MAX_KM = 60.0
#: a model's daily maximum gust needs at least this many values on the day (3-hourly: 8)
MIN_GUST_VALUES = 8


# --- coefficients --------------------------------------------------------------------
def load(path: Path | None = None) -> dict:
    """The coefficients at ``path``, or the bootstrap when it is missing; a variable the
    file lacks (written before it existed) comes from the bootstrap."""
    bootstrap = json.loads(BOOTSTRAP.read_text("utf-8"))
    if path is None or not path.exists() or path == BOOTSTRAP:
        return bootstrap
    doc = json.loads(path.read_text("utf-8"))
    return {**doc, **{v: bootstrap[v] for v in VARIABLES if v not in doc and v in bootstrap}}


def write(doc: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return path


def coefficients(doc: dict, variable: str, lead_day: int | None = None) -> dict:
    """The coefficients of ``variable`` for ``lead_day`` (its own where fitted, else the
    default)."""
    entry = doc[variable]
    if lead_day is not None:
        own = entry.get("by_lead", {}).get(str(max(1, min(MAX_LEAD, lead_day))))
        if own:
            return own
    return entry["default"]


# --- formulas ------------------------------------------------------------------------
def day_length(lat: float, day: date) -> float:
    """Astronomical day length in hours (sun's centre above a flat horizon, simple
    declination formula; the correction is fitted with the same)."""
    n = day.timetuple().tm_yday
    declination = 23.44 * math.sin(math.radians(360 / 365 * (n - 81)))
    x = -math.tan(math.radians(lat)) * math.tan(math.radians(declination))
    return 24 / math.pi * math.acos(max(-1.0, min(1.0, x)))


def _lstsq(columns: list[np.ndarray], y: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(y)), *columns])
    return np.linalg.lstsq(design, y, rcond=None)[0]


def fit_sunshine(sun_h, cloud, length, observed) -> dict:
    """``obs/L ≈ a + b·(sun/L) + d·(1 - cloud/100)`` by least squares."""
    sun_h, cloud, length, observed = (
        np.asarray(v, float) for v in (sun_h, cloud, length, observed)
    )
    a, b, d = _lstsq([sun_h / length, 1 - cloud / 100], observed / length)
    return {"a": float(a), "b": float(b), "d": float(d)}


def predict_sunshine(coef: dict, sun_h, cloud, length) -> np.ndarray:
    sun_h, cloud, length = (np.asarray(v, float) for v in (sun_h, cloud, length))
    share = coef["a"] + coef["b"] * sun_h / length + coef["d"] * (1 - cloud / 100)
    return np.clip(share * length, 0, length)


def fit_cloud(forecast, observed) -> dict:
    a, b = _lstsq([np.asarray(forecast, float)], np.asarray(observed, float))
    return {"a": float(a), "b": float(b)}


def predict_cloud(coef: dict, forecast) -> np.ndarray:
    return np.clip(coef["a"] + coef["b"] * np.asarray(forecast, float), 0, 100)


def fit_gust(forecast, observed, stations) -> dict:
    """``obs ≈ a + b·mean`` plus each station's mean remaining error."""
    forecast, observed = np.asarray(forecast, float), np.asarray(observed, float)
    a, b = _lstsq([forecast], observed)
    rest = pl.DataFrame({"station": list(stations), "r": observed - a - b * forecast})
    residuals = rest.group_by("station").agg(pl.col("r").mean()).sort("station")
    return {
        "a": float(a),
        "b": float(b),
        "stations": {s: round(float(r), 3) for s, r in residuals.iter_rows()},
    }


def predict_gust(coef: dict, forecast, stations) -> np.ndarray:
    forecast = np.asarray(forecast, float)
    shift = np.array([coef.get("stations", {}).get(s, 0.0) for s in stations], float)
    return np.maximum(coef["a"] + coef["b"] * forecast + shift, 0.0)


def correct_gust(doc: dict, forecast, okresy, lead_day: int | None = None) -> np.ndarray:
    """Daily maximum gusts (plain mean of the models) of ``okresy`` corrected, each with
    the remaining error of its representative station (``okres_stations``; none for an
    okres without one)."""
    stations = doc["gust"].get("okres_stations", {})
    coef = coefficients(doc, "gust", lead_day)
    return predict_gust(coef, forecast, [stations.get(o) for o in okresy])


def scale_to(seconds: np.ndarray, target: float, cap: float = 3600.0) -> np.ndarray:
    """Hourly sunshine scaled to add up to ``target`` seconds: proportionally, the hours
    that would exceed ``cap`` held at it and the rest shared by the others. Hours
    without sunshine stay at 0 (so a day without any keeps none)."""
    values = np.clip(np.asarray(seconds, float), 0, cap)
    out = values.copy()
    free = values > 0
    remaining = float(target)
    while free.any():
        base = values[free].sum()
        trial = values * remaining / base
        over = free & (trial > cap)
        if not over.any():
            out[free] = trial[free]
            break
        out[over] = cap
        remaining -= cap * over.sum()
        free &= ~over
    return out


# --- inputs from hourly means --------------------------------------------------------
def _sun_day() -> pl.Expr:
    """UTC day of an hourly sum (the hour ending at ``time``)."""
    return (pl.col("time") - pl.duration(hours=1)).dt.date()


def daily_inputs(frame: pl.DataFrame, keys: Iterable[str] = ("okres",)) -> pl.DataFrame:
    """Per ``keys`` and UTC day: ``sun_h`` (hours of sunshine, the hours ending in the
    day) and ``cloud`` (mean of the instants 06-16 UTC), where the day has at least
    ``MIN_SUN_HOURS`` sunshine values and ``MIN_DAYTIME_HOURS`` cloud values."""
    keys = list(keys)
    first, last = DAYTIME_UTC
    sun = (
        frame.drop_nulls("sunshine_duration")
        .group_by(*keys, day=_sun_day())
        .agg(
            (pl.col("sunshine_duration").clip(0, 3600).sum() / 3600).alias("sun_h"),
            pl.len().alias("n"),
        )
        .filter(pl.col("n") >= MIN_SUN_HOURS)
        .drop("n")
    )
    cloud = (
        frame.drop_nulls("cloud_cover")
        .filter(pl.col("time").dt.hour().is_between(first, last))
        .group_by(*keys, day=pl.col("time").dt.date())
        .agg(pl.col("cloud_cover").mean().alias("cloud"), pl.len().alias("n"))
        .filter(pl.col("n") >= MIN_DAYTIME_HOURS)
        .drop("n")
    )
    return sun.join(cloud, on=[*keys, "day"], how="inner").sort(*keys, "day")


def _lead(day: date, issued: date) -> int:
    return max(1, min(MAX_LEAD, (day - issued).days))


def correct_hourly(
    hourly: pl.DataFrame, points: pl.DataFrame, doc: dict, now: datetime
) -> pl.DataFrame:
    """The outlook's hourly plain means (``okres``, ``time``, ``cloud_cover``,
    ``sunshine_duration``) corrected; the plain means stay as ``cloud_cover_raw`` and
    ``sunshine_duration_raw``. Days without the inputs (the cut ends of the forecast)
    keep the plain sunshine."""
    latitude = dict(points.select("code", "lat").iter_rows())
    raw = hourly.with_columns(
        pl.col("cloud_cover").alias("cloud_cover_raw"),
        pl.col("sunshine_duration").alias("sunshine_duration_raw"),
    )
    targets = {}
    for okres, day, sun_h, cloud in daily_inputs(hourly).iter_rows():
        if okres not in latitude:
            continue
        coef = coefficients(doc, "sunshine", _lead(day, now.date()))
        length = day_length(latitude[okres], day)
        targets[(okres, day)] = float(predict_sunshine(coef, sun_h, cloud, length)) * 3600
    frames = []
    keyed = raw.with_row_index("_row").with_columns(_sun_day().alias("_day"))
    for (okres, day), part in keyed.partition_by("okres", "_day", as_dict=True).items():
        target = targets.get((okres, day))
        if target is not None:
            seconds = part["sunshine_duration"]
            known = seconds.is_not_null().to_numpy()
            values = seconds.to_numpy().astype(float)
            values[known] = scale_to(values[known], target)
            part = part.with_columns(
                pl.Series("sunshine_duration", values).fill_nan(None).cast(pl.Float64)
            )
        frames.append(part)
    out = pl.concat(frames).sort("_row").drop("_row", "_day")
    leads = (
        out.select(pl.col("time").dt.date().alias("day"))
        .to_series()
        .map_elements(lambda d: _lead(d, now.date()), return_dtype=pl.Int64)
    )
    cloud = out["cloud_cover"].to_numpy().astype(float)
    corrected = np.full(len(cloud), np.nan)
    for lead in set(leads.to_list()):
        rows = (leads == lead).to_numpy() & ~np.isnan(cloud)
        corrected[rows] = predict_cloud(coefficients(doc, "cloud", lead), cloud[rows])
    return out.with_columns(pl.Series("cloud_cover", corrected).fill_nan(None))


# --- archive of the outlook's plain means --------------------------------------------
ARCHIVE_SCHEMA = {
    "okres": pl.String,
    "issued": pl.Datetime("us", "UTC"),
    "time": pl.Datetime("us", "UTC"),
    "cloud_cover": pl.Float32,
    "sunshine_duration": pl.Float32,
}


def archive_asset(month: str) -> tuple[str, str]:
    return ARCHIVE_TAG, f"outlook-archive-{month}.parquet"


def archive_rows(hourly: pl.DataFrame, issued: datetime) -> pl.DataFrame:
    """The plain model means of one outlook run (before any correction)."""
    cloud = "cloud_cover_raw" if "cloud_cover_raw" in hourly.columns else "cloud_cover"
    sun = (
        "sunshine_duration_raw"
        if "sunshine_duration_raw" in hourly.columns
        else ("sunshine_duration")
    )
    return hourly.select(
        pl.col("okres"),
        pl.lit(issued.replace(second=0, microsecond=0)).alias("issued"),
        pl.col("time"),
        pl.col(cloud).alias("cloud_cover"),
        pl.col(sun).alias("sunshine_duration"),
    ).cast(ARCHIVE_SCHEMA)


def append_archive(path: Path, rows: pl.DataFrame) -> Path:
    """Add one run to the month file (a run already in it is replaced)."""
    if path.exists():
        old = pl.read_parquet(path).cast(ARCHIVE_SCHEMA)
        rows = pl.concat(
            [old.filter(~pl.col("issued").is_in(rows["issued"].unique().to_list())), rows]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.sort("issued", "okres", "time").write_parquet(path, compression="zstd")
    return path


# --- observations ----------------------------------------------------------------------
def _km(lat1, lon1, lat2, lon2) -> np.ndarray:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlat, dlon = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    h = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(h))


def nearest_stations(
    points: pl.DataFrame, stations: pl.DataFrame, candidates: Iterable[str], max_km: float
) -> pl.DataFrame:
    """``okres`` → ``station``: the nearest of ``candidates`` (stations observing the
    element) at most ``LOWLAND_MAX_M`` high and ``max_km`` from the okres point.
    ``stations``: ``id``, ``lat``, ``lon``, ``elevation``."""
    pool = stations.filter(
        pl.col("id").is_in(list(set(candidates))), pl.col("elevation") <= LOWLAND_MAX_M
    )
    rows = []
    if pool.height:
        lat, lon, ids = pool["lat"].to_numpy(), pool["lon"].to_numpy(), pool["id"].to_list()
        for code, plat, plon in points.select("code", "lat", "lon").iter_rows():
            km = _km(plat, plon, lat, lon)
            best = int(np.argmin(km))
            if km[best] <= max_km:
                rows.append((code, ids[best], round(float(km[best]), 1)))
    return pl.DataFrame(
        rows, schema={"okres": pl.String, "station": pl.String, "km": pl.Float64}, orient="row"
    )


def observed_daily(chmi_daily: pl.DataFrame, element: str) -> pl.DataFrame:
    """``station``, ``day``, ``observed`` from ČHMÚ daily rows (``SSV`` hours, ``Fmax``
    m/s)."""
    return (
        chmi_daily.filter(pl.col("element") == element, pl.col("value").is_not_null())
        .select(
            "station",
            pl.col("time").dt.date().alias("day"),
            pl.col("value").cast(pl.Float64).alias("observed"),
        )
        .unique(["station", "day"], keep="first")
    )


def observed_cloud(chmi_hourly: pl.DataFrame) -> pl.DataFrame:
    """``station``, ``time``, ``observed`` (%) from ČHMÚ hourly ``N`` in octas; 9 (sky
    obscured, mostly fog) counts as overcast."""
    return (
        chmi_hourly.filter(pl.col("element") == "N", pl.col("value").is_not_null())
        .select(
            "station",
            pl.col("time").cast(pl.Datetime("us", "UTC")),
            pl.when(pl.col("value") >= 8)
            .then(100.0)
            .otherwise(pl.col("value").cast(pl.Float64) * 12.5)
            .alias("observed"),
        )
        .unique(["station", "time"], keep="first")
    )


# --- training pairs ----------------------------------------------------------------------
def sunshine_pairs(
    archive: pl.DataFrame, observed: pl.DataFrame, mapping: pl.DataFrame, points: pl.DataFrame
) -> pl.DataFrame:
    """``okres``, ``station``, ``day``, ``lead_day``, ``sun_h``, ``cloud``, ``length``,
    ``observed``: archived outlook days (lead 1-``MAX_LEAD``) with the daily sunshine
    measured at the okres's station."""
    days = daily_inputs(archive, ("okres", "issued")).with_columns(
        (pl.col("day") - pl.col("issued").dt.date()).dt.total_days().alias("lead_day")
    )
    days = days.filter(pl.col("lead_day").is_between(1, MAX_LEAD))
    pairs = days.join(mapping.select("okres", "station"), on="okres").join(
        observed, on=["station", "day"]
    )
    latitude = dict(points.select("code", "lat").iter_rows())
    length = [day_length(latitude[o], d) for o, d in pairs.select("okres", "day").iter_rows()]
    return pairs.with_columns(pl.Series("length", length, pl.Float64)).select(
        "okres", "station", "day", "lead_day", "sun_h", "cloud", "length", "observed"
    )


def cloud_pairs(
    archive: pl.DataFrame, observed: pl.DataFrame, mapping: pl.DataFrame
) -> pl.DataFrame:
    """``okres``, ``station``, ``day``, ``lead_day``, ``forecast``, ``observed``: archived
    hourly cloud 06-16 UTC with the cloud cover observed at the okres's station."""
    first, last = DAYTIME_UTC
    hours = (
        archive.drop_nulls("cloud_cover")
        .filter(pl.col("time").dt.hour().is_between(first, last))
        .with_columns(
            pl.col("time").dt.date().alias("day"),
            (pl.col("time").dt.date() - pl.col("issued").dt.date())
            .dt.total_days()
            .alias("lead_day"),
        )
        .filter(pl.col("lead_day").is_between(1, MAX_LEAD))
    )
    return (
        hours.join(mapping.select("okres", "station"), on="okres")
        .join(observed, on=["station", "time"])
        .select(
            "okres",
            "station",
            "day",
            "lead_day",
            pl.col("cloud_cover").cast(pl.Float64).alias("forecast"),
            "observed",
        )
    )


def okres_gust_stations(run_stations: pl.DataFrame) -> pl.DataFrame:
    """``okres`` → ``station``: the single-runs station chosen for each okres
    (``reason`` "okres"), unless it lies above ``LOWLAND_MAX_M`` (a summit)."""
    return run_stations.filter(
        pl.col("reason") == "okres", pl.col("elevation") <= LOWLAND_MAX_M
    ).select(pl.col("okres_code").alias("okres"), pl.col("id").alias("station"))


def gust_forecasts(runs: pl.LazyFrame | pl.DataFrame, stations: Iterable[str]) -> pl.DataFrame:
    """``station``, ``day``, ``lead_day``, ``forecast``: from the 00 UTC single runs, the
    mean over the models of each model's largest hourly gust on the UTC day (the hours
    ending in it, at least ``MIN_GUST_VALUES`` values), lead day 1-``MAX_LEAD``."""
    return (
        runs.lazy()
        .filter(
            pl.col("station_id").is_in(list(stations)),
            pl.col("run").dt.hour() == 0,
            pl.col("wind_gusts_10m").is_not_null(),
        )
        .with_columns((pl.col("valid_time") - pl.duration(hours=1)).dt.date().alias("day"))
        .with_columns((pl.col("day") - pl.col("run").dt.date()).dt.total_days().alias("lead_day"))
        .filter(pl.col("lead_day").is_between(1, MAX_LEAD))
        .group_by("station_id", "day", "lead_day", "model")
        .agg(pl.col("wind_gusts_10m").max().alias("gust"), pl.len().alias("n"))
        .filter(pl.col("n") >= MIN_GUST_VALUES)
        .group_by("station_id", "day", "lead_day")
        .agg(pl.col("gust").cast(pl.Float64).mean().alias("forecast"))
        .rename({"station_id": "station"})
        .collect()
    )


# --- fitting -----------------------------------------------------------------------------
def _summary(pairs: pl.DataFrame) -> dict:
    return {
        "pairs": pairs.height,
        "days": pairs["day"].n_unique(),
        "stations": pairs["station"].n_unique(),
        "from": str(pairs["day"].min()),
        "to": str(pairs["day"].max()),
    }


def _fit_by_lead(pairs: pl.DataFrame, fit_one) -> dict:
    """``default`` from all lead days, ``by_lead`` where a lead day has ``MIN_DAYS``."""

    def rounded(part: pl.DataFrame) -> dict:
        return {k: round(v, 5) if isinstance(v, float) else v for k, v in fit_one(part).items()}

    entry = {"default": rounded(pairs), "by_lead": {}}
    for (lead,), part in sorted(pairs.partition_by("lead_day", as_dict=True).items()):
        if part["day"].n_unique() >= MIN_DAYS:
            entry["by_lead"][str(lead)] = rounded(part)
    return entry


def fit(
    previous: dict,
    today: date,
    sunshine: pl.DataFrame | None = None,
    cloud: pl.DataFrame | None = None,
    gust: pl.DataFrame | None = None,
    gust_okresy: pl.DataFrame | None = None,
    gust_part: pl.DataFrame | None = None,
) -> dict:
    """New coefficients from the pairs of the last ``WINDOW_DAYS`` days before ``today``
    (``sunshine_pairs``, ``cloud_pairs``, gust pairs ``station``, ``day``,
    ``lead_day``, ``forecast``, ``observed``); a variable with fewer than ``MIN_DAYS``
    days of pairs keeps its ``previous`` coefficients."""
    first = today - timedelta(days=WINDOW_DAYS)

    def recent(pairs: pl.DataFrame | None) -> pl.DataFrame | None:
        if pairs is None:
            return None
        pairs = pairs.filter(pl.col("day").is_between(first, today - timedelta(days=1)))
        return pairs if pairs["day"].n_unique() >= MIN_DAYS else None

    doc = {
        **previous,
        "fitted": datetime.now(UTC).isoformat(timespec="minutes"),
        "provenance": (
            f"Refitted by `mvd sun-cloud-gust` on {today}: per variable, the pairs of the "
            f"{WINDOW_DAYS} days before (outlook archive and single runs against ČHMÚ "
            f"SSV, N and Fmax) once there are {MIN_DAYS} days of them (source "
            '"observations"); a variable with source "bootstrap" keeps the coefficients '
            "described in bootstrap_provenance."
        ),
        "bootstrap_provenance": previous.get("bootstrap_provenance", previous.get("provenance")),
    }
    pairs = recent(sunshine)
    if pairs is not None:
        doc["sunshine"] = {
            "source": "observations",
            **_summary(pairs),
            **_fit_by_lead(
                pairs,
                lambda p: fit_sunshine(p["sun_h"], p["cloud"], p["length"], p["observed"]),
            ),
        }
    pairs = recent(cloud)
    if pairs is not None:
        doc["cloud"] = {
            "source": "observations",
            **_summary(pairs),
            **_fit_by_lead(pairs, lambda p: fit_cloud(p["forecast"], p["observed"])),
        }
    pairs = recent(gust)
    if pairs is not None:
        entry = _fit_by_lead(pairs, lambda p: fit_gust(p["forecast"], p["observed"], p["station"]))
        okres_stations = {}
        if gust_okresy is not None:
            have = set(pairs["station"].unique())
            okres_stations = {o: s for o, s in gust_okresy.iter_rows() if s in have}
        doc["gust"] = {
            "source": "observations",
            **_summary(pairs),
            **entry,
            "okres_stations": dict(sorted(okres_stations.items())),
        }
    pairs = recent(gust_part)
    if pairs is not None:
        check = gust_check(pairs)
        previous_apply = previous.get("gust_part", {}).get("apply", True)
        doc["gust_part"] = {
            "source": "observations",
            **_summary(pairs),
            **_fit_by_lead(pairs, lambda p: fit_gust(p["forecast"], p["observed"], p["station"])),
            "check": check,
            "apply": previous_apply if check is None else check["corrected_mae"] < check["raw_mae"],
        }
    return doc


def gust_check(pairs: pl.DataFrame) -> dict | None:
    """The plain mean against the correction on the last ``CHECK_DAYS`` days of
    ``pairs`` (``station``, ``day``, ``forecast``, ``observed``), fitted on the days
    before; None with fewer than ``MIN_DAYS`` days before them."""
    days = sorted(pairs["day"].unique().to_list())
    if len(days) < MIN_DAYS + CHECK_DAYS:
        return None
    split = days[-CHECK_DAYS]
    train, test = pairs.filter(pl.col("day") < split), pairs.filter(pl.col("day") >= split)
    coef = fit_gust(train["forecast"], train["observed"], train["station"])
    corrected = predict_gust(coef, test["forecast"], test["station"])
    observed, raw = test["observed"].to_numpy(), test["forecast"].to_numpy()
    return {
        "from": str(split),
        "to": str(days[-1]),
        "pairs": test.height,
        "raw_mae": round(float(np.abs(raw - observed).mean()), 3),
        "raw_bias": round(float((raw - observed).mean()), 3),
        "corrected_mae": round(float(np.abs(corrected - observed).mean()), 3),
        "corrected_bias": round(float((corrected - observed).mean()), 3),
    }


# --- the nightly fit from local files ------------------------------------------------------
def _months(first: date, last: date) -> list[tuple[int, int]]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def wanted_chmi(today: date) -> list[tuple[str, str]]:
    """ČHMÚ archive files (``chmi_archive`` names) the fit reads: the daily and hourly
    month files of the window and the captured days (the hourly data of the current
    month are in a month file only after it ends)."""
    first = today - timedelta(days=WINDOW_DAYS + 1)
    wanted = [
        chmi_archive.month_asset(res, y, m)
        for y, m in _months(first, today)
        for res in ("daily", "1hour")
    ]
    days = (today - first).days + 1
    return wanted + [chmi_archive.day_asset(first + timedelta(days=i)) for i in range(days)]


def read_chmi(root: Path, today: date) -> tuple[pl.DataFrame, pl.DataFrame]:
    """ČHMÚ daily ``SSV`` and ``Fmax`` and hourly ``N`` of the window from the archive
    files under ``root/<tag>/<name>`` (month files first, then the captured days)."""
    first = today - timedelta(days=WINDOW_DAYS + 1)
    since = datetime.combine(first, datetime.min.time(), UTC)
    daily, hourly = [], []
    for tag, name in wanted_chmi(today):
        path = root / tag / name
        if not path.exists():
            continue
        frame = pl.scan_parquet(path).filter(pl.col("time") >= since)
        if "-daily-" in name:
            daily.append(frame.filter(pl.col("element").is_in(["SSV", "Fmax"])))
        else:
            hourly.append(frame.filter(pl.col("element") == "N", pl.col("resolution") == "1hour"))
    empty = pl.DataFrame(schema=chmi_archive.SCHEMA)
    return (
        pl.concat(daily).collect() if daily else empty,
        pl.concat(hourly).collect() if hourly else empty,
    )


def read_archive(folder: Path, today: date) -> pl.DataFrame:
    """The archived outlook runs of the window (``outlook-archive-YYYY-MM.parquet``)."""
    first = today - timedelta(days=WINDOW_DAYS + MAX_LEAD + 1)
    paths = [folder / archive_asset(f"{y:04d}-{m:02d}")[1] for y, m in _months(first, today)]
    frames = [pl.read_parquet(p).cast(ARCHIVE_SCHEMA) for p in paths if p.exists()]
    if not frames:
        return pl.DataFrame(schema=ARCHIVE_SCHEMA)
    return pl.concat(frames)


def fit_from_files(
    previous: dict,
    today: date,
    archive: pl.DataFrame,
    chmi_daily: pl.DataFrame,
    chmi_hourly: pl.DataFrame,
    stations: pl.DataFrame,
    points: pl.DataFrame,
    run_stations: pl.DataFrame,
    runs: pl.LazyFrame | pl.DataFrame | None,
    gust_part: pl.DataFrame | None = None,
) -> tuple[dict, dict]:
    """The new coefficients and what they were fitted on, per variable. ``stations``:
    ČHMÚ ``id``, ``lat``, ``lon``, ``elevation``; ``points``: the okres points
    (``code``, ``lat``, ``lon``); ``run_stations``: ``runs.load_stations()``;
    ``gust_part``: the part-of-day gust pairs (``gusts.pairs``)."""
    sun_obs = observed_daily(chmi_daily, "SSV")
    gust_obs = observed_daily(chmi_daily, "Fmax")
    cloud_obs = observed_cloud(chmi_hourly)
    sun_map = nearest_stations(points, stations, sun_obs["station"].unique(), SUN_MAX_KM)
    cloud_map = nearest_stations(points, stations, cloud_obs["station"].unique(), CLOUD_MAX_KM)
    pairs = {
        "sunshine": sunshine_pairs(archive, sun_obs, sun_map, points),
        "cloud": cloud_pairs(archive, cloud_obs, cloud_map),
        "gust": None,
        "gust_part": gust_part,
    }
    reps = okres_gust_stations(run_stations)
    if runs is not None:
        pairs["gust"] = gust_forecasts(runs, reps["station"].unique()).join(
            gust_obs, on=["station", "day"]
        )
    doc = fit(previous, today, pairs["sunshine"], pairs["cloud"], pairs["gust"], reps, gust_part)
    okresy = {
        "sunshine": sun_map.height,
        "cloud": cloud_map.height,
        "gust": reps.height,
        "gust_part": 0 if gust_part is None else gust_part["station"].n_unique(),
    }
    info = {
        v: {
            "okresy": okresy[v],
            "pairs": 0 if pairs[v] is None else pairs[v].height,
            "days": 0 if pairs[v] is None else pairs[v]["day"].n_unique(),
            "source": doc[v]["source"],
        }
        for v in VARIABLES
    }
    return doc, info
