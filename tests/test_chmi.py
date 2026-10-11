import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from meteoverdict.chmi import (
    ChmiFormatError,
    current_meta1_url,
    historical_meta1_url,
    parse_collection,
)

FIXTURES = Path(__file__).parent / "fixtures" / "chmi"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_urls_follow_documented_patterns():
    assert current_meta1_url(date(2026, 10, 11)) == (
        "https://opendata.chmi.cz/meteorology/climate/now/metadata/meta1-20261011.json"
    )
    assert historical_meta1_url() == (
        "https://opendata.chmi.cz/meteorology/climate/historical/metadata/meta1.json"
    )


def test_parse_collection_uses_header_as_columns():
    df = parse_collection(load("meta1-historical.json"))
    assert df.columns == [
        "WSI", "GH_ID", "BEGIN_DATE", "END_DATE", "FULL_NAME", "GEOGR1", "GEOGR2", "ELEVATION"
    ]  # fmt: skip
    assert df.schema["GEOGR1"] == pl.Float64
    assert df.height == 12


def test_parse_collection_handles_hourly_data():
    df = parse_collection(load("1h-0-20000-0-11520-20261011.json"))
    assert df["VAL"].to_list() == [9074.0, 8987.0, 2760.0]


def test_empty_collection_keeps_columns():
    doc = {"data": {"type": "DataCollection", "data": {"header": "A,B", "values": []}}}
    df = parse_collection(doc)
    assert df.columns == ["A", "B"]
    assert df.height == 0


@pytest.mark.parametrize(
    "doc",
    [
        {},
        {"data": {"data": {"values": []}}},
        {"data": None},
    ],
)
def test_missing_envelope_parts_raise(doc):
    with pytest.raises(ChmiFormatError):
        parse_collection(doc)


def test_row_width_mismatch_raises():
    doc = {"data": {"data": {"header": "A,B", "values": [["x"]]}}}
    with pytest.raises(ChmiFormatError, match="row 0"):
        parse_collection(doc)
