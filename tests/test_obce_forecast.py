from datetime import UTC, datetime

import polars as pl

from meteoverdict import models, obce_forecast


def test_places_of_litomerice():
    points = obce_forecast.places("CZ0423")
    assert points.height == 105
    assert {"id", "lat", "lon", "elevation"} <= set(points.columns)
    assert obce_forecast.okresy() == ["CZ0423"]


def test_candidate_runs_are_old_enough_and_newest_first():
    model = next(m for m in models.enabled_models() if m.run_hours == (0, 6, 12, 18))
    runs = obce_forecast.candidate_runs(model, datetime(2026, 10, 18, 1, 30, tzinfo=UTC))
    assert runs[0] == datetime(2026, 10, 17, 18, tzinfo=UTC)
    assert runs == sorted(runs, reverse=True)
    assert all(r.hour in model.run_hours for r in runs)


def test_every_obec_gets_the_okres_weights():
    now = datetime(2026, 10, 18, 0, tzinfo=UTC)
    times = [datetime(2026, 10, 18, h, tzinfo=UTC) for h in (1, 2)]
    rows = pl.DataFrame(
        {
            "station_id": ["A", "A", "B", "B"] * 2,
            "valid_time": times * 4,
            "model": ["m1"] * 4 + ["m2"] * 4,
            "temperature_2m": [10.0, 11.0, 12.0, 13.0, 12.0, 13.0, 14.0, 15.0],
            "precipitation": [0.0] * 8,
            "wind_speed_10m": [1.0] * 8,
        }
    )
    weights = pl.DataFrame(
        {
            "region": ["CZ0423"] * 6,
            "variable": ["temperature_2m"] * 2 + ["precipitation"] * 2 + ["wind_speed_10m"] * 2,
            "lead_day": [1] * 6,
            "model": ["m1", "m2"] * 3,
            "weight": [0.75, 0.25] * 3,
            "correction": [0.0] * 6,
        },
        schema_overrides={"lead_day": pl.Int8},
    )
    out = obce_forecast.combined(rows, weights, "CZ0423", now).sort("okres", "time")
    assert out["okres"].to_list() == ["A", "A", "B", "B"]
    assert out["temperature_2m"].to_list() == [10.5, 11.5, 12.5, 13.5]


def test_the_day_starts_at_prague_midnight():
    assert obce_forecast.start_of_day(datetime(2026, 10, 18, 2, 13, tzinfo=UTC)) == datetime(
        2026, 10, 17, 22, tzinfo=UTC
    )
    # 01:30 Prague on 18 Oct is still that day
    assert obce_forecast.start_of_day(datetime(2026, 10, 17, 23, 30, tzinfo=UTC)) == datetime(
        2026, 10, 17, 22, tzinfo=UTC
    )
