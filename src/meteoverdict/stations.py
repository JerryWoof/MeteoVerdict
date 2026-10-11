"""Station metadata: ČHMÚ ``meta1`` files → ``stations.parquet``.

Two sources (see docs/data-sources.md):

* the current ``now/metadata/meta1-YYYYMMDD.json`` lists stations operating today;
* the historical ``historical/metadata/meta1.json`` has one row per validity period
  (a station's position can change between periods) and also covers closed stations.

A station is **active** when it is in the current list. Stations that are only in the
historical file are kept as inactive if their last period ended on or after
``closed_since``, so backfills can still score them.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import httpx
import polars as pl

from meteoverdict.chmi import (
    ChmiFormatError,
    current_meta1_url,
    historical_meta1_url,
    parse_collection,
)

SCHEMA = {
    "id": pl.String,
    "gh_id": pl.String,
    "name": pl.String,
    "lat": pl.Float64,
    "lon": pl.Float64,
    "elevation": pl.Float64,
    "active": pl.Boolean,
}

#: Coarse bounding box of Czechia (lon, lat). It drops far-away stations such as
#: Reykjavik; exact borders are applied by regions.add_regions.
CZ_BBOX = (12.0, 48.5, 18.9, 51.1)

#: Start of the backfill window (ROADMAP: history since January 2024).
DEFAULT_CLOSED_SINCE = date(2024, 1, 1)

_COLUMNS = {
    "WSI": "id",
    "GH_ID": "gh_id",
    "FULL_NAME": "name",
    "GEOGR2": "lat",  # GEOGR1 is longitude, GEOGR2 latitude (verified)
    "GEOGR1": "lon",
    "ELEVATION": "elevation",
}


def _select(df: pl.DataFrame, active: bool) -> pl.DataFrame:
    missing = set(_COLUMNS) - set(df.columns)
    if missing:
        raise ChmiFormatError(f"meta1 is missing columns: {sorted(missing)}")
    return df.select(
        *(pl.col(src).alias(dst) for src, dst in _COLUMNS.items()),
        pl.lit(active).alias("active"),
    ).cast(SCHEMA)


def build_stations(
    current: pl.DataFrame,
    historical: pl.DataFrame | None = None,
    closed_since: date = DEFAULT_CLOSED_SINCE,
) -> pl.DataFrame:
    """Combine current and historical ``meta1`` tables into one row per station."""
    now = _select(current, active=True)
    duplicated = now.filter(pl.col("id").is_duplicated())["id"].unique().sort().to_list()
    if duplicated:
        raise ChmiFormatError(f"current meta1 lists stations more than once: {duplicated}")

    parts = [now]
    if historical is not None:
        if "BEGIN_DATE" not in historical.columns or "END_DATE" not in historical.columns:
            raise ChmiFormatError("historical meta1 needs BEGIN_DATE and END_DATE")
        last = (
            historical.with_columns(pl.col("END_DATE").str.slice(0, 10).str.to_date())
            .sort("WSI", "BEGIN_DATE")
            .group_by("WSI", maintain_order=True)
            .last()
            .filter(pl.col("END_DATE") >= closed_since)
            .filter(~pl.col("WSI").is_in(now["id"].implode()))
        )
        parts.append(_select(last, active=False))

    lon_min, lat_min, lon_max, lat_max = CZ_BBOX
    return (
        pl.concat(parts)
        .filter(
            pl.col("lon").is_between(lon_min, lon_max),
            pl.col("lat").is_between(lat_min, lat_max),
        )
        .sort("id")
    )


def _get_json(client: httpx.Client, url: str) -> dict:
    response = client.get(url)
    response.raise_for_status()
    return response.json()


def fetch_station_tables(client: httpx.Client, today: date) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Download the current and historical ``meta1`` tables.

    Today's current list is created shortly after midnight UTC, so fall back to
    yesterday's when it is not there yet.
    """
    try:
        current = _get_json(client, current_meta1_url(today))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        current = _get_json(client, current_meta1_url(today - timedelta(days=1)))
    historical = _get_json(client, historical_meta1_url())
    return parse_collection(current), parse_collection(historical)


def write_stations(stations: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stations.write_parquet(path)
