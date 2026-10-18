import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from meteoverdict import aggregate, blendtest, combine, mos, scoring
from meteoverdict.forecasts import SCHEMA as FC_SCHEMA
from meteoverdict.models import load_models
from meteoverdict.observations import SCHEMA as OBS_SCHEMA

MODELS = [m for m in load_models() if m.id in ("ecmwf_ifs", "ncep_gfs_global", "ecmwf_ifs025")]
BIASED, GOOD, NOISY = "ecmwf_ifs", "ncep_gfs_global", "ecmwf_ifs025"
LATE = "dwd_icon"  # a model the backfill delivers the newest days of only
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
FIRST = date(2026, 9, 1)
DAYS = 24


def _data(days=DAYS, change_from=None, late_from=None):
    """Observations (10 °C, 2 m/s, no rain) and D+1 forecasts of three models: one
    2 °C too warm, one good (±0.5), one noisy (±2); from ``change_from`` on the good
    model turns bad; from ``late_from`` on a fourth model (1 °C too cold) has
    forecasts too."""
    rng = np.random.default_rng(1)
    start = datetime(FIRST.year, FIRST.month, FIRST.day, tzinfo=UTC)
    times = [start + timedelta(hours=h) for h in range(24 * days + 1)]
    obs, fc = [], []
    for s in STATIONS["id"]:
        for t in times:
            obs += [
                (s, t, "temperature_2m", 10.0, 0, "recent"),
                (s, t, "wind_speed_10m", 2.0, 0, "recent"),
                (s, t, "precipitation", 0.0, 0, "recent"),
            ]
            good = 0.5 if change_from is None or t.date() < change_from else 4.0
            for model, error in (
                (BIASED, 2.0),
                (GOOD, good * rng.choice([-1, 1])),
                (NOISY, 2.0 * rng.choice([-1, 1])),
            ):
                fc.append((s, t, model, 1, 10.0 + error, 0.1, 2.0 + error / 4))
            if late_from is not None and t.date() >= late_from:
                fc.append((s, t, LATE, 1, 9.0, 0.1, 1.75))
    return (
        pl.DataFrame(obs, schema=OBS_SCHEMA, orient="row"),
        pl.DataFrame(fc, schema=FC_SCHEMA, orient="row"),
    )


def _scores(obs, fc, days=DAYS):
    last = FIRST + timedelta(days=days - 1)
    models = MODELS + [m for m in load_models() if m.id == LATE]
    return scoring.daily_scores(obs, fc, models, FIRST, last)


def test_combine_values_rescales_over_the_models_present_and_clips():
    frame = pl.DataFrame(
        {
            "hour": [1, 1, 1, 2, 2],
            "model": ["a", "b", "c", "a", "b"],
            "precipitation": [1.0, 3.0, None, 0.0, None],
            "weight": [0.25, 0.25, 0.5, 0.5, 0.5],
            "correction": [0.0, 0.0, 0.0, 0.5, 0.0],
        }
    )
    out = dict(combine.combine_values(frame, "precipitation", ["hour"]).sort("hour").rows())
    assert out[1] == pytest.approx(2.0)  # c missing: a and b share its weight
    assert out[2] is None  # one model only (MIN_MODELS = 2)
    frame = frame.with_columns(pl.lit(1.0).alias("precipitation"), pl.lit(2.0).alias("correction"))
    assert combine.combine_values(frame, "precipitation", ["hour"])["precipitation"].min() == 0


def test_windows_of_any_number_of_days():
    assert aggregate.window_start("30d", date(2026, 9, 30), FIRST) == date(2026, 9, 1)
    with pytest.raises(ValueError):
        aggregate.window_start("month", date(2026, 9, 30), FIRST)


def test_training_uses_only_scores_before_the_forecast_was_made():
    obs, fc = _data()
    scores = _scores(obs, fc)
    later = _scores(*_data(change_from=date(2026, 9, 15)))
    as_of = [FIRST + timedelta(days=k) for k in range(DAYS)]
    w1, b1 = blendtest.training(scores, STATIONS, as_of, min_days=5)
    w2, _ = blendtest.training(later, STATIONS, as_of, min_days=5)
    # D+1 for day d is trained on days up to d - 1
    assert (w1["date"] - w1["as_of"]).dt.total_days().unique().to_list() == [1]
    keys = ["date", "variable", "model"]
    both = w1.join(w2, on=keys, suffix="_later")
    gap = (pl.col("weight") - pl.col("weight_later")).abs()
    until = pl.col("date") <= date(2026, 9, 15)
    assert both.filter(until).select(gap.max()).item() < 1e-6  # float32 sums
    assert both.filter(~until).select(gap.max()).item() > 0.01
    # warm-up: first tested day after 5 scored training days
    assert w1["date"].min() == FIRST + timedelta(days=5)
    assert b1.filter(pl.col("variable") == "temperature_2m")["model"].unique().to_list() == [GOOD]


def test_out_of_sample_test_end_to_end():
    obs, fc = _data()
    scores = _scores(obs, fc)
    last = FIRST + timedelta(days=DAYS - 1)
    days, groups, models, info = blendtest.run(
        scores, fc, obs, STATIONS, FIRST, last, min_training_days=5, resamples=200
    )
    at = {c: i for i, c in enumerate(blendtest.GROUP_COLUMNS)}
    rows = {(r[at["level"]], r[at["variable"]]): r for r in groups}
    cz = rows[("cz", "temperature_2m")]
    okres = rows[("okres", "temperature_2m")]
    assert cz[at["days"]] == DAYS - 5 and cz[at["stations"]] == 3
    assert cz[at["best_oos"]] == GOOD and cz[at["best_hindsight"]] == GOOD
    # the good model is chosen every day, so the out-of-sample best is the hindsight best
    assert cz[at["mae_best_oos"]] == pytest.approx(0.5, abs=1e-3)
    assert cz[at["diff_best_hindsight"]] == 0
    assert cz[at["diff_combined"]] == pytest.approx(
        cz[at["mae_combined"]] - cz[at["mae_best_oos"]], abs=2e-3
    )
    assert cz[at["low_combined"]] <= cz[at["diff_combined"]] <= cz[at["high_combined"]]
    assert (
        okres[at["region_name"]] == "Benešov"
        and okres[at["mae_combined"]] == cz[at["mae_combined"]]
    )
    # the plain mean: (2 ± 0.5 ± 2) / 3 per hour, never better than the good model
    assert cz[at["mae_blend"]] > cz[at["mae_best_oos"]]
    # one model everywhere: with a single okres the same as the okres's best
    assert cz[at["best_cz_oos"]] == GOOD and cz[at["best_cz_oos_models"]] == 1
    assert cz[at["mae_best_cz_oos"]] == cz[at["mae_best_oos"]]
    assert cz[at["diff_combined_vs_cz"]] == pytest.approx(cz[at["diff_combined"]], abs=1e-3)
    assert cz[at["low_combined_vs_cz"]] <= cz[at["diff_combined_vs_cz"]]
    assert cz[at["diff_best_oos_vs_cz"]] == 0
    assert len(cz) == len(blendtest.GROUP_COLUMNS)
    # every single model: ours minus it, with an interval, on the same days
    mat = {c: i for i, c in enumerate(blendtest.MODEL_COLUMNS)}
    by_model = {r[mat["model"]]: r for r in models if r[mat["variable"]] == "temperature_2m"}
    assert set(by_model) == {BIASED, GOOD, NOISY}
    for r in by_model.values():
        assert r[mat["days"]] == DAYS - 5 and r[mat["mae_combined"]] == cz[at["mae_combined"]]
        assert r[mat["diff_combined"]] == pytest.approx(
            r[mat["mae_combined"]] - r[mat["mae"]], abs=2e-3
        )
        assert r[mat["low_combined"]] <= r[mat["diff_combined"]] <= r[mat["high_combined"]]
        assert r[mat["low"]] is not None and r[mat["high"]] is not None
    # the biased model is 2 °C off every hour: ours is clearly better
    assert by_model[BIASED][mat["high_combined"]] < 0
    doc = blendtest.document(days, groups, models, info, {}, datetime(2026, 10, 1, tzinfo=UTC))
    assert doc["test_days"] == DAYS - 5 and doc["warm_up_days"] == 5
    assert doc["from"] == str(FIRST + timedelta(days=5)) and doc["to"] == str(last)
    assert any("D+1" in line for line in blendtest.summary(groups))


def test_a_candidate_is_compared_but_never_trained_on_or_picked():
    obs, fc = _data()
    scores = _scores(obs, fc)
    last = FIRST + timedelta(days=DAYS - 1)
    # a perfect experimental forecast (exactly the observations)
    perfect = (
        fc.filter(pl.col("model") == GOOD)
        .with_columns(
            pl.lit("meteoverdict_ai").alias("model"),
            pl.lit(10.0, pl.Float32).alias("temperature_2m"),
            pl.lit(2.0, pl.Float32).alias("wind_speed_10m"),
        )
    )
    args = (scores, fc, obs, STATIONS, FIRST, last)
    _, groups, models, _ = blendtest.run(*args, min_training_days=5, resamples=50)
    _, with_ai, ai_models, _ = blendtest.run(
        *args, min_training_days=5, resamples=50, candidates=perfect
    )
    at = {c: i for i, c in enumerate(blendtest.GROUP_COLUMNS)}
    # the combination, the out-of-sample choice and the hindsight best are unchanged
    for name in ("mae_combined", "best_oos", "best_hindsight", "mae_best_hindsight"):
        assert [r[at[name]] for r in with_ai] == [r[at[name]] for r in groups]
    mat = {c: i for i, c in enumerate(blendtest.MODEL_COLUMNS)}
    ai = [r for r in ai_models if r[mat["model"]] == "meteoverdict_ai"]
    temp = next(r for r in ai if r[mat["variable"]] == "temperature_2m")
    assert temp[mat["mae"]] == pytest.approx(0, abs=1e-6)
    # ours minus the candidate: positive, the candidate is better than the combination
    assert temp[mat["low_combined"]] > 0


def test_a_model_with_the_newest_days_only_does_not_shrink_the_test():
    # regression: a newly added model, delivered by the backfill for its newest window
    # only, made the fair station-days of every model start on its first day, both in
    # each training window (no warm-up left) and in the test period (2026-10-16: 5
    # test days instead of 24)
    late_from = FIRST + timedelta(days=DAYS - 6)
    obs, fc = _data(late_from=late_from)
    scores = _scores(obs, fc)
    late_rows = scores.filter(pl.col("model") == LATE, pl.col("variable") == "temperature_2m")
    assert late_rows["date"].min() == late_from
    last = FIRST + timedelta(days=DAYS - 1)
    days, groups, models, info = blendtest.run(
        scores, fc, obs, STATIONS, FIRST, last, min_training_days=5, resamples=200
    )
    doc = blendtest.document(days, groups, models, info, {}, datetime(2026, 10, 1, tzinfo=UTC))
    assert doc["test_days"] == DAYS - 5 and doc["warm_up_days"] == 5
    at = {c: i for i, c in enumerate(blendtest.GROUP_COLUMNS)}
    cz = next(r for r in groups if r[0] == "cz" and r[at["variable"]] == "temperature_2m")
    assert cz[at["days"]] == DAYS - 5 and cz[at["best_cz_oos"]] == GOOD
    # the late model is compared with ours on the days it has
    mat = {c: i for i, c in enumerate(blendtest.MODEL_COLUMNS)}
    late = next(r for r in models if r[mat["model"]] == LATE and r[0] == "temperature_2m")
    assert late[mat["days"]] == 6 and late[mat["high_combined"]] < 0
    # not trained on while it covers too few of the window's days
    weights, _ = blendtest.training(scores, STATIONS, [last - timedelta(days=1)], min_days=5)
    assert LATE not in weights["model"].to_list()
    assert weights["days"].max() == DAYS - 1


def test_combined_forecast_is_the_weighted_corrected_mean():
    t = datetime(2026, 9, 10, 12, tzinfo=UTC)
    fc = pl.DataFrame(
        [("s1", t, "a", 1, 12.0, 0.0, 2.0), ("s1", t, "b", 1, 9.0, 1.0, 4.0)],
        schema=FC_SCHEMA,
        orient="row",
    )
    pools = pl.DataFrame(
        {
            "variable": ["temperature_2m", "wind_speed_10m", "precipitation_daily"],
            "region": ["CZ0201"] * 3,
            "station_id": ["s1"] * 3,
        }
    )
    weights = pl.DataFrame(
        [
            (date(2026, 9, 10), "CZ0201", v, 1, m, w, c)
            for v in ("temperature_2m", "wind_speed_10m", "precipitation")
            for m, w, c in (("a", 0.75, 2.0 if v == "temperature_2m" else 0.0), ("b", 0.25, 0.0))
        ],
        schema=["date", "region", "variable", "lead_day", "model", "weight", "correction"],
        orient="row",
    ).with_columns(pl.col("lead_day").cast(pl.Int8))
    out = blendtest.combined_forecasts(fc, pools, weights).row(0, named=True)
    assert out["model"] == "combined@CZ0201"
    assert out["temperature_2m"] == pytest.approx(0.75 * 10 + 0.25 * 9)
    assert out["wind_speed_10m"] == pytest.approx(2.5)
    assert out["precipitation"] == pytest.approx(0.25)
    # with the regression blend: its weights, and the 12 UTC correction at the
    # station's elevation (300 m, 1 x 100 m above the okres mean, lapse -0.5)
    coefficients = pl.DataFrame(
        [
            ("CZ0201", "temperature_2m", 1, m, mw, 2, 30, *[b] * 4, *[-0.5] * 4, 200.0, -2.0, 2.0)
            for m, mw, b in (("a", 1.2, 1.0), ("b", -0.2, 0.0))
        ],
        schema=["region", "variable", "lead_day", "model", *mos.COEFFICIENT_COLUMNS],
        orient="row",
    ).with_columns(pl.lit(date(2026, 9, 9)).alias("as_of"), pl.col("lead_day").cast(pl.Int8))
    with_regression = combine.with_mos(
        weights.with_columns(pl.lit(date(2026, 9, 9)).alias("as_of")),
        coefficients,
        keys=("as_of", "region"),
    )
    stations = pl.DataFrame({"id": ["s1"], "elevation": [300.0]})
    out = blendtest.combined_forecasts(fc, pools, with_regression, stations).row(0, named=True)
    # a: 12 - (1 - 0.5) = 11.5, b: 9 - (0 - 0.5) = 9.5 → 1.2 * 11.5 - 0.2 * 9.5
    assert out["temperature_2m"] == pytest.approx(1.2 * 11.5 - 0.2 * 9.5)
    assert out["wind_speed_10m"] == pytest.approx(2.5)  # no regression there


def test_command_writes_the_json(tmp_path):
    from typer.testing import CliRunner

    from meteoverdict.cli import app

    obs, fc = _data()
    for kind, frame in (("obs", obs), ("fc", fc), ("scores", _scores(obs, fc))):
        (tmp_path / kind).mkdir()
        frame.write_parquet(tmp_path / kind / "2026-09.parquet")
    STATIONS.write_parquet(tmp_path / "stations.parquet")
    out = tmp_path / "blend-test.json"
    args = [
        "blend-test",
        "--data-dir",
        str(tmp_path),
        "--stations",
        str(tmp_path / "stations.parquet"),
    ]
    result = CliRunner().invoke(
        app, [*args, "--out", str(out), "--min-training-days", "5", "--resamples", "50"]
    )
    assert result.exit_code == 0, result.output
    assert "warm-up" in result.output and "temperature_2m" in result.output
    doc = json.loads(out.read_text("utf-8"))
    assert doc["test_days"] == DAYS - 5 and doc["training_window"] == "90d"
    assert doc["groups"]["columns"] == blendtest.GROUP_COLUMNS
    assert {r[0] for r in doc["groups"]["rows"]} == {"cz", "okres"}
