# /// script
# requires-python = ">=3.12"
# dependencies = ["pyproj>=3.7"]
# ///
"""Rebuild web/src/data/obce.json: every Czech municipality (obec) for the radar page's
place search, with its okres and the definition point (definiční bod) in WGS 84.

Source: ČÚZK RÚIAN, the state-level exchange file (VFR) "ST_UZSZ" (stát, územní prvky,
základní data), CC BY 4.0, https://vdp.cuzk.gov.cz/. Definition points are in S-JTSK
(EPSG:5514) and converted with pyproj.

Output (compact, about 100 kB gzipped):
  {"source": ..., "date": "YYYYMMDD", "okresy": ["Benešov", ...],
   "obce": [["Třeboň", <index into okresy>, lat, lon, population], ...]}

The population (ČSÚ, 1 January) comes from src/meteoverdict/data/obce-elevations.csv
(scripts/build_obce_elevations.py), matched by the definition point; the place search ranks
bigger places first with it. Missing there (a new obec): no fifth value.

Run: uv run scripts/build_municipalities.py [YYYYMMDD]
(the date of a monthly file: the last day of a month, default the end of last month)
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "src" / "data" / "obce.json"
PEOPLE = ROOT / "src" / "meteoverdict" / "data" / "obce-elevations.csv"
URL = "https://vdp.cuzk.gov.cz/vymenny_format/soucasna/{date}_ST_UZSZ.xml.zip"
NS = {
    "vf": "urn:cz:isvs:ruian:schemas:VymennyFormatTypy:v1",
    "obi": "urn:cz:isvs:ruian:schemas:ObecIntTypy:v1",
    "oki": "urn:cz:isvs:ruian:schemas:OkresIntTypy:v1",
    "gml": "http://www.opengis.net/gml/3.2",
}
DECIMALS = 4  # about 10 m
PRAHA = "554782"  # the capital belongs to no okres in RÚIAN; it is its own (LAU 1 CZ0100)
PRAHA_OKRES = "Hlavní město Praha"


def last_month_end(today: dt.date) -> str:
    return (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m%d")


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse(xml: io.BufferedIOBase) -> tuple[dict[str, str], list[tuple[str, str, float, float]]]:
    """Okres names by code, and (name, okres code, x, y) of every obec."""
    okresy: dict[str, str] = {}
    obce: list[tuple[str, str, float, float]] = []
    for _, element in ET.iterparse(xml, events=("end",)):
        kind = local(element.tag)
        if kind == "Okres" and element.find("oki:Nazev", NS) is not None:
            code = element.findtext("oki:Kod", namespaces=NS)
            okresy[code] = element.findtext("oki:Nazev", namespaces=NS)
            element.clear()
        elif kind == "Obec" and element.find("obi:Nazev", NS) is not None:
            pos = element.find(".//obi:DefinicniBod//gml:pos", NS)
            okres = element.findtext("obi:Okres/oki:Kod", namespaces=NS)
            if element.findtext("obi:Kod", namespaces=NS) == PRAHA:
                okres = PRAHA
            if pos is not None and okres:
                x, y = (float(v) for v in pos.text.split())
                obce.append((element.findtext("obi:Nazev", namespaces=NS), okres, x, y))
            element.clear()
    return okresy, obce


def population() -> dict[tuple[float, float], int]:
    """Population of each obec by its definition point (lat, lon), from PEOPLE."""
    if not PEOPLE.exists():
        return {}
    with PEOPLE.open(encoding="utf-8") as f:
        return {
            (float(r["lat"]), float(r["lon"])): int(float(r["population"]))
            for r in csv.DictReader(f)
            if r["population"]
        }


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else last_month_end(dt.date.today())
    url = URL.format(date=date)
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=300) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    with archive.open(archive.namelist()[0]) as xml:
        okresy, obce = parse(xml)
    okresy[PRAHA] = PRAHA_OKRES
    to_wgs = Transformer.from_crs("EPSG:5514", "EPSG:4326", always_xy=True)
    names = sorted({okresy[code] for _, code, _, _ in obce}, key=lambda s: s.lower())
    index = {name: i for i, name in enumerate(names)}
    people = population()
    rows = []
    for name, code, x, y in obce:
        lon, lat = to_wgs.transform(x, y)
        row = [name, index[okresy[code]], round(lat, DECIMALS), round(lon, DECIMALS)]
        if (row[2], row[3]) in people:
            row.append(people[(row[2], row[3])])
        rows.append(row)
    rows.sort(key=lambda r: (r[0].lower(), names[r[1]]))
    data = {
        "source": "ČÚZK RÚIAN (CC BY 4.0), municipality definition points, " + url,
        "date": date,
        "okresy": names,
        "obce": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(text + "\n", encoding="utf-8")
    print(f"{len(rows)} obce in {len(names)} okresy → {OUT}")


if __name__ == "__main__":
    main()
