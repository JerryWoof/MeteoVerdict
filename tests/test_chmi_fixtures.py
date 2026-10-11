"""Contract tests for the recorded ČHMÚ samples.

They pin the format documented in docs/data-sources.md, so the loaders built in
roadmap 1.2 and 1.5 start from verified facts, and a re-recorded fixture that
changes shape fails loudly.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "chmi"

HEADERS = {
    "meta1-20261011.json": "WSI,GH_ID,FULL_NAME,GEOGR1,GEOGR2,ELEVATION,BEGIN_DATE",
    "meta2-20261011.json": "OBS_TYPE,WSI,EG_EL_ABBREVIATION,NAME,UN_DESCRIPTION,HEIGHT,SCHEDULE",
    "1h-0-20000-0-11520-20261011.json": "STATION,ELEMENT,DT,VAL,FLAG,QUALITY",
}


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def rows(name: str) -> list[dict]:
    collection = load(name)["data"]["data"]
    columns = collection["header"].split(",")
    return [dict(zip(columns, row, strict=True)) for row in collection["values"]]


@pytest.mark.parametrize(("name", "header"), HEADERS.items())
def test_envelope_and_header(name, header):
    doc = load(name)
    assert doc["datovyZdrojID"] == "meteorologie"
    assert doc["data"]["type"] == "DataCollection"
    assert doc["data"]["data"]["header"] == header
    assert rows(name)  # every row matches the header width


def test_meta1_geogr1_is_longitude_and_geogr2_latitude():
    cheb = next(r for r in rows("meta1-20261011.json") if r["FULL_NAME"] == "Cheb")
    assert 12.0 < cheb["GEOGR1"] < 19.0  # Czech longitudes
    assert 48.5 < cheb["GEOGR2"] < 51.1  # Czech latitudes
    assert cheb["ELEVATION"] == 483.0


def test_data_rows_are_long_format_with_utc_timestamps():
    data = rows("1h-0-20000-0-11520-20261011.json")
    for row in data:
        assert row["DT"].endswith("Z")
        assert datetime.fromisoformat(row["DT"]).utcoffset().total_seconds() == 0
        assert isinstance(row["VAL"], float)
        assert isinstance(row["FLAG"], str)
    assert {r["STATION"] for r in data} == {"0-20000-0-11520"}
