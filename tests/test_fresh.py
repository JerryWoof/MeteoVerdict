from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import blend, forecasts, fresh, runs, scoring
from meteoverdict.models import load_models

MODELS = {m.id: m for m in load_models()}
ICON_EU = MODELS["dwd_icon_eu"]  # D+1-4, runs 00/06/12/18
ICON_D2 = MODELS["dwd_icon_d2"]  # D+1, 3-hourly runs in the Previous Runs archive
UKMO = MODELS["ukmo_global_deterministic_10km"]  # 06/18 UTC runs not in the archive's D+2
GEM = MODELS["gem_global"]  # 00 and 12 UTC runs only
IFS = MODELS["ecmwf_ifs"]  # D+1-5


def utc(day, hour=0):
    return datetime(2026, 10, day, hour, tzinfo=UTC)


def code(run: datetime, lead: int) -> float:
    """A value that tells which run and lead it came from: DDHH.lead/1000."""
    return run.day * 100 + run.hour + lead / 1000


def single_runs(model, starts, station="s", last_lead=120, short=None):
    """Single-runs rows of ``model`` as the API stored them before 2026-10-17 (every hour,
    no ``source``); ``short``: run -> last lead."""
    rows = []
    for run in starts:
        for lead in range(1, (short or {}).get(run, last_lead) + 1):
            value = code(run, lead)
            rows.append((run, model.id, station, lead, run + timedelta(hours=lead), value,
                         0.1, 2.0, None))  # fmt: skip
    return pl.DataFrame(rows, schema=runs.HOURLY_SCHEMA, orient="row")


def every_run(first: datetime, last: datetime, hours=(0, 6, 12, 18)):
    found, run = [], first
    while run <= last:
        if run.hour in hours:
            found.append(run)
        run += timedelta(hours=6)
    return found


def rebuilt(frame, models):
    """D+N for the valid hours of 14 Oct."""
    return (
        fresh.previous_days(frame, models, utc(14), utc(14, 23))
        .collect()
        .sort("model", "lead_day", "time", "station_id")
    )


def value_at(table, hour: datetime, lead_day: int, model=None):
    rows = table.filter(pl.col("time") == hour, pl.col("lead_day") == lead_day)
    if model:
        rows = rows.filter(pl.col("model") == model)
    return rows["temperature_2m"].to_list()


def test_d_plus_n_is_the_newest_run_at_least_24n_hours_before():
    table = rebuilt(single_runs(ICON_EU, every_run(utc(9), utc(14, 18))), [ICON_EU])
    assert table.schema == pl.Schema(forecasts.SCHEMA)
    # 14 Oct 05 UTC at D+1: the newest run by 13 Oct 05 UTC is 13 Oct 00 UTC (lead 29)
    assert value_at(table, utc(14, 5), 1) == pytest.approx([code(utc(13, 0), 29)])
    assert value_at(table, utc(14, 6), 1) == pytest.approx([code(utc(13, 6), 24)])
    assert value_at(table, utc(14, 6), 2) == pytest.approx([code(utc(12, 6), 48)])
    assert value_at(table, utc(14, 23), 4) == pytest.approx([code(utc(10, 18), 101)])
    # every hour of every lead day of the model, nothing more (no D+5 for ICON-EU)
    assert table.group_by("lead_day").len().sort("lead_day").rows() == [
        (n, 24) for n in (1, 2, 3, 4)
    ]


def test_an_hour_whose_run_is_missing_is_left_out_not_taken_from_an_older_run():
    starts = [r for r in every_run(utc(9), utc(14, 18)) if r != utc(13, 6)]
    table = rebuilt(single_runs(ICON_EU, starts), [ICON_EU])
    d1 = table.filter(pl.col("lead_day") == 1)
    hours = sorted(t.hour for t in d1["time"])
    assert hours == [0, 1, 2, 3, 4, 5, *range(12, 24)]  # 06-11 needed the 13 Oct 06 run


def test_a_run_that_does_not_reach_the_hour_hands_over_to_the_one_before():
    # the 13 Oct 06 UTC run stops at lead 20 (like the shorter 06/18 UTC runs of IFS)
    starts = every_run(utc(9), utc(14, 18))
    table = rebuilt(single_runs(ICON_EU, starts, short={utc(13, 6): 20}), [ICON_EU])
    assert value_at(table, utc(14, 6), 1) == pytest.approx([code(utc(13, 0), 30)])


def test_models_with_runs_in_between_only_where_a_six_hourly_run_is_the_newest():
    table = rebuilt(single_runs(ICON_D2, every_run(utc(12), utc(14, 18)), last_lead=48), [ICON_D2])
    # the archive's 03, 09, 15 and 21 UTC runs make the hours 03-05, 09-11, … at D+1
    assert sorted(t.hour for t in table["time"]) == [0, 1, 2, 6, 7, 8, 12, 13, 14, 18, 19, 20]


def test_runs_the_archive_keeps_shorter_are_not_used_beyond():
    table = rebuilt(single_runs(UKMO, every_run(utc(9), utc(14, 18))), [UKMO])
    # D+1 from the 06 UTC run as usual, D+2 from the 00 UTC run (06/18 UTC: up to 47 h)
    assert value_at(table, utc(14, 6), 1) == pytest.approx([code(utc(13, 6), 24)])
    assert value_at(table, utc(14, 6), 2) == pytest.approx([code(utc(12, 0), 54)])


def test_two_runs_a_day():
    table = rebuilt(single_runs(GEM, every_run(utc(9), utc(14, 12), (0, 12))), [GEM])
    assert value_at(table, utc(14, 6), 1) == pytest.approx([code(utc(13, 0), 30)])
    assert value_at(table, utc(14, 12), 1) == pytest.approx([code(utc(13, 12), 24)])


def test_d_plus_5_only_120_hours_after_a_run():
    table = rebuilt(single_runs(IFS, every_run(utc(8), utc(14, 18))), [IFS])
    d5 = table.filter(pl.col("lead_day") == 5)
    assert sorted(t.hour for t in d5["time"]) == [0, 6, 12, 18]


def test_fill_adds_only_hours_the_previous_runs_lack():
    derived = rebuilt(single_runs(ICON_EU, every_run(utc(9), utc(14, 18))), [ICON_EU])
    # the backfill has D+1 up to 14 Oct 11 UTC (at another station too)
    have = derived.filter(pl.col("lead_day") == 1, pl.col("time") < utc(14, 12))
    have = pl.concat([have, have.with_columns(pl.lit("t").alias("station_id"))])
    merged, added = fresh.fill(have, derived)
    assert added.height == derived.height - 12
    assert added.filter(pl.col("lead_day") == 1)["time"].min() == utc(14, 12)
    assert merged.collect().height == have.height + added.height


def test_mark_says_which_scores_used_rebuilt_hours():
    added = pl.DataFrame(
        {"station_id": ["s"], "time": [utc(15, 0)], "model": ["m"], "lead_day": [1]},
        schema={k: forecasts.SCHEMA[k] for k in ("station_id", "time", "model", "lead_day")},
    )
    rows = [
        (date(2026, 10, 14), "m", 1, "temperature_2m"),  # 14 Oct hours: Previous Runs
        (date(2026, 10, 15), "m", 1, "temperature_2m"),  # 15 Oct 00 UTC rebuilt
        (date(2026, 10, 14), "m", 1, "precipitation_daily"),  # its 24:00 hour rebuilt
        (date(2026, 10, 14), "m", 1, "precipitation_24h"),  # 06-06 window, includes 00
        (date(2026, 10, 14), "m", 2, "temperature_2m"),  # another lead day
        (date(2026, 10, 15), blend.ID, 1, "temperature_2m"),  # a member was rebuilt
    ]
    scores = pl.DataFrame(
        rows, schema=["date", "model", "lead_day", "variable"], orient="row"
    ).with_columns(pl.col("lead_day").cast(pl.Int8), pl.lit(scoring.PREVIOUS_RUNS).alias("source"))
    marked = fresh.mark(scores, added)
    assert marked["source"].to_list() == [
        "previous_runs",
        "single_runs",
        "single_runs",
        "single_runs",
        "previous_runs",
        "single_runs",
    ]


def test_compare_finds_no_difference_between_identical_sources():
    derived = rebuilt(single_runs(ICON_EU, every_run(utc(9), utc(14, 18))), [ICON_EU])
    d1 = derived.filter(pl.col("lead_day") == 1)
    obs = d1.select(
        "station_id", "time", pl.lit("temperature_2m").alias("variable"),
        (pl.col("temperature_2m") - 1).alias("value"),
    )  # fmt: skip
    table = fresh.compare(derived, derived, obs, [ICON_EU])
    assert table["max_abs_diff"].max() == 0 and table["mae_diff"].abs().max() == 0
    temperature = table.filter(pl.col("variable") == "temperature_2m", pl.col("lead_day") == 1)
    assert temperature["mae_previous"].to_list() == pytest.approx([1.0], abs=1e-3)
    assert temperature["n_obs"].to_list() == [24]
    line = fresh.summary(table)
    # 4 x 24 precipitation values; temperature and wind at native hours (D+4 3-hourly)
    assert line.startswith("single runs vs Previous Runs on 256 overlapping values")
    assert line.endswith("MAE difference at most 0.000")
    assert fresh.summary(table.clear()) == (
        "no hour has both Previous Runs and single-runs forecasts yet"
    )


def test_sources_for_meta():
    scores = pl.DataFrame(
        {
            "date": [date(2026, 10, 1), date(2026, 10, 4), date(2026, 10, 15)],
            "source": [None, "previous_runs", "single_runs"],
        }
    )
    assert fresh.sources(scores) == {
        "previous_runs": {"from": "2026-10-01", "to": "2026-10-04"},
        "single_runs": {"from": "2026-10-15", "to": "2026-10-15"},
    }
    old = scores.drop("source")  # score files from before 2026-10-16
    assert fresh.sources(old) == {"previous_runs": {"from": "2026-10-01", "to": "2026-10-15"}}


def test_window_ends_with_the_hour_after_the_day():
    assert fresh.window(date(2026, 10, 15)) == (utc(15) - timedelta(days=29), utc(16))


def bucket_runs(model, starts, station="s"):
    """Single-runs rows as the bucket stores them: native steps only, each total over
    the step before (``runs.native``)."""
    rows = []
    for run in starts:
        for lead in range(1, 121):
            if model.native_hour(lead):
                step = model.step_at(lead)
                rows.append((run, model.id, station, lead, run + timedelta(hours=lead),
                             code(run, lead), 0.1 * step, 2.0, None, "bucket"))  # fmt: skip
    # as stored before the further variables (old files lack their columns)
    schema = {k: v for k, v in runs.SCHEMA.items() if k not in runs.EXTRA_VARIABLES}
    return pl.DataFrame(rows, schema=schema, orient="row")


def test_native_steps_spread_the_totals_and_keep_instants_at_native_hours():
    table = rebuilt(bucket_runs(ICON_EU, every_run(utc(9), utc(14, 18))), [ICON_EU])
    d4 = table.filter(pl.col("lead_day") == 4)  # leads 96-119: 3-hourly
    assert d4.height == 24  # every hour has its share of the 3-hour total
    assert d4["precipitation"].to_list() == pytest.approx([0.1] * 24)
    # temperature only at native hours: 14 Oct 21 UTC is lead 99 of the 10 Oct 18 run
    assert value_at(table, utc(14, 21), 4) == pytest.approx([code(utc(10, 18), 99)])
    assert value_at(table, utc(14, 23), 4) == [None]  # lead 101: not native, not invented
    # the hour is not taken from an older run either (its lead 107 is not native too)
    d1 = table.filter(pl.col("lead_day") == 1)
    assert d1["temperature_2m"].null_count() == 0  # hourly up to 78 h


def test_an_hour_the_expected_run_lacks_is_left_out_not_taken_from_an_older_run():
    rows = single_runs(ICON_EU, every_run(utc(9), utc(14, 18)))
    # the 13 Oct 06 UTC run has no row at 14 Oct 07 UTC (lead 25) but runs on
    rows = rows.filter(~((pl.col("run") == utc(13, 6)) & (pl.col("lead_h") == 25)))
    table = rebuilt(rows, [ICON_EU])
    assert value_at(table, utc(14, 7), 1) == []
    assert value_at(table, utc(14, 8), 1) == pytest.approx([code(utc(13, 6), 26)])


def test_spread_keeps_api_rows_from_before_as_they_are():
    old = single_runs(ICON_EU, [utc(13)])
    assert fresh.spread(old, [ICON_EU]).collect().height == old.height
    new = bucket_runs(MODELS["ecmwf_aifs025_single"], [utc(13)])
    spread = fresh.spread(new, [MODELS["ecmwf_aifs025_single"]]).collect().sort("lead_h")
    assert spread["lead_h"].to_list() == list(range(1, 121))
    assert spread["precipitation"].to_list() == pytest.approx([0.1] * 120)
    assert spread["temperature_2m"].null_count() == 100  # only at the 20 native hours
