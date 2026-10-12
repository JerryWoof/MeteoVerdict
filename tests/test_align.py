from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import align
from meteoverdict.forecasts import SCHEMA as FC_SCHEMA
from meteoverdict.models import load_models
from meteoverdict.observations import SCHEMA as OBS_SCHEMA

MODELS = {m.id: m for m in load_models()}
START = datetime(2026, 9, 1, tzinfo=UTC)


def hours(n: int, start: datetime = START) -> list[datetime]:
    return [start + timedelta(hours=h) for h in range(n)]


def observations(times, temperature=10.0, rain=1.0, wind=2.0, quality=0) -> pl.DataFrame:
    rows = []
    for t in times:
        for variable, value in (
            ("temperature_2m", temperature),
            ("precipitation", rain),
            ("wind_speed_10m", wind),
        ):
            rows.append(("s", t, variable, value, quality, "recent"))
    return pl.DataFrame(rows, schema=OBS_SCHEMA, orient="row")


def forecasts(model: str, lead_day: int, times, temperature=11.0, rain=0.5, wind=3.0):
    rows = [("s", t, model, lead_day, temperature, rain, wind) for t in times]
    return pl.DataFrame(rows, schema=FC_SCHEMA, orient="row")


def test_hourly_model_pairs_every_hour():
    times = hours(6, START + timedelta(hours=1))
    got = align.pairs(
        observations(times), forecasts("dwd_icon_d2", 1, times), [MODELS["dwd_icon_d2"]]
    ).collect()
    assert got.schema == pl.Schema(align.PAIR_SCHEMA)
    assert got.group_by("variable").len().sort("variable").rows() == [
        ("precipitation", 6),
        ("temperature_2m", 6),
        ("wind_speed_10m", 6),
    ]
    rain = got.filter(pl.col("variable") == "precipitation")
    assert set(rain["period_h"]) == {1}
    assert rain["forecast"].to_list() == [0.5] * 6 and rain["observed"].to_list() == [1.0] * 6
    assert set(got.filter(pl.col("variable") != "precipitation")["period_h"]) == {0}


def test_six_hourly_model_uses_native_hours_and_six_hour_sums():
    aifs = MODELS["ecmwf_aifs025_single"]
    times = hours(25)  # 00:00 … 24:00
    got = align.pairs(observations(times), forecasts(aifs.id, 1, times), [aifs]).collect()
    temperature = got.filter(pl.col("variable") == "temperature_2m")
    assert {t.hour for t in temperature["time"]} == {0, 6, 12, 18}
    rain = got.filter(pl.col("variable") == "precipitation").sort("time")
    # periods 01-06, 07-12, 13-18, 19-24 are complete; 00:00 alone closes the previous one
    assert [t.hour for t in rain["time"]] == [6, 12, 18, 0]
    assert rain["forecast"].to_list() == pytest.approx([3.0] * 4)
    assert rain["observed"].to_list() == pytest.approx([6.0] * 4)
    assert set(rain["period_h"]) == {6}


def test_incomplete_period_is_dropped():
    aifs = MODELS["ecmwf_aifs025_single"]
    times = hours(13)  # 00:00 … 12:00
    obs = observations([t for t in times if t.hour != 9])  # hour ending 09:00 missing
    got = align.pairs(obs, forecasts(aifs.id, 1, times), [aifs]).collect()
    rain = got.filter(pl.col("variable") == "precipitation")
    assert [t.hour for t in rain["time"]] == [6]


def test_step_depends_on_the_lead_day():
    icon = MODELS["dwd_icon_eu"]
    times = hours(7)
    fc = pl.concat([forecasts(icon.id, 3, times), forecasts(icon.id, 4, times)])
    got = align.pairs(observations(times), fc, [icon]).collect()
    t = got.filter(pl.col("variable") == "temperature_2m")
    assert t.filter(pl.col("lead_day") == 3).height == 7  # hourly up to 78 h
    assert {x.hour for x in t.filter(pl.col("lead_day") == 4)["time"]} == {0, 3, 6}


def test_exclude_estimated_observations():
    times = hours(3)
    obs = pl.concat([observations(times[:2]), observations(times[2:], quality=3)])
    icon = MODELS["dwd_icon_d2"]
    fc = forecasts(icon.id, 1, times)
    assert align.pairs(obs, fc, [icon]).collect().height == 9
    assert align.pairs(obs, fc, [icon], exclude_estimated=True).collect().height == 6


def test_unknown_or_missing_side_gives_no_pair():
    times = hours(3)
    icon = MODELS["dwd_icon_d2"]
    fc = forecasts(icon.id, 1, times).with_columns(pl.lit(None, pl.Float32).alias("wind_speed_10m"))
    got = align.pairs(observations(times[:2]), fc, [icon]).collect()
    assert got.filter(pl.col("variable") == "wind_speed_10m").height == 0
    assert got["time"].max() == times[1]


def test_daily_precipitation_needs_a_complete_utc_day():
    icon = MODELS["dwd_icon_d2"]
    day1 = hours(24, START + timedelta(hours=1))  # 01:00 … 24:00 = 1 September
    day2 = hours(23, START + timedelta(hours=25))  # 2 September, one hour short
    times = day1 + day2
    p = align.pairs(observations(times), forecasts(icon.id, 1, times), [icon])
    daily = align.daily_precipitation(p).collect()
    assert daily["date"].to_list() == [date(2026, 9, 1)]
    assert daily["forecast"][0] == pytest.approx(12.0) and daily["observed"][0] == pytest.approx(
        24.0
    )


def test_daily_precipitation_from_six_hour_periods():
    aifs = MODELS["ecmwf_aifs025_single"]
    times = hours(24, START + timedelta(hours=1))
    p = align.pairs(observations(times), forecasts(aifs.id, 2, times), [aifs])
    daily = align.daily_precipitation(p).collect()
    assert daily.select("date", "lead_day", "observed").rows() == [(date(2026, 9, 1), 2, 24.0)]


# hours ending 07:00 on 1 Sept … 06:00 on 2 Sept: ČHMÚ's climatological day of 1 Sept
WINDOW = hours(24, START + timedelta(hours=7))
GAUGE_END = START + timedelta(days=1, hours=6)


def gauge(value: float, time: datetime = GAUGE_END, quality: int = 0) -> pl.DataFrame:
    row = ("s", time, "precipitation_24h", value, quality, "recent")
    return pl.DataFrame([row], schema=OBS_SCHEMA, orient="row")


def test_precipitation_24h_compares_a_gauge_with_the_06_06_forecast_sum():
    icon = MODELS["dwd_icon_d2"]
    fc = forecasts(icon.id, 1, hours(48))  # 0.5 mm every hour, more than the window
    got = align.precipitation_24h(gauge(7.0), fc, [icon]).collect()
    assert got.rows() == [("s", date(2026, 9, 1), icon.id, 1, 12.0, 7.0, 0)]


def test_precipitation_24h_sums_hourly_observations_without_a_gauge():
    icon = MODELS["dwd_icon_d2"]
    obs = observations(hours(48))  # 1 mm every hour
    got = align.precipitation_24h(obs, forecasts(icon.id, 1, hours(48)), [icon]).collect()
    assert got.filter(pl.col("date") == date(2026, 9, 1))["observed"].to_list() == [24.0]
    # 31 Aug and 2 Sept are incomplete within these 48 hours
    assert got["date"].to_list() == [date(2026, 9, 1)]


def test_precipitation_24h_prefers_the_gauge_value():
    icon = MODELS["dwd_icon_d2"]
    obs = pl.concat([observations(WINDOW), gauge(3.0)])
    got = align.precipitation_24h(obs, forecasts(icon.id, 1, WINDOW), [icon]).collect()
    assert got["observed"].to_list() == [3.0]


def test_precipitation_24h_needs_all_24_forecast_hours():
    icon = MODELS["dwd_icon_d2"]
    fc = forecasts(icon.id, 1, WINDOW[1:])
    assert align.precipitation_24h(gauge(7.0), fc, [icon]).collect().height == 0


def test_precipitation_24h_works_for_six_hourly_models_and_listed_lead_days():
    aifs = MODELS["ecmwf_aifs025_single"]
    fc = pl.concat([forecasts(aifs.id, 2, WINDOW), forecasts(aifs.id, 9, WINDOW)])
    got = align.precipitation_24h(gauge(7.0), fc, [aifs]).collect()
    assert got.select("lead_day", "forecast").rows() == [(2, 12.0)]


def test_precipitation_24h_can_exclude_estimated_values():
    icon = MODELS["dwd_icon_d2"]
    fc = forecasts(icon.id, 1, WINDOW)
    got = align.precipitation_24h(gauge(7.0, quality=3), fc, [icon], exclude_estimated=True)
    assert got.collect().height == 0
