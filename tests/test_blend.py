from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import blend, scoring
from meteoverdict.forecasts import SCHEMA as FC_SCHEMA
from meteoverdict.models import load_models
from meteoverdict.observations import SCHEMA as OBS_SCHEMA

MODELS = {m.id: m for m in load_models()}
THREE = [MODELS[i] for i in ("dwd_icon_d2", "dwd_icon_eu", "ecmwf_ifs025")]
START = datetime(2026, 9, 1, tzinfo=UTC)


def hours(n):
    return [START + timedelta(hours=h) for h in range(n)]


def forecasts(model, temperature, times, lead_day=1, rain=0.0):
    rows = [("s", t, model, lead_day, temperature, rain, 2.0) for t in times]
    return pl.DataFrame(rows, schema=FC_SCHEMA, orient="row")


def test_the_blend_is_the_mean_of_at_least_three_models():
    times = hours(2)
    fc = pl.concat(
        [
            forecasts("dwd_icon_d2", 10.0, times),
            forecasts("dwd_icon_eu", 12.0, times),
            forecasts("ecmwf_ifs025", 14.0, times[:1]),  # only the first hour
        ]
    )
    got = blend.forecasts(fc, THREE).collect()
    assert got.schema == pl.Schema(FC_SCHEMA)
    # second hour: two members only, so no blend
    assert got.select("time", "model", "temperature_2m").rows() == [
        (times[0], "blend", pytest.approx(12.0))
    ]


def test_models_not_asked_for_and_older_blends_are_left_out():
    times = hours(1)
    fc = pl.concat(
        [forecasts(m.id, 10.0, times) for m in THREE]
        + [forecasts("gfs_seamless", 40.0, times), forecasts("blend", 99.0, times)]
    )
    got = blend.forecasts(fc, THREE).collect()
    assert got["temperature_2m"].to_list() == [pytest.approx(10.0)]


def test_lead_days_are_blended_separately():
    times = hours(1)
    fc = pl.concat(
        [forecasts(m.id, 10.0, times, lead_day=1) for m in THREE]
        + [forecasts(m.id, 20.0, times, lead_day=2) for m in THREE[1:]]
    )
    got = blend.forecasts(fc, THREE).collect()
    assert got.select("lead_day", "temperature_2m").rows() == [(1, pytest.approx(10.0))]


def test_the_blend_is_scored_like_a_six_hourly_model():
    times = hours(25)
    fc = pl.concat([forecasts(m.id, 10.0 + i, times) for i, m in enumerate(THREE)])
    obs = pl.DataFrame(
        [("s", t, "temperature_2m", 10.0, 0, "recent") for t in times],
        schema=OBS_SCHEMA,
        orient="row",
    )
    table = scoring.daily_scores(obs, fc, THREE, date(2026, 9, 1), date(2026, 9, 1))
    mean = table.filter(pl.col("model") == "blend", pl.col("variable") == "temperature_2m")
    assert mean["n"].to_list() == [4]  # 00, 06, 12, 18 UTC
    assert mean["sum_err"].to_list() == pytest.approx([4.0])  # mean of 10, 11, 12 is 11
    plain = scoring.daily_scores(
        obs, fc, THREE, date(2026, 9, 1), date(2026, 9, 1), with_blend=False
    )
    assert "blend" not in set(plain["model"])
