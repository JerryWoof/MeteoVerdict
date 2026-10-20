from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import polars as pl
import pytest

from meteoverdict import forecasts, runs
from meteoverdict.models import RUNS_FROM, load_models

MODELS = [m for m in load_models() if m.enabled]
BY_ID = {m.id: m for m in MODELS}
NOW = datetime(2026, 10, 13, 14, 25, tzinfo=UTC)
RUN = datetime(2026, 10, 12, 6, tzinfo=UTC)
STATIONS = pl.DataFrame(
    {
        "id": ["a", "b"],
        "lat": [50.0, 49.5],
        "lon": [14.4, 18.7],
        "elevation": [300.0, None],
    }
)
#: last lead hour per model in the fake answers (like the real 06 UTC runs)
LAST = {
    "chmi_aladin_cz_1km": 72,
    "chmi_aladin_central_europe_2km": 72,
    "dwd_icon_d2": 48,
    "ukmo_global_deterministic_10km": 60,
    "meteofrance_arpege_europe": 102,
    "geosphere_arome_austria": 60,
}


def answer(params, without=(), no_data_at=()):
    """A Single Runs answer like Open-Meteo's: a list per location, columns
    ``<variable>_<model>``; a model without data at a location (latitude) is left out."""
    run = datetime.fromisoformat(params["run"]).replace(tzinfo=UTC)
    hours = int(params["forecast_hours"])
    times = [f"{run + timedelta(hours=h):%Y-%m-%dT%H:%M}" for h in range(hours)]
    models = params["models"].split(",")
    lats = params["latitude"].split(",")
    out = []
    for i, _ in enumerate(lats):
        hourly = {"time": times}
        for n, model in enumerate(models):
            if model in without or (float(lats[i]), model) in no_data_at:
                continue
            last = LAST.get(model, 120)
            for var in params["hourly"].split(","):
                base = {
                    "temperature_2m": 10.0,
                    "precipitation": 0.0,
                    "wind_speed_10m": 2.0,
                    "wind_gusts_10m": 5.0,
                }[var]
                values = [base + n if h <= last else None for h in range(hours)]
                name = var if len(models) == 1 else f"{var}_{model}"
                hourly[name] = values
        item = {"latitude": float(lats[i]), "hourly": hourly}
        if i:
            item["location_id"] = i
        out.append(item)
    return out


def unavailable(model):
    return httpx.Response(
        400,
        json={
            "error": True,
            "reason": f"The requested model run is not available. Model: {model}, run: x",
        },
    )


class FakeApi:
    """Open-Meteo stand-in: ``gone`` = {run: {reported model names}} not available."""

    def __init__(self, gone=None, no_data_at=()):
        self.gone = gone or {}
        self.no_data_at = no_data_at
        self.requests = []

    def __call__(self, request):
        params = {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
        self.requests.append(params)
        assert request.url.host == "single-runs-api.open-meteo.com"
        models = params["models"].split(",")
        for reported in sorted(self.gone.get(params["run"], ())):
            real = runs.ALIASES.get(reported, reported)
            if real in models:
                return unavailable(reported)
        payload = answer(params, no_data_at=self.no_data_at)
        lats = {float(x) for x in params["latitude"].split(",")}
        if len(models) == 1 and any(m == models[0] and x in lats for x, m in self.no_data_at):
            return httpx.Response(
                400, json={"error": True, "reason": "No data is available for this location"}
            )
        return httpx.Response(200, json=payload)


def client(api):
    return httpx.Client(transport=httpx.MockTransport(api))


def budget(calls=10_000):
    return forecasts.Budget(max_calls=calls, sleep=lambda _: None)


# --- the station subset ----------------------------------------------------------------


def test_committed_subset_covers_every_okres():
    subset = runs.load_stations()
    # the rule's 100, plus every other temperature station (bucket only)
    core = runs.api_stations(subset)
    assert core.height == runs.TOTAL_STATIONS
    assert subset.filter(pl.col("reason") == "temperature").height > 150
    assert "Tišnov, Hájek" in subset["name"].to_list()  # Blansko's nearest
    assert subset["id"].n_unique() == subset.height
    assert subset["okres_code"].n_unique() == 77
    assert subset.filter(pl.col("reason") == "okres").height == 77
    assert set(subset["elevation_class"]) == {"lowland", "upland", "mountain"}
    assert subset["elevation"].null_count() == 0


def _meta2(elements):
    rows = [(wsi, el) for wsi, els in elements.items() for el in els]
    return pl.DataFrame(
        {
            "OBS_TYPE": ["10M"] * len(rows),
            "WSI": [r[0] for r in rows],
            "EG_EL_ABBREVIATION": [r[1] for r in rows],
        }
    )


def test_select_stations_rule():
    stations = pl.DataFrame(
        {
            "id": ["near", "far", "rain", "peak", "low1", "low2", "closed"],
            "name": list("abcdefg"),
            "lat": [50.0, 50.3, 49.0, 50.7, 49.0, 50.0, 50.0],
            "lon": [14.0, 14.0, 16.0, 15.7, 14.0, 14.01, 14.0],
            "elevation": [300.0, 300.0, 250.0, 1400.0, 200.0, 310.0, 300.0],
            "active": [True, True, True, True, True, True, False],
            "okres_code": ["A", "A", "B", "C", "C", "A", "A"],
            "okres": ["A", "A", "B", "C", "C", "A", "A"],
            "kraj_code": ["K"] * 7,
            "elevation_class": ["lowland"] * 3 + ["mountain"] + ["lowland"] * 3,
        }
    )
    full = ("T", "F", "SRA10M")
    meta2 = _meta2(
        {
            "near": full,
            "far": full,
            "rain": ("SRA10M",),
            "peak": full,
            "low1": full,
            "low2": full,
            "closed": full,
        }
    )
    points = pl.DataFrame(
        {
            "code": ["A", "B", "C"],
            "name": ["A", "B", "C"],
            "lat": [50.0, 49.0, 49.0],
            "lon": [14.0, 16.0, 14.0],
        }
    )
    subset = runs.select_stations(stations, meta2, points, total=5)
    # A: the closest full station; B: only a rain station there; C: low1 is closer than
    # the peak, which then joins as a mountain station; the 5th is the farthest one; the
    # other active temperature station (low2) joins beyond the total, closed does not
    assert subset["id"].to_list() == ["near", "rain", "low1", "peak", "far", "low2"]
    assert subset["reason"].to_list() == [
        "okres", "okres", "okres", "mountain", "spread", "temperature"
    ]  # fmt: skip
    assert subset.equals(runs.select_stations(stations, meta2, points, total=5))


def test_every_other_temperature_station_joins_beyond_the_total():
    stations = pl.DataFrame(
        {
            "id": ["a1", "rain", "t1", "t2", "gone"],
            "name": list("abcde"),
            "lat": [50.0, 49.0, 49.1, 49.2, 49.3],
            "lon": [14.0, 16.0, 16.0, 16.0, 16.0],
            "elevation": [300.0, 400.0, 700.0, 420.0, 400.0],
            "active": [True, True, True, True, False],
            "okres_code": ["A", "B", "A", "A", "A"],
            "okres": ["A", "B", "A", "A", "A"],
            "kraj_code": ["K"] * 5,
            "elevation_class": ["lowland", "upland", "upland", "upland", "upland"],
        }
    )
    full = ("T", "F", "SRA10M")
    meta2 = _meta2({"a1": full, "rain": ("SRA10M",), "t1": ("T",), "t2": full, "gone": full})
    points = pl.DataFrame(
        {"code": ["A", "B"], "name": ["A", "B"], "lat": [50.0, 49.0], "lon": [14.0, 16.0]}
    )
    subset = runs.select_stations(stations, meta2, points, total=2)
    # the rule's two (one per okres), then every other active station with temperature
    assert subset["id"].to_list() == ["a1", "rain", "t1", "t2"]
    assert subset["reason"].to_list() == ["okres", "okres", "temperature", "temperature"]
    assert runs.api_stations(subset)["id"].to_list() == ["a1", "rain"]


# --- which runs --------------------------------------------------------------------------


def test_run_lists():
    # at 14:25 the bucket may have the 12 UTC run already; back 90 days
    bucket_runs = runs.bucket_runs(NOW)
    assert bucket_runs[0] == datetime(2026, 10, 13, 12, tzinfo=UTC)
    assert bucket_runs[-1] == runs.bucket_start(NOW) == datetime(2026, 7, 15, 18, tzinfo=UTC)
    # the API only for runs at least 24 h old (younger ones may still reach the bucket),
    # back to the month the bucket's window starts in; older runs are the backfill's
    api = runs.api_runs(NOW)
    assert api[0] == datetime(2026, 10, 12, 12, tzinfo=UTC)
    assert api[-1] == runs.history_edge(NOW) == datetime(2026, 7, 1, 0, tzinfo=UTC)
    # the edge moves a month at a time, with the bucket's window
    assert runs.history_edge(datetime(2026, 10, 29, 12, tzinfo=UTC)) == api[-1]
    assert runs.history_edge(datetime(2026, 10, 30, 1, tzinfo=UTC)) == api[-1].replace(month=8)
    assert runs.all_runs(NOW, RUNS_FROM)[0] == bucket_runs[0]
    assert runs.all_runs(NOW, RUNS_FROM)[-1] == datetime(2026, 4, 2, 0, tzinfo=UTC)
    days = runs.day_runs(date(2026, 8, 1), date(2026, 8, 14))
    assert len(days) == 56 and days[0] == datetime(2026, 8, 14, 18, tzinfo=UTC)
    assert days[-1] == datetime(2026, 8, 1, 0, tzinfo=UTC)
    assert runs.parse_run("2026-10-12T06") == RUN
    assert runs.parse_run("2026101206") == RUN
    with pytest.raises(ValueError):
        runs.parse_run("2026-10-12T05")


def test_what_the_bucket_and_the_api_are_asked_for(tmp_path):
    two = [BY_ID["dwd_icon_eu"], BY_ID["ecmwf_ifs"]]
    state = runs.State(tmp_path / runs.STATE_NAME)
    old = datetime(2026, 7, 1, 0, tzinfo=UTC)  # before the bucket's window
    state.fetched[runs.key(RUN)] = {"dwd_icon_eu"}
    state.bucket_missing[runs.key(RUN)] = {"ecmwf_ifs"}
    state.missing[runs.key(old)] = {"ecmwf_ifs"}
    assert state.bucket_todo(RUN, two) == []
    assert state.api_todo(RUN, two, NOW) == [BY_ID["ecmwf_ifs"]]
    other = datetime(2026, 10, 12, 0, tzinfo=UTC)  # in the window, not tried yet
    assert state.bucket_todo(other, two) == two and state.api_todo(other, two, NOW) == []
    assert state.api_todo(old, two, NOW) == [BY_ID["dwd_icon_eu"]]  # older: everything
    state.save()
    again = runs.State.load(state.path)
    assert again.bucket_missing == {"2026101206": {"ecmwf_ifs"}}
    # stored, further variables not settled yet: read from the bucket again
    assert again.extra_todo(RUN, two) == [BY_ID["dwd_icon_eu"]]
    again.extra[runs.key(RUN)] = {"dwd_icon_eu"}
    again.save()
    assert runs.State.load(state.path).extra_todo(RUN, two) == []


def test_each_model_from_its_start_in_the_archive():
    aladin = [m for m in MODELS if m.id.startswith("chmi_aladin")]
    assert aladin and {m.single_runs_from for m in aladin} == {runs.ALADIN_FROM}
    # IFS HRES goes back furthest (checked live 2026-10-17): 2024-03-14 00 UTC, the 06
    # and 18 UTC runs from 2024-08-10 on
    assert runs.history_start(MODELS) == date(2024, 3, 14)
    at = lambda *a: [m.id for m in runs.wanted(MODELS, datetime(*a, tzinfo=UTC))]  # noqa: E731
    assert at(2024, 3, 14, 0) == ["ecmwf_ifs"] and at(2024, 3, 13, 12) == []
    assert at(2024, 8, 9, 6) == [] and at(2024, 8, 10, 18) == ["ecmwf_ifs"]
    assert len(at(2026, 4, 2, 0)) == 15  # without ALADIN (2), JMA GSM and GEM Global
    assert len(at(2026, 4, 1, 12)) == 1
    assert all(
        runs.wanted(MODELS, r) == [m for m in MODELS if r.hour in m.run_hours]
        for r in runs.api_runs(NOW)
    )


def test_models_by_run_and_native_hours():
    april = datetime(2026, 4, 15, 12, tzinfo=UTC)
    assert "chmi_aladin_cz_1km" not in {m.id for m in runs.wanted(MODELS, april)}
    assert "gem_global" not in {m.id for m in runs.wanted(MODELS, april)}  # from 2026-05-28
    assert len(MODELS) == 19
    # GEM Global runs at 00 and 12 UTC only
    assert "gem_global" not in {m.id for m in runs.wanted(MODELS, RUN)}
    assert len(runs.wanted(MODELS, RUN)) == 18
    assert len(runs.wanted(MODELS, RUN.replace(hour=12))) == 19
    aifs, icon = BY_ID["ecmwf_aifs025_single"], BY_ID["dwd_icon_eu"]
    assert [h for h in range(1, 13) if aifs.native_hour(h)] == [6, 12]
    assert icon.native_hour(78) and not icon.native_hour(79) and icon.native_hour(81)
    assert icon.step_at(78) == 1 and icon.step_at(79) == 3


def test_cost():
    assert runs.VARIABLES == (
        "temperature_2m",
        "precipitation",
        "wind_speed_10m",
        "wind_gusts_10m",
    )
    assert runs.request_weight(100, 11) == pytest.approx(440)  # 4 x 11 / 10 per station
    assert runs.request_weight(100, 9) == pytest.approx(360)  # runs without ALADIN
    assert runs.request_weight(100, 1) == pytest.approx(100)  # never below 1 per station
    assert runs.run_cost(150, 11) == pytest.approx(660)  # 4 variables
    # 4 variables x 19 models would be 7.6 a station: 760 a run of 100 stations
    assert runs.request_weight(100, 19, variables=4) == pytest.approx(760)


@pytest.mark.parametrize(
    ("stations", "models", "sizes"),
    [
        (100, 11, [100]),  # 330 calls: one request
        (100, 19, [50, 50]),  # 570: two equal requests below MAX_REQUEST
        (101, 19, [51, 50]),
        (250, 1, [84, 83, 83]),  # 100 stations a request at most
        (3, 19, [3]),
        (0, 19, []),
    ],
)
def test_requests_stay_below_the_per_minute_limit(stations, models, sizes):
    assert runs.batches(stations, models) == sizes
    assert all(runs.request_weight(n, models) <= runs.MAX_REQUEST for n in sizes)
    assert all(n <= runs.BATCH for n in sizes)


# --- answers -----------------------------------------------------------------------------


def test_parse_several_models_and_a_missing_one():
    params = {
        "run": "2026-10-12T06:00",
        "forecast_hours": "121",
        "models": "dwd_icon_d2,dwd_icon_eu",
        "latitude": "50,49.5",
        "hourly": "temperature_2m,precipitation,wind_speed_10m",
    }
    payload = answer(params, no_data_at={(49.5, "dwd_icon_d2")})
    models = [BY_ID["dwd_icon_d2"], BY_ID["dwd_icon_eu"]]
    rows = runs.parse(payload, ["a", "b"], models, RUN)
    assert rows.schema == pl.Schema(runs.HOURLY_SCHEMA)
    counts = dict(
        rows.group_by("station_id", "model")
        .len()
        .select(pl.concat_str("station_id", "model", separator="|"), "len")
        .rows()
    )
    assert counts == {"a|dwd_icon_d2": 48, "a|dwd_icon_eu": 120, "b|dwd_icon_eu": 120}
    first = rows.filter(pl.col("station_id") == "a", pl.col("model") == "dwd_icon_eu").sort(
        "lead_h"
    )
    assert first["lead_h"][0] == 1  # lead 0 is not stored
    assert first["valid_time"][0] == RUN + timedelta(hours=1)
    assert first["temperature_2m"][0] == pytest.approx(11.0)


def test_parse_one_model_reads_plain_names():
    params = {
        "run": "2026-10-12T06:00",
        "forecast_hours": "4",
        "models": "dwd_icon_eu",
        "latitude": "50",
        "hourly": "temperature_2m,precipitation,wind_speed_10m",
    }
    rows = runs.parse(answer(params)[0], ["a"], [BY_ID["dwd_icon_eu"]], RUN)
    assert rows["lead_h"].to_list() == [1, 2, 3]


# --- fetching ----------------------------------------------------------------------------


def test_fetch_run_drops_a_model_without_the_run():
    api = FakeApi(gone={"2026-10-12T06:00": {"ncep_gfs013"}})  # reported as ncep_gfs013
    spent = budget()
    with client(api) as c:
        rows, fetched, gone = runs.fetch_run(c, STATIONS, RUN, MODELS, spent)
    assert gone == {"ncep_gfs_global"}
    assert fetched == {m.id for m in MODELS} - gone
    assert "ncep_gfs_global" not in set(rows["model"])
    assert len(api.requests) == 2
    assert api.requests[0]["elevation"] == "300.0,nan"
    assert api.requests[0]["forecast_hours"] == "121"
    assert api.requests[0]["wind_speed_unit"] == "ms"
    assert api.requests[0]["hourly"] == (
        "temperature_2m,precipitation,wind_speed_10m,wind_gusts_10m"
    )
    gusts = rows.filter(pl.col("model") == "dwd_icon_eu")["wind_gusts_10m"]
    assert gusts.null_count() == 0 and gusts.min() > 0
    # both requests count: 2 stations x 4 x 19 / 10, then 2 x 4 x 18 / 10
    assert spent.used == pytest.approx(15.2 + 14.4)


@pytest.mark.parametrize(
    ("reported", "model"),
    [
        ("cmc_gem_gdps_15km", "gem_global"),
        ("meteofrance_arpege_world025", "meteofrance_arpege_world"),
        ("dwd_icon", "dwd_icon"),
        ("dwd_icon_eu_native", "dwd_icon_eu"),
        ("jma_gsm", "jma_gsm"),
    ],
)
def test_reported_names_of_missing_runs(reported, model):
    # the names Open-Meteo reports for a missing run (checked live 2026-10-13/15)
    api = FakeApi(gone={"2026-10-12T06:00": {reported}})
    with client(api) as c:
        _, fetched, gone = runs.fetch_run(c, STATIONS, RUN, MODELS, budget())
    assert gone == {model} and model not in fetched


def test_a_large_run_is_split_into_requests():
    many = pl.DataFrame(
        {
            "id": [f"s{i}" for i in range(100)],
            "lat": [50.0] * 100,
            "lon": [14.4] * 100,
            "elevation": [300.0] * 100,
        }
    )
    api = FakeApi()
    spent = budget()
    spent.clock = iter(range(0, 10**6, 100)).__next__  # 100 s between requests: no waiting
    with client(api) as c:
        rows, fetched, _ = runs.fetch_run(c, many, RUN, MODELS, spent)
    assert len(fetched) == 19 and rows["station_id"].n_unique() == 100
    assert [len(r["latitude"].split(",")) for r in api.requests] == [50, 50]
    assert spent.used == pytest.approx(760)


def test_fetch_run_splits_stations_when_one_model_has_no_data():
    api = FakeApi(no_data_at={(49.5, "dwd_icon_d2")})
    with client(api) as c:
        rows, fetched, gone = runs.fetch_run(c, STATIONS, RUN, [BY_ID["dwd_icon_d2"]], budget())
    assert (fetched, gone) == ({"dwd_icon_d2"}, set())
    assert set(rows["station_id"]) == {"a"}


def test_fetch_run_unknown_model_name_is_an_error():
    api = FakeApi(gone={"2026-10-12T06:00": {"something_else"}})
    api.gone["2026-10-12T06:00"] = {"something_else"}

    def handler(request):
        return unavailable("something_else")

    with client(handler) as c, pytest.raises(ValueError, match="which model"):
        runs.fetch_run(c, STATIONS, RUN, MODELS, budget())


def test_collect_bucket_gaps_first_then_history_and_resume(tmp_path):
    two = [BY_ID["dwd_icon_eu"], BY_ID["ecmwf_ifs"]]
    state = runs.State(tmp_path / runs.STATE_NAME)
    state.bucket_missing = {"2026101206": {"ecmwf_ifs"}, "2026100100": {"dwd_icon_eu", "ecmwf_ifs"}}
    state.save()
    api = FakeApi()
    with client(api) as c:
        # 2 stations, at least 1 call each: 2 calls a run; the first history run does
        # not fit in what is left
        result = runs.collect(c, STATIONS, two, tmp_path, budget(5), NOW)
    assert result.runs == ["2026101206", "2026100100"]
    assert [r["models"] for r in api.requests] == ["ecmwf_ifs", "dwd_icon_eu,ecmwf_ifs"]
    assert result.stopped == "budget of 5 calls reached (4 used)"
    assert result.calls["2026101206"] == pytest.approx(2)
    stored = pl.read_parquet(tmp_path / "runs" / "2026-10.parquet")
    assert set(stored["source"]) == {"api"}
    # stored at native steps: ICON-EU hourly to 78 h, then every 3 hours
    eu = stored.filter(pl.col("model") == "dwd_icon_eu", pl.col("station_id") == "a")
    assert 79 not in eu["lead_h"].to_list() and 81 in eu["lead_h"].to_list()
    with client(api) as c:
        again = runs.collect(c, STATIONS, two, tmp_path, budget(4), NOW)
    # then the history older than the bucket's window, newest first
    assert again.runs == ["2026071512", "2026071506"]


def test_a_budget_too_small_for_all_models_takes_some(tmp_path):
    three = [BY_ID["dwd_icon_eu"], BY_ID["ecmwf_ifs"], BY_ID["dwd_icon"]]
    state = runs.State(tmp_path / runs.STATE_NAME)
    state.bucket_missing = {runs.key(RUN): {m.id for m in three}}
    state.save()
    api = FakeApi()
    with client(api) as c:
        # three models cost 2 x 1.2; two models 2 (at least one call per station)
        result = runs.collect(c, STATIONS, three, tmp_path, budget(2), NOW, modes=("recent",))
    assert [r["models"] for r in api.requests] == ["dwd_icon_eu,ecmwf_ifs"]
    assert result.runs == ["2026101206"]
    left = runs.State.load(tmp_path / runs.STATE_NAME).api_todo(RUN, three, NOW)
    assert [m.id for m in left] == ["dwd_icon"]
    assert runs.affordable(100, 19, 400) == 10  # 4 x 10 / 10 = 4 a station
    assert runs.affordable(100, 3, 100) == 2
    assert runs.affordable(100, 1, 99) == 0


def test_a_model_added_later_is_fetched_newest_run_first(tmp_path):
    two, added = [BY_ID["dwd_icon_eu"], BY_ID["ecmwf_ifs"]], BY_ID["dwd_icon"]
    api = FakeApi()
    with client(api) as c:
        runs.collect(c, STATIONS, two, tmp_path, budget(6), NOW, modes=("history",))
    done = len(api.requests)
    with client(api) as c:
        result = runs.collect(
            c, STATIONS, [*two, added], tmp_path, budget(6), NOW, modes=("history",)
        )
    asked = api.requests[done:]
    assert {r["models"] for r in asked} == {"dwd_icon"}  # only the new model
    assert [r["run"] for r in asked] == sorted((r["run"] for r in asked), reverse=True)
    assert result.runs[0] == "2026071512"


def test_gaps_of_young_runs_are_asked_again(tmp_path):
    two = [BY_ID["dwd_icon_eu"], BY_ID["ecmwf_ifs"]]
    young, old = datetime(2026, 10, 13, 0, tzinfo=UTC), datetime(2026, 10, 10, 0, tzinfo=UTC)
    api = FakeApi(
        gone={f"{young:%Y-%m-%dT%H:%M}": {"ecmwf_ifs"}, f"{old:%Y-%m-%dT%H:%M}": {"ecmwf_ifs"}}
    )
    with client(api) as c:
        result = runs.collect(c, STATIONS, two, tmp_path, budget(), NOW, runs=[young, old])
    assert result.gaps == {"2026101300": {"ecmwf_ifs"}, "2026101000": {"ecmwf_ifs"}}
    state = runs.State.load(tmp_path / runs.STATE_NAME)
    assert state.missing == {"2026101000": {"ecmwf_ifs"}}  # old enough to be a gap
    assert [m.id for m in state.todo(young, two)] == ["ecmwf_ifs"]
    assert state.todo(old, two) == []
    api.gone = {}
    with client(api) as c:
        runs.collect(c, STATIONS, two, tmp_path, budget(), NOW, runs=[young, old])
    assert api.requests[-1]["models"] == "ecmwf_ifs"  # only the missing model
    assert runs.State.load(tmp_path / runs.STATE_NAME).todo(young, two) == []


def test_open_meteo_down_stops_cleanly(tmp_path):
    def handler(request):
        return httpx.Response(503, text="down")

    with client(handler) as c:
        result = runs.collect(c, STATIONS, MODELS, tmp_path, budget(), NOW, runs=[RUN])
    assert "unavailable" in result.stopped
    assert result.runs == []
    assert not (tmp_path / "runs").exists()


def test_failed_run_is_reported_and_others_continue(tmp_path):
    other = datetime(2026, 10, 12, 0, tzinfo=UTC)
    api = FakeApi(gone={"2026-10-12T06:00": {"mystery_model"}})

    def handler(request):
        if "2026-10-12T06" in str(request.url):
            return unavailable("mystery_model")
        return api(request)

    two = [BY_ID["dwd_icon_eu"], BY_ID["ecmwf_ifs"]]
    with client(handler) as c:
        result = runs.collect(c, STATIONS, two, tmp_path, budget(), NOW, runs=[RUN, other])
    assert result.failed == ["2026101206"]
    assert result.runs == ["2026101200"]
    text = runs.summary(result, 10, tmp_path, two, NOW)
    assert "Failed: 2026101206" in text and "## Single runs" in text


class FakeStore:
    def __init__(self):
        self.files = {}  # (tag, name) -> (bytes, label)
        self.puts = []

    def assets(self, tag):
        return {
            n: {"name": n, "label": label} for (t, n), (_, label) in self.files.items() if t == tag
        }

    def put(self, tag, name, path, label=""):
        self.files[(tag, name)] = (path.read_bytes(), label)
        self.puts.append(name)

    def download(self, tag, name, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[(tag, name)][0])
        return dest


def test_sync_through_releases(tmp_path):
    releases = FakeStore()
    two = [BY_ID["dwd_icon_eu"], BY_ID["ecmwf_ifs"]]
    first = tmp_path / "one"
    with client(FakeApi()) as c:
        runs.collect(
            c, STATIONS, two, first, budget(), NOW, runs=[RUN], sync=runs.RunsSync(releases, first)
        )
    assert releases.puts == ["runs-2026-10.parquet", "runs-state.json"]
    assert ("runs-2026-10", "runs-2026-10.parquet") in releases.files
    # another machine: pulls the state and the month before adding a run to it
    second = tmp_path / "two"
    sync = runs.RunsSync(releases, second)
    sync.pull_state()
    other = datetime(2026, 10, 12, 0, tzinfo=UTC)
    with client(FakeApi()) as c:
        result = runs.collect(c, STATIONS, two, second, budget(), NOW, runs=[RUN, other], sync=sync)
    assert result.runs == ["2026101200"]
    stored = pl.read_parquet(second / "runs" / "2026-10.parquet")
    assert stored["run"].n_unique() == 2
    releases.puts.clear()
    sync.push(["2026-10"])  # unchanged: only the state goes up again
    assert releases.puts == ["runs-state.json"]


def test_runs_from_in_the_catalogue(tmp_path):
    path = tmp_path / "m.yaml"
    path.write_text(
        "models:\n  - {id: x, name: X, provider: P, grid: 1 km, step_hours: 1,"
        " forecast_days: 3, max_lead_day: 2, archive_from: 2026-06-24, runs_from: 2026-06-23}\n"
    )
    (model,) = load_models(path)
    assert model.single_runs_from == date(2026, 6, 23)
    assert BY_ID["dwd_icon_eu"].single_runs_from == RUNS_FROM


# --- two workflows, one state --------------------------------------------------------


def test_the_state_is_merged_before_it_goes_up(tmp_path):
    releases = FakeStore()
    two = [BY_ID["dwd_icon_eu"], BY_ID["ecmwf_ifs"]]
    # the backfill (older months) and fetch-runs (the bucket's months) start from the
    # same released state and each upload what they fetched
    backfill_dir, runs_dir = tmp_path / "backfill", tmp_path / "runs"
    old = datetime(2026, 6, 1, 0, tzinfo=UTC)
    for folder, run in ((runs_dir, RUN), (backfill_dir, old)):
        sync = runs.RunsSync(releases, folder)
        sync.pull_state()
        with client(FakeApi()) as c:
            runs.collect(c, STATIONS, two, folder, budget(), NOW, runs=[run], sync=sync)
    name = (runs.STATE_TAG, runs.STATE_NAME)
    (tmp_path / "released.json").write_bytes(releases.files[name][0])
    released = runs.State.load(tmp_path / "released.json")
    assert set(released.fetched) == {runs.key(RUN), runs.key(old)}  # nothing lost
    # unchanged: no download, nothing to merge
    puts = len(releases.puts)
    runs.RunsSync(releases, backfill_dir).push([])
    assert len(releases.puts) == puts + 1
    assert runs.State.load(backfill_dir / runs.STATE_NAME).fetched == released.fetched


def test_merge_is_a_union(tmp_path):
    mine, theirs = runs.State(tmp_path / "a.json"), runs.State(tmp_path / "b.json")
    mine.fetched = {"2026101200": {"a"}}
    mine.bucket_missing = {"2026101200": {"b"}}
    theirs.fetched = {"2026101200": {"b"}, "2026060100": {"a"}}
    theirs.missing = {"2026060100": {"c"}}
    theirs.extra = {"2026101200": {"b"}}
    mine.merge(theirs)
    assert mine.extra == {"2026101200": {"b"}}
    assert mine.fetched == {"2026101200": {"a", "b"}, "2026060100": {"a"}}
    assert mine.missing == {"2026060100": {"c"}}
    assert mine.bucket_missing == {"2026101200": {"b"}}
    two = [BY_ID["dwd_icon_eu"], BY_ID["ecmwf_ifs"]]
    assert runs.backfill_pending(mine, two, NOW) > 0


def hourly_rows(model, last=120, precipitation=0.1, source=None):
    rows = [
        (RUN, model, "a", h, RUN + timedelta(hours=h), 10.0 + h, precipitation, 2.0, 3.0)
        for h in range(1, last + 1)
    ]
    frame = pl.DataFrame(rows, schema=runs.HOURLY_SCHEMA, orient="row")
    return frame.with_columns(pl.lit(source, pl.String).alias("source"))


def test_native_keeps_the_native_hours_with_their_totals():
    legacy = hourly_rows("ecmwf_ifs025")  # 3-hourly, every hour filled by the API
    gap = hourly_rows("dwd_icon_eu").filter(pl.col("lead_h") != 80)
    bucket_rows = hourly_rows("jma_gsm", source="bucket")  # kept as they are
    out = runs.native(pl.concat([legacy, gap, bucket_rows]), MODELS).collect()
    ifs = out.filter(pl.col("model") == "ecmwf_ifs025").sort("lead_h")
    assert ifs["lead_h"].to_list() == list(range(3, 121, 3))
    assert ifs["precipitation"].to_list() == pytest.approx([0.3] * 40)
    assert ifs["temperature_2m"][0] == pytest.approx(13.0)
    eu = out.filter(pl.col("model") == "dwd_icon_eu").sort("lead_h")
    assert eu.filter(pl.col("lead_h") == 81)["precipitation"].to_list() == [None]  # 80 lacks
    assert eu.filter(pl.col("lead_h") == 78)["precipitation"].to_list() == [pytest.approx(0.1)]
    assert out.filter(pl.col("model") == "jma_gsm").height == 120
    # without a source column at all (month files from before 2026-10-17)
    assert runs.native(legacy.drop("source"), MODELS).collect().height == 40
    stored = runs.from_api(legacy.drop("source"), MODELS)
    assert stored.schema == pl.Schema(runs.SCHEMA) and set(stored["source"]) == {"api"}
    # the further variables come from the bucket only: null in the API's rows
    assert stored.select(runs.EXTRA_VARIABLES).null_count().sum_horizontal().item() == (
        stored.height * len(runs.EXTRA_VARIABLES)
    )


def test_summary_states_the_budget(tmp_path):
    text = runs.summary(runs.Result(), 0, tmp_path, MODELS, NOW, budget_note="100 calls")
    assert "- Budget: 100 calls" in text
    assert "runs complete since 2024-03-14" in text
    assert "the history since 2026-07-01)" in text and "left to the D+N backfill" in text
