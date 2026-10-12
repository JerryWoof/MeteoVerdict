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
    yesterday = DAY - timedelta(days=1)
    scores = score_rows(
        [
            (yesterday, "s1", "a", 1, 1.0),
            (yesterday, "s1", "b", 1, 2.0),
            (DAY, "s1", "a", 1, 9.0),  # model b covers s1 but lacks this day: dropped for a too
        ]
    )
    table = agg.aggregate(scores, STATIONS, windows=("all",))
    cz = table.filter(pl.col("level") == "cz").select("model", "n", "mae", "days").rows()
    assert cz == [("a", 24, 1.0, 1), ("b", 24, 2.0, 1)]


def test_a_model_that_never_reaches_a_station_does_not_remove_it():
    # like ICON-D2 at the eastern tip: model b has no score at s3 at all
    scores = score_rows(
        [
            (DAY, "s1", "a", 1, 1.0),
            (DAY, "s1", "b", 1, 2.0),
            (DAY, "s3", "a", 1, 3.0),
        ]
    )
    table = agg.aggregate(scores, STATIONS, windows=("all",))
    cz = table.filter(pl.col("level") == "cz").select("model", "stations", "mae").rows()
    assert cz == [("a", 2, 2.0), ("b", 1, 2.0)]


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
    assert winter.select("days", "from", "to").row(0) == (3, date(2024, 12, 31), DAY)
    start, days_filter = agg.window_days("jja", DAY, date(2024, 1, 1))
    picked = pl.DataFrame({"date": days}).filter(days_filter)["date"].to_list()
    assert (start, picked) == (date(2024, 1, 1), [date(2025, 7, 1)])


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
