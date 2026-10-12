from datetime import UTC, date, datetime

import polars as pl

from meteoverdict import partitions


def rows(day: int, **extra) -> pl.DataFrame:
    return pl.DataFrame(
        {"key": [f"k{day}"], "time": [datetime(2026, 9, day, tzinfo=UTC)], "n": [day], **extra}
    )


def test_a_column_added_later_is_merged_with_old_files(tmp_path):
    partitions.write_monthly(rows(1), tmp_path, ["key", "time"])
    partitions.write_monthly(rows(2, a_30=[1]), tmp_path, ["key", "time"])
    stored = pl.read_parquet(tmp_path / "2026-09.parquet").sort("time")
    assert stored.select("n", "a_30").rows() == [(1, None), (2, 1)]


def test_months_with_different_columns_are_read_together(tmp_path):
    partitions.write_monthly(rows(30, a_30=[1]), tmp_path, ["key", "time"])
    october = pl.DataFrame({"key": ["k"], "time": [datetime(2026, 10, 1, tzinfo=UTC)], "n": [0]})
    partitions.write_monthly(october, tmp_path, ["key", "time"])
    # the newer month lacks the column; reading must not depend on the file order
    both = partitions.scan_months(tmp_path, date(2026, 9, 1), date(2026, 10, 31)).collect()
    assert both.sort("time")["a_30"].to_list() == [1, None]
