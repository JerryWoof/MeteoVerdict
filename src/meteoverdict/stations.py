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

from datetime import date
from pathlib import Path

import httpx
import polars as pl

from meteoverdict.chmi import (
    ChmiFormatError,
    fetch_current_meta,
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
    if "BEGIN_DATE" not in current.columns:
        raise ChmiFormatError("current meta1 needs BEGIN_DATE")
    # A WSI can appear twice, e.g. when a station gets new equipment (new GH_ID, new
    # BEGIN_DATE) or with two slightly different positions. Keep the newest row.
    now = _select(
        current.with_row_index("_order")
        .sort("BEGIN_DATE", "_order", descending=[True, False])
        .unique("WSI", keep="first", maintain_order=True),
        active=True,
    )

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
    current = fetch_current_meta(client, 1, today)
    historical = parse_collection(_get_json(client, historical_meta1_url()))
    return current, historical


def write_stations(stations: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stations.write_parquet(path)


# --- kind of station ------------------------------------------------------------------
#: Kinds of ČHMÚ station (all are ČHMÚ's own network), from the WIGOS id and the elements
#: ``meta2`` lists (docs/data-sources.md#kinds-of-station):
#:
#: * ``main``: main (synoptic) station with a WMO number, WIGOS ``0-20000-0-<WMO>``;
#: * ``climate``: automatic climate station, air temperature every 10 minutes;
#: * ``climate_manual``: climate station with daily (manual) values only;
#: * ``snow``: automatic snow station in the mountains: snow depth and temperature every
#:   10 minutes, no precipitation or wind;
#: * ``precipitation_auto``: automatic precipitation station (10-minute precipitation,
#:   no air temperature);
#: * ``precipitation``: precipitation station read once a day (at 07 local time) by an
#:   observer, no 10-minute data;
#: * ``other``: anything else (e.g. no elements listed).
NETWORKS = (
    "main",
    "climate",
    "climate_manual",
    "snow",
    "precipitation_auto",
    "precipitation",
    "other",
)
MAIN_PREFIX = "0-20000-"


def network(wsi: str, elements: dict[str, dict]) -> str:
    """Kind of station (one of ``NETWORKS``) from its WIGOS id and its elements, as
    ``station_pages.element_table`` gives them (``types`` 10M/1H/DLY/PHENO and
    ``until``, None while still measured). Elements still measured count; a closed
    station (none still measured) is judged by everything it ever measured."""
    if wsi.startswith(MAIN_PREFIX):
        return "main"
    open_ = {c: e for c, e in elements.items() if e.get("until") is None}
    current = open_ or elements
    automatic = {c for c, e in current.items() if "10M" in (e.get("types") or [])}
    daily = {c for c, e in current.items() if "DLY" in (e.get("types") or [])}
    if "T" in automatic:
        if "SCEa" in automatic and not automatic & {"SRA10M", "F"}:
            return "snow"
        return "climate"
    if "SRA10M" in automatic:
        return "precipitation_auto"
    if "T" in daily:
        return "climate_manual"
    if "SRA" in daily:
        return "precipitation"
    return "other"
