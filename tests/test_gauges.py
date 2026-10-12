import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import polars as pl
import pytest

from meteoverdict import gauges
from meteoverdict.observations import SCHEMA

FIXTURES = Path(__file__).parent / "fixtures" / "chmi"
W = "0-203-0-10101067001"  # Bílá Třemešná, a manual rain gauge
AUGUST = json.loads((FIXTURES / f"dly-{W}-202608.json").read_text(encoding="utf-8"))
SEPTEMBER = json.loads((FIXTURES / f"dly-{W}-202609.json").read_text(encoding="utf-8"))
CSV = (FIXTURES / f"dly-{W}-SRA.csv").read_bytes()


def server(recent: dict[str, dict], csv: bytes | None = CSV):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        for stamp, body in recent.items():
            if path.endswith(f"-{stamp}.json"):
                return httpx.Response(200, json=body)
        if path.endswith("-SRA.csv") and csv is not None:
            return httpx.Response(200, content=csv)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_urls():
    assert gauges.recent_url(W, 2026, 8).endswith(f"/recent/data/daily/08/dly-{W}-202608.json")
    assert gauges.historical_csv_url(W).endswith(
        f"/historical_csv/data/daily/precipitation/dly-{W}-SRA.csv"
    )


def test_values_are_stamped_with_the_end_of_their_window():
    client, _ = server({"202608": AUGUST})
    rows = gauges.fetch_gauge_precipitation(client, [W], date(2026, 8, 1), date(2026, 8, 4))
    assert rows.schema == pl.Schema(SCHEMA)
    assert set(rows["variable"]) == {"precipitation_24h"}
    # the value ČHMÚ stamps 2026-08-01T06:00Z fell until 2 August 06:00 UTC
    assert rows["time"].to_list() == [datetime(2026, 8, d, 6, tzinfo=UTC) for d in (2, 3, 4, 5)]
    first = next(r for r in AUGUST["data"]["data"]["values"] if r[1] == "SRA")
    assert rows["value"][0] == first[4]
    assert gauges.window(date(2026, 8, 1)) == (
        datetime(2026, 8, 1, 6, tzinfo=UTC),
        datetime(2026, 8, 2, 6, tzinfo=UTC),
    )


def test_missing_values_of_a_late_month_are_dropped():
    # in October 2026 most September values of manual gauges were still missing ("", Q4)
    client, _ = server({"202609": SEPTEMBER})
    rows = gauges.fetch_gauge_precipitation(client, [W], date(2026, 9, 1), date(2026, 9, 5))
    assert rows.height == sum(isinstance(r[4], float) for r in SEPTEMBER["data"]["data"]["values"])


def test_closed_years_come_from_the_historical_csv_once():
    client, seen = server({})
    rows = gauges.fetch_gauge_precipitation(client, [W], date(2025, 3, 1), date(2025, 12, 31))
    assert set(rows["source"]) == {"historical"}
    assert rows.height == 7  # the fixture's rows: 1-5 March and 30-31 December
    last = rows.filter(pl.col("time") == datetime(2026, 1, 1, 6, tzinfo=UTC))["value"][0]
    assert last == pytest.approx(4.1)
    assert sum(p.endswith("-SRA.csv") for p in seen) == 1


def test_gauge_stations_are_the_ones_without_10_minute_data():
    stations = pl.DataFrame({"id": ["auto", "gauge", "closed"], "active": [True, True, False]})
    meta2 = pl.DataFrame({"OBS_TYPE": ["10M"], "WSI": ["auto"], "EG_EL_ABBREVIATION": ["SRA10M"]})
    assert gauges.gauge_stations(stations, meta2)["id"].to_list() == ["gauge", "closed"]
