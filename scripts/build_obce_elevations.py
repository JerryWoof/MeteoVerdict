"""Build src/meteoverdict/data/obce-elevations.csv: the obce of the given okresy (from
web/src/data/obce.json, ČÚZK RÚIAN definition points) with their elevation from the
Open-Meteo Elevation API (Copernicus DEM GLO-90). Test of the forecast for every obec.

    uv run python scripts/build_obce_elevations.py Litoměřice
"""

import json
import sys
from pathlib import Path

import httpx
import polars as pl

from meteoverdict import combine

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.open-meteo.com/v1/elevation"


def main(names: list[str]) -> None:
    doc = json.loads((ROOT / "web/src/data/obce.json").read_text())
    codes = dict(combine.okres_points().select("name", "code").rows())
    rows = []
    for name in names:
        index = doc["okresy"].index(name)
        obce = [o for o in doc["obce"] if o[1] == index]
        for start in range(0, len(obce), 100):
            part = obce[start : start + 100]
            response = httpx.get(
                API,
                params={
                    "latitude": ",".join(str(o[2]) for o in part),
                    "longitude": ",".join(str(o[3]) for o in part),
                },
                timeout=30,
            )
            response.raise_for_status()
            for o, elevation in zip(part, response.json()["elevation"], strict=True):
                rows.append((codes[name], o[0], o[2], o[3], elevation))
    table = pl.DataFrame(rows, schema=["okres", "name", "lat", "lon", "elevation"], orient="row")
    if table.select("okres", "name").is_duplicated().any():
        raise SystemExit("two obce of one okres share a name")
    path = ROOT / "src/meteoverdict/data/obce-elevations.csv"
    table.sort("okres", "name").write_csv(path)
    print(f"{path}: {table.height} obce")


if __name__ == "__main__":
    main(sys.argv[1:] or ["Litoměřice"])
