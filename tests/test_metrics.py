import math

import polars as pl
import pytest

from meteoverdict import metrics


def scored(forecast, observed, groups=None) -> pl.DataFrame:
    frame = pl.DataFrame(
        {"forecast": forecast, "observed": observed, "g": groups or [0] * len(forecast)}
    )
    return metrics.continuous_scores(frame.group_by("g").agg(metrics.error_sums()).sort("g"))


def test_continuous_metrics_by_hand():
    # errors -1, 0, -2: MAE 1, bias -1, RMSE sqrt(5/3)
    row = scored([1.0, 2.0, 3.0], [2.0, 2.0, 5.0]).row(0, named=True)
    assert row["n"] == 3
    assert row["mae"] == pytest.approx(1.0)
    assert row["bias"] == pytest.approx(-1.0)
    assert row["rmse"] == pytest.approx(math.sqrt(5 / 3))


def test_missing_values_are_not_counted():
    row = scored([1.0, None, 3.0], [2.0, 2.0, None]).row(0, named=True)
    assert row["n"] == 1 and row["mae"] == pytest.approx(1.0)


def test_sums_are_additive():
    forecast, observed = [1.0, 4.0, 2.0, 8.0, 0.5], [2.0, 3.0, 2.0, 5.0, 0.0]
    parts = scored(forecast, observed, groups=[0, 0, 1, 1, 1])
    combined = metrics.continuous_scores(parts.select(metrics.SUMS).sum())
    whole = scored(forecast, observed)
    for column in ("n", "mae", "bias", "rmse"):
        assert combined[column][0] == pytest.approx(whole[column][0])


def test_empty_group_has_null_metrics():
    empty = pl.DataFrame({"n": [0], "sum_err": [0.0], "sum_abs_err": [0.0], "sum_sq_err": [0.0]})
    row = metrics.continuous_scores(empty).row(0, named=True)
    assert row["mae"] is None and row["bias"] is None and row["rmse"] is None


def counts(a, b, c, d, threshold=5.0) -> pl.DataFrame:
    return pl.DataFrame(
        dict(zip(metrics.counts_columns(threshold), [[a], [b], [c], [d]], strict=True))
    )


def test_finley_tornado_forecasts():
    # Finley (1884), the classic verification example: ETS (Gilbert skill score) = 0.216
    row = metrics.categorical_scores(counts(28, 72, 23, 2680), 5.0).row(0, named=True)
    assert row["pod_5"] == pytest.approx(28 / 51)
    assert row["far_5"] == pytest.approx(0.72)
    assert row["ets_5"] == pytest.approx(0.216, abs=5e-4)


def test_perfect_and_no_event_cases():
    perfect = metrics.categorical_scores(counts(10, 0, 0, 90), 5.0).row(0, named=True)
    assert (perfect["pod_5"], perfect["far_5"]) == (1.0, 0.0)
    assert perfect["ets_5"] == pytest.approx(1.0)
    quiet = metrics.categorical_scores(counts(0, 0, 0, 30), 5.0).row(0, named=True)
    assert quiet["pod_5"] is None and quiet["far_5"] is None and quiet["ets_5"] is None


def test_contingency_counts_from_values():
    frame = pl.DataFrame(
        {
            "forecast": [0.0, 0.1, 6.0, 4.9, 5.0, 0.0],
            "observed": [0.0, 0.0, 7.0, 5.0, 1.0, 0.2],
        }
    )
    got = frame.select(metrics.contingency_counts(5.0) + metrics.contingency_counts(0.1))
    # >= 5 mm: hit (6/7), miss (4.9/5.0), false alarm (5.0/1.0), 3 correct negatives
    assert got.select(metrics.counts_columns(5.0)).row(0) == (1, 1, 1, 3)
    # >= 0.1 mm: hits 6/7, 4.9/5.0, 5.0/1.0; false alarm 0.1/0.0; miss 0.0/0.2; cn 0.0/0.0
    assert got.select(metrics.counts_columns(0.1)).row(0) == (3, 1, 1, 1)


def test_labels():
    assert metrics.label(0.1) == "0p1" and metrics.label(5.0) == "5"
    assert metrics.counts_columns(0.1) == ["a_0p1", "b_0p1", "c_0p1", "d_0p1"]
