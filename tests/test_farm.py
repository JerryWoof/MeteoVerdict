from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import farm
from meteoverdict.models import enabled_models

MODELS = {m.id: m for m in enabled_models()}
D2, ALADIN = "dwd_icon_d2", "chmi_aladin_cz_1km"
IFS025, AIFS, EU = "ecmwf_ifs025", "ecmwf_aifs025_single", "dwd_icon_eu"
RUN = datetime(2026, 10, 14, 12, tzinfo=UTC)
HORIZON = {D2: 48, ALADIN: 72}


def utc(day, hour):
    return datetime(2026, 10, day, hour, tzinfo=UTC)


def forecasts(models, run=RUN, stations=("s1",), temp=None, gust=None, rain=None, horizon=None):
    """Rows like runs/YYYY-MM.parquet: constant 10 °C, 2 m/s gusts and no rain unless
    ``temp``/``gust``/``rain`` (model, valid time) -> value say otherwise."""
    rows = []
    for model in models:
        last = (horizon or {}).get(model, HORIZON.get(model, 120))
        for station in stations:
            for lead in range(1, last + 1):
                t = run + timedelta(hours=lead)
                g = None if model == AIFS else (gust or {}).get((model, t), 2.0)
                rows.append(
                    (
                        run,
                        model,
                        station,
                        lead,
                        t,
                        (temp or {}).get((model, t), 10.0),
                        (rain or {}).get((model, t), 0.0),
                        3.0,
                        g,
                    )
                )
    return pl.DataFrame(
        rows,
        schema={
            "run": pl.Datetime("us", "UTC"),
            "model": pl.String,
            "station_id": pl.String,
            "lead_h": pl.Int16,
            "valid_time": pl.Datetime("us", "UTC"),
            "temperature_2m": pl.Float32,
            "precipitation": pl.Float32,
            "wind_speed_10m": pl.Float32,
            "wind_gusts_10m": pl.Float32,
        },
        orient="row",
    )


def observations(first, last, stations=("s1",), temp=None, gust=None, rain=None, skip=()):
    rows = []
    t = first
    while t <= last:
        for s in stations:
            for variable, values, default in (
                ("temperature_2m", temp, 10.0),
                ("wind_gusts_10m", gust, 2.0),
                ("precipitation", rain, 0.0),
            ):
                if (s, variable, t) in skip:
                    continue
                rows.append((s, t, variable, (values or {}).get(t, default), 0, "now"))
        t += timedelta(hours=1)
    return pl.DataFrame(
        rows,
        schema={
            "station_id": pl.String,
            "time": pl.Datetime("us", "UTC"),
            "variable": pl.String,
            "value": pl.Float32,
            "quality": pl.UInt8,
            "source": pl.String,
        },
        orient="row",
    )


def row(table, **match):
    found = table.filter(*[pl.col(k) == v for k, v in match.items()])
    assert found.height == 1, found
    return found.row(0, named=True)


# --- definitions ---------------------------------------------------------------------


def test_nights_follow_prague_time():
    table = farm.nights(date(2026, 10, 14), date(2026, 10, 25))
    first = table.row(0, named=True)
    # CEST: 18:00 local = 16 UTC, 09:00 local = 07 UTC, 16 full hours
    assert (first["start"], first["end"], first["hours"]) == (utc(14, 16), utc(15, 7), 16)
    # clocks go back on 25 October 2026: that night has 17 hours
    autumn = table.filter(pl.col("night") == date(2026, 10, 24)).row(0, named=True)
    assert (autumn["start"], autumn["end"], autumn["hours"]) == (utc(24, 16), utc(25, 8), 17)
    winter = table.filter(pl.col("night") == date(2026, 10, 25)).row(0, named=True)
    assert (winter["start"], winter["hours"]) == (utc(25, 17), 16)


def test_night_of_and_block_end():
    times = pl.DataFrame({"t": [utc(14, 15), utc(14, 16), utc(14, 23), utc(15, 7), utc(15, 8)]})
    got = times.select(farm.night_of(pl.col("t")))["t"].to_list()
    assert got == [None, date(2026, 10, 14), date(2026, 10, 14), date(2026, 10, 14), None]
    ends = times.select(farm.block_end(pl.col("t")))["t"].to_list()
    assert ends == [utc(14, 15), utc(14, 18), utc(15, 0), utc(15, 9), utc(15, 9)]


def test_bins():
    leads = pl.DataFrame({"h": [1, 6, 7, 24, 25, 72, 120, 121]})
    got = leads.select(farm.bin_expr(pl.col("h")).alias("bin"))["bin"].to_list()
    assert got == ["1-6", "1-6", "7-12", "13-24", "25-48", "49-72", "73-120", None]


def test_observed_units_need_every_hour():
    skip = {("s1", "wind_gusts_10m", utc(14, 4))}
    gust = {utc(14, 2): 12.0, utc(14, 5): 16.0}
    obs = observations(utc(14, 1), utc(14, 6), gust=gust, rain={utc(14, 1): 0.4, utc(14, 3): 0.3},
                       skip=skip)  # fmt: skip
    gusts = farm.observed_units(obs, "gust")
    # 00-03 complete (max 12), 03-06 misses 04:00
    assert gusts.rows() == [("s1", utc(14, 3), 12.0)]
    rain = farm.observed_units(obs, "rain3h").sort("unit_end")
    assert rain["observed"].to_list() == pytest.approx([0.7, 0.0])
    frost = farm.observed_units(
        observations(utc(14, 16), utc(15, 7), temp={utc(15, 4): -0.5}), "frost"
    )
    assert frost.rows() == [("s1", utc(15, 7), -0.5)]
    # one hour missing: no night
    gap = observations(utc(14, 16), utc(15, 7), skip={("s1", "temperature_2m", utc(15, 1))})
    assert farm.observed_units(gap, "frost").height == 0


# --- forecast units ------------------------------------------------------------------


def test_block_units_use_own_output_hours():
    models = [MODELS[m] for m in (D2, IFS025, AIFS, EU)]
    gust = {
        (D2, RUN + timedelta(hours=2)): 11.0,  # inside the block ending at lead 3
        (IFS025, RUN + timedelta(hours=2)): 30.0,  # interpolated hour: ignored
        (IFS025, RUN + timedelta(hours=3)): 9.0,
        (EU, RUN + timedelta(hours=80)): 25.0,  # 3-hourly after 78 h: ignored
    }
    fc = forecasts([m.id for m in models], gust=gust)
    units = farm.forecast_units(fc, models, "gust")
    at = lambda m, lead: row(units, model=m, end_lead=lead)["forecast"]  # noqa: E731
    assert at(D2, 3) == pytest.approx(11.0)
    assert at(IFS025, 3) == pytest.approx(9.0)
    assert at(EU, 81) == pytest.approx(2.0)
    assert units.filter(pl.col("model") == AIFS).height == 0  # no gusts at all
    assert row(units, model=D2, end_lead=3)["unit_end"] == RUN + timedelta(hours=3)
    rain = farm.forecast_units(fc, models, "rain3h")
    assert rain.filter(pl.col("model") == AIFS).height == 0  # 6-hourly: not scored


def test_rain_blocks_from_native_steps_and_from_hourly_api_rows():
    models = [MODELS[m] for m in (D2, IFS025, EU)]
    # the API, every hour filled (stored before 2026-10-17): IFS 0.25° spreads its 3-hour
    # total of 1.5 mm over the hours 1-3
    spread = {(IFS025, RUN + timedelta(hours=h)): 0.5 for h in (1, 2, 3)}
    hourly = forecasts([m.id for m in models], rain={**spread, (D2, RUN + timedelta(hours=2)): 0.7})
    # the bucket: native steps only, the 3-hour total at its end
    native = (
        forecasts([IFS025, EU], rain={(IFS025, RUN + timedelta(hours=3)): 1.5})
        .with_columns(pl.lit("bucket").alias("source"))
        .filter(pl.col("lead_h") % (pl.when(pl.col("model") == IFS025).then(3).otherwise(1)) == 0)
        .filter((pl.col("model") != EU) | (pl.col("lead_h") <= 78) | (pl.col("lead_h") % 3 == 0))
    )
    for frame in (hourly, native):
        units = farm.forecast_units(frame, models, "rain3h")
        assert row(units, model=IFS025, end_lead=3)["forecast"] == pytest.approx(1.5)
        assert row(units, model=EU, end_lead=81)["forecast"] == pytest.approx(0.0)
    units = farm.forecast_units(hourly, models, "rain3h")
    assert row(units, model=D2, end_lead=3)["forecast"] == pytest.approx(0.7)
    assert units.filter(pl.col("model") == IFS025).height == 40  # every 3-hour block


def test_night_units():
    models = [MODELS[m] for m in (D2, AIFS)]
    temp = {(D2, utc(15, 4)): -1.0, (AIFS, utc(15, 0)): -3.0, (AIFS, utc(15, 4)): -9.0}
    units = farm.forecast_units(forecasts([D2, AIFS], temp=temp), models, "frost")
    first = row(units, model=D2, unit_end=utc(15, 7))
    assert (first["forecast"], first["end_lead"]) == (-1.0, 19)
    # AIFS: only 18 and 00 UTC (and 06) are its own hours; 04 UTC is interpolated
    assert row(units, model=AIFS, unit_end=utc(15, 7))["forecast"] == -3.0
    # the night of 14 Oct starts at lead 4 (16 UTC); D2 ends at 48 h: nights ending 19, 43
    assert sorted(units.filter(pl.col("model") == D2)["end_lead"].to_list()) == [19, 43]
    # a run starting inside a night does not score that night
    late = farm.forecast_units(
        forecasts([D2], run=utc(14, 18), horizon={D2: 48}), [MODELS[D2]], "frost"
    )
    assert late["unit_end"].to_list() == [utc(16, 7)]


def test_night_unit_needs_every_own_hour():
    fc = forecasts([D2]).filter(pl.col("valid_time") != utc(15, 2))
    units = farm.forecast_units(fc, [MODELS[D2]], "frost")
    assert units["unit_end"].to_list() == [utc(16, 7)]


# --- the fair set and scores ---------------------------------------------------------


def test_required_models_cover_the_whole_bin():
    models = [MODELS[m] for m in (D2, ALADIN, IFS025, AIFS)]
    cover = farm.coverage(forecasts([m.id for m in models]))
    req = farm.required(cover, models)
    pick = lambda e, b: sorted(req.filter(event=e, bin=b)["model"].to_list())  # noqa: E731
    assert pick("frost", "25-48") == sorted([D2, ALADIN, IFS025, AIFS])
    assert pick("frost", "49-72") == sorted([ALADIN, IFS025, AIFS])
    assert pick("frost", "73-120") == sorted([IFS025, AIFS])
    assert pick("gust", "1-6") == sorted([D2, ALADIN, IFS025])  # AIFS has no gusts
    assert pick("rain3h", "73-120") == [IFS025]


def test_fair_scores_and_counts():
    models = [MODELS[m] for m in (D2, ALADIN)]
    # night ending 15 Oct 07 UTC (bin 13-24): observed -0.5; D2 says -1 (hit), ALADIN +1 (miss)
    temp = {(D2, utc(15, 4)): -1.0, (ALADIN, utc(15, 4)): 1.0}
    # night ending 16 Oct 07 UTC (bin 25-48): no frost; ALADIN false alarm at -2.5
    temp[(ALADIN, utc(16, 3))] = -2.5
    gust = {(D2, utc(14, 14)): 16.0, (ALADIN, utc(14, 14)): 9.0}
    fc = forecasts([D2, ALADIN], temp=temp, gust=gust)
    obs = observations(utc(14, 13), utc(18, 0), temp={utc(15, 5): -0.5}, gust={utc(14, 15): 15.5})
    table, info = farm.farm_scores(fc, obs, models)
    hit = row(table, event="frost", threshold=0.0, bin="13-24", model=D2)
    assert (hit["hits"], hit["misses"], hit["false_alarms"], hit["correct_negatives"]) == (
        1,
        0,
        0,
        0,
    )
    assert (hit["pod"], hit["far"], hit["csi"], hit["events"], hit["units"]) == (
        1.0,
        0.0,
        1.0,
        1,
        1,
    )
    miss = row(table, event="frost", threshold=0.0, bin="13-24", model=ALADIN)
    assert (miss["misses"], miss["pod"], miss["bias"]) == (1, 0.0, 0.0)
    alarm = row(table, event="frost", threshold=-2.0, bin="25-48", model=ALADIN)
    assert (alarm["false_alarms"], alarm["far"], alarm["events"]) == (1, 1.0, 0)
    assert alarm["pod"] is None  # no observed event
    g = row(table, event="gust", threshold=15.0, bin="1-6", model=D2)
    assert (g["hits"], g["units"], g["runs"], g["stations"]) == (1, 2, 1, 1)
    assert row(table, event="gust", threshold=15.0, bin="1-6", model=ALADIN)["misses"] == 1
    # the set shrinks: after 48 h, where D2 has ended, ALADIN alone (to 72 h)
    frost = table.filter(event="frost", threshold=0.0)
    assert sorted(frost.filter(bin="25-48")["model"].to_list()) == sorted([D2, ALADIN])
    assert frost.filter(bin="49-72")["model"].to_list() == [ALADIN]
    assert set(frost["bin"]) == {"13-24", "25-48", "49-72"}
    assert info["runs"] == 1 and info["stations"] == 1
    doc = farm.document(table, info, datetime(2026, 10, 15, tzinfo=UTC), {D2: "ICON-D2"})
    assert doc["columns"] == farm.COLUMNS
    assert doc["bins"][0] == "1-6" and doc["small_sample"] == 20
    assert doc["models"][D2]["name"] == "ICON-D2"
    assert doc["events"]["frost"]["op"] == "<="
    assert len(doc["rows"][0]) == len(farm.COLUMNS)
    assert farm.summary(table)


def test_a_unit_one_model_lacks_is_dropped_for_all():
    models = [MODELS[m] for m in (D2, ALADIN)]
    fc = forecasts([D2, ALADIN]).filter(
        ~((pl.col("model") == ALADIN) & (pl.col("valid_time") == utc(14, 14)))
    )
    obs = observations(utc(14, 13), utc(18, 0))
    table, _ = farm.farm_scores(fc, obs, models)
    first = table.filter(event="rain3h", threshold=0.5, bin="1-6")
    assert first["units"].to_list() == [1, 1]  # the block ending 15 UTC is gone for both


def test_ets_matches_the_formula():
    counts = pl.DataFrame(
        {"hits": [8], "misses": [2], "false_alarms": [3], "correct_negatives": [87]}
    )
    r = farm.scores(counts).row(0, named=True)
    random_hits = 11 * 10 / 100
    assert r["pod"] == pytest.approx(0.8)
    assert r["far"] == pytest.approx(3 / 11)
    assert r["csi"] == pytest.approx(8 / 13)
    assert r["ets"] == pytest.approx((8 - random_hits) / (13 - random_hits))
    assert r["bias"] == pytest.approx(1.1)


def test_runs_without_gust_column():
    fc = forecasts([D2, ALADIN]).drop("wind_gusts_10m")
    obs = observations(utc(14, 13), utc(18, 0))
    table, _ = farm.farm_scores(fc, obs, [MODELS[D2], MODELS[ALADIN]])
    assert "gust" not in set(table["event"]) and "frost" in set(table["event"])


def test_gusts_from_fewer_run_hours_than_temperature():
    models = [MODELS[m] for m in (D2, ALADIN)]
    old = forecasts([D2, ALADIN], run=utc(14, 6)).with_columns(
        pl.lit(None, pl.Float32).alias("wind_gusts_10m")
    )
    cover = farm.coverage(pl.concat([forecasts([D2, ALADIN]), old]))
    req = farm.required(cover, models)
    assert sorted(req.filter(event="gust", bin="1-6")["model"].to_list()) == sorted([D2, ALADIN])


def test_a_model_with_few_runs_does_not_cut_the_runs_of_the_others():
    models = [MODELS[m] for m in (D2, ALADIN)]
    runs = [RUN + timedelta(days=k) for k in range(5)]
    # ALADIN (as if added recently) has only the last of five runs
    fc = pl.concat([forecasts([D2], run=r) for r in runs] + [forecasts([ALADIN], run=runs[-1])])
    obs = observations(utc(14, 13), utc(23, 0))
    table, info = farm.farm_scores(fc, obs, models)
    assert set(table["model"]) == {D2}
    assert info["runs"] == 5
    assert info["short_record"] == {ALADIN: {"runs": 1, "of": 5, "coverage": 0.2}}
    doc = farm.document(table, info, datetime(2026, 10, 16, tzinfo=UTC))
    assert doc["short_record"] == info["short_record"]
