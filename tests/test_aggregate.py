import json
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import aggregate as agg

STATIONS = pl.DataFrame(
    {
        "id": ["s1", "s2", "s3"],
        "name": ["One", "Two", "Three"],
        "okres_code": ["CZ0201", "CZ0201", "CZ0642"],
        "okres": ["Benešov", "Benešov", "Brno-město"],
        "kraj_code": ["CZ020", "CZ020", "CZ064"],
        "kraj": ["Středočeský kraj", "Středočeský kraj", "Jihomoravský kraj"],
        "elevation_class": ["lowland", "upland", "lowland"],
    }
)


def score_rows(rows):
    """rows: (date, station, model, lead_day, abs_error) for temperature, n = 24."""
    return pl.DataFrame(
        [
            {
                "date": d,
                "station_id": s,
                "model": m,
                "lead_day": lead,
                "variable": "temperature_2m",
                "period_h": 0,
                "n": 24,
                "sum_err": err * 24,
                "sum_abs_err": err * 24,
                "sum_sq_err": err * err * 24,
            }
            for d, s, m, lead, err in rows
        ]
    )


DAY = date(2026, 9, 30)


@pytest.mark.parametrize(
    ("day", "start"),
    [
        (date(2026, 9, 30), date(2026, 9, 1)),
        (date(2026, 12, 5), date(2026, 12, 1)),
        (date(2027, 1, 15), date(2026, 12, 1)),
        (date(2027, 2, 28), date(2026, 12, 1)),
        (date(2026, 3, 1), date(2026, 3, 1)),
        (date(2026, 8, 31), date(2026, 6, 1)),
    ],
)
def test_season_start(day, start):
    assert agg.season_start(day) == start


def test_windows():
    assert agg.window_start("90d", DAY, date(2024, 1, 1)) == date(2026, 7, 3)
    assert agg.window_start("all", DAY, date(2024, 1, 1)) == date(2024, 1, 1)
    with pytest.raises(ValueError):
        agg.window_start("year", DAY, DAY)


def test_only_days_every_covering_model_has_are_compared():
    days = [DAY - timedelta(days=i) for i in range(5)]
    scores = score_rows(
        [(d, "s1", "a", 1, 1.0) for d in days[1:]]
        + [(d, "s1", "b", 1, 2.0) for d in days[1:]]
        # model b covers s1 on 4 of 5 days (80 %), so it is compared, and the day it
        # lacks is dropped for a too
        + [(DAY, "s1", "a", 1, 9.0)]
    )
    table = agg.aggregate(scores, STATIONS, windows=("all",))
    cz = table.filter(pl.col("level") == "cz").select("model", "n", "mae", "days").rows()
    assert cz == [("a", 96, 1.0, 4), ("b", 96, 2.0, 4)]
    assert not table["short_record"].any()


def _with_new_model(old_days: int = 40, new_days: int = 10) -> pl.DataFrame:
    """Models a and b on ``old_days`` days, model c (added recently) on the last
    ``new_days`` of them, at all three stations."""
    days = [DAY - timedelta(days=i) for i in range(old_days)]
    rows = [
        (d, s, m, 1, e)
        for d in days
        for s in ("s1", "s2", "s3")
        for m, e in (("a", 1.0), ("b", 2.0))
    ]
    rows += [(d, s, "c", 1, 0.5) for d in days[:new_days] for s in ("s1", "s2", "s3")]
    return score_rows(rows)


def test_a_model_with_a_short_record_does_not_cut_the_others_days():
    # October 2026: eight models added with 10 days cut the 90-day window to 10 days
    table = agg.aggregate(_with_new_model(), STATIONS, windows=("90d",))
    cz = table.filter(pl.col("level") == "cz")
    got = {
        m: (d, s, round(c, 2))
        for m, d, s, c in cz.select("model", "days", "short_record", "coverage").rows()
    }
    assert got == {"a": (40, False, 1.0), "b": (40, False, 1.0), "c": (10, True, 0.25)}
    # its own rows: its own station-days, so its MAE is still its own
    assert cz.filter(pl.col("model") == "c")["mae"].item() == 0.5
    # every level and region compares a and b on all their days
    compared = table.filter(~pl.col("short_record"))
    assert set(compared["days"]) == {40}
    assert set(compared["model"]) == {"a", "b"}


def test_a_new_model_is_compared_once_it_has_enough_days():
    table = agg.aggregate(_with_new_model(40, 32), STATIONS, windows=("90d",))
    cz = table.filter(pl.col("level") == "cz")
    assert not cz["short_record"].any()
    assert set(cz["days"]) == {32}  # compared on the days all three have


def test_coverage_falls_back_to_all_models_when_none_has_enough():
    days = [DAY - timedelta(days=i) for i in range(4)]
    scores = score_rows(
        [(d, "s1", "a", 1, 1.0) for d in days[:2]] + [(d, "s1", "b", 1, 1.0) for d in days[2:]]
    )
    cover = agg.coverage(scores)
    assert cover["covered"].to_list() == [True, True]


def test_metadata_lists_the_models_left_out():
    table = agg.aggregate(_with_new_model(), STATIONS, windows=("90d",))
    meta = agg.metadata(table, {}, datetime(2026, 10, 16, tzinfo=UTC))
    assert meta["short_record"] == {
        "90d": {"c": {"coverage": 0.25, "days": 10, "variables": ["temperature_2m"]}}
    }
    assert meta["min_coverage"] == agg.MIN_COVERAGE


def test_regions_compare_all_their_models_on_the_same_stations():
    # like ICON-D2 at the eastern tip: model b has no score at s3 at all
    scores = score_rows(
        [
            (DAY, "s1", "a", 1, 1.0),
            (DAY, "s1", "b", 1, 2.0),
            (DAY, "s3", "a", 1, 3.0),
        ]
    )
    table = agg.aggregate(scores, STATIONS, windows=("all",))

    def rows(level, region):
        here = table.filter(pl.col("level") == level, pl.col("region") == region)
        return here.select("model", "stations", "mae").rows()

    # Czechia: s3 lacks model b, so it is left out for model a too
    assert rows("cz", "cz") == [("a", 1, 1.0), ("b", 1, 2.0)]
    # s3's kraj and the station itself only have model a: still scored
    assert rows("kraj", "CZ064") == [("a", 1, 3.0)]
    assert rows("station", "s3") == [("a", 1, 3.0)]


def test_a_window_starts_no_earlier_than_the_first_scored_day():
    rows = [(DAY, "s1", m, 1, 1.0) for m in ("a", "b")]
    table = agg.aggregate(score_rows(rows), STATIONS, windows=("90d",))
    assert set(table["from"]) == {DAY}


def test_common_days_are_per_lead_day():
    scores = score_rows(
        [
            (DAY, "s1", "a", 1, 1.0),
            (DAY, "s1", "b", 1, 2.0),
            (DAY, "s2", "a", 2, 3.0),  # only model a has lead day 2: kept
        ]
    )
    table = agg.aggregate(scores, STATIONS, windows=("all",))
    lead2 = table.filter(pl.col("level") == "cz", pl.col("lead_day") == 2)
    assert lead2.select("model", "mae").rows() == [("a", 3.0)]


def test_levels_and_station_minimum():
    rows = [(DAY, s, m, 1, e) for s in ("s1", "s2", "s3") for m, e in (("a", 1.0), ("b", 2.0))]
    table = agg.aggregate(score_rows(rows), STATIONS, windows=("all",))
    levels = table.filter(pl.col("model") == "a").select(
        "level", "region", "stations", "enough_stations"
    )
    got = {(r[0], r[1]): (r[2], r[3]) for r in levels.rows()}
    assert got[("cz", "cz")] == (3, True)
    assert got[("kraj", "CZ020")] == (2, False)
    assert got[("okres", "CZ0201")] == (2, False)
    assert got[("elevation", "lowland")] == (2, False)
    assert got[("station", "s3")] == (1, True)  # a station is always rankable on its own


def test_window_filters_old_days():
    old = DAY - timedelta(days=200)
    rows = [(d, "s1", m, 1, e) for d in (old, DAY) for m, e in (("a", 1.0), ("b", 1.0))]
    table = agg.aggregate(score_rows(rows), STATIONS)
    days = {
        w: d
        for w, d in table.filter(pl.col("level") == "cz", pl.col("model") == "a")
        .select("window", "days")
        .rows()
    }
    assert days == {"90d": 1, "season": 1, "all": 2, "mam": 1, "son": 1}  # 14 Mar, 30 Sep


def test_season_windows_span_all_years():
    days = [date(2024, 12, 31), date(2025, 1, 15), date(2025, 7, 1), date(2026, 2, 1), DAY]
    rows = [(d, "s1", m, 1, 1.0) for d in days for m in ("a", "b")]
    table = agg.aggregate(score_rows(rows), STATIONS)
    winter = table.filter(
        pl.col("level") == "cz", pl.col("model") == "a", pl.col("window") == "djf"
    )
    # from/to: the first and last scored day inside the season's months
    span = (3, date(2024, 12, 31), date(2026, 2, 1))
    assert winter.select("days", "from", "to").row(0) == span
    start, days_filter = agg.window_days("jja", DAY, date(2024, 1, 1))
    picked = pl.DataFrame({"date": days}).filter(days_filter)["date"].to_list()
    assert (start, picked) == (date(2024, 1, 1), [date(2025, 7, 1)])


def test_meta_windows_of_the_seasons_span_their_scored_days():
    # scored 10 Aug to 30 Sep (as published on 15 Oct 2026): jja must not end on 30 Sep
    days = [date(2026, 8, 10) + timedelta(days=k) for k in range(52)]
    rows = [(d, "s1", m, 1, 1.0) for d in days for m in ("a", "b")]
    table = agg.aggregate(score_rows(rows), STATIONS)
    meta = agg.metadata(table, {}, datetime(2026, 10, 15, 10, 6, tzinfo=UTC))
    assert meta["as_of"] == "2026-09-30"
    assert meta["windows"]["jja"] == {"from": "2026-08-10", "to": "2026-08-31"}
    assert meta["windows"]["son"] == {"from": "2026-09-01", "to": "2026-09-30"}
    assert meta["windows"]["90d"] == {"from": "2026-08-10", "to": "2026-09-30"}
    assert meta["windows"]["season"] == {"from": "2026-09-01", "to": "2026-09-30"}
    assert "djf" not in meta["windows"]  # no scored winter day: no rows


def test_no_scores_is_an_error():
    empty = score_rows([(DAY, "s1", "a", 1, 1.0)]).head(0)
    with pytest.raises(ValueError, match="no scores"):
        agg.aggregate(empty, STATIONS)


def test_json_output(tmp_path):
    rows = [(DAY, s, m, 1, e) for s in ("s1", "s2", "s3") for m, e in (("a", 1.23456), ("b", 2.0))]
    table = agg.aggregate(score_rows(rows), STATIONS, windows=("all",))
    meta = agg.metadata(table, {"a": "Model A", "b": "Model B"}, datetime(2026, 10, 12, tzinfo=UTC))
    written = agg.write_json(table, tmp_path, meta)
    assert tmp_path / "meta.json" in written
    doc = json.loads((tmp_path / "all" / "kraj" / "temperature_2m.json").read_text())
    assert doc["columns"][:4] == ["region", "region_name", "lead_day", "model"]
    row = dict(zip(doc["columns"], doc["rows"][0], strict=True))
    assert row["mae"] == 1.235 and row["enough_stations"] is False
    saved = json.loads((tmp_path / "meta.json").read_text())
    assert saved["as_of"] == "2026-09-30" and saved["min_stations"] == agg.MIN_STATIONS
    assert "CC BY-SA 4.0" in saved["licence"]


def test_station_positions_for_the_map(tmp_path):
    stations = STATIONS.with_columns(
        lat=pl.Series([50.0077777, 49.1, 49.2]), lon=pl.lit(14.4), active=pl.lit(True)
    )
    path = agg.write_stations(stations, tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["columns"] == ["id", "name", "lat", "lon", "okres_code", "kraj_code", "active"]
    assert doc["rows"][0] == ["s1", "One", 50.00778, 14.4, "CZ0201", "CZ020", True]


def test_daily_error_series_per_station(tmp_path):
    old = DAY - timedelta(days=agg.SERIES_DAYS)  # just outside the 90 days
    days = (old, DAY - timedelta(days=1), DAY)
    rows = [(d, "s1", m, 1, e) for d in days for m, e in (("a", 1.234), ("b", 2.0))]
    rows.append((DAY, "s2", "a", 3, 1.0))  # D+3 is not kept
    written = agg.write_series(score_rows(rows), tmp_path, DAY, ("temperature_2m",))
    assert [p.name for p in written] == ["s1.json"]
    doc = json.loads(written[0].read_text(encoding="utf-8"))
    assert (doc["from"], doc["to"]) == ("2026-07-03", "2026-09-30")
    series = doc["series"]["temperature_2m"]["1"]
    assert sorted(series) == ["a", "b"] and len(series["a"]) == agg.SERIES_DAYS
    assert series["a"][-2:] == [1.23, 1.23] and series["a"][0] is None


def test_json_leaves_out_empty_columns_and_native_precipitation(tmp_path):
    rows = [(DAY, s, m, 1, 1.0) for s in ("s1", "s2", "s3") for m in ("a", "b")]
    scores = pl.concat(
        [score_rows(rows), score_rows(rows).with_columns(variable=pl.lit("precipitation"))]
    )
    table = agg.aggregate(scores, STATIONS, windows=("all",))
    written = agg.write_json(table, tmp_path, {})
    assert not any(p.name == "precipitation.json" for p in written)
    doc = json.loads((tmp_path / "all" / "cz" / "temperature_2m.json").read_text())
    assert "pod_5" not in doc["columns"] and "mae" in doc["columns"]


# --- stations by kind (network level) ---------------------------------------------------
MAIN = "0-20000-0-11518"  # a main WMO station
NETWORK_STATIONS = pl.concat(
    [
        STATIONS,
        STATIONS.head(1).with_columns(id=pl.lit(MAIN), name=pl.lit("Main")),
    ]
)


def test_main_stations_are_compared_on_their_own():
    rows = [(DAY, s, m, 1, e) for s in ("s1", "s2") for m, e in (("a", 2.0), ("b", 1.0))]
    rows += [(DAY, MAIN, "a", 1, 0.5), (DAY, MAIN, "b", 1, 1.5)]
    table = agg.aggregate(score_rows(rows), NETWORK_STATIONS, windows=("all",))
    network = table.filter(pl.col("level") == "network")
    columns = ("region", "model", "stations", "mae")
    got = {(r, m): (n, mae) for r, m, n, mae in network.select(columns).rows()}
    assert got == {
        ("main", "a"): (1, 0.5),
        ("main", "b"): (1, 1.5),
        ("other", "a"): (2, 2.0),
        ("other", "b"): (2, 1.0),
    }
    kinds = pl.DataFrame({"id": [MAIN, "0-203-0-11518", "s1"]}).select(
        agg.network_class(pl.col("id"))
    )
    assert kinds.to_series().to_list() == ["main", "other", "other"]


# --- bias-corrected MAE -----------------------------------------------------------------
def slot_rows(rows, variable="wind_speed_10m"):
    """rows: (date, station, model, lead_day, hour, error): one pair per row."""
    return pl.DataFrame(
        [
            {
                "date": d,
                "station_id": s,
                "model": m,
                "lead_day": lead,
                "variable": f"{variable}_{h:02d}utc",
                "period_h": 0,
                "n": 1,
                "sum_err": e,
                "sum_abs_err": abs(e),
                "sum_sq_err": e * e,
            }
            for d, s, m, lead, h, e in rows
        ]
    )


def test_the_bias_comes_only_from_days_known_before_the_forecast():
    days = [DAY - timedelta(days=k) for k in range(40)]
    # a constant +2 bias, and a wild error on the last day that must not leak into it
    rows = [(d, "s1", "a", 1, 0, 2.0) for d in days[1:]] + [(DAY, "s1", "a", 1, 0, 10.0)]
    out = agg.bias_corrected(slot_rows(rows))
    last = out.filter(pl.col("date") == DAY).row(0, named=True)
    assert last["bias"] == pytest.approx(2.0)
    assert last["abs_err_bc"] == pytest.approx(8.0)
    # D+1 on DAY - 1 may use days up to DAY - 3 only: training ends on d - N - 1
    yesterday = out.filter(pl.col("date") == DAY - timedelta(days=1)).row(0, named=True)
    assert yesterday["bias"] == pytest.approx(2.0)
    # the first days have too few training days
    first = out.filter(pl.col("date") <= days[-1] + timedelta(days=agg.BIAS_MIN_DAYS))
    assert first["bias"].is_null().all()


def test_the_training_window_is_the_last_days_before_the_forecast():
    days = [DAY - timedelta(days=k) for k in range(60)]
    # error 5 long ago, 1 in the last 30 days before the D+2 forecast for DAY was made
    rows = [
        (d, "s1", "a", 2, 12, 1.0 if (DAY - d).days <= 2 + agg.BIAS_TRAINING_DAYS else 5.0)
        for d in days
    ]
    out = agg.bias_corrected(slot_rows(rows))
    last = out.filter(pl.col("date") == DAY).row(0, named=True)
    # days DAY-32 … DAY-3: 30 days, all with error 1
    assert last["bias"] == pytest.approx(1.0)


def test_bias_corrected_mae_next_to_the_raw_one():
    days = [DAY - timedelta(days=k) for k in range(30)]
    slots = []
    daily = []
    for d in days:
        for s in ("s1", "s2", "s3"):
            # a: always 3 too strong (MAE 3, nothing left once the bias is removed);
            # b: ±1 on alternate days, no bias (MAE 1, stays 1)
            e_b = 1.0 if d.toordinal() % 2 else -1.0
            for model, e in (("a", 3.0), ("b", e_b)):
                slots += [(d, s, model, 1, h, e) for h in (0, 6, 12, 18)]
                daily.append(
                    {
                        "date": d, "station_id": s, "model": model, "lead_day": 1,
                        "variable": "wind_speed_10m", "period_h": 0, "n": 4,
                        "sum_err": 4 * e, "sum_abs_err": 4 * abs(e), "sum_sq_err": 4 * e * e,
                    }
                )  # fmt: skip
    scores = pl.concat([pl.DataFrame(daily), slot_rows(slots)], how="diagonal_relaxed")
    table = agg.aggregate(scores, STATIONS, windows=("all",))
    cz = table.filter(pl.col("level") == "cz", pl.col("variable") == "wind_speed_10m")
    got = {m: (mae, bc) for m, mae, bc in cz.select("model", "mae", "mae_bc").rows()}
    assert got["a"] == (pytest.approx(3.0), pytest.approx(0.0))
    # b: the bias of a training window is about 0 (± 1 / days), so its MAE stays about 1
    assert got["b"] == (pytest.approx(1.0), pytest.approx(1.0, abs=0.05))
    # the per-hour wind rows are not aggregated on their own; no correction per station
    assert not table["variable"].str.starts_with("wind_speed_10m_").any()
    station = table.filter(pl.col("level") == "station", pl.col("variable") == "wind_speed_10m")
    assert station["mae_bc"].is_null().all()


def test_bias_corrected_pairs_are_the_same_for_every_model():
    days = [DAY - timedelta(days=k) for k in range(30)]
    slots = [(d, "s1", "a", 1, 0, 1.0) for d in days]
    # model b's per-hour rows start later: a is corrected only on b's days too
    slots += [(d, "s1", "b", 1, 0, 2.0) for d in days[:15]]
    daily = [
        {
            "date": d, "station_id": "s1", "model": m, "lead_day": 1, "variable": "temperature_2m",
            "period_h": 0, "n": 1, "sum_err": 1.0, "sum_abs_err": 1.0, "sum_sq_err": 1.0,
        }
        for d in days for m in ("a", "b")
    ]  # fmt: skip
    scores = pl.concat(
        [pl.DataFrame(daily), slot_rows(slots, "temperature_2m")], how="diagonal_relaxed"
    )
    table = agg.aggregate(scores, STATIONS, windows=("all",))
    cz = table.filter(pl.col("level") == "cz", pl.col("variable") == "temperature_2m")
    n_bc = dict(cz.select("model", "n_bc").rows())
    # b has 10 training days (its days up to d - 2) from its 12th day on: 4 of its 15
    # days, and a is corrected on those same 4 only
    assert n_bc["a"] == n_bc["b"] == 15 - agg.BIAS_MIN_DAYS - 1


def test_event_skill_at_the_new_thresholds_is_published(tmp_path):
    rows = []
    for d in [DAY - timedelta(days=k) for k in range(4)]:
        for s in ("s1", "s2", "s3"):
            for m, hit in (("a", True), ("b", False)):
                rows.append(
                    {
                        "date": d, "station_id": s, "model": m, "lead_day": 1,
                        "variable": "precipitation_daily", "period_h": 24, "n": 1,
                        "sum_err": 0.0, "sum_abs_err": 1.0, "sum_sq_err": 1.0,
                        # observed ≥ 1 mm on the first two days; a forecasts it, b never
                        "a_1": int(hit and d >= DAY - timedelta(days=1)),
                        "b_1": 0,
                        "c_1": int(not hit and d >= DAY - timedelta(days=1)),
                        "d_1": int(d < DAY - timedelta(days=1)),
                    }
                )  # fmt: skip
    table = agg.aggregate(pl.DataFrame(rows), STATIONS, windows=("all",))
    cz = table.filter(pl.col("level") == "cz")
    assert dict(cz.select("model", "ets_1").rows()) == {"a": 1.0, "b": 0.0}
    agg.write_json(table, tmp_path, {})
    doc = json.loads((tmp_path / "all" / "cz" / "precipitation_daily.json").read_text())
    assert {"ets_1", "pod_1", "far_1"} <= set(doc["columns"])
    assert "ets_10" not in doc["columns"]  # no counts at 10 mm in these rows
    station = json.loads((tmp_path / "all" / "station" / "precipitation_daily.json").read_text())
    assert "ets_1" not in station["columns"] and "mae" in station["columns"]  # file size
