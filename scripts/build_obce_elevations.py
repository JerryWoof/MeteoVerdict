"""Build src/meteoverdict/data/obce-elevations.csv: the obce of the given okresy (from
web/src/data/obce.json, ČÚZK RÚIAN definition points) with their elevation from the
Open-Meteo Elevation API (Copernicus DEM GLO-90) and their population on 1 January
(ČSÚ DataStat, set OBY02A, matched by okres and name). Test of the forecast for
every obec.

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


def main(names: list[str]) -> None:
    doc = json.loads((ROOT / "web/src/data/obce.json").read_text())
    codes = dict(combine.okres_points().select("name", "code").rows())
    year, people = population()
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
                code = codes[name]
                rows.append((code, o[0], o[2], o[3], elevation, people.get((code, o[0]))))
    columns = ["okres", "name", "lat", "lon", "elevation", "population"]
    table = pl.DataFrame(rows, schema=columns, orient="row")
    missing = table.filter(pl.col("population").is_null())["name"].to_list()
    if missing:
        print(f"no population for {len(missing)} obce: {', '.join(missing)}")
    if table.select("okres", "name").is_duplicated().any():
        raise SystemExit("two obce of one okres share a name")
    path = ROOT / "src/meteoverdict/data/obce-elevations.csv"
    table.sort("okres", "name").write_csv(path)
    print(f"{path}: {table.height} obce, population on 1 Jan {year}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["Litoměřice"])
