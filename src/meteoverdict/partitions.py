"""Monthly Parquet partitions (``YYYY-MM.parquet``) that new rows are merged into."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl


def write_monthly(
    rows: pl.DataFrame, out_dir: Path, keys: list[str], time_column: str = "time"
) -> list[Path]:
    """Merge ``rows`` into ``out_dir/YYYY-MM.parquet`` by the month of ``time_column``.

    New rows replace stored rows with the same ``keys``; other stored rows are kept.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    by_month = rows.with_columns(pl.col(time_column).dt.strftime("%Y-%m").alias("_month"))
    for (month,), part in by_month.group_by("_month", maintain_order=True):
        path = out_dir / f"{month}.parquet"
        part = part.drop("_month")
        if path.exists():
            old = pl.read_parquet(path)
            kept = old.join(part.select(keys), on=keys, how="anti")
            part = pl.concat([kept, part], how="diagonal_relaxed")
        part.sort(keys).write_parquet(path, compression="zstd")
        written.append(path)
    return written


def months(first: date, last: date) -> list[str]:
    """``YYYY-MM`` of every month from ``first`` to ``last``."""
    found, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        found.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return found


def scan_months(folder: Path, first: date, last: date) -> pl.LazyFrame | None:
    """Lazily read the monthly files of ``folder`` that exist for ``first`` to ``last``."""
    paths = [folder / f"{m}.parquet" for m in months(first, last)]
    paths = [p for p in paths if p.exists()]
    if not paths:
        return None
    # files written before a column was added lack it: fill with nulls, in any order
    return pl.concat([pl.scan_parquet(p) for p in paths], how="diagonal_relaxed")


def month_end(day: date) -> date:
    """Last day of ``day``'s month."""
    following = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return following - timedelta(days=1)
