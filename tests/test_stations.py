import json
from datetime import date
from pathlib import Path

import httpx
import polars as pl
import pytest

from meteoverdict.chmi import ChmiFormatError, parse_collection
from meteoverdict.stations import (
    SCHEMA,
    build_stations,
    fetch_station_tables,
    write_stations,
)

FIXTURES = Path(__file__).parent / "fixtures" / "chmi"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def current() -> pl.DataFrame:
    return parse_collection(fixture("meta1-20261011.json"))


@pytest.fixture
def historical() -> pl.DataFrame:
    return parse_collection(fixture("meta1-historical.json"))


def period(wsi: str, begin: str, end: str, lon: float = 15.0, lat: float = 50.0) -> dict:
    return {
        "WSI": wsi,
        "GH_ID": "X",
        "BEGIN_DATE": begin,
        "END_DATE": end,
        "FULL_NAME": wsi,
        "GEOGR1": lon,
        "GEOGR2": lat,
        "ELEVATION": 300.0,
    }


def test_current_stations_are_active_and_foreign_ones_dropped(current):
    stations = build_stations(current)
    assert stations.schema == pl.Schema(SCHEMA)
    assert stations["name"].to_list() == ["Cheb", "Karlovy Vary, Olšová Vrata", "Praha, Libuš"]
    assert stations["active"].all()


def test_latitude_and_longitude_are_not_swapped(current):
    cheb = build_stations(current).row(0, named=True)
    assert (cheb["lat"], cheb["lon"], cheb["elevation"]) == (50.068333, 12.391389, 483.0)


def test_current_position_wins_over_historical(current, historical):
    stations = build_stations(current, historical)
    cheb = stations.filter(pl.col("name") == "Cheb").row(0, named=True)
    assert (cheb["lat"], cheb["lon"], cheb["active"]) == (50.068333, 12.391389, True)
    assert stations["id"].is_unique().all()


def test_closed_stations_are_kept_only_if_closed_recently(current, historical):
    assert "Svatý Petr, Špindlerův Mlýn" not in build_stations(current, historical)["name"]
    old = build_stations(current, historical, closed_since=date(1995, 1, 31))
    petr = old.filter(pl.col("id") == "0-203-0-10101004001").row(0, named=True)
    assert petr["active"] is False
    # Marambio's coordinates are outside Czechia, so it never shows up
    assert "Marambio, Base" not in old["name"]


def test_station_missing_from_current_list_is_inactive_at_its_last_position(current):
    historical = pl.DataFrame(
        [
            period("A", "2000-01-01T00:00:00Z", "2009-12-31T23:59:00Z", lon=14.0),
            period("A", "2010-01-01T00:00:00Z", "3999-12-31T23:59:00Z", lon=14.5),
        ]
    )
    row = build_stations(current, historical).filter(pl.col("id") == "A").row(0, named=True)
    assert (row["lon"], row["active"]) == (14.5, False)


def test_duplicate_station_keeps_the_newest_row(current):
    # real rows from now/metadata/meta1-20261011.json
    columns = ["WSI", "GH_ID", "FULL_NAME", "GEOGR1", "GEOGR2", "ELEVATION", "BEGIN_DATE"]
    rows = [
        ["0-203-0-11502020001", "U1PEKL01", "Petrovice, Krásný Les", 13.937667, 50.767361,
         631.0, "1963-11-01T00:00:00Z"],
        ["0-203-0-11502020001", "U7PEKL01", "Petrovice, Krásný Les", 13.937667, 50.767361,
         631.0, "2026-08-20T11:00:00Z"],
        ["0-203-0-41003091001", "O2OLKL01", "Olomouc, Klášterní Hradisko", 17.264465,
         49.608795, 215.0, "1876-01-01T00:00:00Z"],
        ["0-203-0-41003091001", "O2OLKL01", "Olomouc, Klášterní Hradisko", 17.26413,
         49.6076625, 215.0, "1876-01-01T00:00:00Z"],
    ]  # fmt: skip
    duplicated = pl.DataFrame(rows, schema=columns, orient="row")
    stations = build_stations(pl.concat([current, duplicated]))
    assert stations["id"].is_unique().all()
    petrovice = stations.filter(pl.col("id") == "0-203-0-11502020001").row(0, named=True)
    assert petrovice["gh_id"] == "U7PEKL01"  # the newer configuration
    olomouc = stations.filter(pl.col("id") == "0-203-0-41003091001").row(0, named=True)
    assert olomouc["lon"] == 17.264465  # same BEGIN_DATE: first listed row wins


def test_missing_columns_are_an_error(current, historical):
    with pytest.raises(ChmiFormatError, match="BEGIN_DATE"):
        build_stations(current.drop("BEGIN_DATE"))
    with pytest.raises(ChmiFormatError, match="GEOGR1"):
        build_stations(current.drop("GEOGR1"))
    with pytest.raises(ChmiFormatError, match="END_DATE"):
        build_stations(current, historical.drop("END_DATE"))


def test_write_stations_round_trips(tmp_path, current):
    stations = build_stations(current)
    path = tmp_path / "nested" / "stations.parquet"
    write_stations(stations, path)
    assert pl.read_parquet(path).equals(stations)


def mock_client(responses: dict[str, dict]) -> tuple[httpx.Client, list[str]]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        for suffix, body in responses.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, json=body)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_fetch_falls_back_to_yesterdays_current_list():
    client, seen = mock_client(
        {
            "meta1-20261011.json": fixture("meta1-20261011.json"),
            "historical/metadata/meta1.json": fixture("meta1-historical.json"),
        }
    )
    current, historical = fetch_station_tables(client, date(2026, 10, 12))
    assert [p.rsplit("/", 1)[1] for p in seen] == [
        "meta1-20261012.json",
        "meta1-20261011.json",
        "meta1.json",
    ]
    assert current.height == 4
    assert "END_DATE" in historical.columns


def test_fetch_does_not_hide_server_errors():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(httpx.HTTPStatusError):
        fetch_station_tables(client, date(2026, 10, 12))
