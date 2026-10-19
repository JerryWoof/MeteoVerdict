from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from meteoverdict import obce_loso, scoring
from meteoverdict.forecasts import SCHEMA as FC_SCHEMA
from meteoverdict.models import load_models
from meteoverdict.observations import SCHEMA as OBS_SCHEMA

BIASED, GOOD, NOISY = "ecmwf_ifs", "ncep_gfs_global", "ecmwf_ifs025"
MODELS = [m for m in load_models() if m.id in (BIASED, GOOD, NOISY)]
#: five stations in okres Benešov (CZ0201), a few km apart; "t" is the target
STATIONS = pl.DataFrame(
    {
        "id": ["t", "a", "b", "c", "d"],
        "name": ["Target", "A", "B", "C", "D"],
        "lat": [49.78, 49.80, 49.76, 49.70, 49.83],
        "lon": [14.69, 14.72, 14.60, 14.80, 14.85],
        "elevation": [400.0, 380.0, 420.0, 450.0, 360.0],
        "okres_code": ["CZ0201"] * 5,
        "okres": ["Benešov"] * 5,
        "kraj_code": ["CZ020"] * 5,
        "kraj": ["Středočeský kraj"] * 5,
        "elevation_class": ["upland"] * 5,
    }
)
FIRST = date(2026, 9, 1)
DAYS = 24
#: the target is this much warmer than the models say, the other stations are not
TARGET_OFFSET = 3.0


def _data(target_offset: float = TARGET_OFFSET):
    """Observations (10 °C, more at the target; 2 m/s; dry) and D+1, D+2 forecasts of
    three models: one 2 °C too warm and wet, one good (±0.5), one noisy (±2)."""
    rng = np.random.default_rng(1)
    start = datetime(FIRST.year, FIRST.month, FIRST.day, tzinfo=UTC)
    times = [start + timedelta(hours=h) for h in range(24 * DAYS + 1)]
    obs, fc = [], []
    for s in STATIONS["id"]:
        offset = target_offset if s == "t" else 0.0
        for t in times:
            obs += [
                (s, t, "temperature_2m", 10.0 + offset, 0, "recent"),
                (s, t, "wind_speed_10m", 2.0, 0, "recent"),
                (s, t, "precipitation", 0.0, 0, "recent"),
            ]
            for lead in (1, 2):
                for model, error, rain in (
                    (BIASED, 2.0, 1.0),
                    (GOOD, 0.5 * rng.choice([-1, 1]), 0.0),
                    (NOISY, 2.0 * rng.choice([-1, 1]), 0.0),
                ):
                    fc.append((s, t, model, lead, 10.0 + error, rain, 2.0 + error / 4))
    return (
        pl.DataFrame(obs, schema=OBS_SCHEMA, orient="row"),
        pl.DataFrame(fc, schema=FC_SCHEMA, orient="row"),
    )


def test_block_bootstrap_keeps_runs_of_consecutive_days():
    index = obce_loso.block_bootstrap(10, 4, 50, np.random.default_rng(0))
    assert index.shape == (50, 10)
    assert index.min() >= 0 and index.max() <= 9
    # inside a block the days follow each other (wrapping round at the end)
    for row in index:
        for block in range(0, 8, 4):
            run = row[block : block + 4]
            assert all((run[i + 1] - run[i]) % 10 == 1 for i in range(3))
    # one block longer than the period: the whole period, from a random start
    assert sorted(obce_loso.block_bootstrap(3, 5, 1, np.random.default_rng(0))[0]) == [0, 1, 2]


def test_removal_sets_and_batches():
    targets = ["t", "a"]
    assert obce_loso.removal_sets(STATIONS, targets, None) == {"t": {"t"}, "a": {"a"}}
    near = obce_loso.removal_sets(STATIONS, ["t"], 5.0)["t"]
    assert near == {"t", "a"}  # a is about 3 km away, the others further
    okres_of = dict(STATIONS.select("id", "okres_code").iter_rows())
    zone = obce_loso.zones(STATIONS)
    assert set(STATIONS["id"]) <= zone["CZ0201"]
    removed = obce_loso.removal_sets(STATIONS, targets, None)
    # two targets of one okres are never held out together
    assert obce_loso.batches(targets, okres_of, removed, zone) == [["t"], ["a"]]


def test_nearest_station_is_not_held_out():
    available = pl.DataFrame({"variable": ["temperature_2m"] * 5, "station_id": STATIONS["id"]})
    removed = obce_loso.removal_sets(STATIONS, ["t"], 5.0)
    got = obce_loso.nearest_stations(STATIONS, available, ["t"], removed)
    assert got.rows() == [("t", "temperature_2m", "b")]
    got = obce_loso.nearest_stations(STATIONS, available, ["t"], {"t": {"t"}})
    assert got.rows() == [("t", "temperature_2m", "a")]


def test_height_class():
    frame = pl.DataFrame({"dz": [10.0, -200.0, 600.0]})
    assert frame.select(obce_loso.height_class(pl.col("dz")).alias("c"))["c"].to_list() == [
        "within 150 m",
        "150-400 m",
        "over 400 m",
    ]


def _scored(target_offset: float, regression: bool) -> pl.DataFrame:
    obs, fc = _data(target_offset)
    last = FIRST + timedelta(days=DAYS - 1)
    scores = scoring.daily_scores(obs, fc, MODELS, FIRST, last)
    return obce_loso.run(
        scores, fc, obs, STATIONS, FIRST, last, "loso", min_training_days=5,
        regression=regression, targets=["t"],
    )  # fmt: skip


def _bias(scored: pl.DataFrame) -> dict[str, float]:
    temperature = scored.filter(pl.col("variable") == "temperature_2m")
    return dict(
        temperature.group_by("model").agg(pl.col("sum_err").sum() / pl.col("n").sum()).rows()
    )


@pytest.mark.parametrize("regression", [False, True])
def test_held_out_station_does_not_train_its_own_forecast(regression):
    scored = _scored(TARGET_OFFSET, regression)
    assert set(scored["model"]) == set(obce_loso.SERIES)
    assert scored["station_id"].unique().to_list() == ["t"]
    # what the target measured never reaches its own forecast: 3 °C more there moves
    # every series' error by exactly -3 (the forecasts are the same)
    bias, plain = _bias(scored), _bias(_scored(0.0, regression))
    for series in obce_loso.SERIES:
        assert bias[series] - plain[series] == pytest.approx(-TARGET_OFFSET, abs=1e-4)
    # the biased model is corrected: the combination beats the plain median
    assert abs(plain[obce_loso.OBEC]) < abs(plain[obce_loso.MEDIAN])
    # every series on the same station-days
    counts = scored.group_by("variable", "lead_day", "model").len()
    assert counts.group_by("variable", "lead_day").agg(pl.col("len").n_unique())["len"].max() == 1

    groups = obce_loso.results({"loso": scored}, STATIONS, block=3, resamples=50)
    at = {c: i for i, c in enumerate(obce_loso.GROUP_COLUMNS)}
    overall = [r for r in groups if r[at["stratum"]] == "all"]
    assert {r[at["lead_day"]] for r in overall} == {"1", "2", "all"}
    row = next(
        r for r in overall
        if r[at["variable"]] == "temperature_2m" and r[at["lead_day"]] == "all"
    )  # fmt: skip
    assert row[at["low_okres"]] <= row[at["diff_okres"]] <= row[at["high_okres"]]
    doc = obce_loso.document({"loso": scored}, groups, STATIONS, datetime(2026, 10, 1, tzinfo=UTC))
    assert doc["stations"]["loso"]["temperature_2m"] == 1
    assert doc["by_station"]["rows"][0][:2] == ["loso", "t"]
    assert obce_loso.summary(groups)
