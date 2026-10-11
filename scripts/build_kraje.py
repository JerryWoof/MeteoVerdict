# /// script
# requires-python = ">=3.12"
# dependencies = ["shapely>=2.1"]
# ///
"""Rebuild src/meteoverdict/data/kraje.geojson from the ČÚZK kraj boundaries.

Source: ČÚZK INSPIRE Administrative Units (CC BY 4.0), as converted to GeoJSON by
https://github.com/siwekm/czech-geojson (CC BY 4.0), pinned to one commit.
The 14 polygons are simplified together with ``shapely.coverage_simplify`` so that
neighbouring kraje keep identical shared borders (no gaps, no overlaps).

Run: uv run scripts/build_kraje.py
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import shapely
from shapely.geometry import mapping, shape

COMMIT = "6e77140c48483a08ecd2b8debce1f22f101db463"
URL = f"https://raw.githubusercontent.com/siwekm/czech-geojson/{COMMIT}/kraje.json"
TOLERANCE_DEG = 0.002  # max border shift measured at about 0.006° (≈ 0.6 km)
DECIMALS = 4  # ≈ 10 m
OUT = Path(__file__).resolve().parents[1] / "src" / "meteoverdict" / "data" / "kraje.geojson"


def _round(coords):
    if isinstance(coords[0], float | int):
        return [round(c, DECIMALS) for c in coords]
    return [_round(c) for c in coords]


def main() -> None:
    with urllib.request.urlopen(URL, timeout=120) as response:
        source = json.load(response)
    features = source["features"]
    simplified = shapely.coverage_simplify([shape(f["geometry"]) for f in features], TOLERANCE_DEG)
    out = {
        "type": "FeatureCollection",
        "source": f"ČÚZK INSPIRE Administrative Units (CC BY 4.0) via {URL}",
        "features": [
            {
                "type": "Feature",
                # "CZ0100000000" → NUTS 3 code "CZ010"
                "properties": {"code": f["id"][:5], "name": f["name"]},
                "geometry": {**mapping(geom), "coordinates": _round(mapping(geom)["coordinates"])},
            }
            for f, geom in zip(features, simplified, strict=True)
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
