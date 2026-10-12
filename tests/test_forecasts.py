import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import polars as pl
import pytest

from meteoverdict import forecasts as fc
from meteoverdict.models import load_models

FIXTURES = Path(__file__).parent / "fixtures" / "open-meteo"
ALADIN_RESPONSE = json.loads((FIXTURES / "aladin-2-stations-20261009.json").read_text())
INVALID_MODEL = (FIXTURES / "error-invalid-model.json").read_text()
DAILY_LIMIT = (
    '{"error":true,"reason":"Daily API request limit exceeded. Please try again tomorrow."}'
)
MODELS = {m.id: m for m in load_models()}
ALADIN = MODELS["chmi_aladin_cz_1km"]
STATIONS = pl.DataFrame(
    {
        "id": ["0-20000-0-11520", "0-20000-0-11406"],
        "lat": [50.007778, 50.068333],
        "lon": [14.446944, 12.391389],
        "elevation": [302.04, 483.0],
    }
)


@pytest.mark.parametrize(
    ("locations", "variables", "days", "weight"),
    [
        (1, 15, 14, 1.5),  # Open-Meteo's own examples: 2 weeks, 15 variables = 1.5 calls
        (1, 15, 28, 3.0),  # 4 weeks = 3.0
        (1, 6, 14, 1.0),  # never below 1 per location
        (1, 6, 1, 1.0),
        (100, 15, 3, 150.0),  # shorter windows cost the same as 14 days
    ],
)
def test_call_weight(locations, variables, days, weight):
    assert fc.call_weight(locations, variables, days) == pytest.approx(weight)


def test_windows_are_at_most_14_days():
    got = list(fc.windows(date(2026, 1, 1), date(2026, 1, 30)))
    assert got == [
        (date(2026, 1, 1), date(2026, 1, 14)),
        (date(2026, 1, 15), date(2026, 1, 28)),
        (date(2026, 1, 29), date(2026, 1, 30)),
    ]


def test_hourly_names_follow_the_measured_lead_days():
    assert fc.hourly_names(ALADIN) == [
        "temperature_2m_previous_day1",
        "precipitation_previous_day1",
        "wind_speed_10m_previous_day1",
        "temperature_2m_previous_day2",
        "precipitation_previous_day2",
        "wind_speed_10m_previous_day2",
    ]


def test_parse_real_response():
    rows = fc.parse(ALADIN_RESPONSE, STATIONS["id"].to_list(), ALADIN)
    assert rows.schema == pl.Schema(fc.SCHEMA)
    assert rows.height == 2 * 2 * 24  # stations x lead days x hours
    libus = rows.filter(pl.col("station_id") == "0-20000-0-11520", pl.col("lead_day") == 1)
    assert libus["time"][0] == datetime(2026, 10, 9, tzinfo=UTC)
    first = ALADIN_RESPONSE[0]["hourly"]["temperature_2m_previous_day1"][0]
    assert libus["temperature_2m"][0] == pytest.approx(first)
    # the second location carries location_id 1
    cheb = rows.filter(pl.col("station_id") == "0-20000-0-11406", pl.col("lead_day") == 2)
    second = ALADIN_RESPONSE[1]["hourly"]["wind_speed_10m_previous_day2"]
    assert cheb["wind_speed_10m"].to_list() == pytest.approx(second)


def test_parse_drops_hours_without_any_value():
    payload = json.loads(json.dumps(ALADIN_RESPONSE[0]))
    for name in fc.hourly_names(ALADIN):
        payload["hourly"][name] = [None] * 24
    assert fc.parse(payload, ["x"], ALADIN).height == 0


def test_parse_rejects_a_location_mismatch():
    with pytest.raises(ValueError, match="asked for 3"):
        fc.parse(ALADIN_RESPONSE, ["a", "b", "c"], ALADIN)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_budget_paces_below_the_minute_limit_and_stops_at_max():
    clock = FakeClock()
    budget = fc.Budget(max_calls=1000, per_minute=100, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        budget.spend(50)
    assert budget.used == 150
    assert clock.slept and clock.now >= 60  # the third 50 had to wait a minute
    with pytest.raises(fc.QuotaError, match="budget of 1000"):
        budget.spend(900)


def open_meteo(responses):
    """Mock server: answers come from ``responses(params)`` -> (status, text)."""
    seen = []

    def handler(request):
        params = {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
        seen.append(params)
        status, text = responses(params)
        return httpx.Response(status, text=text)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def no_wait_budget(max_calls=1e9):
    clock = FakeClock()
    return fc.Budget(max_calls=max_calls, clock=clock, sleep=clock.sleep)


def test_fetch_sends_station_elevation_and_respects_archive_start():
    client, seen = open_meteo(lambda p: (200, json.dumps(ALADIN_RESPONSE)))
    budget = no_wait_budget()
    rows = fc.fetch_forecasts(
        client, STATIONS, [ALADIN], date(2026, 6, 1), date(2026, 6, 30), budget
    )
    # ALADIN's archive starts 2026-06-24: one window, no requests before it
    assert [(p["start_date"], p["end_date"]) for p in seen] == [("2026-06-24", "2026-06-30")]
    assert seen[0]["elevation"] == "302.0,483.0"
    assert seen[0]["models"] == "chmi_aladin_cz_1km" and seen[0]["wind_speed_unit"] == "ms"
    assert budget.used == 2  # 2 stations x weight 1
    assert rows.height == 0  # the canned answer is for 2026-10-09, outside the range


def test_daily_limit_stops_with_partial_results():
    answers = iter([(200, json.dumps(ALADIN_RESPONSE)), (429, DAILY_LIMIT)])
    client, _ = open_meteo(lambda p: next(answers))
    ifs = MODELS["ecmwf_ifs"]
    with pytest.raises(fc.QuotaError, match="Daily API request limit") as info:
        fc.fetch_forecasts(
            client, STATIONS, [ALADIN, ifs], date(2026, 10, 9), date(2026, 10, 9), no_wait_budget()
        )
    assert info.value.partial.height == 2 * 2 * 24


def test_invalid_request_raises_with_the_reason():
    client, _ = open_meteo(lambda p: (400, INVALID_MODEL))
    with pytest.raises(ValueError, match="MultiDomains"):
        fc.fetch_forecasts(
            client, STATIONS, [ALADIN], date(2026, 10, 9), date(2026, 10, 9), no_wait_budget()
        )


def test_minute_limit_429_is_retried():
    answers = iter(
        [
            (429, '{"error":true,"reason":"Minutely API request limit exceeded."}'),
            (200, json.dumps(ALADIN_RESPONSE)),
        ]
    )
    client, seen = open_meteo(lambda p: next(answers))
    rows = fc.fetch_forecasts(
        client, STATIONS, [ALADIN], date(2026, 10, 9), date(2026, 10, 9), no_wait_budget()
    )
    assert len(seen) == 2 and rows.height == 96


def test_estimate_matches_what_fetch_spends():
    client, _ = open_meteo(lambda p: (200, json.dumps(ALADIN_RESPONSE)))
    budget = no_wait_budget()
    fc.fetch_forecasts(client, STATIONS, [ALADIN], date(2026, 9, 1), date(2026, 10, 9), budget)
    assert fc.estimate_calls(2, [ALADIN], date(2026, 9, 1), date(2026, 10, 9)) == budget.used


NO_DATA = '{"error":true,"reason":"No data is available for this location"}'


def five_stations():
    return pl.DataFrame(
        {
            "id": [f"s{i}" for i in range(5)],
            "lat": [50.0] * 5,
            "lon": [14.0, 15.0, 16.0, 18.7, 18.8],
            "elevation": [300.0] * 5,
        }
    )


def answer_unless_far_east(params):
    lons = [float(x) for x in params["longitude"].split(",")]
    if any(lon > 18.6 for lon in lons):
        return 400, NO_DATA
    one = ALADIN_RESPONSE[0]
    return 200, json.dumps([one] * len(lons) if len(lons) > 1 else one)


def test_stations_without_data_are_found_skipped_and_remembered():
    client, seen = open_meteo(answer_unless_far_east)
    uncovered: dict[str, set[str]] = {}
    rows = fc.fetch_forecasts(
        client, five_stations(), [ALADIN], date(2026, 10, 9), date(2026, 10, 9),
        no_wait_budget(), uncovered=uncovered,
    )  # fmt: skip
    assert uncovered == {ALADIN.id: {"s3", "s4"}}
    assert sorted(set(rows["station_id"])) == ["s0", "s1", "s2"]

    client, seen = open_meteo(answer_unless_far_east)
    fc.fetch_forecasts(
        client, five_stations(), [ALADIN], date(2026, 10, 9), date(2026, 10, 9),
        no_wait_budget(), uncovered=uncovered,
    )  # fmt: skip
    assert len(seen) == 1 and "18.7" not in seen[0]["longitude"]  # no second search


PRECIPITATION_RESPONSE = json.loads(
    (FIXTURES / "aladin-precipitation-2-stations-20261009.json").read_text()
)


def test_rain_gauges_ask_for_precipitation_only_in_28_day_requests():
    client, seen = open_meteo(lambda p: (200, json.dumps(PRECIPITATION_RESPONSE)))
    budget = no_wait_budget()
    first, last = date(2026, 9, 12), date(2026, 10, 9)  # 28 days
    ask = {"variables": ("precipitation",), "max_days": fc.GAUGE_DAYS}
    rows = fc.fetch_forecasts(client, STATIONS, [ALADIN], first, last, budget, **ask)
    assert [(p["start_date"], p["end_date"]) for p in seen] == [("2026-09-12", "2026-10-09")]
    assert seen[0]["hourly"] == "precipitation_previous_day1,precipitation_previous_day2"
    assert budget.used == 2  # still one call per location
    assert fc.estimate_calls(2, [ALADIN], first, last, **ask) == budget.used
    assert rows.height == 2 * 2 * 24
    assert rows["temperature_2m"].null_count() == rows.height
    cheb = rows.filter(pl.col("station_id") == "0-20000-0-11406", pl.col("lead_day") == 2)
    second = PRECIPITATION_RESPONSE[1]["hourly"]["precipitation_previous_day2"]
    assert cheb["precipitation"].to_list() == pytest.approx(second)


def test_the_longest_model_still_costs_one_call_per_gauge_and_28_days():
    longest = max(MODELS.values(), key=lambda m: len(m.lead_days))
    names = fc.hourly_names(longest, ("precipitation",))
    assert fc.call_weight(100, len(names), fc.GAUGE_DAYS) == 100
