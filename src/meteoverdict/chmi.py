"""ČHMÚ open data: URLs and the shared JSON envelope.

Formats are documented in docs/data-sources.md. Every JSON file wraps a table as
``data.data.header`` (a comma-separated string) and ``data.data.values`` (rows in
that column order).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

BASE_URL = "https://opendata.chmi.cz/meteorology/climate"

#: Station list valid today; republished daily, kept for 10 days.
CURRENT_META1 = "now/metadata/meta1-{day:%Y%m%d}.json"
#: Station history with one row per validity period; republished yearly.
HISTORICAL_META1 = "historical/metadata/meta1.json"


class ChmiFormatError(ValueError):
    """A file does not have the documented ČHMÚ envelope."""


def current_meta1_url(day: date) -> str:
    return f"{BASE_URL}/{CURRENT_META1.format(day=day)}"


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
