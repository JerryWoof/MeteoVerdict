"""Rebuild src/meteoverdict/data/okres-elevations.csv, the elevation of every okres's
forecast point (``combine.okres_points``).

The temperature and wind corrections of the combined forecast depend on how high the
forecast point is above the okres's stations (``meteoverdict.mos``). The elevation is
Open-Meteo's (its Elevation API, the 90 m digital elevation model its forecasts are
corrected to at a point), fetched once and committed: rebuild it only when the forecast
points change (``tests/test_combine.py`` checks that they match).

Run (one Open-Meteo request):
    uv run scripts/build_okres_elevations.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx
import polars as pl

from meteoverdict import combine

URL = "https://api.open-meteo.com/v1/elevation"
DATA = Path(__file__).resolve().parents[1] / "src" / "meteoverdict" / "data"
OUT = DATA / combine.ELEVATIONS_FILE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    points = combine.okres_points().select("code", "lat", "lon").sort("code")
    params = {
        "latitude": ",".join(str(v) for v in points["lat"]),
        "longitude": ",".join(str(v) for v in points["lon"]),
    }
    response = httpx.get(URL, params=params, timeout=60)
    response.raise_for_status()
    elevation = response.json()["elevation"]
    if len(elevation) != points.height:
        raise SystemExit(f"{len(elevation)} elevations for {points.height} points")
    points.with_columns(pl.Series("elevation", elevation, pl.Float64)).write_csv(args.out)
    print(f"{points.height} okres points → {args.out}")


if __name__ == "__main__":
    main()
