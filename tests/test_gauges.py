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


def test_scheduled_runs_skip_the_historical_csv():
    client, seen = server({"202608": AUGUST})
    rows = gauges.fetch_gauge_precipitation(
        client, [W], date(2026, 7, 1), date(2026, 8, 3), historical=False
    )
    assert rows["time"].min() == datetime(2026, 8, 2, 6, tzinfo=UTC)  # July is not in recent/
    assert not any(p.endswith("-SRA.csv") for p in seen)


def test_a_total_after_missing_days_is_dropped():
    # a manual gauge: days 1, 2, (3, 4 missing), 5, 6 → the value of day 5 is probably the
    # total of days 3 to 5 and is left out
    def row(day, value, source="recent", station="g"):
        return {
            "station_id": station,
            "time": datetime(2026, 9, day + 1, 6, tzinfo=UTC),
            "variable": "precipitation_24h",
            "value": value,
            "quality": 0,
            "source": source,
        }

    rows = pl.DataFrame([row(1, 0.0), row(2, 1.2), row(5, 43.7), row(6, 0.4)], schema=SCHEMA)
    assert gauges.drop_after_gaps(rows)["value"].to_list() == pytest.approx([0.0, 1.2, 0.4])
    # a gauge's first value stays (nothing before it to have a gap after), and so does the
    # checked historical archive
    assert gauges.drop_after_gaps(rows.filter(pl.col("value") > 40)).height == 1
    old = pl.DataFrame([row(1, 0.0, "historical"), row(5, 3.0, "historical")], schema=SCHEMA)
    assert gauges.drop_after_gaps(old).height == 2
    # gaps are per gauge
    two = pl.DataFrame([row(1, 0.0), row(2, 0.1, station="h"), row(3, 0.2)], schema=SCHEMA)
    assert gauges.drop_after_gaps(two)["value"].to_list() == pytest.approx([0.0, 0.1])
    assert gauges.drop_after_gaps(rows.clear()).height == 0


def test_a_total_after_a_gap_across_a_month_boundary_is_dropped():
    # the backfill fetches one month at a time: the September readings decide whether the
    # first October value follows a gap
    def month(days):
        values = [[W, "SRA", "06:00", f"{d}T06:00:00Z", 1.0, "", 0.0] for d in days]
        header = "STATION,ELEMENT,VTYPE,DT,VAL,FLAG,QUALITY"
        return {"data": {"data": {"header": header, "values": values}}}

    september = month([f"2026-09-{d:02d}" for d in range(20, 25)])  # until 24 Sept
    october = month(["2026-10-02", "2026-10-03"])
    client, seen = server({"202609": september, "202610": october}, csv=None)
    rows = gauges.fetch_gauge_precipitation(
        client, [W], date(2026, 10, 1), date(2026, 10, 31), historical=False
    )
    assert rows["time"].to_list() == [datetime(2026, 10, 4, 6, tzinfo=UTC)]
    assert any(p.endswith("-202609.json") for p in seen)
    # without September (not published yet) the first value stays, as before
    client, _ = server({"202610": october}, csv=None)
    rows = gauges.fetch_gauge_precipitation(
        client, [W], date(2026, 10, 1), date(2026, 10, 31), historical=False
    )
    assert rows.height == 2
