import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from meteoverdict import rain_calibration as rc

POINTS = pl.DataFrame(
    {
        "code": ["A", "B", "C"],
        "lat": [50.0, 50.2, 49.0],  # A-B ~22 km apart, C ~110 km from both
        "lon": [14.0, 14.0, 14.0],
    }
)
MODELS = ["m1", "m2", "m3", "m4"]


def synthetic(days: int, seed: int = 0) -> tuple[pl.DataFrame, pl.DataFrame]:
    """``totals`` and ``observed`` where rain is likelier the more models are wet."""
    rng = np.random.default_rng(seed)
    totals, observed = [], []
    for d in range(days):
        day = date(2026, 8, 1) + timedelta(days=d)
        for okres in ("A", "B", "C"):
            for part in rc.PARTS:
                signal = rng.gamma(0.4, 2.0)
                observed.append((okres, day, part, float(signal * rng.uniform(0.3, 1.7))))
                for lead in (1, 2):
                    for model in MODELS:
                        value = max(0.0, signal + rng.normal(0, 0.5 * lead))
                        issue = day - timedelta(days=lead)
                        totals.append((okres, issue, day, part, lead, model, value))
    totals = pl.DataFrame(
        totals,
        schema={
            "okres": pl.String, "issue": pl.Date, "day": pl.Date, "part": pl.String,
            "lead": pl.Int8, "model": pl.String, "fc": pl.Float64,
        },
        orient="row",
    )  # fmt: skip
    observed = pl.DataFrame(
        observed,
        schema={"okres": pl.String, "day": pl.Date, "part": pl.String, "obs": pl.Float64},
        orient="row",
    )
    return totals, observed


def test_logistic_regression_is_at_the_penalised_optimum():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(2000, 3))
    y = (rng.uniform(size=2000) < 1 / (1 + np.exp(-(0.5 + x @ [1.0, -2.0, 0.0])))).astype(float)
    intercept, coefficients = rc.fit_logistic(x, y)
    p = rc.predict(intercept, coefficients, x)
    # gradient of sum(log loss) + 0.5 |b|^2 (C = 1, intercept not penalised) is zero
    assert abs(np.sum(p - y)) < 1e-6
    assert np.allclose(x.T @ (p - y) + coefficients, 0, atol=1e-6)
    assert coefficients == pytest.approx([1.0, -2.0, 0.0], abs=0.25)
    # sample weights of 2 are the same as every case twice
    twice = rc.fit_logistic(np.vstack([x, x]), np.r_[y, y])
    weighted = rc.fit_logistic(x, y, np.full(2000, 2.0))
    assert twice[0] == pytest.approx(weighted[0]) and np.allclose(twice[1], weighted[1])


def test_neighbours_within_40_km_and_itself():
    pairs = rc.neighbours(POINTS)
    by = {k: sorted(v) for k, v in pairs.group_by("okres").agg("nbr").iter_rows()}
    assert by == {"A": ["A", "B"], "B": ["A", "B"], "C": ["C"]}


def test_features_of_one_case():
    totals = pl.DataFrame(
        {
            "okres": ["A"] * 4 + ["B"] * 2,
            "day": [date(2026, 9, 1)] * 6,
            "part": ["night"] * 6,
            "lead": pl.Series([1] * 6, dtype=pl.Int8),
            "model": ["m1", "m2", "m3", "m4", "m1", "m2"],
            "fc": [0.0, 0.2, 1.5, 6.0, 9.0, 0.0],
        }
    )
    weights = pl.DataFrame(
        {"lead": [1, 1], "model": ["m1", "m4"], "weight": [3.0, 0.5]},
        schema={"lead": pl.Int8, "model": pl.String, "weight": pl.Float64},
    )
    a = rc.features(totals, rc.neighbours(POINTS), weights).filter(pl.col("okres") == "A")
    row = a.row(0, named=True)
    assert row["n_models"] == 4
    assert row["share"] == 0.75 and row["share1"] == 0.5 and row["share5"] == 0.25
    assert row["mean"] == pytest.approx(7.7 / 4) and row["max"] == 6.0
    # m1 dry weighs 3, m2 and m3 wet 1 each (no weight), m4 wet 0.5
    assert row["wshare"] == pytest.approx(2.5 / 5.5)
    # neighbourhood A+B by model: m1 wet in B only, m2 in A only; largest 9, 0.2, 1.5, 6
    assert row["nb_share"] == pytest.approx((0.5 + 0.5 + 1 + 1) / 4)
    assert row["nb_maxmean"] == pytest.approx((9 + 0.2 + 1.5 + 6) / 4)


def test_six_hour_totals_from_station_hours():
    stations = pl.DataFrame({"id": ["s1", "s2"], "okres_code": ["A", "A"]})
    # 06-12 Prague time on 2 September = the hours ending 05..10 UTC
    times = [datetime(2026, 9, 2, h, tzinfo=UTC) for h in range(5, 11)]
    fc = pl.DataFrame(
        {
            "station_id": ["s1"] * 6 + ["s2"] * 6 + ["s2"],
            "time": times * 2 + [datetime(2026, 9, 2, 11, tzinfo=UTC)],
            "model": "m1",
            "lead_day": pl.Series([2] * 13, dtype=pl.Int8),
            "precipitation": [0.5] * 6 + [1.0] * 6 + [9.0],
        }
    )
    out = rc.six_hour_forecasts(fc, stations, date(2026, 9, 1), date(2026, 9, 3))
    morning = out.filter(pl.col("part") == "morning")
    assert morning.select("okres", "issue", "day", "lead", "fc").row(0) == (
        "A", date(2026, 8, 31), date(2026, 9, 2), 2, pytest.approx(4.5),
    )  # fmt: skip
    # the afternoon has one hour only: left out
    assert out.filter(pl.col("part") == "afternoon").is_empty()
    obs = pl.DataFrame(
        {
            "station_id": ["s1"] * 6 + ["s2"] * 5,
            "time": times + times[:5],
            "variable": "precipitation",
            "value": [1.0] * 11,
        }
    )
    seen = rc.six_hour_observations(obs, stations, date(2026, 9, 1), date(2026, 9, 3))
    # s2 misses an hour: only s1 counts
    assert seen.select("okres", "day", "part", "obs", "stations").rows() == [
        ("A", date(2026, 9, 2), "morning", 6.0, 1)
    ]


def test_fit_needs_enough_days_and_improves_on_the_share(tmp_path):
    totals, observed = synthetic(40)
    nbrs = rc.neighbours(POINTS)
    assert rc.fit(totals.filter(pl.col("day") < date(2026, 8, 20)), observed, nbrs) is None
    cal = rc.fit(totals, observed, nbrs, generated=datetime(2026, 9, 10, 4, tzinfo=UTC))
    assert cal is not None and cal.days == 40 and cal.cases == totals.height // 4
    assert cal.info["brier"] < cal.info["brier_share"]
    assert set(cal.weights) == {1, 2} and set(cal.weights[1]) == set(MODELS)
    assert np.mean(list(cal.weights[1].values())) == pytest.approx(1.0)
    assert cal.heavy_coefficients is not None and 0.02 <= cal.heavy_flag_at <= 0.6

    path = rc.write(cal, tmp_path / rc.FILE)
    doc = json.loads(path.read_text())
    assert doc["features"] == list(rc.FEATURES) and doc["to"] == "2026-09-09"
    loaded = rc.load(path, today=date(2026, 9, 12))
    assert loaded.coefficients == cal.coefficients and loaded.weights == cal.weights
    # too old, another version, missing: the outlook keeps the raw share
    assert rc.load(path, today=date(2026, 9, 9) + timedelta(days=rc.MAX_AGE_DAYS + 1)) is None
    path.write_text(json.dumps({**doc, "version": 99}))
    assert rc.load(path, today=date(2026, 9, 12)) is None
    assert rc.load(tmp_path / "missing.json") is None


def test_apply_blends_and_falls_back_to_the_share():
    totals, observed = synthetic(40)
    nbrs = rc.neighbours(POINTS)
    cal = rc.fit(totals, observed, nbrs)
    case = totals.filter(pl.col("day") == date(2026, 9, 1), pl.col("lead") == 1).drop("issue")
    raw = rc.apply(case, None, None)
    assert raw["rain_probability"].to_list() == raw["model_share"].to_list()
    assert raw["heavy_rain"].null_count() == raw.height and not raw["calibrated"].any()

    out = rc.apply(case, cal, nbrs).sort("okres", "part")
    feats = rc.features(case, nbrs, cal.weight_frame()).sort("okres", "part")
    fitted = rc.predict(cal.intercept, np.array(cal.coefficients), rc.design(feats))
    expected = rc.BLEND * fitted + (1 - rc.BLEND) * feats["share"].to_numpy()
    assert np.allclose(out["rain_probability"].to_numpy(), expected)
    assert out["calibrated"].all() and out["heavy_rain"].null_count() == 0
    assert out["heavy_rain_probability"].is_between(0, 1).all()

    # fewer than MIN_MODELS models: the raw share, no heavy-rain probability
    few = case.filter(pl.col("model").is_in(["m1", "m2"]))
    out = rc.apply(few, cal, nbrs)
    assert out["rain_probability"].to_list() == out["model_share"].to_list()
    assert not out["calibrated"].any() and out["heavy_rain_probability"].null_count() == out.height


def test_flag_threshold_maximises_ets():
    p = np.array([0.05, 0.1, 0.3, 0.4, 0.5, 0.9])
    event = np.array([False, False, False, True, True, True])
    at, best = rc.flag_threshold(p, event)
    assert at == pytest.approx(0.31) and best == pytest.approx(1.0)
