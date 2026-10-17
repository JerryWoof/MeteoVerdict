"""What the weather was like: measured values per okres and part of day, the past days of
the forecast map (web/tv.html), from the ČHMÚ archive (docs/data-sources.md#observed-map).

For every past day the map offers, ``<out>/<YYYY-MM-DD>.json`` holds per okres the values
measured at its ČHMÚ stations, aggregated by the outlook's parts of day in Prague time
(night 0-6, morning 6-12, afternoon 12-18, evening 18-24, and the whole day 0-24), with the
number of stations behind each value, and, where the outlook's own parts of day were
archived (``outlook.parts_archive_asset``), what our forecast said a few days before.
``<out>/<YYYY-MM-DD>-stations.json`` has the stations' own values (the map's station
dots), ``<out>/index.json`` the days.

A station's value of a period (from the 10-minute and hourly archive, the last
``PART_DAYS`` days):

==========  ==================  ======================================================
field       from                rule
==========  ==================  ======================================================
``tmax``    TMA (10 min), T     highest of the 10-minute maxima and the hourly values
``tmin``    TMI (10 min), T     lowest
``r``       SRA1H               total; every hour of the period must be there
``wind``    F at the full hour  highest (as the forecast: the highest hourly wind)
``gust``    Fmax (10 min)       strongest gust
``ssv``     SSV1H (0.1 h)       hours of sunshine; only periods with daylight
``cloud``   N (octas)           mean cloud cover in %, sky obscured (9) left out
==========  ==================  ======================================================

A 10-minute value belongs to the period its 10 minutes fall in, an hourly total to the
period of its hour, a value at the full hour to the period of that time (as the
outlook's instantaneous values). Temperature, wind and gust need values in at least
``MIN_SHARE`` of the period's hours (cloud half of them; sunshine in ``MIN_SHARE`` of its
daylight hours), else the station has no value for that period.

An okres's value is the mean over its stations with a value (``tmax``, ``tmin``, ``r``,
``wind``, ``ssv``, ``cloud``), with the extremes beside (``tmax_hi``, ``tmin_lo``,
``r_hi``) and the strongest gust; ``n_*`` count the stations. Older days (up to
``DAILY_DAYS`` back) have the whole day only, from ČHMÚ's daily climate values with
ČHMÚ's own windows (``station_diary.FIELDS``: precipitation 07-07 CET, including the
manual rain gauges).

Values of quality 1 (suspect), 2 (poor) and 4 (missing) are left out, as everywhere.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from meteoverdict import (
    aggregate,
    chmi_archive,
    hindcast,
    neighbours,
    outlook,
    station_diary,
    sun_cloud_gust,
)
from meteoverdict.sun import sun_times

TIME_ZONE = outlook.TIME_ZONE
PRAGUE = ZoneInfo(TIME_ZONE)
PARTS = outlook.PARTS
#: the parts of day, then the whole day (as the forecast map)
PERIODS = (*PARTS, "day")
#: days back with parts of day (the 10-minute and hourly data the station pages read)
PART_DAYS = 30
#: days back with the whole day from the daily climate values
DAILY_DAYS = 60
#: share of a period's hours with a value that a station needs
MIN_SHARE = 0.8
CLOUD_SHARE = 0.5
#: a period gets sunshine only with at least this much daylight (h)
MIN_LIGHT_H = 0.5
#: a day counts as measured (hourly) with this many stations with a temperature
MIN_STATIONS = 50
KEEP_QUALITY = station_diary.KEEP_QUALITY
#: published under site/data: data/scores/observed/ in the web app
FOLDER = "observed"
ZIP = "observed-data.zip"
INDEX = "index.json"
#: the okres values, in the files' order
COLUMNS = ("tmax", "tmin", "tmax_hi", "tmin_lo", "r", "r_hi", "wind", "gust", "ssv", "cloud")
#: station counts: temperature, precipitation, wind, gust, sunshine, cloud
COUNTS = {
    "n_t": "tmax",
    "n_r": "r",
    "n_w": "wind",
    "n_g": "gust",
    "n_s": "ssv",
    "n_c": "cloud",
}
#: groups of values an okres may borrow from its neighbours, each with the column whose
#: station count (``COUNTS``) says whether the okres has a station of its own
GROUPS = {"t": "tmax", "r": "r", "w": "wind", "g": "gust", "s": "ssv", "c": "cloud"}
#: an okres without a station of its own for a group takes the nearest stations of other
#: okresy with a value, at most this far from its border, as many as the scoring borrows
BORROW_MAX_KM = neighbours.MAX_KM
BORROW_STATIONS = aggregate.MIN_STATIONS
#: a station's values (the station dots)
STATION_COLUMNS = ("tmax", "tmin", "r", "wind", "gust", "ssv", "cloud")
DIGITS = {"r": 1, "r_hi": 1, "ssv": 1, "cloud": 0}
#: forecast leads (days before the day, Prague time) kept beside the measured values;
#: lead 0 (the day's first run) only when there is no other
LEADS = (1, 2, 3)
SOURCE = "ČHMÚ, opendata.chmi.cz, CC BY 4.0"
NOTES = (
    "Measured values per okres (mean over its ČHMÚ stations, n_* stations) by part of day "
    "in Prague time; tmax/tmin from the 10-minute maxima and minima, r precipitation total "
    "(mm, from the hourly totals, all hours needed), wind the highest value at the full hour "
    "(m/s), gust the strongest 10-minute gust in the okres (m/s), ssv sunshine (h), cloud the "
    "mean cloud cover (%, synoptic stations only), light the hours of daylight at the okres "
    "point; tmax_hi/tmin_lo/r_hi the extremes over the stations. An okres without a "
    "station of its own for a value takes it from the nearest stations of other okresy "
    "(at most 30 km from its border, up to 3): 'borrowed' lists them per value group "
    "(t, r, w, g, s, c) and period, 'bst' names them. Daily days: the whole day "
    "from ČHMÚ's daily climate values (precipitation 07-07 CET incl. manual rain gauges, "
    "temperature 21-21 CET). forecasts: our outlook's parts of day from runs issued 'lead' "
    "days before (Prague time). Format: docs/data-sources.md#observed-map."
)

#: (resolution, element) → (field, kind): ``end10`` the 10 minutes ending at the time,
#: ``end1h`` the hour ending at it, ``inst`` a value at the full hour
SOURCES: dict[tuple[str, str], tuple[str, str]] = {
    ("10min", "TMA"): ("tmax", "end10"),
    ("10min", "TMI"): ("tmin", "end10"),
    ("10min", "T"): ("t", "inst"),
    ("10min", "Fmax"): ("gust", "end10"),
    ("10min", "F"): ("wind", "inst"),
    ("1hour", "SRA1H"): ("r", "end1h"),
    ("1hour", "SSV1H"): ("ssv", "end1h"),
    ("1hour", "N"): ("n", "inst"),
}
#: instantaneous 10-minute elements are read at the full hour only (much smaller)
FULL_HOUR_ONLY = {"T", "F"}
OBS_SCHEMA = {
    "station": pl.String,
    "time": pl.Datetime("ms", "UTC"),
    "field": pl.String,
    "kind": pl.String,
    "value": pl.Float64,
}


# --- days and parts of day -----------------------------------------------------------
def prague_today(now: datetime) -> date:
    return now.astimezone(PRAGUE).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC start and end of a Prague day."""
    start = datetime.combine(day, time(), PRAGUE).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(), PRAGUE).astimezone(UTC)
    return start, end


def part_bounds(day: date, part: str) -> tuple[datetime, datetime]:
    """UTC start and end of a part of a Prague day ("day": the whole day)."""
    if part == "day":
        return day_bounds(day)
    first, end = outlook.PARTS[part]
    start = datetime.combine(day, time(first), PRAGUE)
    stop = (
        datetime.combine(day + timedelta(days=1), time(), PRAGUE)
        if end == 24
        else datetime.combine(day, time(end), PRAGUE)
    )
    return start.astimezone(UTC), stop.astimezone(UTC)


def expected_hours(day: date, part: str) -> int:
    """Hours of a period on the clock (a part is 5 or 7 hours on the days the clock changes)."""
    start, end = part_bounds(day, part)
    return round((end - start).total_seconds() / 3600)


def daylight(lat: float, lon: float, day: date) -> list[float]:
    """Hours of daylight (sunrise to sunset) in each period of a Prague day at a point."""
    rise, set_ = sun_times(lat, lon, day)
    out = []
    for part in PERIODS:
        start, end = part_bounds(day, part)
        if rise is None or set_ is None:
            out.append(0.0)
            continue
        overlap = (min(end, set_) - max(start, rise)).total_seconds() / 3600
        out.append(round(max(0.0, overlap), 1))
    return out


def _with_period(frame: pl.DataFrame) -> pl.DataFrame:
    """Add ``slot`` (start of the interval a value covers), the Prague ``day`` and
    ``part`` and ``hour`` (the UTC hour of the slot, to count hours with a value)."""
    slot = (
        pl.when(pl.col("kind") == "end10")
        .then(pl.col("time") - pl.duration(minutes=10))
        .when(pl.col("kind") == "end1h")
        .then(pl.col("time") - pl.duration(hours=1))
        .otherwise(pl.col("time"))
    )
    local = pl.col("slot").dt.convert_time_zone(TIME_ZONE)
    part = pl.lit(None, pl.String)
    for name, (first, end) in outlook.PARTS.items():
        part = (
            pl.when(local.dt.hour().is_between(first, end - 1)).then(pl.lit(name)).otherwise(part)
        )
    return (
        frame.with_columns(slot.alias("slot"))
        .with_columns(
            local.dt.date().alias("day"),
            part.alias("part"),
            pl.col("slot").dt.truncate("1h").alias("hour"),
        )
        .drop("slot")
    )


# --- reading the archive -------------------------------------------------------------
def _months(first: date, last: date) -> list[tuple[int, int]]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def read_fine(root: Path, first: date, last: date) -> pl.DataFrame:
    """Observation rows (``OBS_SCHEMA``) of the Prague days ``first`` … ``last``: checked
    month files first, then the captured days (``chmi-now-…``) for what they lack."""
    since = day_bounds(first)[0]
    until = day_bounds(last)[1]
    pairs = pl.DataFrame(
        {
            "resolution": [r for r, _ in SOURCES],
            "element": [e for _, e in SOURCES],
            "field": [f for f, _ in SOURCES.values()],
            "kind": [k for _, k in SOURCES.values()],
        }
    )
    keep = (
        (pl.col("time") >= since)
        & (pl.col("time") <= until)
        & pl.col("value").is_not_null()
        & pl.col("quality").is_in(KEEP_QUALITY)
        & pl.col("element").is_in(pairs["element"].unique().implode())
        & (~pl.col("element").is_in(list(FULL_HOUR_ONLY)) | (pl.col("time").dt.minute() == 0))
    )
    paths = []
    for year, month in _months(since.date(), until.date()):
        for res in chmi_archive.MONTH_RESOLUTIONS:
            tag, name = chmi_archive.month_asset(res, year, month)
            paths.append(root / tag / name)
    day = since.date()
    while day <= until.date():
        tag, name = chmi_archive.day_asset(day)
        paths.append(root / tag / name)
        day += timedelta(days=1)
    parts = [
        pl.scan_parquet(p).filter(keep).select("station", "resolution", "time", "element", "value")
        for p in paths
        if p.exists()
    ]
    if not parts:
        return pl.DataFrame(schema=OBS_SCHEMA)
    return (
        pl.concat(parts)
        .unique(["station", "resolution", "time", "element"], keep="first", maintain_order=True)
        .join(pairs.lazy(), on=["resolution", "element"])
        .select(
            "station",
            pl.col("time").dt.cast_time_unit("ms"),
            "field",
            "kind",
            pl.col("value").cast(pl.Float64),
        )
        .collect()
    )


def read_daily(root: Path, first: date, last: date) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The daily climate rows and the phenomena of ``first`` … ``last`` from the recent
    month files (``chmi-daily-YYYY-MM``, ``chmi-phenomena-YYYY-MM``)."""
    out = []
    for resolution in ("daily", "phenomena"):
        paths = [
            root / tag / name
            for tag, name in (
                chmi_archive.month_asset(resolution, y, m) for y, m in _months(first, last)
            )
        ]
        frames = [
            pl.scan_parquet(p).filter(
                pl.col("time").dt.date().is_between(first, last + timedelta(days=1))
            )
            for p in paths
            if p.exists()
        ]
        out.append(
            pl.concat(frames).collect() if frames else pl.DataFrame(schema=chmi_archive.SCHEMA)
        )
    return out[0], out[1]


# --- a station's values -------------------------------------------------------------
def _agg(field: str | list[str], how: str) -> pl.Expr:
    fields = [field] if isinstance(field, str) else field
    value = pl.col("value").filter(pl.col("field").is_in(fields))
    return getattr(value, how)()


def _hours(field: str | list[str]) -> pl.Expr:
    fields = [field] if isinstance(field, str) else field
    return pl.col("hour").filter(pl.col("field").is_in(fields)).n_unique()


def station_periods(
    rows: pl.DataFrame, light: Callable[[str, date], list[float]] | None = None
) -> pl.DataFrame:
    """One row per station, Prague day and period (``PERIODS``) with ``STATION_COLUMNS``,
    null where the station's values do not cover enough of the period (module doc).
    ``light(station, day)``: hours of daylight per period (``daylight``), for the
    sunshine; without it every period counts as daylit."""
    if rows.height == 0:
        return pl.DataFrame(
            schema={
                "station": pl.String,
                "day": pl.Date,
                "part": pl.String,
                **dict.fromkeys(STATION_COLUMNS, pl.Float64),
            }
        )
    rows = _with_period(rows)
    stats = [
        _agg(["tmax", "t"], "max").alias("tmax"),
        _agg(["tmin", "t"], "min").alias("tmin"),
        _hours(["tmax", "tmin", "t"]).alias("h_t"),
        _agg("r", "sum").alias("r"),
        _hours("r").alias("h_r"),
        _agg("wind", "max").alias("wind"),
        _hours("wind").alias("h_w"),
        _agg("gust", "max").alias("gust"),
        _hours("gust").alias("h_g"),
        (_agg("ssv", "sum") / 10).alias("ssv"),
        _hours("ssv").alias("h_s"),
        (
            pl.col("value").filter((pl.col("field") == "n") & (pl.col("value") <= 8)).mean() * 12.5
        ).alias("cloud"),
        pl.col("hour")
        .filter((pl.col("field") == "n") & (pl.col("value") <= 8))
        .n_unique()
        .alias("h_c"),
    ]
    parts = rows.group_by("station", "day", "part").agg(stats)
    days = rows.group_by("station", "day").agg(stats).with_columns(pl.lit("day").alias("part"))
    table = pl.concat([parts, days], how="diagonal_relaxed")
    keys = table.select("day", "part").unique()
    hours = keys.with_columns(
        pl.Series(
            "expected",
            [expected_hours(d, p) for d, p in keys.iter_rows()],
            dtype=pl.Int64,
        )
    )
    table = table.join(hours, on=["day", "part"])
    index = {p: i for i, p in enumerate(PERIODS)}
    if light is None:
        table = table.with_columns(pl.col("expected").cast(pl.Float64).alias("light"))
    else:
        cache: dict[tuple[str, date], list[float]] = {}
        lights = []
        for station, day, part in table.select("station", "day", "part").iter_rows():
            if (station, day) not in cache:
                cache[(station, day)] = light(station, day)
            lights.append(cache[(station, day)][index[part]])
        table = table.with_columns(pl.Series("light", lights, dtype=pl.Float64))
    need = (pl.col("expected") * MIN_SHARE).ceil()
    keep = {
        "tmax": pl.col("h_t") >= need,
        "tmin": pl.col("h_t") >= need,
        "r": pl.col("h_r") >= pl.col("expected"),
        "wind": pl.col("h_w") >= need,
        "gust": pl.col("h_g") >= need,
        "ssv": (pl.col("light") >= MIN_LIGHT_H)
        & (pl.col("h_s") >= (pl.col("light") * MIN_SHARE).floor()),
        "cloud": pl.col("h_c") >= (pl.col("expected") * CLOUD_SHARE).ceil(),
    }
    return (
        table.select(
            "station",
            "day",
            "part",
            *[pl.when(ok).then(pl.col(c)).alias(c) for c, ok in keep.items()],
        )
        .with_columns(pl.col(c).cast(pl.Float64) for c in STATION_COLUMNS)
        .sort("station", "day", "part")
    )


def station_days(daily: pl.DataFrame) -> pl.DataFrame:
    """The whole day from ČHMÚ's daily climate values (``station_diary.FIELDS`` and
    windows): one row per station and day with ``part`` "day", ``STATION_COLUMNS`` (no
    wind, no cloud) and ``sno`` (new snow, cm)."""
    choice = pl.DataFrame(
        {
            "element": [e for e, _ in station_diary.FIELDS.values()],
            "vtype": [v for _, v in station_diary.FIELDS.values()],
            "field": list(station_diary.FIELDS),
        }
    )
    rows = (
        daily.filter(pl.col("value").is_not_null(), pl.col("quality").is_in(KEEP_QUALITY))
        .join(choice, on=["element", "vtype"], how="inner")
        .select("station", pl.col("time").dt.date().alias("day"), "field", "value")
        .unique(["station", "day", "field"], keep="first", maintain_order=True)
    )
    wide = rows.pivot("field", index=["station", "day"], values="value")
    for field in station_diary.FIELDS:
        if field not in wide.columns:
            wide = wide.with_columns(pl.lit(None, pl.Float64).alias(field))
    return wide.select(
        "station",
        "day",
        pl.lit("day").alias("part"),
        pl.col("tx").cast(pl.Float64).alias("tmax"),
        pl.col("tn").cast(pl.Float64).alias("tmin"),
        pl.col("r").cast(pl.Float64).alias("r"),
        pl.lit(None, pl.Float64).alias("wind"),
        pl.col("g").cast(pl.Float64).alias("gust"),
        pl.col("ssv").cast(pl.Float64).alias("ssv"),
        pl.lit(None, pl.Float64).alias("cloud"),
        pl.col("sno").cast(pl.Float64).alias("sno"),
    ).sort("station", "day")


def day_extras(daily: pl.DataFrame, phenomena: pl.DataFrame) -> pl.DataFrame:
    """Per station and day: ``sno`` (new snow, cm, ČHMÚ's daily value) and ``ph`` (the
    phenomena recorded, ``station_diary.PHENOMENA``), for the observed symbol."""
    snow = (
        daily.filter(
            pl.col("element") == "SNO",
            pl.col("vtype") == "06:00",
            pl.col("value").is_not_null(),
            pl.col("quality").is_in(KEEP_QUALITY),
        )
        .select(
            "station",
            pl.col("time").dt.date().alias("day"),
            pl.col("value").cast(pl.Float64).alias("sno"),
        )
        .unique(["station", "day"], keep="first")
    )
    ph = (
        phenomena.filter(pl.col("element").is_in(station_diary.PHENOMENA))
        .select("station", pl.col("time").dt.date().alias("day"), pl.col("element").alias("code"))
        .unique()
        .group_by("station", "day")
        .agg(pl.col("code").sort().alias("ph"))
    )
    return snow.join(ph, on=["station", "day"], how="full", coalesce=True)


# --- okres values ----------------------------------------------------------------------
def _okres_aggs() -> dict[str, list[pl.Expr]]:
    """The okres values of each group of ``GROUPS``, over the stations given."""
    return {
        "t": [
            pl.col("tmax").mean(),
            pl.col("tmin").mean(),
            pl.col("tmax").max().alias("tmax_hi"),
            pl.col("tmin").min().alias("tmin_lo"),
        ],
        "r": [pl.col("r").mean(), pl.col("r").max().alias("r_hi")],
        "w": [pl.col("wind").mean()],
        "g": [pl.col("gust").max()],
        "s": [pl.col("ssv").mean()],
        "c": [pl.col("cloud").mean()],
    }


def borrowed_stations(
    values: pl.DataFrame,
    stations: pl.DataFrame,
    distance: pl.DataFrame,
    own: pl.DataFrame,
    max_km: float = BORROW_MAX_KM,
    count: int = BORROW_STATIONS,
) -> pl.DataFrame:
    """Where an okres has no station with a value of a variable group (``GROUPS``) in a
    period, the nearest ``count`` stations of other okresy with one, at most ``max_km``
    from its border (the scoring's borrowed stations, ``neighbours.pools``; ties by
    station id). ``distance``: ``neighbours.distances``; ``own``: ``okres``, ``day``,
    ``part`` and the counts (``COUNTS``) of the okres's own stations. One row per okres,
    day, period, group and station: ``okres``, ``day``, ``part``, ``group``, ``station``,
    ``km``."""
    home = stations.select(pl.col("id").alias("station"), pl.col("okres_code").alias("home"))
    near = (
        distance.filter(pl.col("distance_km") <= max_km)
        .select(
            pl.col("region").alias("okres"),
            pl.col("station_id").alias("station"),
            pl.col("distance_km").alias("km"),
        )
        .join(home, on="station")
        .filter(pl.col("okres") != pl.col("home"))
        .drop("home")
    )
    frames = []
    for group, column in GROUPS.items():
        count_column = next(n for n, c in COUNTS.items() if c == column)
        has = values.filter(pl.col(column).is_not_null()).select("station", "day", "part")
        covered = own.filter(pl.col(count_column) > 0).select("okres", "day", "part")
        frames.append(
            has.join(near, on="station")
            .join(covered, on=["okres", "day", "part"], how="anti")
            .sort("okres", "day", "part", "km", "station")
            .filter(pl.int_range(pl.len()).over("okres", "day", "part") < count)
            .with_columns(pl.lit(group).alias("group"))
        )
    schema = {
        "okres": pl.String,
        "day": pl.Date,
        "part": pl.String,
        "group": pl.String,
        "station": pl.String,
        "km": pl.Float64,
    }
    if not frames:
        return pl.DataFrame(schema=schema)
    return pl.concat([f.select(list(schema)).cast(schema) for f in frames]).sort(
        "okres", "day", "part", "group", "km", "station"
    )


def okres_periods(
    values: pl.DataFrame, stations: pl.DataFrame, distance: pl.DataFrame | None = None
) -> pl.DataFrame:
    """One row per okres, day and period: the mean over its stations (``tmax``, ``tmin``,
    ``r``, ``wind``, ``ssv``, ``cloud``), the extremes (``tmax_hi``, ``tmin_lo``,
    ``r_hi``, ``gust``) and the number of stations behind each (``COUNTS``); ``st`` the
    stations with any value. ``stations``: ``id`` and ``okres_code``.

    With ``distance`` (``neighbours.distances``), an okres without a station of its own
    for a variable group takes that group's values from the nearest stations of its
    neighbours (``borrowed_stations``); ``b_<group>`` lists them (null: its own)."""
    where = stations.select(pl.col("id").alias("station"), pl.col("okres_code").alias("okres"))
    joined = values.join(where, on="station", how="inner")
    aggs = _okres_aggs()
    own = (
        joined.group_by("okres", "day", "part")
        .agg(
            *[e for exprs in aggs.values() for e in exprs],
            *[pl.col(c).count().alias(n) for n, c in COUNTS.items()],
            pl.col("station")
            .filter(pl.any_horizontal([pl.col(c).is_not_null() for c in STATION_COLUMNS]))
            .unique()
            .sort()
            .alias("st"),
        )
        .with_columns(pl.lit(None, pl.List(pl.String)).alias(f"b_{g}") for g in GROUPS)
    )
    if distance is None:
        return own.sort("okres", "day", "part")
    borrowed = borrowed_stations(values, stations, distance, own)
    keys = ["okres", "day", "part"]
    out = own
    for group, column in GROUPS.items():
        count_column = next(n for n, c in COUNTS.items() if c == column)
        picked = borrowed.filter(pl.col("group") == group)
        if picked.height == 0:
            continue
        lent = (
            picked.join(values, on=["station", "day", "part"])
            .group_by(keys)
            .agg(
                *aggs[group],
                pl.col(column).count().alias(count_column),
                pl.col("station").sort_by("km", "station").alias(f"b_{group}"),
            )
        )
        replaced = [c for c in lent.columns if c not in keys]
        out = (
            out.join(lent, on=keys, how="full", coalesce=True, suffix="_lent")
            .with_columns(
                pl.when(pl.col(f"{count_column}_lent").is_not_null())
                .then(pl.col(f"{c}_lent"))
                .otherwise(pl.col(c))
                .alias(c)
                for c in replaced
            )
            .drop(f"{c}_lent" for c in replaced)
        )
    counts = list(COUNTS)
    return out.with_columns(pl.col(counts).fill_null(0)).sort(keys)


def _value(v, column: str):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    r = round(v, DIGITS.get(column, 1))
    return int(r) if r == int(r) else r


# --- the forecast that was ---------------------------------------------------------------
def read_parts_archive(folder: Path, first: date, last: date) -> pl.DataFrame:
    """The archived outlook parts of day (``outlook.parts_archive_asset``) of the runs
    that may forecast ``first`` … ``last``."""
    since = datetime.combine(first - timedelta(days=max(LEADS) + 1), time(), UTC)
    names = {
        outlook.parts_archive_asset(datetime(y, m, 1, tzinfo=UTC))[1]
        for y, m in _months(since.date(), last)
    }
    frames = [
        pl.read_parquet(folder / n).cast(outlook.PARTS_ARCHIVE_SCHEMA)
        for n in sorted(names)
        if (folder / n).exists()
    ]
    if not frames:
        return pl.DataFrame(schema=outlook.PARTS_ARCHIVE_SCHEMA)
    return pl.concat(frames).filter(pl.col("day").is_between(first, last))


#: a same-day run (lead 0) is shown when issued before this hour, Prague time
SAME_DAY_BEFORE_HOUR = 12


def pick_runs(archive: pl.DataFrame, day: date) -> list[tuple[int, datetime]]:
    """The runs shown beside the measured ``day``: for each lead of ``LEADS`` the newest
    run issued that many Prague days before, and the day's first run (lead 0) when it
    was issued before ``SAME_DAY_BEFORE_HOUR`` (the morning's forecast for the day)."""
    runs = archive.filter(pl.col("day") == day)["issued"].unique().sort().to_list()
    by_day: dict[int, list[datetime]] = {}
    for issued in runs:
        lead = (day - issued.astimezone(PRAGUE).date()).days
        by_day.setdefault(lead, []).append(issued)
    picked = [(lead, max(by_day[lead])) for lead in LEADS if lead in by_day]
    if 0 in by_day and min(by_day[0]).astimezone(PRAGUE).hour < SAME_DAY_BEFORE_HOUR:
        picked.insert(0, (0, min(by_day[0])))
    return picked


def _entry(
    lead: int,
    kind: str,
    rows: pl.DataFrame,
    periods: tuple[str, ...],
    columns: tuple[str, ...],
    **extra,
) -> dict:
    """A forecast of the day file: ``{"lead", "kind", …extra, "columns", "okresy":
    {code: {column: [per period]}}}`` from rows with ``okres``, ``part`` and ``columns``."""
    at = {(o, p): row for o, p, *row in rows.select("okres", "part", *columns).iter_rows()}
    okresy = {}
    for code in sorted(rows["okres"].unique().to_list()):
        values: dict[str, list] = {}
        for i, column in enumerate(columns):
            out = []
            for part in periods:
                row = at.get((code, part))
                v = row[i] if row else None
                if column == "rain_probability" and v is not None:
                    v = round(v, 2)
                elif column != "symbol":
                    v = _value(v, column)
                out.append(v)
            values[column] = out
        if any(v is not None for vs in values.values() for v in vs):
            okresy[code] = values
    # a column no okres has (a rebuilt forecast's cloud, gust, sunshine) is left out
    kept = [c for c in columns if any(v is not None for o in okresy.values() for v in o[c])]
    okresy = {code: {c: values[c] for c in kept} for code, values in okresy.items()}
    return {"lead": lead, "kind": kind, **extra, "columns": kept, "okresy": okresy}


def _stamp(issued: datetime) -> str:
    return issued.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")


#: what the plain-means archive gives per part (sky only, no temperature or rain)
SKY_COLUMNS = ("cloud", "sunshine", "symbol")


def sky_parts(means: pl.DataFrame, issued: datetime, day: date) -> pl.DataFrame:
    """One stored run of the plain-means archive (``sun_cloud_gust.archive_rows``: hourly
    cloud cover and sunshine per okres) as parts of ``day``: ``cloud`` (mean; the whole
    day 6-18 as the map), ``sunshine`` (h) and the sky symbol (``outlook.symbol``)."""
    run = means.filter(pl.col("issued") == issued)
    rows = outlook._local(run).filter(pl.col("day") == day)
    sums = outlook._local(run, hour_ending=True).filter(pl.col("day") == day)
    parts = rows.group_by("okres", "part").agg(
        pl.col("cloud_cover").mean().alias("cloud"), pl.len().alias("hours")
    )
    parts = parts.filter(pl.col("hours") >= outlook.MIN_PART_HOURS).join(
        sums.group_by("okres", "part").agg(
            (pl.col("sunshine_duration").sum() / 3600).alias("sunshine")
        ),
        on=["okres", "part"],
        how="left",
    )
    daytime = pl.col("part").is_in(["morning", "afternoon"])
    whole = (
        rows.group_by("okres")
        .agg(pl.col("cloud_cover").filter(daytime).mean().alias("cloud"), pl.len().alias("hours"))
        .filter(pl.col("hours") >= outlook.MIN_DAY_HOURS)
        .join(
            sums.group_by("okres").agg(
                (pl.col("sunshine_duration").sum() / 3600).alias("sunshine")
            ),
            on="okres",
            how="left",
        )
        .with_columns(pl.lit("day").alias("part"))
    )
    table = pl.concat(
        [parts.drop("hours"), whole.drop("hours").select(parts.drop("hours").columns)]
    )
    symbols = [outlook.symbol(c, None, None, None) for c in table["cloud"].to_list()]
    return table.with_columns(pl.Series("symbol", symbols, pl.String))


def forecast_doc(
    archive: pl.DataFrame,
    day: date,
    periods: tuple[str, ...],
    hindcasts: pl.DataFrame | None = None,
    means: pl.DataFrame | None = None,
) -> list[dict]:
    """The forecasts of ``day`` beside the measurements, one per lead (0: the day's
    morning run), each ``{"lead", "kind", "issued"?, "trained_to"?, "columns",
    "okresy"}``, by lead:

    - ``stored``: the map's own parts of day (``archive``, ``outlook.parts_archive_rows``);
    - ``stored_sky``: where only the plain means of a run were stored (``means``,
      ``sun_cloud_gust.archive_rows``): cloud cover, sunshine and the sky symbol;
    - ``rebuilt``: our forecast rebuilt out of sample (``hindcasts``,
      ``meteoverdict.hindcast``: no cloud, the symbol only when wet); where a stored
      run of the same lead has the sky, its cloud, sunshine and symbol fill in
      (``sky_issued``).

    A stored run is preferred to a rebuilt one of the same lead."""
    entries: dict[int, dict] = {}
    for lead, issued in pick_runs(archive, day):
        run = archive.filter(pl.col("day") == day, pl.col("issued") == issued)
        entries[lead] = _entry(
            lead, "stored", run, periods, outlook.PARTS_ARCHIVE_COLUMNS, issued=_stamp(issued)
        )
    skies: dict[int, tuple[datetime, pl.DataFrame]] = {}
    if means is not None and means.height:
        local = means.with_columns(
            pl.col("time").dt.convert_time_zone(TIME_ZONE).dt.date().alias("day")
        )
        for lead, issued in pick_runs(local.select("issued", "day").unique(), day):
            if lead not in entries:
                skies[lead] = (issued, sky_parts(means, issued, day))
    if hindcasts is not None and hindcasts.height:
        rebuilt = hindcasts.filter(pl.col("day") == day)
        for lead in sorted(rebuilt["lead"].unique().to_list()):
            if lead in entries:
                continue
            rows = rebuilt.filter(pl.col("lead") == lead)
            extra = {"trained_to": rows["trained_to"].max().isoformat()}
            if lead in skies:
                issued, sky = skies.pop(lead)
                rows = (
                    rows.drop("cloud", "sunshine")
                    .join(sky.rename({"symbol": "sky"}), on=["okres", "part"], how="left")
                    .with_columns(pl.coalesce("symbol", "sky").alias("symbol"))
                )
                extra["sky_issued"] = _stamp(issued)
            entries[lead] = _entry(
                lead, "rebuilt", rows, periods, outlook.PARTS_ARCHIVE_COLUMNS, **extra
            )
    for lead, (issued, sky) in skies.items():
        entries[lead] = _entry(lead, "stored_sky", sky, periods, SKY_COLUMNS, issued=_stamp(issued))
    return [entries[k] for k in sorted(entries) if entries[k]["okresy"]]


# --- the files ---------------------------------------------------------------------------
def day_doc(
    day: date,
    source: str,
    okres_rows: pl.DataFrame,
    extras: pl.DataFrame,
    points: pl.DataFrame,
    stations: pl.DataFrame,
    forecasts: list[dict],
    generated: datetime,
    distance: pl.DataFrame | None = None,
) -> dict:
    """The okres file of one day (``source`` "hourly": parts of day; "daily": the whole
    day from the daily climate values). An okres with borrowed stations (``okres_rows``
    ``b_<group>``) gets ``borrowed`` ({group: [station ids or null per period]}) and
    ``bst`` (those stations: id, name, their okres, km from its border, nearest first);
    ``distance`` (``neighbours.distances``) gives the km."""
    periods = PERIODS if source == "hourly" else ("day",)
    rows = okres_rows.filter(pl.col("day") == day)
    at = {(r["okres"], r["part"]): r for r in rows.iter_rows(named=True)}
    where = stations.select(pl.col("id").alias("station"), pl.col("okres_code").alias("okres"))
    names = dict(stations.select("id", "name").iter_rows()) if "name" in stations.columns else {}
    okres_names = (
        dict(stations.select("id", "okres").iter_rows()) if "okres" in stations.columns else {}
    )
    km = (
        {
            (o, s): d
            for o, s, d in distance.select("region", "station_id", "distance_km").iter_rows()
        }
        if distance is not None
        else {}
    )
    extra = extras.filter(pl.col("day") == day).join(where, on="station", how="inner")
    snow = {o: s for o, s in extra.group_by("okres").agg(pl.col("sno").max()).iter_rows()}
    ph = {
        o: sorted({c for codes in lists if codes for c in codes})
        for o, lists in extra.group_by("okres").agg(pl.col("ph")).iter_rows()
    }
    okresy = {}
    for code, lat, lon in points.select("code", "lat", "lon").iter_rows():
        entry: dict = {}
        for column in (*COLUMNS, *COUNTS):
            values = [at.get((code, p), {}).get(column) for p in periods]
            entry[column] = [(v or 0) if column in COUNTS else _value(v, column) for v in values]
        light = daylight(lat, lon, day)
        entry["light"] = light if source == "hourly" else [light[-1]]
        stations_of = sorted({s for p in periods for s in (at.get((code, p), {}).get("st") or [])})
        entry["st"] = stations_of
        lent = {
            g: [at.get((code, p), {}).get(f"b_{g}") for p in periods]
            for g in GROUPS
            if any(at.get((code, p), {}).get(f"b_{g}") for p in periods)
        }
        if lent:
            entry["borrowed"] = lent
            ids = {s for lists in lent.values() for ids in lists if ids for s in ids}
            entry["bst"] = sorted(
                (
                    {
                        "id": s,
                        "name": names.get(s, s),
                        "okres": okres_names.get(s),
                        "km": round(km.get((code, s), 0.0), 1),
                    }
                    for s in ids
                ),
                key=lambda b: (b["km"], b["id"]),
            )
        if ph.get(code):
            entry["ph"] = ph[code]
        if snow.get(code) is not None:
            entry["sno"] = _value(snow[code], "sno")
        okresy[code] = entry
    return {
        "day": day.isoformat(),
        "generated": generated.isoformat(timespec="minutes"),
        "time_zone": TIME_ZONE,
        "source": source,
        "parts": list(periods),
        "columns": list(COLUMNS),
        "counts": list(COUNTS),
        "borrow": {"max_km": BORROW_MAX_KM, "stations": BORROW_STATIONS},
        "okresy": okresy,
        "forecasts": forecasts,
        "notes": NOTES,
        "source_credit": SOURCE,
    }


def stations_doc(day: date, source: str, values: pl.DataFrame) -> dict:
    """The stations' own values of one day: ``{"day", "parts", "columns", "stations":
    {id: [value of each column for each period, period by period]}}``."""
    periods = PERIODS if source == "hourly" else ("day",)
    rows = values.filter(pl.col("day") == day)
    at = {(r["station"], r["part"]): r for r in rows.iter_rows(named=True)}
    out = {}
    for station in sorted(rows["station"].unique().to_list()):
        flat = [
            _value(at.get((station, p), {}).get(c), c) for p in periods for c in STATION_COLUMNS
        ]
        if any(v is not None for v in flat):
            out[station] = flat
    return {
        "day": day.isoformat(),
        "source": source,
        "parts": list(periods),
        "columns": list(STATION_COLUMNS),
        "stations": out,
        "source_credit": SOURCE,
    }


def _write(path: Path, doc: dict) -> Path:
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path


def build(
    root: Path,
    stations: pl.DataFrame,
    points: pl.DataFrame,
    out: Path,
    today: date,
    parts_archive: pl.DataFrame | None = None,
    part_days: int = PART_DAYS,
    hindcasts: pl.DataFrame | None = None,
    means: pl.DataFrame | None = None,
    daily_days: int = DAILY_DAYS,
    min_stations: int = MIN_STATIONS,
    generated: datetime | None = None,
    log: Callable[[str], None] = print,
) -> list[Path]:
    """Write the day files of the ``daily_days`` Prague days before ``today`` (parts of
    day for the last ``part_days``, where the archive has complete hourly data), and
    ``index.json``; files of days no longer offered are removed. ``parts_archive``,
    ``means`` and ``hindcasts``: the stored and rebuilt forecasts (``forecast_doc``)."""
    generated = generated or datetime.now(UTC)
    out.mkdir(parents=True, exist_ok=True)
    last = today - timedelta(days=1)
    first_parts = today - timedelta(days=part_days)
    first = today - timedelta(days=daily_days)
    fine = read_fine(root, first_parts, last)
    newest = fine["time"].max() if fine.height else None
    where = {
        s: (lat, lon)
        for s, lat, lon in stations.select("id", "lat", "lon").iter_rows()
        if lat is not None and lon is not None
    }
    by_okres = dict(stations.select("id", "okres_code").iter_rows())
    okres_at = {c: (lat, lon) for c, lat, lon in points.select("code", "lat", "lon").iter_rows()}

    cache: dict[tuple[float, float, date], list[float]] = {}

    def light(station: str, day: date) -> list[float]:
        # the okres point: the stations' own positions change the hours by minutes only
        lat, lon = okres_at.get(by_okres.get(station), where.get(station, (49.8, 15.5)))
        if (lat, lon, day) not in cache:
            cache[(lat, lon, day)] = daylight(lat, lon, day)
        return cache[(lat, lon, day)]

    located = stations.filter(
        pl.col("lat").is_not_null(), pl.col("lon").is_not_null(), pl.col("okres_code").is_not_null()
    )
    distance = neighbours.distances(located) if located.height else None
    hourly = station_periods(fine, light)
    daily, phenomena = read_daily(root, first, last)
    extras = day_extras(daily, phenomena)
    from_daily = station_days(daily)
    measured = hourly.filter(pl.col("part") == "day", pl.col("tmax").is_not_null())
    counts = dict(measured.group_by("day").len().iter_rows())
    archive = (
        parts_archive
        if parts_archive is not None
        else pl.DataFrame(schema=outlook.PARTS_ARCHIVE_SCHEMA)
    )
    written, entries, keep = [], [], {INDEX}
    day = last
    while day >= first:
        _, end = day_bounds(day)
        complete = newest is not None and newest >= end
        if day >= first_parts and complete and counts.get(day, 0) >= min_stations:
            source, values = "hourly", hourly.filter(pl.col("day") == day)
        elif from_daily.filter(pl.col("day") == day).height:
            source, values = "daily", from_daily.filter(pl.col("day") == day)
        else:
            day -= timedelta(days=1)
            continue
        periods = PERIODS if source == "hourly" else ("day",)
        forecasts = forecast_doc(archive, day, periods, hindcasts, means)
        okres_rows = okres_periods(values, stations, distance)
        doc = day_doc(
            day, source, okres_rows, extras, points, stations, forecasts, generated, distance
        )
        name = f"{day.isoformat()}.json"
        written.append(_write(out / name, doc))
        station_name = f"{day.isoformat()}-stations.json"
        written.append(_write(out / station_name, stations_doc(day, source, values)))
        keep |= {name, station_name}
        entries.append(
            {
                "day": day.isoformat(),
                "source": source,
                "leads": [f["lead"] for f in forecasts],
                "kinds": [f["kind"] for f in forecasts],
            }
        )
        day -= timedelta(days=1)
    for old in out.glob("*.json"):
        if old.name not in keep:
            old.unlink()
    index = {
        "generated": generated.isoformat(timespec="minutes"),
        "time_zone": TIME_ZONE,
        "part_days": part_days,
        "days": sorted(entries, key=lambda e: e["day"]),
        "notes": NOTES,
        "source_credit": SOURCE,
    }
    written.append(_write(out / INDEX, index))
    total = sum(p.stat().st_size for p in written)
    hourly_days = sum(e["source"] == "hourly" for e in entries)
    log(
        f"wrote {len(entries)} observed days ({hourly_days} with parts of day, "
        f"{sum(bool(e['leads']) for e in entries)} with a forecast), {total / 1e6:.2f} MB"
    )
    return written


def wanted_assets(today: date) -> list[tuple[str, str]]:
    """Archive files the observed map reads: the 10-minute and hourly months and captured
    days of the last ``PART_DAYS`` + 1 days, the daily and phenomena months of the last
    ``DAILY_DAYS`` + 1 days."""
    first = today - timedelta(days=PART_DAYS + 1)
    wanted = []
    for year, month in _months(first, today):
        wanted += [chmi_archive.month_asset(r, year, month) for r in chmi_archive.MONTH_RESOLUTIONS]
    wanted += [
        chmi_archive.day_asset(first + timedelta(days=i)) for i in range((today - first).days + 1)
    ]
    for year, month in _months(today - timedelta(days=DAILY_DAYS + 1), today):
        wanted += [chmi_archive.month_asset(r, year, month) for r in ("daily", "phenomena")]
    return wanted


def parts_archive_names(today: date) -> list[tuple[str, str]]:
    """The outlook parts archive files the forecasts of the offered days are in."""
    first = today - timedelta(days=DAILY_DAYS + max(LEADS) + 1)
    return [
        outlook.parts_archive_asset(datetime(y, m, 1, tzinfo=UTC)) for y, m in _months(first, today)
    ]


def means_archive_names(today: date) -> list[tuple[str, str]]:
    """The plain-means archive files (``sun_cloud_gust.archive_asset``) of those days."""
    first = today - timedelta(days=DAILY_DAYS + max(LEADS) + 1)
    return [sun_cloud_gust.archive_asset(f"{y}-{m:02d}") for y, m in _months(first, today)]


#: the rebuilt forecasts (``mvd hindcast``)
HINDCAST_ASSET = (hindcast.TAG, hindcast.ASSET)
