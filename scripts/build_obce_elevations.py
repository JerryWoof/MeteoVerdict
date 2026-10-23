"""Build src/meteoverdict/data/obce-elevations.csv: the obce of every okres (or of the
given ones) from web/src/data/obce.json (ČÚZK RÚIAN definition points), with their elevation
from the AWS Terrain Tiles (terrarium, zoom 11; EU-DEM here) and their population on 1 January
(ČSÚ DataStat, set OBY02A, matched by okres and name). Test of the forecast for
every obec.

    uv run python scripts/build_obce_elevations.py            # every okres
    uv run python scripts/build_obce_elevations.py Litoměřice # some
"""

import io
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
import polars as pl
from PIL import Image

from meteoverdict import regions

ROOT = Path(__file__).resolve().parent.parent
# population of every obec on 1 January of the latest year (CSV; Okres and Obec columns)
POPULATION = (
    "https://data.csu.gov.cz/api/dotaz/v1/data/sady/OBY02A/vlastni"
    "?format=CSV&IndicatorType=2406P&UZ35H=*&CasR.poslednich=1&kodZvlast=true"
)


def population() -> tuple[str, dict[tuple[str, str], int]]:
    """The year and (okres code, obec name) -> inhabitants; a name twice in an okres is left out."""
    response = httpx.get(POPULATION, timeout=300)
    response.raise_for_status()
    table = pl.read_csv(response.content, infer_schema=False).filter(pl.col("UZ35H.OBEC") != "")
    year = table["CasR"].unique().to_list()
    if len(year) != 1:
        raise SystemExit(f"population: expected one year, got {year}")
    keys = ["UZ35H.OKRES", "Okresy a obce-Obec"]
    unique = table.filter(~pl.struct(keys).is_duplicated())
    values = {(k, n): round(float(v)) for k, n, v in unique.select(*keys, "Hodnota").iter_rows()}
    return year[0], values


#: obce whose name is twice in one okres: ČSÚ names them by their SO ORP; ours (RÚIAN
#: definition points) are told apart by position (checked on the map 2026-10-18)
TWINS = {
    ("CZ0643", "Březina"): [((49.2816, 16.7495), "Šlapanice"), ((49.3212, 16.4214), "Tišnov")],
    ("CZ0321", "Mezholezy"): [
        ((49.4117, 13.1038), "Domažlice"),
        ((49.6246, 12.9049), "Horšovský Týn"),
    ],
}
#: ČSÚ's spelling of an SO ORP where it differs (seen 2026-10-18: "Horšovský Zýn")
CSU_ORP = {"Horšovský Týn": "Horšovský Zýn"}


def twin(code: str, name: str, lat: float, lon: float) -> str | None:
    """The SO ORP of an obec named twice in its okres, by its position; None otherwise."""
    for where, orp in TWINS.get((code, name), []):
        if abs(where[0] - lat) < 0.01 and abs(where[1] - lon) < 0.01:
            return orp
    return None


#: AWS Terrain Tiles (terrarium PNG, the radar base map's relief): height = R*256 + G +
#: B/256 - 32768 m; zoom 11 is a pixel of about 50 m here, and has no request limit
TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TILE_ZOOM = 11


def elevations(points: list[tuple[float, float]]) -> list[float]:
    """The height (m) of each (lat, lon) from the terrain tiles, nearest pixel."""
    n = 2**TILE_ZOOM
    where = []
    for lat, lon in points:
        x = (lon + 180) / 360 * n
        y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
        where.append((int(x), int(y), int((x % 1) * 256), int((y % 1) * 256)))

    def fetch(tile: tuple[int, int]) -> np.ndarray:
        for attempt in range(4):
            try:
                response = httpx.get(TILES.format(z=TILE_ZOOM, x=tile[0], y=tile[1]), timeout=60)
                response.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 3:
                    raise
        rgb = np.asarray(Image.open(io.BytesIO(response.content)).convert("RGB"), dtype=np.float64)
        return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768

    needed = sorted({(w[0], w[1]) for w in where})
    with ThreadPoolExecutor(16) as pool:
        tiles = dict(zip(needed, pool.map(fetch, needed), strict=True))
    print(f"{len(needed)} terrain tiles")
    return [round(float(tiles[(tx, ty)][py, px]), 1) for tx, ty, px, py in where]


def main(names: list[str]) -> None:
    doc = json.loads((ROOT / "web/src/data/obce.json").read_text())
    codes = dict(regions.okres_points().select("name", "code").rows())
    # ČÚZK's okres of Prague is "území Hlavního města Prahy", RÚIAN's obec list says the city
    codes["Hlavní město Praha"] = codes["území Hlavního města Prahy"]
    year, people = population()
    chosen = set(names) if names else set(doc["okresy"])
    places = []
    for name, index, lat, lon, *_ in doc["obce"]:  # a fifth value: the population
        okres = doc["okresy"][index]
        if okres not in chosen:
            continue
        code = codes[okres]
        orp = twin(code, name, lat, lon)
        key = f"{name} (SO ORP {CSU_ORP.get(orp, orp)})" if orp else name
        places.append((code, f"{name} ({orp})" if orp else name, lat, lon, people.get((code, key))))
    heights = elevations([(p[2], p[3]) for p in places])
    rows = [(*p[:4], h, p[4]) for p, h in zip(places, heights, strict=True)]
    columns = ["okres", "name", "lat", "lon", "elevation", "population"]
    table = pl.DataFrame(rows, schema=columns, orient="row")
    missing = table.filter(pl.col("population").is_null())
    if missing.height:
        print(f"no population for {missing.height} obce: {missing.select('okres', 'name').rows()}")
    if table.select("okres", "name").is_duplicated().any():
        raise SystemExit("two obce of one okres share a name")
    path = ROOT / "src/meteoverdict/data/obce-elevations.csv"
    table.sort("okres", "name").write_csv(path)
    okresy = table["okres"].n_unique()
    print(f"{path}: {table.height} obce in {okresy} okresy, population on 1 Jan {year}")


if __name__ == "__main__":
    main(sys.argv[1:])  # no names: every okres
