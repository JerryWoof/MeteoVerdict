from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from meteoverdict import mos

STATIONS = pl.DataFrame(
    {
        "id": ["low", "mid", "high", "other"],
        "elevation": [200.0, 400.0, 600.0, 300.0],
        "okres_code": ["CZ0201", "CZ0201", "CZ0201", "CZ0202"],
        "okres": ["Benešov", "Benešov", "Benešov", "Beroun"],
    }
)
FIRST = date(2026, 8, 1)


def synthetic_pairs(days=40, seed=0, models=("a", "b", "c"), lead=1, drop=None):
    """Temperature pairs: model a is 1 °C too warm at 00 UTC and 3 °C at 12 UTC, plus
    0.5 °C per 100 m above the okres mean; b has no bias but more noise; c is noise."""
    rng = np.random.default_rng(seed)
    mean = {"CZ0201": 400.0, "CZ0202": 300.0}
    okres = dict(zip(STATIONS["id"], STATIONS["okres_code"], strict=True))
    elevation = dict(zip(STATIONS["id"], STATIONS["elevation"], strict=True))
    rows = []
    for d in range(days):
        day = FIRST + timedelta(days=d)
        for station in STATIONS["id"]:
            dz = (elevation[station] - mean[okres[station]]) / 100
            for slot in range(4):
                truth = 10 + 5 * np.sin(slot) + rng.normal(0, 2)
                bias_a = [1.0, 2.0, 3.0, 2.0][slot] + 0.5 * dz
                forecast = {
                    "a": truth + bias_a + rng.normal(0, 0.3),
                    "b": truth + rng.normal(0, 1.0),
                    "c": truth + rng.normal(0, 3.0),
                }
                for m in models:
                    if drop and drop(m, d):
                        continue
                    rows.append(("temperature_2m", station, day, slot, lead, m, forecast[m], truth))
    schema = {
        "variable": pl.String, "station_id": pl.String, "date": pl.Date, "slot": pl.Int8,
        "lead_day": pl.Int8, "model": pl.String, "forecast": pl.Float64, "observed": pl.Float64,
    }  # fmt: skip
    return pl.DataFrame(rows, schema=schema, orient="row")


def table_of(pairs):
    return mos.tables(pairs, mos.own_okres(STATIONS), STATIONS)[("temperature_2m", 1)]


def test_solve_keeps_the_weights_summing_to_one():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(200, 3))
    y = x @ np.array([0.2, 0.5, 0.6]) + rng.normal(0, 0.1, 200)
    w = mos.solve(x, y, np.full(3, 1 / 3), 0.0)
    assert w.sum() == pytest.approx(1.0)
    # a very strong ridge keeps the prior
    assert mos.solve(x, y, np.array([0.5, 0.25, 0.25]), 1e9) == pytest.approx([0.5, 0.25, 0.25])


def test_fit_learns_the_hour_of_day_and_elevation_bias():
    t = table_of(synthetic_pairs())
    assert t.okresy == ["CZ0201", "CZ0202"]
    assert t.elevation.tolist() == [400.0, 300.0]
    f = mos.fit(t, mos.day_number(FIRST + timedelta(days=39)))
    assert f is not None and f.models == ["a", "b", "c"] and f.days == 40
    a = f.models.index("a")
    benesov = f.okresy.index("CZ0201")
    # slot biases of a, shrunk 10 days towards its all-hours bias of 2
    expected = [(40 * b + 10 * 2.0) / 50 for b in (1.0, 2.0, 3.0, 2.0)]
    assert f.bias[benesov, :, a] == pytest.approx(expected, abs=0.15)
    assert f.lapse[benesov, :, a] == pytest.approx([0.5] * 4, abs=0.1)
    assert f.lapse[benesov, :, f.models.index("b")] == pytest.approx([0.0] * 4, abs=0.15)
    assert f.weights.sum(1) == pytest.approx([1.0, 1.0])
    # the noisy model gets little weight once a is corrected
    assert f.weights[benesov, f.models.index("c")] < 0.15
    # the combination beats every model on the training days (once corrected)
    rows = np.arange(t.size)
    p = f.predict(t.forecast, t.okres[rows], t.slot[rows], t.dz[rows])
    assert np.abs(p - t.observed).mean() < np.abs(t.forecast[:, 1] - t.observed).mean()


def test_fit_uses_only_the_window_and_needs_enough_days():
    t = table_of(synthetic_pairs(days=20))
    assert mos.fit(t, mos.day_number(FIRST + timedelta(days=12))) is None  # 13 days
    f = mos.fit(t, mos.day_number(FIRST + timedelta(days=19)), window=15)
    assert f.days == 15
    assert mos.fit(t, mos.day_number(FIRST + timedelta(days=19)), min_days=21) is None


def test_fit_leaves_out_models_with_few_values():
    # c starts after 15 of 40 days: covers 62 % of the rows < MIN_COVERAGE
    t = table_of(synthetic_pairs(drop=lambda m, d: m == "c" and d < 15))
    f = mos.fit(t, mos.day_number(FIRST + timedelta(days=39)))
    assert f.models == ["a", "b"]
    assert mos.fit(t, mos.day_number(FIRST + timedelta(days=39)), allowed={"a"}) is None


def test_frame_has_the_shrunk_coefficients():
    t = table_of(synthetic_pairs())
    f = mos.fit(t, mos.day_number(FIRST + timedelta(days=39)))
    frame = f.frame()
    assert frame.columns == ["region", "variable", "lead_day", "model", *mos.COEFFICIENT_COLUMNS]
    assert frame.height == 2 * 3
    row = frame.filter(pl.col("region") == "CZ0201", pl.col("model") == "a").row(0, named=True)
    shrink = 40 / 45
    assert row["bias_12"] == pytest.approx(shrink * f.bias[0, 2, 0])
    assert row["lapse_00"] == pytest.approx(shrink * f.lapse[0, 0, 0])
    assert row["station_elevation"] == 400.0 and row["mos_models"] == 3
    assert (row["dz_min"], row["dz_max"]) == (-2.0, 2.0)
    total = frame.group_by("region").agg(pl.col("mos_weight").sum())["mos_weight"]
    assert total.to_list() == pytest.approx([1.0, 1.0])


def test_coefficients_for_several_days():
    pairs = synthetic_pairs()
    days = [FIRST + timedelta(days=20), FIRST + timedelta(days=39)]
    out = mos.coefficients(pairs, mos.own_okres(STATIONS), STATIONS, days)
    assert out["as_of"].unique().sort().to_list() == days
    assert out.filter(pl.col("as_of") == days[0])["mos_days"].unique().to_list() == [21]
    allowed = pl.DataFrame(
        {"variable": ["temperature_2m"] * 2, "lead_day": [1, 1], "model": ["a", "b"]}
    ).cast({"lead_day": pl.Int8})
    only = mos.coefficients(pairs, mos.own_okres(STATIONS), STATIONS, days, allowed=allowed)
    assert set(only["model"]) == {"a", "b"}


def test_pairs_are_at_the_synoptic_hours():
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    times = [t0 + timedelta(hours=h) for h in (0, 3, 6)]
    fc = pl.DataFrame(
        {
            "station_id": "low",
            "time": times,
            "model": ["a", "a", "blend"],
            "lead_day": pl.Series([1, 1, 1], dtype=pl.Int8),
            "temperature_2m": [10.0, 11.0, 12.0],
            "wind_speed_10m": [3.0, None, 4.0],
            "precipitation": [0.0, 0.0, 0.0],
        }
    )
    obs = pl.DataFrame(
        {
            "station_id": "low",
            "time": [t0, t0, t0 + timedelta(hours=3), t0 + timedelta(hours=6)],
            "variable": ["temperature_2m", "wind_speed_10m", "temperature_2m", "temperature_2m"],
            "value": [9.0, 2.5, 10.0, 11.0],
        }
    )
    out = mos.pairs(obs, fc, date(2026, 9, 1), date(2026, 9, 1)).sort("variable")
    assert out.select("variable", "slot", "model", "forecast", "observed").rows() == [
        ("temperature_2m", 0, "a", 10.0, 9.0),
        ("wind_speed_10m", 0, "a", 3.0, 2.5),
    ]


def test_inverse_error_is_the_method_before():
    x = np.array([[11.0, 10.0], [13.0, 12.5], [12.0, 9.0], [10.0, 11.0]])
    y = np.array([10.0, 12.0, 10.0, 10.0])
    w, c = mos.inverse_error(x, y, np.array([0, 0, 0, 0]), 1, days=30)
    bias = (x - y[:, None]).mean(0)
    assert c[0] == pytest.approx(30 / 35 * bias)
    assert w.sum() == pytest.approx(1.0)
    variance = ((x - y[:, None]) ** 2).mean(0) - bias**2
    inv = 1 / variance
    assert w[0] == pytest.approx(0.5 * inv / inv.sum() + 0.25)


def test_the_wind_guard_falls_back_where_the_regression_did_worse():
    pairs = synthetic_pairs().with_columns(pl.lit("wind_speed_10m").alias("variable"))
    t = mos.tables(pairs, mos.own_okres(STATIONS), STATIONS)[("wind_speed_10m", 1)]
    end = mos.day_number(FIRST + timedelta(days=39))
    # a clean regression keeps every okres
    assert mos.fit(t, end).fitted.all()
    assert not mos.worse_than_before(t, end, ["a", "b", "c"], 90, 14).any()
    # in Beroun, model a's error flips in the last week: the regression, which trusts
    # a's correction, does worse there than the inverse-error weights
    late = (t.day > end - mos.GUARD_DAYS) & (t.okres == t.okresy.index("CZ0202"))
    a = t.models.index("a")
    t.forecast[late, a] -= 2 * (t.forecast[late, a] - t.observed[late]) + 6
    worse = mos.worse_than_before(t, end, ["a", "b", "c"], 90, 14)
    assert worse.tolist() == [False, True]
    assert mos.fit(t, end).fitted.tolist() == [True, False]
    assert mos.fit(t, end, guard=False).fitted.all()
    # temperature is not guarded
    assert "temperature_2m" not in mos.GUARD_VARIABLES
