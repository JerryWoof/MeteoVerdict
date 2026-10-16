import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from meteoverdict import gusts, outlook
from meteoverdict import sun_cloud_gust as scg

RUN = datetime(2026, 10, 15, 18, tzinfo=UTC)
NOW = datetime(2026, 10, 16, 5, 52, tzinfo=UTC)
PLAIN = {"gust_part": {"default": {"a": 0.0, "b": 1.0, "stations": {}}, "by_lead": {}}}


def single_run(values, hours=120, run=RUN, stations=("s1",), models=("m1", "m2", "m3")):
    """Hourly gusts of every model and station: ``values[model]`` m/s, lead 1..hours."""
    rows = []
    for model in models:
        for station in stations:
            for lead in range(1, hours + 1):
                rows.append((run, model, station, lead, run + timedelta(hours=lead), values[model]))
    return pl.DataFrame(
        rows,
        schema={
            "run": pl.Datetime("us", "UTC"),
            "model": pl.String,
            "station_id": pl.String,
            "lead_h": pl.Int16,
            "valid_time": pl.Datetime("us", "UTC"),
            "wind_gusts_10m": pl.Float32,
        },
        orient="row",
    )


def test_parts_are_the_outlooks():
    assert gusts.PARTS == outlook.PARTS
    assert gusts.TIME_ZONE == outlook.TIME_ZONE


def test_station_parts_mean_of_each_models_largest_gust():
    frame = single_run({"m1": 5.0, "m2": 7.0, "m3": 9.0})
    # one stronger hour of m1 in the afternoon of 17 October (12-18 Prague = 10-16 UTC)
    frame = frame.with_columns(
        pl.when(
            (pl.col("model") == "m1")
            & (pl.col("valid_time") == datetime(2026, 10, 17, 14, tzinfo=UTC))
        )
        .then(20.0)
        .otherwise(pl.col("wind_gusts_10m"))
        .alias("wind_gusts_10m")
    )
    parts = gusts.station_parts(frame, ["s1"])
    row = parts.filter(pl.col("day") == date(2026, 10, 17), pl.col("part") == "afternoon")
    assert row["forecast"][0] == pytest.approx((20 + 7 + 9) / 3)
    assert row["models"][0] == 3
    assert row["lead_day"][0] == 2  # ends 46 h after the run's start
    # the run starts 20:00 Prague time: its evening is cut, the next night is the first
    assert parts["day"].min() == date(2026, 10, 16)
    assert set(parts.filter(pl.col("day") == date(2026, 10, 16))["part"]) == set(gusts.PARTS)
    assert parts.filter(pl.col("day") == date(2026, 10, 15)).is_empty()
    # the run ends 20 Oct 18 UTC (20:00 Prague): the evening of the 20th is not covered
    assert parts.filter(pl.col("day") == date(2026, 10, 20), pl.col("part") == "evening").is_empty()
    assert not parts.filter(
        pl.col("day") == date(2026, 10, 20), pl.col("part") == "afternoon"
    ).is_empty()


def test_a_model_ending_early_leaves_the_later_parts_and_too_few_models_none():
    long = single_run({"m1": 5.0, "m2": 7.0, "m3": 9.0}, models=("m1", "m2", "m3"))
    short = single_run({"m4": 30.0}, hours=30, models=("m4",))
    parts = gusts.station_parts(pl.concat([long, short]), ["s1"])
    late = parts.filter(pl.col("day") == date(2026, 10, 18))
    assert (late["models"] == 3).all() and (late["forecast"] == 7.0).all()
    early = parts.filter(pl.col("day") == date(2026, 10, 16), pl.col("part") == "morning")
    assert early["models"][0] == 4
    two = single_run({"m1": 5.0, "m2": 7.0}, models=("m1", "m2"))
    assert gusts.station_parts(two, ["s1"]).is_empty()


def test_okres_gusts_corrected_with_day_maximum_and_warning():
    frame = single_run({"m1": 10.0, "m2": 12.0, "m3": 14.0}, stations=("s1", "s2"))
    mapping = pl.DataFrame({"okres": ["CZ0100", "CZ0100"], "station": ["s1", "s2"]})
    doc = {
        "gust_part": {
            "default": {"a": 1.0, "b": 1.0, "stations": {"s1": 0.5, "s2": -0.5}},
            "by_lead": {"1": {"a": 2.0, "b": 1.0, "stations": {}}},
            "apply": True,
        }
    }
    table = gusts.okres_gusts(frame, mapping, doc, NOW)
    night16 = table.filter(pl.col("day") == date(2026, 10, 16), pl.col("part") == "night")
    assert night16["gust"][0] == pytest.approx(14.0)  # lead day 1: 12 + 2
    later = table.filter(pl.col("day") == date(2026, 10, 18), pl.col("part") == "morning")
    assert later["gust"][0] == pytest.approx(13.0)  # 12 + 1, station shifts cancel
    assert later["gust_warning"][0] is False and night16["gust_warning"][0] is True
    day = table.filter(pl.col("day") == date(2026, 10, 17), pl.col("part") == "day")
    parts17 = table.filter(pl.col("day") == date(2026, 10, 17), pl.col("part") != "day")
    assert day["gust"][0] == parts17["gust"].max()
    # the 20th lacks its evening: no whole-day value
    assert table.filter(pl.col("day") == date(2026, 10, 20), pl.col("part") == "day").is_empty()
    # not applied: the plain mean
    doc["gust_part"]["apply"] = False
    plain = gusts.okres_gusts(frame, mapping, doc, NOW)
    assert (plain["gust"] == 12.0).all()


def test_no_recent_run_no_gusts():
    frame = single_run({"m1": 10.0, "m2": 12.0, "m3": 14.0})
    mapping = pl.DataFrame({"okres": ["CZ0100"], "station": ["s1"]})
    later = NOW + timedelta(hours=gusts.MAX_RUN_AGE_H)
    assert gusts.okres_gusts(frame, mapping, PLAIN, later).is_empty()
    assert gusts.okres_gusts(None, mapping, PLAIN, NOW).is_empty()
    # the newest run counts, an older one is ignored
    older = single_run({"m1": 1.0, "m2": 1.0, "m3": 1.0}, run=RUN - timedelta(hours=6))
    table = gusts.okres_gusts(pl.concat([older, frame]), mapping, PLAIN, NOW)
    assert (table["gust"] == 12.0).all()


def test_okres_stations_lowland_and_not_far_above_the_point():
    stations = pl.DataFrame(
        {
            "id": ["low", "summit", "ridge", "other"],
            "lat": [50.0, 50.01, 50.02, 49.9],
            "lon": [14.0, 14.01, 14.02, 14.1],
            "elevation": [300.0, 1300.0, 700.0, 250.0],
            "okres_code": ["A", "A", "A", "C"],
        }
    )
    points = pl.DataFrame(
        {"code": ["A", "B", "D"], "lat": [50.0, 50.05, 52.0], "lon": [14.0, 14.05, 16.0]}
    )
    elevations = pl.DataFrame({"code": ["A", "B", "D"], "elevation": [350.0, 300.0, 300.0]})
    mapping = gusts.okres_stations(stations, points, elevations)
    assert sorted(mapping.filter(pl.col("okres") == "A")["station"]) == ["low"]  # 700 m: > +300
    # B has no station of its own: the nearest lowland one within FALLBACK_KM
    assert mapping.filter(pl.col("okres") == "B")["station"].to_list() == ["low"]
    assert mapping.filter(pl.col("okres") == "D").is_empty()


def test_observed_parts_and_pairs():
    frame = single_run({"m1": 10.0, "m2": 12.0, "m3": 14.0})
    times = [datetime(2026, 10, 16, 0, tzinfo=UTC) + timedelta(hours=h) for h in range(1, 25)]
    obs = pl.DataFrame(
        {
            "station_id": "s1",
            "time": times,
            "variable": "wind_gusts_10m",
            "value": [float(h) for h in range(1, 25)],
        },
        schema_overrides={"time": pl.Datetime("us", "UTC")},
    )
    observed = gusts.observed_parts(obs, ["s1"])
    # morning 16 Oct = 04-10 UTC: the hours ending 05..10 UTC
    morning = observed.filter(pl.col("day") == date(2026, 10, 16), pl.col("part") == "morning")
    assert morning["observed"][0] == 10.0
    # the night of the 16th has only the hours ending 01..04 UTC: too few
    assert observed.filter(pl.col("part") == "night").is_empty()
    pairs = gusts.pairs(frame, obs, ["s1"])
    assert set(pairs.columns) == {"station", "day", "part", "lead_day", "forecast", "observed"}
    assert pairs.filter(pl.col("part") == "morning")["forecast"][0] == 12.0
    assert gusts.pairs(None, obs, ["s1"]) is None


def gust_pairs(days=40, a=1.0, b=1.0):
    rng = np.random.default_rng(1)
    first = date(2026, 9, 1)
    rows = []
    for d in range(days):
        for station in ("s1", "s2"):
            for part in gusts.PARTS:
                f = float(rng.uniform(2, 15))
                rows.append((station, first + timedelta(days=d), part, 1, f, a + b * f))
    return pl.DataFrame(
        rows, schema=["station", "day", "part", "lead_day", "forecast", "observed"], orient="row"
    )


def test_the_part_fit_checks_itself_against_the_plain_mean():
    previous = scg.load()
    pairs = gust_pairs(a=1.5, b=1.0)
    doc = scg.fit(previous, date(2026, 10, 11), gust_part=pairs)
    entry = doc["gust_part"]
    assert entry["source"] == "observations"
    assert entry["default"]["a"] == pytest.approx(1.5, abs=1e-6)
    assert entry["check"]["corrected_mae"] < entry["check"]["raw_mae"]
    assert entry["apply"] is True
    # observations equal to the plain mean plus noise: the correction cannot beat it
    noisy = pairs.with_columns(
        (pl.col("forecast") + pl.Series(np.random.default_rng(2).normal(0, 2, pairs.height))).alias(
            "observed"
        )
    )
    shifted = noisy.with_columns(
        pl.when(pl.col("day") >= date(2026, 10, 1))
        .then(pl.col("observed") - 3)
        .otherwise(pl.col("observed") + 3)
        .alias("observed")
    )
    entry = scg.fit(previous, date(2026, 10, 11), gust_part=shifted)["gust_part"]
    assert entry["apply"] is False
    # too few days for the check: the previous decision stays
    short = scg.fit(previous, date(2026, 10, 11), gust_part=gust_pairs(days=25))["gust_part"]
    assert short["check"] is None and short["apply"] is previous["gust_part"]["apply"]


def test_older_coefficients_get_the_part_fit_from_the_bootstrap(tmp_path):
    old = {k: v for k, v in scg.load().items() if k != "gust_part"}
    path = tmp_path / "old.json"
    path.write_text(json.dumps(old), "utf-8")
    doc = scg.load(path)
    assert doc["gust_part"]["source"] == "bootstrap"
    # off until the nightly check on the single runs shows it beats the plain mean
    assert doc["gust_part"]["apply"] is False
    assert doc["gust_part"]["check"]["corrected_mae"] < doc["gust_part"]["check"]["raw_mae"]


def test_unreadable_runs_leave_the_outlook_gusts_empty(tmp_path):
    bad = tmp_path / "bad.parquet"
    bad.write_bytes(b"not parquet")
    table = pl.DataFrame({"okres": ["CZ0100"], "day": [date(2026, 10, 17)], "part": ["morning"]})
    points = pl.DataFrame({"code": ["CZ0100"], "lat": [50.07], "lon": [14.47]})
    out = outlook.add_gusts(table, pl.scan_parquet(bad), points, PLAIN, NOW)
    assert out["gust"].to_list() == [None] and out["gust_warning"].to_list() == [None]


def test_a_gust_is_never_below_the_wind(monkeypatch):
    table = pl.DataFrame(
        {
            "okres": ["CZ0100", "CZ0100"],
            "day": [date(2026, 10, 17)] * 2,
            "part": ["night", "morning"],
            "wind": [2.2, 14.0],
        }
    )
    values = pl.DataFrame(
        {
            "okres": ["CZ0100", "CZ0100"],
            "day": [date(2026, 10, 17)] * 2,
            "part": ["night", "morning"],
            "gust": [1.9, 12.0],
            "gust_warning": [False, False],
        }
    )
    monkeypatch.setattr(gusts, "okres_gusts", lambda *args: values)
    points = pl.DataFrame({"code": ["CZ0100"], "lat": [50.07], "lon": [14.47]})
    out = outlook.add_gusts(table, None, points, PLAIN, NOW)
    assert out["gust"].to_list() == [2.2, 14.0]
    # the raised gust reaches the warning
    assert out["gust_warning"].to_list() == [False, True]
