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


def test_the_blend_is_compared_with_the_best_model_but_not_ranked():
    data = scores(
        {
            "a": [1.0, 1.1, 0.9, 1.0, 1.2, 1.0],
            "b": [2.0, 2.1, 1.9, 2.0, 2.2, 2.0],
            "blend": [0.5, 0.6, 0.4, 0.5, 0.7, 0.5],
        }
    )
    got = cz(ranking.rank(data, STATIONS, resamples=200))
    assert got.select("model", "rank").rows() == [("a", 1), ("b", 2), ("blend", None)]
    a, mean = got.row(0, named=True), got.row(2, named=True)
    assert a["clear_winner"]  # the blend does not take the win from the best model
    assert mean["diff_to_best"] == pytest.approx(-0.5)
    assert mean["diff_ci_high"] < 0 and not mean["clear_winner"]


def test_a_region_ranks_its_models_on_the_same_stations():
    # model b has no scores at s3 (like ICON-D2 in the far east), where a is much worse
    data = pl.concat(
        [
            scores({"a": [1.0, 1.1, 0.9], "b": [1.2, 1.3, 1.1]}, stations=("s1", "s2")),
            scores({"a": [9.0, 9.0, 9.0]}, stations=("s3",)),
        ]
    )
    got = cz(ranking.rank(data, STATIONS, resamples=100))
    # without s3 for both, a stays ahead; counting s3 for a alone would put b first
    assert got.select("model", "rank").rows() == [("a", 1), ("b", 2)]


def test_a_model_with_a_short_record_is_not_ranked_and_does_not_cut_the_others():
    # a and b on 20 days, c (added recently) on the last 4: a and b are ranked on all
    # 20 days and c is not ranked at all
    errors = {"a": [1.0] * 20, "b": [2.0] * 20}
    rows = scores(errors, stations=("s1", "s2", "s3"))
    new = scores({"c": [0.1] * 4}, stations=("s1", "s2", "s3"))
    table = cz(ranking.rank(pl.concat([rows, new]), STATIONS, resamples=100))
    assert table.select("model", "rank").rows() == [("a", 1), ("b", 2)]
    assert table.filter(pl.col("model") == "a")["clear_winner"].item()


def test_main_and_other_stations_are_ranked_separately():
    # model a is better at the main WMO station, b at the other two
    main = "0-20000-0-11520"
    stations = pl.concat([STATIONS, STATIONS.head(1).with_columns(id=pl.lit(main))])
    days = 20
    table = pl.concat(
        [
            scores({"a": [1.0] * days, "b": [2.0] * days}, stations=(main,)),
            scores({"a": [2.0] * days, "b": [1.0] * days}, stations=("s1", "s2")),
        ]
    )
    ranks = ranking.rank(table, stations, windows=("all",), resamples=200)
    network = ranks.filter(pl.col("level") == "network", pl.col("rank") == 1)
    assert dict(network.select("region", "model").rows()) == {"main": "a", "other": "b"}


def test_block_weights_draw_runs_of_consecutive_days():
    rng = np.random.default_rng(4)
    weights = ranking.block_weights(30, rng, resamples=500)
    assert weights.shape == (500, 30)
    assert (weights.sum(axis=1) == 30).all()
    # circular: the first and last days are drawn about as often as the middle ones
    assert weights[:, 0].mean() == pytest.approx(1.0, abs=0.15)
    assert weights[:, -1].mean() == pytest.approx(1.0, abs=0.15)
    # a resample of 3 days still varies (the block shrinks to 1 day)
    short = ranking.block_weights(3, rng, resamples=200)
    assert (short.sum(axis=1) == 3).all() and len({tuple(r) for r in short}) > 1


def test_blocks_widen_the_interval_when_errors_persist_for_days():
    rng = np.random.default_rng(5)
    days = 90
    # the difference between the models changes with a weather regime of 6 days
    regime = np.repeat(rng.normal(0, 0.5, days // 6), 6)
    a = np.full(days, 1.0) * 24
    b = (1.1 + regime) * 24
    abs_err, n = np.column_stack([a, b]), np.full((days, 2), 24.0)

    def width(block):
        rng = np.random.default_rng(6)
        _, _, bounds = ranking.bootstrap_group(abs_err, n, rng, 2000, block=block)
        return bounds[1][1] - bounds[0][1]

    assert width(4) > 1.3 * width(1)


def test_probability_of_being_best():
    rng = np.random.default_rng(7)
    days = 60
    a = 1.0 + rng.normal(0, 0.05, days)
    abs_err = np.column_stack([a, a + 0.5, a + rng.normal(0, 0.3, days)]) * 24
    n = np.full((days, 3), 24.0)
    ranked = np.array([True, True, False])  # the third is the blend: never "best"
    _, _, _, p_best = ranking.bootstrap_best(abs_err, n, rng, 500, ranked)
    assert p_best[0] == pytest.approx(1.0) and p_best[1] == 0 and p_best[2] == 0
    # two identical models share every resample
    twins = np.column_stack([a, a]) * 24
    _, _, _, p_best = ranking.bootstrap_best(twins, n[:, :2], rng, 100)
    assert list(p_best) == [0.5, 0.5]


def test_diebold_mariano():
    rng = np.random.default_rng(8)
    days = 60
    a = 1.0 + rng.normal(0, 0.2, days)
    n = np.full((days, 3), 24.0)
    abs_err = np.column_stack([a, a + 0.3 + rng.normal(0, 0.1, days), a + 0.5]) * 24
    stat, p = ranking.diebold_mariano(abs_err, n, 0)
    assert np.isnan(stat[0]) and np.isnan(p[0])
    assert stat[1] > 10 and p[1] < 1e-6
    assert stat[2] == np.inf and p[2] == 0  # the same difference every day
    noise = np.column_stack([a, a + rng.normal(0, 0.3, days)]) * 24
    _, p = ranking.diebold_mariano(noise, n[:, :2], 0)
    assert p[1] > 0.05


def test_ranking_publishes_p_best_dm_and_the_small_sample_flag():
    rng = np.random.default_rng(9)
    a = list(1.0 + rng.normal(0, 0.1, 40))
    b = [x + 0.5 for x in a]
    table = cz(ranking.rank(scores({"a": a, "b": b}), STATIONS, windows=("all",), resamples=300))
    rows = table.select("model", "p_best", "dm_p", "small_sample").rows()
    assert rows == [("a", 1.0, None, False), ("b", 0.0, 0.0, False)]
    short = cz(
        ranking.rank(scores({"a": a[:20], "b": b[:20]}), STATIONS, windows=("all",), resamples=50)
    )
    assert short["small_sample"].all()


def test_tied_unless_both_tests_say_worse():
    rng = np.random.default_rng(10)
    a = list(rng.uniform(0.5, 2.5, 40))
    b = [x + 0.05 + rng.normal(0, 0.3) for x in a]
    table = cz(ranking.rank(scores({"a": a, "b": b}), STATIONS, windows=("all",), resamples=300))
    second = table.filter(pl.col("rank") == 2).row(0, named=True)
    assert second["tied_with_best"] and second["dm_p"] > ranking.DM_ALPHA
    assert not table["clear_winner"].any()
