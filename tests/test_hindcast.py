from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from meteoverdict import hindcast, scoring
from meteoverdict.forecasts import SCHEMA as FC_SCHEMA
from meteoverdict.models import load_models
from meteoverdict.observations import SCHEMA as OBS_SCHEMA

BIASED, GOOD, NOISY = "ecmwf_ifs", "ncep_gfs_global", "ecmwf_ifs025"
MODELS = [m for m in load_models() if m.id in (BIASED, GOOD, NOISY)]
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


def _data():
    """Observations (10 °C, 2 m/s, dry) and D+1 and D+2 forecasts of three models: one
    2 °C too warm and wet (1 mm an hour), one good (±0.5), one noisy (±2)."""
    rng = np.random.default_rng(1)
    start = datetime(FIRST.year, FIRST.month, FIRST.day, tzinfo=UTC)
    times = [start + timedelta(hours=h) for h in range(24 * DAYS + 1)]
    obs, fc = [], []
    for s in STATIONS["id"]:
        for t in times:
            obs += [
                (s, t, "temperature_2m", 10.0, 0, "recent"),
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


def test_trained_strictly_before_the_forecast_was_issued():
    # a D+1 forecast for the 16th is made on the 15th; its scores come out on the 16th
    assert hindcast.as_of(date(2026, 10, 16), 1) == date(2026, 10, 14)
    assert hindcast.as_of(date(2026, 10, 16), 3) == date(2026, 10, 12)


def test_rebuilt_parts_of_day_out_of_sample():
    obs, fc = _data()
    last = FIRST + timedelta(days=DAYS - 1)
    scores = scoring.daily_scores(obs, fc, MODELS, FIRST, last)
    day = date(2026, 9, 20)
    early = FIRST + timedelta(days=3)  # too little training: left out
    rows = hindcast.rebuild(
        scores, fc, obs, STATIONS, [early, day], min_training_days=5, regression=False
    )
    assert rows.schema == pl.Schema(hindcast.SCHEMA)
    assert rows["day"].unique().to_list() == [day]
    assert sorted(rows["lead"].unique().to_list()) == [1, 2]
    assert set(rows["part"]) == {"night", "morning", "afternoon", "evening", "day"}
    lead1 = rows.filter(pl.col("lead") == 1)
    assert lead1["trained_to"].unique().to_list() == [day - timedelta(days=2)]
    assert rows.filter(pl.col("lead") == 2)["trained_to"].unique().to_list() == [
        day - timedelta(days=3)
    ]
    whole = lead1.filter(pl.col("part") == "day").row(0, named=True)
    # the biased model is corrected and the good one weighs most: close to 10 °C
    assert whole["tmax"] == pytest.approx(10.0, abs=1.0)
    assert whole["tmin"] == pytest.approx(10.0, abs=1.0)
    # one model of three is wet: showers (≥ 30 % of the models), not rain (≥ 50 %);
    # no cloud cover in the stored D+N, so no sky
    assert whole["rain_probability"] == pytest.approx(1 / 3)
    assert whole["symbol"] == "showers" and whole["cloud"] is None
    assert whole["okres"] == "CZ0201"


def test_share_of_wet_models_by_part():
    start = datetime(2026, 9, 19, 22, tzinfo=UTC)  # 00:00 in Prague
    hours = [start + timedelta(hours=h + 1) for h in range(24)]
    totals = pl.DataFrame(
        {
            "okres": ["X"] * 48,
            "lead_day": [1] * 48,
            "model": ["a"] * 24 + ["b"] * 24,
            "time": hours * 2,
            # a: 0.1 mm every hour; b: dry
            "precipitation": [0.1] * 24 + [0.0] * 24,
        }
    ).cast({"time": pl.Datetime("us", "UTC")})
    got = {
        r["part"]: r["rain_probability"]
        for r in hindcast.chances(totals)
        .filter(pl.col("day") == date(2026, 9, 20))
        .iter_rows(named=True)
    }
    # 0.6 mm in a part (≥ 0.2) for one model of two
    assert got == {"night": 0.5, "morning": 0.5, "afternoon": 0.5, "evening": 0.5, "day": 0.5}


def test_merge_replaces_days_and_drops_old_ones(tmp_path):
    def rows(day, tmax):
        return (
            pl.DataFrame(
                {"lead": [1], "okres": ["X"], "day": [day], "part": ["day"], "tmax": [tmax]}
            )
            .with_columns(
                *[
                    pl.lit(None).alias(c)
                    for c in hindcast.SCHEMA
                    if c not in ("lead", "okres", "day", "part", "tmax")
                ]
            )
            .select(list(hindcast.SCHEMA))
            .cast(hindcast.SCHEMA)
        )

    path = tmp_path / hindcast.ASSET
    hindcast.merge(
        path,
        pl.concat([rows(date(2026, 9, 1), 1.0), rows(date(2026, 9, 2), 2.0)]),
        date(2026, 9, 1),
    )
    hindcast.merge(path, rows(date(2026, 9, 2), 3.0), date(2026, 9, 2))
    back = pl.read_parquet(path)
    assert back["day"].to_list() == [date(2026, 9, 2)] and back["tmax"].to_list() == [3.0]
