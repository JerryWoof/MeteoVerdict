"""Rebuild src/meteoverdict/data/run-stations.csv, the station subset of `mvd fetch-runs`.

The rule is ``meteoverdict.runs.select_stations`` (one station per okres, then the
mountain stations, then the stations farthest from the chosen ones, up to 100); it is
documented in docs/data-sources.md#the-station-subset. The subset is committed so that
it stays the same from run to run: rebuild it only on purpose (a station closed, or the
rule changed), as the run history at a dropped station ends.

Run (needs network for ČHMÚ's meta2):
    uv run mvd stations && uv run scripts/build_run_stations.py [--stations PATH]
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl

from meteoverdict import combine, runs
from meteoverdict.chmi import fetch_current_meta

OUT = Path(__file__).resolve().parents[1] / "src" / "meteoverdict" / "data" / runs.STATIONS_FILE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stations", type=Path, default=Path("data/stations.parquet"))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    stations = pl.read_parquet(args.stations)
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        meta2 = fetch_current_meta(client, 2, datetime.now(UTC).date())
    subset = runs.select_stations(stations, meta2, combine.okres_points())
    subset.write_csv(args.out)
    counts = subset.group_by("elevation_class").len().sort("elevation_class").rows()
    print(
        f"{subset.height} stations in {subset['okres_code'].n_unique()} okresy "
        f"({', '.join(f'{c} {n}' for c, n in counts)}) → {args.out}"
    )


if __name__ == "__main__":
    main()
