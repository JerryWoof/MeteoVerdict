from datetime import UTC, date, datetime

import polars as pl

from meteoverdict import combine, extras, observations
from meteoverdict.models import load_models

ICON = next(m for m in load_models() if m.id == "dwd_icon_d2")
DAY = date(2026, 10, 11)


def at(hour: int) -> datetime:
    return datetime(2026, 10, 11, hour, tzinfo=UTC)


def obs(variable: str, value: float, hours=(0, 6, 7, 12)) -> pl.DataFrame:
    rows = [("a", at(h), variable, value, 0, "now") for h in hours]
    return pl.DataFrame(rows, schema=observations.SCHEMA, orient="row")


def forecast(**values) -> pl.DataFrame:
    rows = [("a", at(h), ICON.id, 1, *values.values()) for h in (0, 6, 7, 12)]
    return pl.DataFrame(
        rows, schema=["station_id", "time", "model", "lead_day", *values], orient="row"
    )


def test_daily_scores_use_the_synoptic_hours_only():
    table = extras.daily_scores(
        obs("relative_humidity_2m", 60.0),
        forecast(relative_humidity_2m=70.0),
        [ICON],
        DAY,
        DAY,
    )
    row = table.row(0, named=True)
    assert row["variable"] == "relative_humidity_2m" and row["n"] == 3  # 07 UTC left out
    assert row["sum_err"] == 30.0 and row["sum_abs_err"] == 30.0


def test_wind_direction_error_wraps_around_north():
    speed = obs("wind_speed_10m", 3.0)
    direction = obs("wind_direction_10m", 350.0)
    table = extras.daily_scores(
        pl.concat([speed, direction]), forecast(wind_direction_10m=10.0), [ICON], DAY, DAY
    )
    row = table.row(0, named=True)
    assert row["sum_err"] == 60.0  # +20 degrees at each of the three hours, not -340


def test_wind_direction_of_a_calm_is_not_scored():
    speed = obs("wind_speed_10m", 0.4)
    direction = obs("wind_direction_10m", 350.0)
    table = extras.daily_scores(
        pl.concat([speed, direction]), forecast(wind_direction_10m=10.0), [ICON], DAY, DAY
    )
    assert table.is_empty()


def test_angles_are_combined_as_vectors_across_north():
    frame = pl.DataFrame(
        {
            "okres": ["x", "x"],
            "wind_direction_10m": [350.0, 10.0],
            "weight": [1.0, 1.0],
            "correction": [0.0, 0.0],
        }
    )
    out = combine.combine_values(frame, "wind_direction_10m", ["okres"])
    value = out["wind_direction_10m"][0]
    assert min(value, 360 - value) < 1e-6  # north, not 180


def test_humidity_stays_between_zero_and_100():
    frame = pl.DataFrame(
        {
            "okres": ["x", "x"],
            "relative_humidity_2m": [99.0, 101.0],
            "weight": [1.0, 1.0],
            "correction": [-5.0, -5.0],
        }
    )
    out = combine.combine_values(frame, "relative_humidity_2m", ["okres"])
    assert out["relative_humidity_2m"][0] == 100.0


def test_the_extra_variables_get_weights_like_temperature():
    rows = []
    for variable in combine.EXTRA_VARIABLES:
        for model, rmse in (("m1", 1.0), ("m2", 2.0)):
            rows.append(
                {
                    "level": "okres",
                    "region": "CZ0201",
                    "region_name": "Benešov",
                    "window": "90d",
                    "variable": variable,
                    "lead_day": 1,
                    "model": model,
                    "n": 2400,
                    "days": 100,
                    "mae": rmse,
                    "rmse": rmse,
                    "bias": 0.5,
                    "enough_stations": True,
                }
            )
    w = combine.weights(pl.DataFrame(rows))
    assert set(w["variable"]) == set(combine.EXTRA_VARIABLES)
    gusts = w.filter(pl.col("variable") == "wind_gusts_10m")
    assert gusts.filter(model="m1")["weight"][0] > gusts.filter(model="m2")["weight"][0]
    assert gusts["correction"].max() > 0


def test_pressure_is_read_from_the_hourly_elements(tmp_path):
    meta2 = pl.DataFrame(
        {
            "OBS_TYPE": ["1H", "1H", "10M"],
            "WSI": ["w1", "w2", "w3"],
            "EG_EL_ABBREVIATION": ["P_hm", "Td", "P_hm"],
        }
    )
    assert observations.hourly_station_ids(meta2) == {"w1"}
    raw = pl.DataFrame(
        {
            "STATION": ["w1", "w1"],
            "ELEMENT": ["P_hm", "P_hm"],
            "DT": ["2026-10-11T06:00:00Z", "2026-10-11T07:00:00Z"],
            "VAL": ["1013.2", ""],
            "QUALITY": [0, 4],
        }
    )
    rows = observations.normalize(raw, "now", observations.HOURLY_ELEMENTS)
    assert rows["variable"].to_list() == ["pressure_msl"] and abs(rows["value"][0] - 1013.2) < 0.01
    assert "pressure_msl" in observations.EXTRA_VARIABLES
