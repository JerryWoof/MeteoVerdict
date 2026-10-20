from datetime import UTC, date, datetime, timedelta

import polars as pl

from meteoverdict import station_fc

FIRST = date(2026, 10, 10)
LAST = date(2026, 10, 11)


def _runs(model: str, offset: float, hours=range(0, 49)) -> pl.DataFrame:
    run = datetime(2026, 10, 9, 0, tzinfo=UTC)  # the 00 UTC run of day D-1 for D = 10 Oct
    rows = [
        {
            "run": run,
            "model": model,
            "station_id": "S1",
            "lead_h": h,
            "valid_time": run + timedelta(hours=h),
            "temperature_2m": 10.0 + offset + (h % 24) / 10,
            "precipitation": 0.5,
            "wind_speed_10m": 3.0,
            "wind_gusts_10m": 6.0 + h % 3,
        }
        for h in hours
    ]
    return pl.DataFrame(rows).with_columns(pl.col("run").dt.cast_time_unit("us"))


def test_daily_forecast_values_and_blend():
    runs = pl.concat([_runs("a", 0), _runs("b", 1), _runs("c", 2)])
    daily = station_fc.daily_forecasts(runs, FIRST, LAST)
    one = daily.filter((pl.col("model") == "a") & (pl.col("date") == date(2026, 10, 10)))
    assert one["lead_day"].to_list() == [1]
    # 10 Oct local = 9 Oct 22:00 UTC .. 10 Oct 21:59 UTC; the run covers it from lead 22 h
    assert one["tmax"][0] > one["tmin"][0]
    assert round(one["wind"][0], 1) == 3.0
    blend = daily.filter((pl.col("model") == "blend") & (pl.col("date") == date(2026, 10, 10)))
    assert blend["wind"][0] == 3.0
    # two models are not enough for a blend (MIN_MEMBERS)
    two = station_fc.daily_forecasts(pl.concat([_runs("a", 0), _runs("b", 1)]), FIRST, LAST)
    assert two.filter(pl.col("model") == "blend").height == 0


def test_uncovered_day_has_no_value():
    runs = _runs("a", 0, hours=range(0, 30))  # ends 10 Oct 06:00 UTC: 10 Oct is not covered
    daily = station_fc.daily_forecasts(runs, FIRST, LAST)
    assert daily.filter(pl.col("date") == date(2026, 10, 10)).height == 0


def test_observations_need_enough_hours():
    rows = [
        {
            "station_id": "S1",
            "time": datetime(2026, 10, 10, 0, tzinfo=UTC) + timedelta(hours=h),
            "variable": "temperature_2m",
            "value": float(h),
        }
        for h in range(0, 24)
    ]
    obs = pl.DataFrame(rows).with_columns(pl.col("time").dt.cast_time_unit("us"))
    day = station_fc.daily_observations(obs, FIRST, LAST)
    # Prague day 10 Oct = 22 UTC hours (0..21 on the 10th); the 2 hours of the 11th are too few
    assert day["tmax"].to_list() == [21.0]
    assert day["tmin"].to_list() == [0.0]
    assert station_fc.daily_observations(obs.head(10), FIRST, LAST).height == 0


def test_documents_layout():
    runs = pl.concat([_runs("a", 0), _runs("b", 1), _runs("c", 2)])
    daily = station_fc.daily_forecasts(runs, FIRST, LAST)
    obs = pl.DataFrame({"station_id": ["S1"], "date": [FIRST], "tmax": [12.0]})
    docs = station_fc.documents(daily, obs, FIRST, LAST)
    doc = docs["S1"]
    assert doc["from"] == "2026-10-10" and doc["to"] == "2026-10-11"
    assert doc["obs"]["tmax"] == [12.0, None]
    assert set(doc["series"]["tmax"]["1"]) == {"a", "b", "c", "blend"}
    assert len(doc["series"]["tmax"]["1"]["a"]) == 2


def test_error_documents_one_file_per_day(tmp_path):
    docs = {
        "S1": {
            "from": "2026-10-10",
            "to": "2026-10-11",
            "obs": {"tmax": [12.0, None], "r": [0.0, 1.0]},
            "series": {
                "tmax": {"1": {"a": [13.24, 20.0], "b": [None, 5.0]}},
                "r": {"2": {"a": [0.4, None]}},
            },
        },
        "S0": {
            "from": "2026-10-10",
            "to": "2026-10-11",
            "obs": {},
            "series": {"tmax": {"1": {"a": [1.0, 1.0]}}},
        },
    }
    out = station_fc.error_documents(docs)
    assert list(out) == ["2026-10-10"]  # the 11th has no measured value with a model value
    doc = out["2026-10-10"]
    assert doc["stations"] == ["S0", "S1"] and doc["scale"] == 10
    assert doc["e"]["tmax"]["1"] == {"a": [None, 12]}  # (13.24 - 12.0) in tenths; b has no value
    assert doc["e"]["r"]["2"] == {"a": [None, 4]}
    paths = station_fc.write(docs, tmp_path, {}, datetime(2026, 10, 12, tzinfo=UTC))
    assert {p.name for p in paths} == {"S0.json", "S1.json", "err-2026-10-10.json", "index.json"}
