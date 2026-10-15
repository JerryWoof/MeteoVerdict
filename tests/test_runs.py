import dataclasses
import json
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import polars as pl
import pytest

from meteoverdict import backfill, forecasts, runs
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
                base = {"temperature_2m": 10.0, "precipitation": 0.0, "wind_speed_10m": 2.0}[var]
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
    assert subset.height == runs.TOTAL_STATIONS
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
    # the peak, which then joins as a mountain station; the 5th is the farthest one
    assert subset["id"].to_list() == ["near", "rain", "low1", "peak", "far"]
    assert subset["reason"].to_list() == ["okres", "okres", "okres", "mountain", "spread"]
    assert subset.equals(runs.select_stations(stations, meta2, points, total=5))


# --- which runs --------------------------------------------------------------------------


def test_run_lists():
    recent = runs.recent_runs(NOW)
    # at 14:25 the 06 UTC run is 8.4 h old: too fresh; 48 h back to 2026-10-11 18 UTC
    assert recent[0] == datetime(2026, 10, 13, 0, tzinfo=UTC)
    assert recent[-1] == datetime(2026, 10, 11, 18, tzinfo=UTC)
    assert len(recent) == 6
    history = runs.history_runs(NOW)
    assert history[0] == datetime(2026, 10, 11, 12, tzinfo=UTC)
    # back to the first run with ALADIN by default, to the archive start on request
    assert (
        history[-1]
        == datetime(2026, 6, 23, 0, tzinfo=UTC)
        == datetime.combine(runs.HISTORY_FROM, datetime.min.time(), UTC)
    )
    archive = runs.history_runs(NOW, RUNS_FROM)
    assert archive[-1] == datetime.combine(RUNS_FROM, datetime.min.time(), UTC)
    assert archive[: len(history)] == history
    assert not set(recent) & set(history)
    assert runs.parse_run("2026-10-12T06") == RUN
    assert runs.parse_run("2026101206") == RUN
    with pytest.raises(ValueError):
        runs.parse_run("2026-10-12T05")


def test_history_floor_is_the_first_aladin_run():
    aladin = [m for m in MODELS if m.id.startswith("chmi_aladin")]
    assert aladin and {m.single_runs_from for m in aladin} == {runs.HISTORY_FROM}
    history = runs.history_runs(NOW)
    assert all(
        runs.wanted(MODELS, r) == [m for m in MODELS if r.hour in m.run_hours] for r in history
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
    assert runs.request_weight(100, 11) == pytest.approx(330)  # 3 x 11 / 10 per station
    assert runs.request_weight(100, 1) == pytest.approx(100)  # never below 1 per station
    assert runs.run_cost(150, 11) == pytest.approx(495)
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
    assert rows.schema == pl.Schema(runs.SCHEMA)
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
    # both requests count: 2 stations x 3 x 19 / 10, then 2 x 3 x 18 / 10
    assert spent.used == pytest.approx(11.4 + 10.8)


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
    assert spent.used == pytest.approx(570)


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


def test_collect_recent_first_then_history_and_resume(tmp_path):
    two = [BY_ID["dwd_icon_eu"], BY_ID["ecmwf_ifs"]]
    api = FakeApi()
    with client(api) as c:
        # 2 stations x 0.6 -> 2 calls per run (at least 1 per station): 3 runs fit in 7
        result = runs.collect(c, STATIONS, two, tmp_path, budget(7), NOW)
    assert result.runs == ["2026101300", "2026101218", "2026101212"]
    assert "budget" in result.stopped
    assert result.calls["2026101300"] == pytest.approx(2)
    stored = pl.read_parquet(tmp_path / "runs" / "2026-10.parquet")
    assert stored.select("run", "model", "station_id").unique().height == 3 * 2 * 2
    state = json.loads((tmp_path / runs.STATE_NAME).read_text())
    assert sorted(state["fetched"]) == ["2026101212", "2026101218", "2026101300"]
    with client(api) as c:
        again = runs.collect(c, STATIONS, two, tmp_path, budget(4), NOW)
    assert again.runs == ["2026101206", "2026101200"]  # continues, nothing twice


def test_a_model_added_later_is_fetched_newest_run_first(tmp_path):
    two, added = [BY_ID["dwd_icon_eu"], BY_ID["ecmwf_ifs"]], BY_ID["dwd_icon"]
    api = FakeApi()
    with client(api) as c:
        runs.collect(c, STATIONS, two, tmp_path, budget(), NOW, modes=("recent",))
    done = len(api.requests)
    with client(api) as c:
        result = runs.collect(
            c, STATIONS, [*two, added], tmp_path, budget(), NOW, modes=("recent",)
        )
    asked = api.requests[done:]
    assert {r["models"] for r in asked} == {"dwd_icon"}  # only the new model
    assert [r["run"] for r in asked] == sorted((r["run"] for r in asked), reverse=True)
    assert result.runs[0] == "2026101300"


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


# --- the budget --------------------------------------------------------------------------

BACKFILL_FROM = date(2026, 8, 1)


def backfill_state(tmp_path, last, models=MODELS):
    """A backfill state with every complete window up to ``last`` fetched and scored."""
    state = backfill.State(tmp_path / "backfill-state.json")
    for start, end in backfill.complete_windows(BACKFILL_FROM, last):
        state.fc_done |= {backfill.fc_key(m, start, end) for m in models}
        state.scored.add(backfill.window_key(start, end))
        span = backfill.gauge_window(BACKFILL_FROM, last, start)
        if span:
            state.fc_done |= {backfill.gauge_key(m, *span) for m in models}
    return state


def shared(state, day, part=(0, 2500), share=4500.0):
    return runs.shared_budget(850, share, part, lambda: state, MODELS, BACKFILL_FROM, day)


def test_shared_budget_takes_what_the_backfill_leaves(tmp_path):
    today = date(2026, 10, 14)  # windows from 1 Aug end 14 Aug … 9 Oct, next 23 Oct
    done = backfill_state(tmp_path, today)
    calls, why = shared(done, today)
    assert calls == 3350
    assert why == (
        "3350 calls (850 normal + 2500 shared; 4500 of 4500 left, this run takes 0-2500: "
        "the backfill's current windows (last 90 days) are done)"
    )
    assert shared(done, today, part=(2500, 4500))[0] == 850 + 2000
    assert shared(done, today, share=0) == (850, "850 calls (normal)")
    # the backfill finished its current windows this morning with 3000 calls: 1500 left
    done.calls_on, done.calls_used = "2026-10-14", 3000.0
    calls, why = shared(done, today)
    assert calls == 850 + 1500
    assert "1500 of 4500 left, this run takes 0-2500: the backfill used 3000 of the 4500" in why
    calls, why = shared(done, today, part=(2500, 4500))
    assert calls == 850 and "1500 of 4500 left, this run takes 2500-4500" in why
    # ... without recording how much (an older version): nothing
    done.calls_used = None
    assert shared(done, today)[0] == 850
    # yesterday's calls do not count today
    done.calls_on, done.calls_used = "2026-10-13", 4500.0
    assert shared(done, today)[0] == 3350
    # the window 10..23 Oct is fetched tomorrow: today stays normal
    calls, why = shared(done, date(2026, 10, 23))
    assert calls == 850 and "2026-10-10..2026-10-23 becomes due tomorrow" in why
    calls, why = shared(done, date(2026, 10, 24))
    # with the 28-day gauge window 26 Sep..23 Oct, the window before it is pending too
    assert calls == 850
    assert "2 current backfill windows pending (newest 2026-10-10..2026-10-23)" in why


def test_shared_budget_ignores_older_windows_but_not_new_models(tmp_path):
    today, first = date(2026, 10, 14), date(2026, 5, 1)
    done = backfill.State(tmp_path / "s.json")
    windows = backfill.complete_windows(first, today)
    for start, end in windows:
        done.fc_done |= {backfill.fc_key(m, start, end) for m in MODELS}
        span = backfill.gauge_window(first, today, start)
        if span:
            done.fc_done |= {backfill.gauge_key(m, *span) for m in MODELS}
    # older windows pending (here: the oldest one, more than 90 days back) do not count
    oldest = windows[0]
    assert not backfill.is_current(oldest[1], today - timedelta(days=1))
    done.fc_done -= {backfill.fc_key(m, *oldest) for m in MODELS}
    assert backfill.pending_windows(MODELS, first, today, done) == [oldest]
    assert backfill.share_left(MODELS, first, today, done, 4500)[0] == 4500
    # a model added later is pending in every current window: nothing until fetched
    calls, why = shared(backfill_state(tmp_path, today, MODELS[:-1]), today)
    assert calls == 850 and "5 current backfill windows pending" in why


def test_shared_budget_falls_back_when_the_state_cannot_be_read(tmp_path):
    def broken():
        raise httpx.ConnectError("no route to GitHub")

    calls, why = runs.shared_budget(
        850, 4500, (0, 2500), broken, MODELS, BACKFILL_FROM, date(2026, 10, 14)
    )
    assert calls == 850
    assert why == (
        "850 calls (normal; no shared calls: backfill state not readable: no route to GitHub)"
    )
    # a missing state loads as empty: everything pending, so normal too
    empty = backfill.State.load(tmp_path / "nothing.json")
    assert shared(empty, date.today())[0] == 850


def test_history_done_for_the_backfill(tmp_path):
    state = runs.State(tmp_path / runs.STATE_NAME)
    history = runs.history_runs(NOW)
    ok, why = runs.history_done(lambda: state, MODELS, NOW)
    assert (
        not ok and why == f"single-runs history first: {len(history)} runs since 2026-06-23 pending"
    )
    for run in history[: -runs.HISTORY_SLACK]:
        state.fetched[runs.key(run)] = {m.id for m in runs.wanted(MODELS, run)}
    assert runs.history_pending(state, MODELS, NOW) == runs.HISTORY_SLACK
    assert runs.history_done(lambda: state, MODELS, NOW) == (
        True,
        f"single-runs history complete ({runs.HISTORY_SLACK} runs pending)",
    )
    # a model added later makes the history pending again
    newcomer = dataclasses.replace(BY_ID["dwd_icon"], id="new_model")
    assert not runs.history_done(lambda: state, [*MODELS, newcomer], NOW)[0]
    assert runs.history_pending(state, [*MODELS, newcomer], NOW) == len(history)

    def broken():
        raise ValueError("bad json")

    assert runs.history_done(broken, MODELS, NOW) == (
        False,
        "single-runs state not readable: bad json",
    )


def test_summary_states_the_budget(tmp_path):
    text = runs.summary(runs.Result(), 0, tmp_path, MODELS, NOW, budget_note="750 calls (normal)")
    assert "- Budget: 750 calls (normal)" in text
    assert "runs complete since 2026-06-23" in text
