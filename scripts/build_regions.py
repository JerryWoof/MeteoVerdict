# /// script
# requires-python = ">=3.12"
# dependencies = ["shapely>=2.1"]
# ///
"""Rebuild src/meteoverdict/data/{kraje,okresy}.geojson from the ČÚZK boundaries.

Source: ČÚZK INSPIRE Administrative Units (CC BY 4.0), as converted to GeoJSON by
https://github.com/siwekm/czech-geojson (CC BY 4.0), pinned to one commit.
Each level (14 kraje, 77 okresy) is simplified as one coverage with
``shapely.coverage_simplify`` so that neighbours keep identical shared borders (no gaps,
no overlaps).

Run: uv run scripts/build_regions.py
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import shapely
from shapely.geometry import mapping, shape

COMMIT = "6e77140c48483a08ecd2b8debce1f22f101db463"
SOURCE = f"https://raw.githubusercontent.com/siwekm/czech-geojson/{COMMIT}"
DATA = Path(__file__).resolve().parents[1] / "src" / "meteoverdict" / "data"
#: output file → (source file, length of the code taken from the feature id)
LEVELS = {
    "kraje.geojson": ("kraje.json", 5),  # "CZ0100000000" → NUTS 3 "CZ010"
    "okresy.geojson": ("okresy.json", 6),  # "CZ0201000000" → LAU 1 "CZ0201"
}
TOLERANCE_DEG = 0.002  # max border shift measured at about 0.006° (≈ 0.6 km)
DECIMALS = 4  # ≈ 10 m


def _round(coords):
    if isinstance(coords[0], float | int):
        return [round(c, DECIMALS) for c in coords]
    return [_round(c) for c in coords]


def build(source_file: str, code_length: int, out: Path) -> None:
    url = f"{SOURCE}/{source_file}"
    with urllib.request.urlopen(url, timeout=300) as response:
        features = json.load(response)["features"]
    simplified = shapely.coverage_simplify([shape(f["geometry"]) for f in features], TOLERANCE_DEG)
    doc = {
        "type": "FeatureCollection",
        "source": f"ČÚZK INSPIRE Administrative Units (CC BY 4.0) via {url}",
        "features": [
            {
                "type": "Feature",
                "properties": {"code": f["id"][:code_length], "name": f["name"]},
                "geometry": {**mapping(geom), "coordinates": _round(mapping(geom)["coordinates"])},
            }
            for f, geom in zip(features, simplified, strict=True)
        ],
    }
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KiB)")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for out, (source_file, code_length) in LEVELS.items():
        build(source_file, code_length, DATA / out)


if __name__ == "__main__":
    main()
