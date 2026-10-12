from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import metrics, scoring
from meteoverdict.forecasts import SCHEMA as FC_SCHEMA
from meteoverdict.models import load_models
from meteoverdict.observations import SCHEMA as OBS_SCHEMA

MODELS = load_models()
ICON_D2 = "dwd_icon_d2"
START = datetime(2026, 9, 1, tzinfo=UTC)


def hours(n, start=START):
    return [start + timedelta(hours=h) for h in range(n)]


def observations(times, rain=lambda t: 1.0):
    rows = []
    for t in times:
        rows += [
            ("s", t, "temperature_2m", 10.0, 0, "recent"),
            ("s", t, "wind_speed_10m", 2.0, 0, "recent"),
            ("s", t, "precipitation", rain(t), 0, "recent"),
        ]
    return pl.DataFrame(rows, schema=OBS_SCHEMA, orient="row")


def forecasts(times, temperature=12.0, rain=0.0):
    rows = [("s", t, ICON_D2, 1, temperature, rain, 3.0) for t in times]
    return pl.DataFrame(rows, schema=FC_SCHEMA, orient="row")


def test_one_row_per_day_station_model_lead_and_variable():
    times = hours(49)  # 1 Sep 00:00 … 3 Sep 00:00
    table = scoring.daily_scores(
        observations(times), forecasts(times), MODELS, date(2026, 9, 1), date(2026, 9, 2)
    )
    assert table.select(scoring.KEYS).is_duplicated().sum() == 0
    assert table.schema["n"] == pl.UInt16 and table.schema["sum_abs_err"] == pl.Float32
    assert table.schema["a_5"] == pl.UInt8
    got = {(r["date"], r["variable"]): r for r in table.iter_rows(named=True)}
    first = date(2026, 9, 1)
    # temperature: 00:00 … 23:00 belong to 1 September; ranked at the synoptic hours
    assert got[(first, "temperature_2m_hourly")]["n"] == 24
    assert got[(first, "temperature_2m_hourly")]["sum_err"] == pytest.approx(48.0)
    assert got[(first, "temperature_2m")]["n"] == 4
    assert got[(first, "temperature_2m")]["sum_err"] == pytest.approx(8.0)
    # precipitation: the hours ending 01:00 … 24:00 belong to 1 September
    assert got[(first, "precipitation")]["n"] == 24
    assert got[(first, "precipitation")]["period_h"] == 1
    daily = got[(first, "precipitation_daily")]
    assert (daily["n"], daily["period_h"]) == (1, 24)
    assert daily["sum_err"] == pytest.approx(-24.0)
    # 24 mm observed, 0 forecast: a miss for both thresholds
    assert [daily[c] for c in metrics.counts_columns(5.0)] == [0, 0, 1, 0]
    assert [daily[c] for c in metrics.counts_columns(0.1)] == [0, 0, 1, 0]
    assert [daily[c] for c in metrics.counts_columns(20.0)] == [0, 0, 1, 0]  # heavy rain
    # hourly rows carry no contingency counts
    assert got[(first, "temperature_2m")]["a_5"] is None


def test_dates_outside_the_range_are_dropped():
    times = hours(72)
    table = scoring.daily_scores(
        observations(times), forecasts(times), MODELS, date(2026, 9, 2), date(2026, 9, 2)
    )
    assert set(table["date"]) == {date(2026, 9, 2)}


def test_scores_add_up_to_the_metrics_of_all_pairs():
    times = hours(25)
    obs = observations(times, rain=lambda t: float(t.hour % 3))
    fc = forecasts(times, rain=1.0)
    table = scoring.daily_scores(obs, fc, MODELS, date(2026, 9, 1), date(2026, 9, 1))
    rain = metrics.continuous_scores(
        table.filter(pl.col("variable") == "precipitation").select(metrics.SUMS).sum()
    )
    # hours ending 01:00 … 24:00: observed 1, 2, 0, 1, 2, 0, …; forecast 1 → |errors| 0, 1, 1
    assert rain["mae"][0] == pytest.approx(16 / 24)


def test_climatological_day_includes_rain_gauges():
    times = hours(49)  # automatic station "s": complete 06-06 window of 1 September
    gauge_end = START + timedelta(days=1, hours=6)
    gauge = pl.DataFrame(
        [("g", gauge_end, "precipitation_24h", 6.0, 0, "recent")], schema=OBS_SCHEMA, orient="row"
    )
    fc = pl.concat(
        [
            forecasts(times, rain=0.25),
            forecasts(times, rain=0.25).with_columns(station_id=pl.lit("g")),
        ]
    )
    table = scoring.daily_scores(
        pl.concat([observations(times), gauge]), fc, MODELS, date(2026, 9, 1), date(2026, 9, 2)
    )
    rows = table.filter(pl.col("variable") == "precipitation_24h").sort("station_id")
    assert rows["date"].to_list() == [date(2026, 9, 1)] * 2
    assert rows["station_id"].to_list() == ["g", "s"]
    assert set(rows["period_h"]) == {24} and set(rows["n"]) == {1}
    # forecast 6 mm everywhere; gauge observed 6 mm, station 24 mm
    assert rows["sum_err"].to_list() == pytest.approx([0.0, -18.0])
    assert [rows[c][0] for c in metrics.counts_columns(5.0)] == [1, 0, 0, 0]
    assert [rows[c][1] for c in metrics.counts_columns(5.0)] == [1, 0, 0, 0]


def test_heat_days_are_counted_on_the_daily_maximum():
    times = hours(24)
    obs = pl.DataFrame(
        [("s", t, "temperature_2m", 31.0 if t.hour == 13 else 20.0, 0, "recent") for t in times],
        schema=OBS_SCHEMA,
        orient="row",
    )
    table = scoring.daily_scores(
        obs, forecasts(times, temperature=29.0), MODELS, date(2026, 9, 1), date(2026, 9, 1)
    )
    row = table.filter(pl.col("variable") == "temperature_max").row(0, named=True)
    assert (row["n"], row["period_h"], row["sum_err"]) == (1, 24, pytest.approx(-2.0))
    # 31 °C observed, 29 °C forecast: a missed tropical day
    assert [row[c] for c in metrics.counts_columns(30.0)] == [0, 0, 1, 0]


def test_temperature_at_synoptic_hours_is_scored_for_six_hourly_models_too():
    times = hours(24)
    aifs = [m for m in MODELS if m.id == "ecmwf_aifs025_single"]
    fc = forecasts(times).with_columns(model=pl.lit(aifs[0].id))
    table = scoring.daily_scores(
        observations(times), fc, aifs, date(2026, 9, 1), date(2026, 9, 1), with_blend=False
    )
    synoptic = table.filter(pl.col("variable").str.ends_with("utc")).sort("variable")
    assert synoptic["variable"].to_list() == [
        f"temperature_2m_{h}utc" for h in ("00", "06", "12", "18")
    ]
    assert synoptic["n"].to_list() == [1] * 4
    assert synoptic["sum_err"].to_list() == pytest.approx([2.0] * 4)  # 12 °C vs 10 °C


def test_ranked_temperature_and_wind_use_the_same_hours_for_every_model():
    times = hours(24)
    aifs = next(m for m in MODELS if m.id == "ecmwf_aifs025_single")
    icon = next(m for m in MODELS if m.id == ICON_D2)
    fc = pl.concat([forecasts(times), forecasts(times).with_columns(model=pl.lit(aifs.id))])
    table = scoring.daily_scores(
        observations(times), fc, [icon, aifs], date(2026, 9, 1), date(2026, 9, 1), with_blend=False
    )
    n = {(r["model"], r["variable"]): r["n"] for r in table.iter_rows(named=True)}
    assert n[(ICON_D2, "temperature_2m")] == n[(aifs.id, "temperature_2m")] == 4
    assert n[(ICON_D2, "wind_speed_10m")] == n[(aifs.id, "wind_speed_10m")] == 4
    assert (n[(ICON_D2, "temperature_2m_hourly")], n[(aifs.id, "temperature_2m_hourly")]) == (24, 4)
