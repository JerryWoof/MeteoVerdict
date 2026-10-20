from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import blend_interval as bi

LAST = date(2026, 10, 10)


def _errors(days=30, okresy=("A", "B")):
    rows = []
    for k in range(days):
        day = LAST - timedelta(days=k)
        for okres in okresy:
            for station in range(3):
                for hour in bi.HOURS:
                    for lead in (1, 2):
                        # errors -2 … +2, 0.1 apart, the same every day
                        error = (station * 7 + k) % 41 / 10 - 2.0
                        rows.append((day, okres, f"{okres}{station}", lead, hour, error))
    return pl.DataFrame(rows, schema=bi.SCHEMA, orient="row")


def test_quantiles_of_the_last_window_with_the_national_row():
    table = bi.quantiles(_errors(), LAST)
    assert set(table["okres"]) == {"A", "B", "CZ"}
    row = table.filter((pl.col("okres") == "CZ") & (pl.col("lead") == 1) & (pl.col("hour") == 0))
    assert row["lo"][0] == pytest.approx(-2 + 0.4 * 0.07 * 10, abs=0.3)
    assert row["hi"][0] > 0 > row["lo"][0]
    assert row["n"][0] == 30 * 2 * 3


def test_only_the_window_counts():
    old = _errors(60).with_columns(
        pl.when(pl.col("date") <= LAST - timedelta(days=30))
        .then(pl.col("error") + 100)
        .otherwise(pl.col("error"))
        .alias("error")
    )
    table = bi.quantiles(old, LAST)
    assert table["hi"].max() < 5


def test_a_small_okres_takes_the_national_range():
    errors = pl.concat([_errors(okresy=("A",)), _errors(okresy=("S",)).head(10)])
    table = bi.quantiles(errors, LAST)
    assert "S" not in set(table["okres"])
    doc = bi.document(table, LAST, datetime(2026, 10, 11, tzinfo=UTC))
    assert set(doc["okresy"]) == {"A", "CZ"}
    assert bi.interval_at(doc, "S", 1, 0) == bi.interval_at(doc, "CZ", 1, 0)


def test_interpolated_in_the_hour_of_the_day():
    doc = {
        "hours": [0, 6, 12, 18],
        "okresy": {"CZ": {"1": {"lo": [-1, -2, -3, -4], "hi": [1, 2, 3, 4]}}},
    }
    assert bi.interval_at(doc, "A", 1, 3) == (-1.5, 1.5)
    assert bi.interval_at(doc, "A", 1, 21) == pytest.approx((-2.5, 2.5))  # 18 → 24 (= 00)
    assert bi.interval_at(doc, "A", 5, 3) is None


def test_the_range_is_added_to_the_hourly_forecast():
    now = datetime(2026, 10, 11, 4, tzinfo=UTC)
    doc = {
        "hours": [0, 6, 12, 18],
        "okresy": {
            "CZ": {"1": {"lo": [-1] * 4, "hi": [2] * 4}, "2": {"lo": [-2] * 4, "hi": [3] * 4}}
        },
    }
    hourly = pl.DataFrame(
        {
            "okres": ["A", "A"],
            "time": [now + timedelta(hours=2), now + timedelta(hours=50)],
            "temperature_2m": [10.0, 12.0],
        }
    ).cast({"time": pl.Datetime("us", "UTC")})
    got = bi.add_interval(hourly, doc, now)
    assert got["temperature_2m_lo"].to_list() == [9.0, 10.0]
    assert got["temperature_2m_hi"].to_list() == [12.0, 15.0]
    none = bi.add_interval(hourly, None, now)
    assert none["temperature_2m_lo"].null_count() == 2


def test_an_old_or_broken_file_is_not_used(tmp_path):
    path = tmp_path / bi.FILE
    assert bi.load(path) is None
    doc = bi.document(bi.quantiles(_errors(), LAST), LAST, datetime(2026, 10, 11, tzinfo=UTC))
    bi.write(doc, path)
    assert bi.load(path, datetime(2026, 10, 12, tzinfo=UTC)) is not None
    assert bi.load(path, datetime(2026, 11, 12, tzinfo=UTC)) is None
    path.write_text("{", "utf-8")
    assert bi.load(path) is None


def test_merge_replaces_days_and_drops_old_ones(tmp_path):
    path = tmp_path / bi.ASSET
    bi.merge(path, _errors(3), LAST - timedelta(days=5))
    bi.merge(
        path,
        _errors(1).with_columns(pl.lit(9.0, pl.Float32).alias("error")),
        LAST - timedelta(days=5),
    )
    back = pl.read_parquet(path)
    assert back.filter(pl.col("date") == LAST)["error"].unique().to_list() == [9.0]
    assert back["date"].n_unique() == 3
