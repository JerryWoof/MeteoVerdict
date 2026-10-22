from datetime import UTC, datetime

import polars as pl
import pytest

from meteoverdict import combine, models, mos, obce_forecast


def test_places_of_litomerice():
    points = obce_forecast.places("CZ0423")
    assert points.height == 105
    assert {"id", "okres", "name", "lat", "lon", "elevation", "population"} <= set(points.columns)
    assert points["id"][0].startswith("CZ0423/")
    assert points["population"].null_count() == 0
    assert points.filter(pl.col("name") == "Litoměřice")["population"].item() > 20000
    every = obce_forecast.places()
    assert every["okres"].n_unique() == 77
    assert every["id"].is_unique().all()


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
    points = pl.DataFrame({"id": ["A", "B"], "okres": ["CZ0423", "CZ0423"]})
    out = obce_forecast.combined(rows, weights, points, now).sort("okres", "time")
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


def test_corrections_at_the_obec_height():
    # the okres point of Benešov (CZ0201) is at 430 m, its stations at 400 m on average
    regression = {
        **{c: b for c, b in zip(mos.BIAS_COLUMNS, [1.0, 2.0, 3.0, 4.0], strict=True)},
        **{c: 1.0 for c in mos.LAPSE_COLUMNS},
        "station_elevation": 400.0, "dz_min": -2.0, "dz_max": 2.0,
    }  # fmt: skip
    point = combine.slot_corrections(pl.lit(430.0), combine.POINT_LAPSE_FACTOR)
    weights = (
        pl.DataFrame(
            [{"region": "o", "variable": "temperature_2m", "correction": 0.0, **regression}]
        )
        .with_columns(point)
        .join(pl.DataFrame({"_elevation": [600.0, 900.0, None]}), how="cross")
    )
    out = obce_forecast.at_obec_height(weights)
    slots = out.select(combine.SLOT_CORRECTIONS).rows()
    # 600 m: 2 steps of 100 m above the stations at half strength → +1.0
    assert slots[0] == pytest.approx((2.0, 3.0, 4.0, 5.0))
    # 900 m: clipped to dz_max (2 steps), as for the okres point
    assert slots[1] == pytest.approx((2.0, 3.0, 4.0, 5.0))
    assert out["correction"][0] == pytest.approx(3.5)
    # no height: the point's corrections (30 m above the stations → +0.15)
    assert slots[2] == pytest.approx((1.15, 2.15, 3.15, 4.15))
    assert out["correction"][2] == 0.0
    # a weight file from before the elevation term was kept: unchanged
    old = weights.drop(combine.ELEVATION_TERM_COLUMNS)
    assert obce_forecast.at_obec_height(old).equals(old)


def test_document_has_every_models_wind_and_precipitation():
    now = datetime(2026, 10, 18, 0, tzinfo=UTC)
    times = [datetime(2026, 10, 18, h, tzinfo=UTC) for h in (1, 2)]
    rows = pl.DataFrame(
        {
            "station_id": ["A"] * 4,
            "valid_time": times * 2,
            "model": ["m1"] * 2 + ["m2"] * 2,
            "run": [now] * 4,
            "temperature_2m": [10.0, 11.0, 12.0, 13.0],
            "precipitation": [0.0, 0.25, None, None],
            "wind_speed_10m": [1.04, 2.0, 3.0, None],
        }
    )
    hourly = pl.DataFrame(
        {
            "okres": ["A"] * 2,
            "time": times,
            "temperature_2m": [10.5, 11.5],
            "precipitation": [0.1, 0.2],
            "wind_speed_10m": [1.0, 2.0],
        }
    )
    points = pl.DataFrame(
        {
            "id": ["A"],
            "name": ["Aa"],
            "lat": [50.0],
            "lon": [14.0],
            "elevation": [200.0],
            "population": [100],
        }
    )
    doc = obce_forecast.document("CZ0423", points, rows, hourly, now)
    place = doc["places"][0]
    assert place["models"] == {"m1": [10.0, 11.0], "m2": [12.0, 13.0]}
    assert place["models_wind_speed_10m"] == {"m1": [1.0, 2.0], "m2": [3.0, None]}
    # m2 has no precipitation at this place: no entry
    assert place["models_precipitation"] == {"m1": [0.0, 0.2]}
    for key in ("models", "models_wind_speed_10m", "models_precipitation"):
        assert all(len(s) == len(doc["times"]) for s in place[key].values())
