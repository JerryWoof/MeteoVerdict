"""Daily precipitation of ČHMÚ's manual rain gauges (roadmap 1.5b).

About 280 active stations only report daily precipitation (``SRA``), read at 07:00
local time. ČHMÚ stamps the value with the start of its 24-hour window: the value at
``2026-09-04T06:00Z`` fell from 4 Sept 06:00 to 5 Sept 06:00 UTC (checked against the
hourly totals of Praha-Libuš: 30 of 30 days). We store it as ``precipitation_24h``
stamped with the window's **end**, like every other value (the period ends at ``time``).

Sources: ``recent/data/daily/MM/dly-{WSI}-{YYYYMM}.json`` for the last 12 months and
``historical_csv/data/daily/precipitation/dly-{WSI}-SRA.csv`` (one file per station,
1905 to the last closed year, about 2.5 MB) for older months. Manual gauges report
with a delay: in October 2026 the July and August values were complete, September
mostly still missing.
"""

from __future__ import annotations

import calendar
import io
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import httpx
import polars as pl

from meteoverdict.chmi import BASE_URL, parse_collection
from meteoverdict.observations import KEEP_QUALITY, SCHEMA, automatic_station_ids

VARIABLE = "precipitation_24h"
#: Czech record: 345 mm in 24 h (Nová Ves, 1897).
PLAUSIBLE_MM = (0.0, 400.0)


def recent_url(wsi: str, year: int, month: int) -> str:
    return f"{BASE_URL}/recent/data/daily/{month:02d}/dly-{wsi}-{year}{month:02d}.json"


def historical_csv_url(wsi: str) -> str:
    return f"{BASE_URL}/historical_csv/data/daily/precipitation/dly-{wsi}-SRA.csv"


def gauge_stations(stations: pl.DataFrame, meta2: pl.DataFrame) -> pl.DataFrame:
    """Active stations without 10-minute data (manual gauges), plus inactive ones."""
    automatic = automatic_station_ids(meta2)
    return stations.filter(~pl.col("id").is_in(list(automatic)) | ~pl.col("active"))


def _normalize(rows: pl.DataFrame, source: str) -> pl.DataFrame:
    """SRA rows (STATION, DT = window start, VAL, QUALITY) → precipitation_24h rows."""
    start = pl.col("DT").str.replace(r"Z$", "").str.to_datetime(time_zone="UTC")
    low, high = PLAUSIBLE_MM
    return (
        rows.select(
            pl.col("STATION").alias("station_id"),
            (start + pl.duration(days=1)).alias("time"),
            pl.lit(VARIABLE).alias("variable"),
            pl.col("VAL").cast(pl.String).cast(pl.Float32, strict=False).alias("value"),
            pl.col("QUALITY").cast(pl.Float64).cast(pl.UInt8).alias("quality"),
            pl.lit(source).alias("source"),
        )
        .filter(
            pl.col("quality").is_in(KEEP_QUALITY),
            pl.col("value").is_not_null(),
            pl.col("value").is_between(low, high),
        )
        .cast(SCHEMA)
    )


def _recent(client: httpx.Client, wsi: str, year: int, month: int) -> pl.DataFrame | None:
    response = client.get(recent_url(wsi, year, month))
    if response.status_code == 404:
        return None
    response.raise_for_status()
    rows = parse_collection(response.json())
    return _normalize(rows.filter(pl.col("ELEMENT") == "SRA"), "recent")


def _historical(client: httpx.Client, wsi: str) -> pl.DataFrame | None:
    response = client.get(historical_csv_url(wsi))
    if response.status_code == 404:
        return None
    response.raise_for_status()
    # header STATION,ELEMENT,TIMEFUNC,DT,VALUE,FLAG,QUALITY plus a trailing comma
    rows = pl.read_csv(io.BytesIO(response.content), infer_schema=False).rename({"VALUE": "VAL"})
    return _normalize(rows, "historical")


def fetch_gauge_precipitation(
    client: httpx.Client,
    station_ids: Iterable[str],
    start: date,
    end: date,
    workers: int = 8,
    historical: bool = True,
) -> pl.DataFrame:
    """``precipitation_24h`` for windows starting on ``start`` … ``end`` (06:00 UTC each).

    Months missing in ``recent/`` come from the ``historical_csv/`` file (2.5 MB per
    station, so the scheduled runs pass ``historical=False`` and read only ``recent/``).
    """

    def one(wsi: str) -> pl.DataFrame:
        parts, older = [], None
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            got = _recent(client, wsi, y, m)
            if (got is None or got.height == 0) and historical:
                if older is None:  # one CSV covers every closed year
                    older = _historical(client, wsi)
                got = older
            if got is not None:
                first = date(y, m, 1)
                last = date(y, m, calendar.monthrange(y, m)[1])
                parts.append(
                    got.filter(
                        (pl.col("time") - timedelta(days=1)).dt.date().is_between(first, last)
                    )
                )
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return pl.concat(parts) if parts else pl.DataFrame(schema=SCHEMA)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        frames = [pl.DataFrame(schema=SCHEMA), *pool.map(one, list(station_ids))]
    window = (pl.col("time") - timedelta(days=1)).dt.date().is_between(start, end)
    return (
        pl.concat(frames)
        .filter(window)
        .unique(["station_id", "time", "variable"], keep="first", maintain_order=True)
        .sort("station_id", "time")
    )


def window(day: date) -> tuple[datetime, datetime]:
    """The 24 hours a gauge value of ``day`` covers (06:00 to 06:00 UTC)."""
    start = datetime(day.year, day.month, day.day, 6, tzinfo=UTC)
    return start, start + timedelta(days=1)
