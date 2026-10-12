"""ČHMÚ open data: URLs and the shared JSON envelope.

Formats are documented in docs/data-sources.md. Every JSON file wraps a table as
``data.data.header`` (a comma-separated string) and ``data.data.values`` (rows in
that column order).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx
import polars as pl

BASE_URL = "https://opendata.chmi.cz/meteorology/climate"

#: Metadata valid today (meta1 stations, meta2 elements per station, …);
#: republished daily, kept for 10 days.
CURRENT_META = "now/metadata/meta{n}-{day:%Y%m%d}.json"
#: Station history with one row per validity period; republished yearly.
HISTORICAL_META1 = "historical/metadata/meta1.json"


class ChmiFormatError(ValueError):
    """A file does not have the documented ČHMÚ envelope."""


def current_meta_url(n: int, day: date) -> str:
    return f"{BASE_URL}/{CURRENT_META.format(n=n, day=day)}"


def current_meta1_url(day: date) -> str:
    return current_meta_url(1, day)


def fetch_current_meta(client: httpx.Client, n: int, today: date) -> pl.DataFrame:
    """Today's ``metaN`` table, or yesterday's when today's is not published yet
    (it appears shortly after midnight UTC)."""
    response = client.get(current_meta_url(n, today))
    if response.status_code == 404:
        response = client.get(current_meta_url(n, today - timedelta(days=1)))
    response.raise_for_status()
    return parse_collection(response.json())


def historical_meta1_url() -> str:
    return f"{BASE_URL}/{HISTORICAL_META1}"


def parse_collection(doc: dict[str, Any]) -> pl.DataFrame:
    """Turn a ČHMÚ JSON document into a DataFrame with the header's column names.

    Column types are inferred from the values; callers cast what they rely on.
    """
    try:
        collection = doc["data"]["data"]
        columns = collection["header"].split(",")
        values = collection["values"]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ChmiFormatError(f"not a ČHMÚ DataCollection: missing {exc}") from exc
    for i, row in enumerate(values):
        if len(row) != len(columns):
            raise ChmiFormatError(f"row {i} has {len(row)} values, header has {len(columns)}")
    return pl.DataFrame(values, schema=columns, orient="row", infer_schema_length=None)
