"""Monthly Parquet partitions (``YYYY-MM.parquet``) that new rows are merged into."""

from __future__ import annotations

from pathlib import Path

import polars as pl


def write_monthly(rows: pl.DataFrame, out_dir: Path, keys: list[str]) -> list[Path]:
    """Merge ``rows`` into ``out_dir/YYYY-MM.parquet`` by the month of ``time``.

    New rows replace stored rows with the same ``keys``; other stored rows are kept.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    by_month = rows.with_columns(pl.col("time").dt.strftime("%Y-%m").alias("_month"))
    for (month,), part in by_month.group_by("_month", maintain_order=True):
        path = out_dir / f"{month}.parquet"
        part = part.drop("_month")
        if path.exists():
            old = pl.read_parquet(path)
            part = pl.concat([old.join(part.select(keys), on=keys, how="anti"), part])
        part.sort(keys).write_parquet(path, compression="zstd")
        written.append(path)
    return written
