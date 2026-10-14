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
    assert all(len(runs.wanted(MODELS, r)) == len(MODELS) for r in history)


def test_models_by_run_and_native_hours():
    april = datetime(2026, 4, 15, 12, tzinfo=UTC)
    assert "chmi_aladin_cz_1km" not in {m.id for m in runs.wanted(MODELS, april)}
    assert len(runs.wanted(MODELS, RUN)) == 11
    aifs, icon = BY_ID["ecmwf_aifs025_single"], BY_ID["dwd_icon_eu"]
    assert [h for h in range(1, 13) if aifs.native_hour(h)] == [6, 12]
    assert icon.native_hour(78) and not icon.native_hour(79) and icon.native_hour(81)
    assert icon.step_at(78) == 1 and icon.step_at(79) == 3


def test_cost():
    assert runs.request_weight(100, 11) == pytest.approx(330)  # 3 x 11 / 10 per station
    assert runs.request_weight(100, 1) == pytest.approx(100)  # never below 1 per station
    assert runs.run_cost(150, 11) == pytest.approx(495)


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
    # both requests count: 2 stations x 3.3, then 2 x 3.0
    assert spent.used == pytest.approx(6.6 + 6.0)


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


def test_extra_budget_only_when_the_backfill_is_idle(tmp_path):
    today = date(2026, 10, 14)  # windows from 1 Aug end 14 Aug … 9 Oct, next 23 Oct
    done = backfill_state(tmp_path, today)

    def budget(state, extra=3000.0, day=today):
        return runs.handover_budget(750, extra, lambda: state, MODELS, BACKFILL_FROM, day)

    calls, why = budget(done)
    assert calls == 3750
    assert (
        why == "3750 calls (750 normal + 3000 extra: backfill idle (all 5 complete "
        "windows since 2026-08-01 fetched))"
    )
    assert budget(done, extra=0) == (750, "750 calls (normal)")
    # a model enabled later makes every window pending again
    calls, why = budget(backfill_state(tmp_path, today, MODELS[:-1]))
    assert calls == 750 and "5 backfill windows pending (newest 2026-09-26..2026-10-09)" in why
    # the backfill asked Open-Meteo today (e.g. finished a window this morning)
    done.calls_on = "2026-10-14"
    assert budget(done)[0] == 750 and "used Open-Meteo calls today" in budget(done)[1]
    done.calls_on = "2026-10-13"
    assert budget(done)[0] == 3750
    # the window 10..23 Oct is fetched tomorrow: today stays normal
    calls, why = budget(done, day=date(2026, 10, 23))
    assert calls == 750 and "2026-10-10..2026-10-23 becomes due tomorrow" in why
    calls, why = budget(done, day=date(2026, 10, 24))
    # with the 28-day gauge window 26 Sep..23 Oct, the window before it is pending too
    assert calls == 750 and "2 backfill windows pending (newest 2026-10-10..2026-10-23)" in why


def test_extra_budget_falls_back_when_the_state_cannot_be_read(tmp_path):
    def broken():
        raise httpx.ConnectError("no route to GitHub")

    calls, why = runs.handover_budget(750, 3000, broken, MODELS, BACKFILL_FROM, date(2026, 10, 14))
    assert calls == 750
    assert (
        why == "750 calls (normal; extra 3000 not used: backfill state not readable: "
        "no route to GitHub)"
    )
    # a missing state loads as empty: everything pending, so normal too
    empty = backfill.State.load(tmp_path / "nothing.json")
    calls, _ = runs.handover_budget(750, 3000, lambda: empty, MODELS, BACKFILL_FROM, date.today())
    assert calls == 750


def test_summary_states_the_budget(tmp_path):
    text = runs.summary(runs.Result(), 0, tmp_path, MODELS, NOW, budget_note="750 calls (normal)")
    assert "- Budget: 750 calls (normal)" in text
    assert "runs complete since 2026-06-23" in text
