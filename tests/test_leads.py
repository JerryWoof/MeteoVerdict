from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import leads

RUN = datetime(2026, 10, 10, 6, tzinfo=UTC)
CZ1, LAMB = "chmi_aladin_cz_1km", "chmi_aladin_central_europe_2km"
A, B = "0-20000-0-11520", "0-20000-0-11406"


def archive(model=CZ1, run=RUN, station=A, steps=range(0, 4), temp=None, accum=None, wind=None):
    """Archive rows like ``aladin.extract_run``: one per lead hour."""
    steps = list(steps)
    n = len(steps)
    return pl.DataFrame(
        {
            "model": [model] * n,
            "run": [run] * n,
            "lead_h": pl.Series(steps, dtype=pl.Int16),
            "station_id": [station] * n,
            "temperature_2m": pl.Series(temp or [10.0 + s for s in steps], dtype=pl.Float32),
            "wind_speed_10m": pl.Series(wind or [2.0] * n, dtype=pl.Float32),
            "precipitation_accum": pl.Series(
                accum or [None, *[0.5 * s for s in steps[1:]]], dtype=pl.Float32
            ),
            "valid_time": [run + timedelta(hours=s) for s in steps],
        }
    )


def obs(station, start, values, variable="temperature_2m"):
    return pl.DataFrame(
        {
            "station_id": [station] * len(values),
            "time": [start + timedelta(hours=i) for i in range(len(values))],
            "variable": [variable] * len(values),
            "value": pl.Series(values, dtype=pl.Float32),
            "quality": pl.Series([0] * len(values), dtype=pl.UInt8),
            "source": ["now"] * len(values),
        }
    )


def test_archive_names_and_files(tmp_path):
    assert leads.run_of("chmi_aladin_cz_1km_2026101006.parquet") == (CZ1, RUN)
    assert leads.run_of("obs-2026-10.parquet") is None
    folder = tmp_path / "aladin-2026-10"
    folder.mkdir()
    for name in ("chmi_aladin_cz_1km_2026100918.parquet", "chmi_aladin_cz_1km_2026101006.parquet"):
        archive().write_parquet(folder / name)
    (folder / "notes.parquet").write_bytes(b"")
    assert [p.name for p in leads.archive_files(tmp_path, since=RUN)] == [
        "chmi_aladin_cz_1km_2026101006.parquet"
    ]
    assert len(leads.archive_files(tmp_path)) == 2


def test_forecast_hours_hourly_precipitation_from_accumulation():
    # accumulated 0.3, 0.3, 1.0 at leads 1..3; a tiny decrease is packing noise
    rows = archive(accum=[None, 0.3, 0.3, 1.0]).vstack(
        archive(station=B, accum=[None, 0.2, 0.19, 0.5])
    )
    fc = leads.forecast_hours(rows).collect()
    assert fc["lead_h"].min() == 1  # the analysis is not scored
    rain = fc.filter(pl.col("variable") == "precipitation").sort("station_id", "lead_h")
    by_station = {s: g["forecast"].to_list() for (s,), g in rain.group_by("station_id")}
    assert by_station[A] == pytest.approx([0.3, 0.0, 0.7], abs=1e-6)
    assert by_station[B] == pytest.approx([0.2, 0.0, 0.31], abs=1e-6)
    temp = fc.filter(pl.col("variable") == "temperature_2m", pl.col("station_id") == A)
    assert sorted(temp["forecast"].to_list()) == [11.0, 12.0, 13.0]
    assert temp.sort("lead_h")["valid_time"].to_list() == [
        RUN + timedelta(hours=h) for h in (1, 2, 3)
    ]


def test_precipitation_needs_the_previous_lead():
    rows = archive(steps=[0, 1, 3], accum=[None, 0.4, 1.0])  # lead 2 missing
    fc = leads.forecast_hours(rows).collect().filter(pl.col("variable") == "precipitation")
    assert fc.sort("lead_h")["lead_h"].to_list() == [1]


def test_pairs_use_the_valid_time_and_a_common_sample():
    rows = pl.concat(
        [
            archive(model=CZ1, temp=[0, 11, 12, 13]),
            archive(model=LAMB, temp=[0, 10, 10, 10]),
            archive(model=CZ1, station=B),  # only one model at B: left out
        ]
    )
    observed = obs(A, RUN, [9.0, 10.0, 11.0, 12.0]).vstack(obs(B, RUN, [9.0, 9.0, 9.0, 9.0]))
    p = leads.pairs(leads.forecast_hours(rows), observed)
    assert set(p["station_id"]) == {A}
    assert p.filter(pl.col("variable") != "temperature_2m").height == 0  # no wind/rain obs
    cz = p.filter(pl.col("model") == CZ1).sort("lead_h")
    # lead 2 is valid at 08 UTC: forecast 12, observed 11
    assert cz.select("lead_h", "forecast", "observed").rows() == [
        (1, 11, 10),
        (2, 12, 11),
        (3, 13, 12),
    ]
    assert set(p["run_hour"]) == {"06"}


def test_lead_scores_by_lead_hour_run_hour_and_kraj():
    run2 = RUN + timedelta(hours=6)
    rows = pl.concat(
        [
            archive(run=RUN, temp=[0, 11, 12, 13]),
            archive(run=run2, temp=[0, 14, 12, 12]),
        ]
    )
    observed = obs(A, RUN, [10.0] * 10)
    p = leads.pairs(leads.forecast_hours(rows), observed)
    stations = pl.DataFrame({"id": [A], "kraj_code": ["CZ010"], "kraj": ["Hlavní město Praha"]})
    table = leads.lead_scores(p, stations)
    cz = table.filter(pl.col("region") == "cz", pl.col("run_hour") == "all")
    lead1 = cz.filter(pl.col("lead_h") == 1).row(0, named=True)
    # errors at H+1: 06 run +1, 12 run +4 → MAE 2.5, bias 2.5, RMSE sqrt(8.5)
    assert (lead1["n"], lead1["runs"], lead1["stations"]) == (2, 2, 1)
    assert lead1["mae"] == pytest.approx(2.5)
    assert lead1["bias"] == pytest.approx(2.5)
    assert lead1["rmse"] == pytest.approx(8.5**0.5)
    assert lead1["a_0p1"] is None  # counts only for precipitation
    by_hour = table.filter(pl.col("region") == "cz", pl.col("lead_h") == 1)
    assert by_hour["run_hour"].to_list() == ["all", "06", "12"]
    assert by_hour.filter(pl.col("run_hour") == "12")["mae"].item() == pytest.approx(4)
    kraj = table.filter(pl.col("region") == "CZ010")
    assert kraj["run_hour"].unique().to_list() == ["all"]
    assert kraj.filter(pl.col("lead_h") == 1)["mae"].item() == pytest.approx(2.5)


def test_precipitation_contingency_counts():
    rows = archive(accum=[None, 0.0, 0.5, 0.5])  # hourly 0.0, 0.5, 0.0
    observed = obs(A, RUN + timedelta(hours=1), [0.2, 0.3, 0.0], "precipitation")
    table = leads.lead_scores(leads.pairs(leads.forecast_hours(rows), observed))
    rain = table.filter(pl.col("variable") == "precipitation", pl.col("run_hour") == "all")
    counts = {
        r["lead_h"]: (r["a_0p1"], r["b_0p1"], r["c_0p1"], r["d_0p1"])
        for r in rain.iter_rows(named=True)
    }
    assert counts == {1: (0, 0, 1, 0), 2: (1, 0, 0, 0), 3: (0, 0, 0, 1)}


def test_publication_delays_and_document():
    old = archive()  # written before ``published`` existed
    new = archive(model=LAMB).with_columns(
        pl.lit(RUN + timedelta(hours=4, minutes=24)).alias("published")
    )
    assert leads.publication_delays(old) == {CZ1: None}
    delays = leads.publication_delays(pl.concat([old, new], how="diagonal_relaxed"))
    assert delays == {CZ1: None, LAMB: 4.4}

    rows = pl.concat([archive(model=CZ1), archive(model=LAMB)])
    p = leads.pairs(leads.forecast_hours(rows), obs(A, RUN, [10.0] * 5))
    table = leads.lead_scores(p)
    doc = leads.document(
        table, p, datetime(2026, 10, 13, 7, tzinfo=UTC), delays, {CZ1: "ALADIN 1 km"}
    )
    assert doc["columns"] == leads.COLUMNS
    assert len(doc["rows"]) == table.height
    assert doc["first_run"] == doc["last_run"] == "2026-10-10T06:00Z"
    assert doc["models"][CZ1] == {
        "name": "ALADIN 1 km",
        "runs": 1,
        "pairs": 3,
        "publication_delay_h": None,
    }
    assert doc["models"][LAMB]["publication_delay_h"] == 4.4
    assert doc["regions"] == {"cz": "Česko"}
    empty = leads.document(table.clear(), p.clear(), datetime(2026, 10, 13, tzinfo=UTC))
    assert (empty["rows"], empty["first_run"], empty["models"]) == ([], None, {})


class FakeStore:
    def __init__(self, files):
        self.files = files  # {tag: {name: bytes}}
        self.downloaded = []

    def assets(self, tag):
        return {n: {"name": n, "size": len(b)} for n, b in self.files.get(tag, {}).items()}

    def download(self, tag, name, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[tag][name])
        self.downloaded.append(name)
        return dest


def test_download_archive_only_new_runs_since(tmp_path):
    store = FakeStore(
        {
            "aladin-2026-10": {
                "chmi_aladin_cz_1km_2026100900.parquet": b"old",
                "chmi_aladin_cz_1km_2026101006.parquet": b"run",
                "README.txt": b"x",
            }
        }
    )
    assert (
        leads.download_archive(store, tmp_path, ["2026-09", "2026-10"], RUN, log=lambda _: None)
        == 1
    )
    assert store.downloaded == ["chmi_aladin_cz_1km_2026101006.parquet"]
    assert leads.download_archive(store, tmp_path, ["2026-10"], RUN, log=lambda _: None) == 0


# --- every model, from the single runs --------------------------------------------------


def model(id_, step=1, coarser_after=None, coarser_step=None):
    from datetime import date

    from meteoverdict.models import Model

    return Model(
        id=id_, name=id_.upper(), provider="P", grid="1 km", step_hours=step,
        forecast_days=5, max_lead_day=1, archive_from=date(2026, 1, 1),
        coarser_after_h=coarser_after, coarser_step_h=coarser_step,
    )  # fmt: skip


def single(model_id, run=RUN, station=A, last=3, temp=10.0, rain=0.0, skip=()):
    """Rows like ``runs.parse``: one per lead hour 1…last."""
    hours = [h for h in range(1, last + 1) if h not in skip]
    n = len(hours)
    return pl.DataFrame(
        {
            "run": [run] * n,
            "model": [model_id] * n,
            "station_id": [station] * n,
            "lead_h": pl.Series(hours, dtype=pl.Int16),
            "valid_time": [run + timedelta(hours=h) for h in hours],
            "temperature_2m": pl.Series([temp] * n, dtype=pl.Float32),
            "precipitation": pl.Series([rain] * n, dtype=pl.Float32),
            "wind_speed_10m": pl.Series([2.0] * n, dtype=pl.Float32),
        }
    )


def test_horizons_per_run_hour():
    rows = pl.concat(
        [
            single("x", last=5),
            single("x", run=RUN + timedelta(hours=6), last=2),
            single("x", run=RUN + timedelta(days=1), last=5),
        ]
    )
    assert leads.horizons(rows).rows() == [("x", "06", 5), ("x", "12", 2)]


def test_required_models_reach_the_lead_with_native_output():
    table = pl.DataFrame(
        {
            "model": ["hourly", "hourly", "six", "six", "short"],
            "run_hour": ["00", "06", "00", "06", "00"],
            "horizon_h": [12, 6, 12, 12, 3],
        },
        schema_overrides={"horizon_h": pl.Int16},
    )
    models = [model("hourly"), model("six", step=6), model("short")]
    req = leads.required(table, models)

    def at(stratum, lead, variable="temperature_2m"):
        found = req.filter(
            pl.col("stratum") == stratum, pl.col("lead_h") == lead, pl.col("variable") == variable
        )
        return sorted(found["model"])

    assert at("00", 1) == ["hourly", "short"]  # six: no own output at H+1
    assert at("00", 6) == ["hourly", "six"]
    assert at("00", 6, "precipitation") == ["hourly"]  # no hourly sums from 6-hourly output
    assert at("06", 12) == ["six"]
    # all run hours: a model must reach the lead in each; "short" has no 06 runs
    assert at("all", 6) == ["hourly", "six"]
    assert at("all", 12) == ["six"]
    assert at("all", 2) == ["hourly"]
    n = req.filter(pl.col("stratum") == "00", pl.col("lead_h") == 1).select("n_required")
    assert set(n["n_required"]) == {2}


def test_run_scores_on_the_fair_set():
    observed = obs(A, RUN, [10.0] * 6).vstack(obs(B, RUN, [10.0] * 6))
    rows = pl.concat(
        [
            single("long", last=4, temp=11.0),
            single("long", station=B, last=4, temp=13.0),
            single("short", last=2, temp=12.0),
            single("short", station=B, last=2, temp=12.0, skip=(1,)),  # gap at B, H+1
        ]
    )
    models = [model("long"), model("short")]
    table, info = leads.run_lead_scores(rows, observed, models)
    allruns = table.filter(pl.col("run_hour") == "all", pl.col("variable") == "temperature_2m")

    def mae(m, lead):
        found = allruns.filter(pl.col("model") == m, pl.col("lead_h") == lead)
        return found.select("mae", "n").row(0) if found.height else None

    # H+1: B is left out for both (short has no H+1 there), so long is scored at A only
    assert mae("long", 1) == (pytest.approx(1.0), 1)
    assert mae("short", 1) == (pytest.approx(2.0), 1)
    # H+2: both stations, both models
    assert mae("long", 2) == (pytest.approx(2.0), 2)
    assert mae("short", 2) == (pytest.approx(2.0), 2)
    # H+3: short has ended, long alone
    assert mae("long", 3) == (pytest.approx(2.0), 2)
    assert mae("short", 3) is None
    assert set(table["run_hour"]) == {"all", "06"}
    assert info["models"]["long"]["horizon_h"] == {"06": 4}
    assert info["models"]["short"]["runs"] == 1
    assert info["stations"] == 2
    assert info["first_run"] == info["last_run"] == RUN

    doc = leads.runs_document(
        table, info, datetime(2026, 10, 13, tzinfo=UTC), {"short": 4.4}, {"long": "Long"}
    )
    assert doc["columns"] == leads.RUN_COLUMNS and "region" not in doc["columns"]
    assert doc["models"]["long"]["name"] == "Long"
    assert doc["models"]["short"]["publication_delay_h"] == 4.4
    assert doc["first_run"] == "2026-10-10T06:00Z"
    assert len(doc["rows"]) == table.height
    assert "Open-Meteo" in doc["source"]


def test_run_scores_chunks_add_up():
    observed = obs(A, RUN, [10.0] * 30)
    rows = pl.concat(
        [single("m", run=RUN + timedelta(hours=6 * k), last=3, temp=10.0 + k) for k in range(4)]
    )
    whole, _ = leads.run_lead_scores(rows, observed, [model("m")], chunk_runs=10)
    parts, _ = leads.run_lead_scores(rows, observed, [model("m")], chunk_runs=1)
    assert whole.equals(parts)
    first = whole.filter(
        pl.col("run_hour") == "all", pl.col("lead_h") == 1, pl.col("variable") == "temperature_2m"
    )
    assert first.select("runs", "n", "mae").row(0) == (4, 4, pytest.approx(1.5))


def test_run_scores_without_pairs():
    table, info = leads.run_lead_scores(single("m"), obs(B, RUN, [1.0]), [model("m")])
    assert table.height == 0 and info["models"] == {}


def test_a_model_with_few_runs_does_not_cut_the_fair_set():
    # "new" (added recently) has 1 of 5 runs: the fair set keeps all 5 runs of "old"
    runs = [RUN + timedelta(days=k) for k in range(5)]
    observed = pl.concat([obs(A, r, [10.0] * 4) for r in runs])
    rows = pl.concat(
        [single("old", run=r, last=3, temp=11.0) for r in runs]
        + [single("new", run=runs[-1], last=3, temp=12.0)]
    )
    table, info = leads.run_lead_scores(rows, observed, [model("old"), model("new")])
    assert set(table["model"]) == {"old"}
    first = table.filter(
        pl.col("run_hour") == "all", pl.col("lead_h") == 1, pl.col("variable") == "temperature_2m"
    )
    assert first["runs"].item() == 5
    assert info["short_record"] == {"new": {"runs": 1, "of": 5, "coverage": 0.2}}
    doc = leads.runs_document(table, info, datetime(2026, 10, 16, tzinfo=UTC))
    assert doc["short_record"] == info["short_record"]
    assert info["first_run"] == runs[0]


def test_run_coverage_counts_only_the_run_hours_a_model_has():
    from meteoverdict import runs as runs_mod

    runs = [RUN + timedelta(hours=6 * k) for k in range(8)]  # 06, 12, 18, 00 twice
    rows = pl.concat(
        [single("all", run=r) for r in runs]
        # like GEM Global: no 06 and 18 UTC runs, but every 00 and 12 UTC one
        + [single("twice", run=r) for r in runs if r.hour in (0, 12)]
        + [single("new", run=runs[-1])]
    )
    cover = {m: (n, of, ok) for m, n, of, _, ok in runs_mod.coverage(rows).rows()}
    assert cover == {"all": (8, 8, True), "new": (1, 2, False), "twice": (4, 4, True)}


# --- ranking by lead band ----------------------------------------------------------------

MAIN, OTHER = "0-20000-0-11520", "0-203-0-11201020001"
DAY0 = datetime(2026, 8, 1, tzinfo=UTC)


def band_rows(model_id, run, station, temp, last=72, gust=5.0, rain=None, step=1):
    """Single-run rows with all four band variables, leads step…last."""
    hours = [h for h in range(step, last + 1, step)]
    n = len(hours)
    rain = rain or {}
    return pl.DataFrame(
        {
            "run": [run] * n,
            "model": [model_id] * n,
            "station_id": [station] * n,
            "lead_h": pl.Series(hours, dtype=pl.Int16),
            "valid_time": [run + timedelta(hours=h) for h in hours],
            "temperature_2m": pl.Series([temp] * n, dtype=pl.Float32),
            "precipitation": pl.Series([rain.get(h, 0.0) for h in hours], dtype=pl.Float32),
            "wind_speed_10m": pl.Series([2.0] * n, dtype=pl.Float32),
            "wind_gusts_10m": pl.Series([gust] * n, dtype=pl.Float32),
        }
    )


def band_obs(station, days):
    hours = 24 * (days + 4)
    frames = [obs(station, DAY0, [10.0] * hours)]
    frames.append(obs(station, DAY0, [2.0] * hours, "wind_speed_10m"))
    frames.append(obs(station, DAY0, [5.0] * hours, "wind_gusts_10m"))
    # 1 mm in the hour ending at 03 UTC every day
    frames.append(
        obs(station, DAY0, [1.0 if i % 24 == 3 else 0.0 for i in range(hours)], "precipitation")
    )
    return pl.concat(frames)


def test_band_required_reach_and_sets():
    table = pl.DataFrame(
        {
            "model": ["hourly", "hourly", "six", "six", "short", "short", "coarse"],
            "run_hour": ["00", "06", "00", "06", "00", "06", "00"],
            "horizon_h": [72, 72, 72, 72, 48, 30, 72],
        },
        schema_overrides={"horizon_h": pl.Int16},
    )
    models = [
        model("hourly"), model("six", step=6), model("short"),
        model("coarse", coarser_after=48, coarser_step=3),
    ]  # fmt: skip
    req = leads.band_required(table, models, gusts={"hourly", "short", "coarse"})

    def members(set_, band, variable="temperature_2m"):
        found = req.filter(
            pl.col("set") == set_, pl.col("band") == band, pl.col("variable") == variable
        )
        return sorted(set(found["model"]))

    # short reaches 30 h at 06 UTC: not in H+25-48 although its 00 UTC runs reach 48 h
    assert members("hourly", "h13-24") == ["coarse", "hourly", "short"]
    assert members("hourly", "h25-48") == ["coarse", "hourly"]
    # coarse is 3-hourly after H+48: not in the hourly set there, in the 6h set
    assert members("hourly", "h49-72") == ["hourly"]
    assert members("6h", "h49-72") == ["coarse", "hourly", "six"]
    assert members("hourly", "h49-72", "wind_gusts_10m") == ["hourly"]
    assert members("6h", "h1-6", "precipitation") == []
    six = req.filter(pl.col("set") == "6h", pl.col("band") == "h25-48")
    assert sorted(set(six["lead_h"])) == [30, 36, 42, 48]
    hourly = req.filter(pl.col("set") == "hourly", pl.col("band") == "h7-12")
    assert sorted(set(hourly["lead_h"])) == list(range(7, 13))


def test_band_scores_fair_sets_intervals_and_bias():
    days = 15
    runs = [DAY0 + timedelta(days=k) for k in range(days)]
    rows = []
    for run in runs:
        for station in (MAIN, OTHER):
            rows.append(band_rows("good", run, station, 10.5, rain={3: 1.0, 27: 1.0}))
            rows.append(band_rows("bad", run, station, 12.0))
            rows.append(band_rows("six", run, station, 11.0, step=6))
    rows = pl.concat(rows).with_columns(
        # bad has no gusts
        pl.when(pl.col("model") == "bad")
        .then(None)
        .otherwise("wind_gusts_10m")
        .alias("wind_gusts_10m")
    )
    observed = pl.concat([band_obs(MAIN, days), band_obs(OTHER, days)])
    stations = pl.DataFrame({"id": [MAIN, OTHER], "kraj_code": ["CZ010", "CZ010"]})
    models = [model("good"), model("bad"), model("six", step=6)]
    sums, info = leads.band_sums(rows, observed, models, chunk_runs=4)
    assert info["reach"] == {"bad": 72, "good": 72, "six": 72}
    table = leads.band_scores(sums, stations, resamples=50)

    def get(model_id, band="h1-6", set_="hourly", variable="temperature_2m", region="cz"):
        found = table.filter(
            pl.col("region") == region, pl.col("band") == band, pl.col("set") == set_,
            pl.col("variable") == variable, pl.col("model") == model_id,
        )  # fmt: skip
        return found.row(0, named=True) if found.height else None

    good, bad = get("good"), get("bad")
    assert (good["rank"], good["mae"], good["bias"]) == (1, pytest.approx(0.5), pytest.approx(0.5))
    assert (bad["rank"], bad["mae"]) == (2, pytest.approx(2.0))
    assert bad["diff"] == pytest.approx(1.5) and not bad["tied"]
    assert bad["diff_low"] == pytest.approx(1.5) and good["clear"]
    assert get("six") is None  # 6-hourly: not in the hourly set
    assert (good["runs"], good["stations"], good["days"]) == (days, 2, days)
    assert good["n"] == days * 2 * 6
    # 6h set: lead 6 only in H+1-6, every model
    assert get("six", set_="6h")["mae"] == pytest.approx(1.0)
    assert get("good", set_="6h")["n"] == days * 2
    # bias from the 30 valid dates before the run's day, at least 10: the last 5 runs
    assert good["n_bc"] == 5 * 2 * 6 and good["mae_bc"] == pytest.approx(0.0, abs=1e-6)
    # gusts: only the models with gusts
    assert get("bad", variable="wind_gusts_10m") is None
    assert get("good", variable="wind_gusts_10m")["mae"] == pytest.approx(0.0)
    # rain >= 1 mm in the hour: good catches every event, bad none
    rain = get("good", variable="precipitation")
    assert rain["ets_1"] == pytest.approx(1.0) and rain["pod_1"] == pytest.approx(1.0)
    assert get("bad", variable="precipitation")["ets_1"] == pytest.approx(0.0)
    assert get("good")["ets_1"] is None
    # station kinds; the kraj has two stations only: no kraj rows
    assert get("good", region="main")["stations"] == 1
    assert get("good", region="other")["n"] == days * 6
    assert set(table["level"]) == {"cz", "network"}
    assert list(table.columns) == leads.BAND_COLUMNS


def test_band_rankings_windows_documents_and_default():
    days = 12
    runs = [DAY0 + timedelta(hours=6 * k) for k in range(4 * days)]
    rows = pl.concat(
        [band_rows(m, run, MAIN, t) for run in runs for m, t in (("a", 10.5), ("b", 11.0))]
    )
    stations = pl.DataFrame({"id": [MAIN], "kraj_code": ["CZ010"]})
    out = leads.band_rankings(
        rows, band_obs(MAIN, days + 1), [model("a"), model("b")], stations, resamples=20
    )
    assert set(out) == {"90d", "all"}
    table, facts = out["all"]
    first = table.filter(
        pl.col("level") == "cz", pl.col("band") == "h13-24", pl.col("set") == "hourly",
        pl.col("variable") == "temperature_2m", pl.col("rank") == 1,
    )  # fmt: skip
    assert first.select("model", "runs", "days").row(0) == ("a", 4 * days, days)
    assert facts["first_day"] == DAY0.date()
    # fewer than 60 days: the page keeps D+1
    assert leads.band_default(table) is None
    assert leads.band_default(table.with_columns(pl.lit(60, pl.UInt32).alias("days"))) == "h13-24"
    docs = leads.band_documents(
        table, facts, "all", datetime(2026, 10, 17, tzinfo=UTC), {"cz": "Česko"}, {"a": "A"}
    )
    assert set(docs) == {"leads-bands-all.json", "leads-bands-all-kraj.json"}
    doc = docs["leads-bands-all.json"]
    assert doc["columns"] == leads.BAND_COLUMNS
    assert doc["models"] == {"a": "A", "b": "b"}
    assert doc["members"]["h1-6"]["hourly"]["temperature_2m"] == ["a", "b"]
    assert doc["preliminary_days"] == leads.PRELIMINARY_DAYS
    assert doc["first_run"] == "2026-08-01T00:00Z"
    assert docs["leads-bands-all-kraj.json"]["rows"] == []
    assert len(doc["rows"]) == table.height


def test_window_sums_keeps_the_last_days():
    sums = pl.DataFrame({"day": [DAY0.date() + timedelta(days=k) for k in range(100)]})
    assert leads.window_sums(sums, 90).height == 90
    assert leads.window_sums(sums, None).height == 100
