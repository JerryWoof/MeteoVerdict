from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from meteoverdict import ranking

STATIONS = pl.DataFrame(
    {
        "id": ["s1", "s2", "s3"],
        "name": ["One", "Two", "Three"],
        "okres_code": ["CZ0201"] * 3,
        "okres": ["Benešov"] * 3,
        "kraj_code": ["CZ020"] * 3,
        "kraj": ["Středočeský kraj"] * 3,
        "elevation_class": ["lowland"] * 3,
    }
)
DAY = date(2026, 9, 30)


def scores(errors: dict[str, list[float]], variable="temperature_2m", stations=("s1",)):
    """errors: model -> mean absolute error per day (one value per day, n = 24)."""
    rows = []
    for model, per_day in errors.items():
        for i, err in enumerate(per_day):
            for station in stations:
                rows.append(
                    {
                        "date": DAY - timedelta(days=len(per_day) - 1 - i),
                        "station_id": station,
                        "model": model,
                        "lead_day": 1,
                        "variable": variable,
                        "n": 24,
                        "sum_err": err * 24,
                        "sum_abs_err": err * 24,
                        "sum_sq_err": err * err * 24,
                    }
                )
    return pl.DataFrame(rows)


def cz(table):
    return table.filter(pl.col("level") == "cz", pl.col("window") == "all")


def test_bootstrap_separates_clearly_different_models():
    rng = np.random.default_rng(1)
    abs_err = np.column_stack([np.full(30, 1.0), np.full(30, 3.0)]) * 24
    n = np.full((30, 2), 24.0)
    order, diff, bounds = ranking.bootstrap_group(abs_err, n, rng, resamples=200)
    assert list(order) == [0, 1]
    assert diff[1] == pytest.approx(2.0)
    assert bounds[0][1] == pytest.approx(2.0) and bounds[1][1] == pytest.approx(2.0)


def test_clear_winner_when_the_gap_is_consistent():
    rng = np.random.default_rng(2)
    a = list(1.0 + rng.normal(0, 0.1, 40))
    b = [x + 0.5 for x in a]
    table = cz(ranking.rank(scores({"a": a, "b": b}), STATIONS, windows=("all",), resamples=300))
    assert table.select("model", "rank", "tied_with_best", "clear_winner").rows() == [
        ("a", 1, False, True),
        ("b", 2, False, False),
    ]


def test_tie_when_the_difference_is_noise():
    rng = np.random.default_rng(3)
    a = list(rng.uniform(0.5, 2.5, 20))
    b = list(rng.uniform(0.5, 2.5, 20))
    table = cz(ranking.rank(scores({"a": a, "b": b}), STATIONS, windows=("all",), resamples=300))
    assert table["tied_with_best"].to_list() == [False, True]
    assert table["clear_winner"].to_list() == [False, False]
    low, high = table.filter(pl.col("rank") == 2).select("diff_ci_low", "diff_ci_high").row(0)
    assert low <= 0 <= high


def test_days_are_resampled_together_across_stations():
    # every station has the same daily errors: three stations add no new information,
    # so the interval must be as wide as with one station
    rng = np.random.default_rng(4)
    a, b = list(rng.uniform(0, 2, 15)), list(rng.uniform(0, 2, 15))
    one = cz(ranking.rank(scores({"a": a, "b": b}), STATIONS, windows=("all",), seed=7))
    three = cz(
        ranking.rank(
            scores({"a": a, "b": b}, stations=("s1", "s2", "s3")),
            STATIONS,
            windows=("all",),
            seed=7,
        )
    )

    def width(t):
        rank2 = t.filter(pl.col("rank") == 2)
        return rank2.select(pl.col("diff_ci_high") - pl.col("diff_ci_low")).item()

    assert width(three) == pytest.approx(width(one))


def test_single_model_is_not_a_winner_and_results_are_reproducible():
    table = cz(ranking.rank(scores({"a": [1.0, 2.0]}), STATIONS, windows=("all",)))
    assert table.select("rank", "clear_winner").rows() == [(1, False)]
    data = scores({"a": [1.0, 1.5, 0.7], "b": [1.2, 1.1, 0.9]})
    assert ranking.rank(data, STATIONS, seed=5).equals(ranking.rank(data, STATIONS, seed=5))


def test_hourly_precipitation_is_not_ranked():
    data = pl.concat(
        [
            scores({"a": [1.0, 2.0], "b": [2.0, 3.0]}),
            scores({"a": [1.0, 2.0], "b": [2.0, 3.0]}, variable="precipitation"),
        ]
    )
    assert set(ranking.rank(data, STATIONS)["variable"]) == {"temperature_2m"}


def test_both_daily_precipitation_totals_are_ranked():
    data = pl.concat(
        [
            scores({"a": [1.0, 2.0], "b": [2.0, 3.0]}, variable=variable)
            for variable in ("precipitation_daily", "precipitation_24h")
        ]
    )
    assert set(ranking.rank(data, STATIONS)["variable"]) == {
        "precipitation_daily",
        "precipitation_24h",
    }
