"""Hourly station observations from ČHMÚ 10-minute data.

The verified variables come from the 10-minute files (see docs/data-sources.md):

* ``temperature_2m``: element ``T`` (2 m) at the full hour.
* ``wind_speed_10m``: element ``F`` (10 m) at the full hour.
* ``precipitation``: sum of the six ``SRA10M`` values ending at the hour (HH-1:10 to HH:00),
  only when all six are present. This equals ČHMÚ's own hourly ``SRA1H`` and matches
  Open-Meteo, whose hourly precipitation is the sum over the preceding hour.

Times are UTC. Per station and month the data comes from ``recent/`` (checked data of
the last 12 months), ``historical/`` (closed years) or, for days not published there
yet, ``now/`` (last ~3 days, unchecked).
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import polars as pl

from meteoverdict import partitions
from meteoverdict.chmi import BASE_URL, parse_collection

ELEMENTS = {"T": "temperature_2m", "F": "wind_speed_10m", "SRA10M": "precipitation"}
#: now/ keeps about three days; older day files are never asked for.
NOW_KEEPS_DAYS = 4

#: QUALITY codes (meta4) we keep: 0 good, 3 estimated, 5 unknown (unchecked now/ data).
#: Dropped: 1 suspect, 2 poor, 4 missing.
KEEP_QUALITY = (0, 3, 5)

SCHEMA = {
    "station_id": pl.String,
    "time": pl.Datetime("us", "UTC"),
    "variable": pl.String,
    "value": pl.Float32,
    "quality": pl.UInt8,
    "source": pl.String,
}


def month_urls(wsi: str, year: int, month: int) -> list[tuple[str, str]]:
    """Candidate monthly files, best first: ``(source, url)``."""
    stamp = f"{year}{month:02d}"
    return [
        ("recent", f"{BASE_URL}/recent/data/10min/{month:02d}/10m-{wsi}-{stamp}.json"),
        ("historical", f"{BASE_URL}/historical/data/10min/{year}/10m-{wsi}-{stamp}.json"),
    ]


def day_url(wsi: str, day: date) -> str:
    return f"{BASE_URL}/now/data/10m-{wsi}-{day:%Y%m%d}.json"


def _get(client: httpx.Client, url: str) -> dict | None:
    response = client.get(url)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _months(start: date, end: date) -> list[tuple[int, int]]:
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def raw_station(
    client: httpx.Client, wsi: str, start: date, end: date, today: date | None = None
) -> list[tuple[str, pl.DataFrame]]:
    """10-minute rows for ``wsi`` covering ``start`` to ``end``: ``[(source, rows)]``."""
    oldest_in_now = (today or datetime.now(UTC).date()) - timedelta(days=NOW_KEEPS_DAYS)
    parts = []
    for year, month in _months(start, end):
        first = max(start, date(year, month, 1))
        last = min(end, date(year, month, calendar.monthrange(year, month)[1]))
        for source, url in month_urls(wsi, year, month):
            if (doc := _get(client, url)) is not None:
                rows = parse_collection(doc)
                parts.append((source, rows))
                if rows.height:  # a partly published month: the rest may be in now/
                    first = max(first, date.fromisoformat(rows["DT"].max()[:10]) + timedelta(1))
                else:
                    first = last + timedelta(days=1)
                break
        day = max(first, oldest_in_now)  # days not in a monthly file: try now/
        while day <= last:
            if (doc := _get(client, day_url(wsi, day))) is not None:
                parts.append(("now", parse_collection(doc)))
            day += timedelta(days=1)
    return parts


def normalize(raw: pl.DataFrame, source: str) -> pl.DataFrame:
    """Long 10-minute rows → typed rows of the elements we use, bad quality dropped."""
    if raw.height == 0:
        return pl.DataFrame(schema={**SCHEMA, "time": pl.Datetime("us", "UTC")})
    return (
        raw.filter(pl.col("ELEMENT").is_in(list(ELEMENTS)))
        .select(
            pl.col("STATION").alias("station_id"),
            pl.col("DT").str.to_datetime("%Y-%m-%dT%H:%M:%SZ", time_zone="UTC").alias("time"),
            pl.col("ELEMENT").replace_strict(ELEMENTS).alias("variable"),
            # missing values come as "" (QUALITY 4); real values as numbers
            pl.col("VAL").cast(pl.String).cast(pl.Float32, strict=False).alias("value"),
            pl.col("QUALITY").cast(pl.UInt8).alias("quality"),
            pl.lit(source).alias("source"),
        )
        .filter(pl.col("quality").is_in(KEEP_QUALITY), pl.col("value").is_not_null())
    )


def to_hourly(ten_minute: pl.DataFrame) -> pl.DataFrame:
    """Hourly values: instant T and F at HH:00, precipitation summed over the hour."""
    full_hour = pl.col("time").dt.minute() == 0
    instant = ten_minute.filter(
        pl.col("variable").is_in(["temperature_2m", "wind_speed_10m"]), full_hour
    )
    rain = ten_minute.filter(pl.col("variable") == "precipitation")
    hourly_rain = (
        # the slot ending at HH:10 … HH+1:00 belongs to the hour ending HH+1:00
        rain.with_columns((pl.col("time") - pl.duration(minutes=1)).dt.truncate("1h").alias("h"))
        .group_by("station_id", "h")
        .agg(
            pl.col("value").sum(),
            pl.col("quality").max(),
            pl.col("source").first(),
            pl.len().alias("n"),
        )
        .filter(pl.col("n") == 6)
        .select(
            "station_id",
            (pl.col("h") + pl.duration(hours=1)).alias("time"),
            pl.lit("precipitation").alias("variable"),
            "value",
            "quality",
            "source",
        )
    )
    return pl.concat([instant.select(list(SCHEMA)), hourly_rain.cast(SCHEMA)])


def fetch_observations(
    client: httpx.Client,
    station_ids: Iterable[str],
    start: date,
    end: date,
    workers: int = 8,
    today: date | None = None,
) -> pl.DataFrame:
    """Hourly observations for the stations, ``start`` 00:00 to ``end`` 23:00 UTC.

    The day before ``start`` is read too, so the first hour's precipitation is complete.
    """

    def one(wsi: str) -> pl.DataFrame:
        parts = raw_station(client, wsi, start - timedelta(days=1), end, today)
        rows = [normalize(raw, source) for source, raw in parts]
        return to_hourly(pl.concat(rows)) if rows else pl.DataFrame(schema=SCHEMA)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        frames = [pl.DataFrame(schema=SCHEMA), *pool.map(one, list(station_ids))]
    first = datetime.combine(start, datetime.min.time(), UTC)
    last = datetime.combine(end, datetime.min.time(), UTC) + timedelta(hours=23)
    return (
        pl.concat(frames)
        .filter(pl.col("time").is_between(first, last))
        .unique(["station_id", "time", "variable"], keep="first", maintain_order=True)
        .sort("station_id", "variable", "time")
    )


def automatic_station_ids(meta2: pl.DataFrame) -> set[str]:
    """Stations that report at least one of our elements every 10 minutes (from ``meta2``).

    The other stations (manual rain gauges) only have daily data.
    """
    return set(
        meta2.filter(
            pl.col("OBS_TYPE") == "10M", pl.col("EG_EL_ABBREVIATION").is_in(list(ELEMENTS))
        )["WSI"].to_list()
    )


def write_monthly(observations: pl.DataFrame, out_dir: Path) -> list[Path]:
    """Merge into ``out_dir/YYYY-MM.parquet``: new rows replace old ones with the same
    station, time and variable (e.g. checked ``recent/`` data replacing ``now/`` data)."""
    return partitions.write_monthly(observations, out_dir, ["station_id", "time", "variable"])
