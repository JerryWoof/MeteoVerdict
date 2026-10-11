"""Station → kraj (region) and elevation class.

Kraj boundaries come from ``data/kraje.geojson`` (ČÚZK, CC BY 4.0, simplified by
scripts/build_kraje.py; borders shift by at most ~0.6 km). Stations in a kraj polygon
get that kraj. Stations just outside every polygon (on the national border, within
``BORDER_TOLERANCE_KM``) get the nearest kraj; the rest are outside Czechia.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from itertools import pairwise

import polars as pl

BORDER_TOLERANCE_KM = 2.0

#: Elevation classes (ROADMAP "Scope v1"): lowland < 400 m, upland 400 to 800 m, mountain > 800 m.
LOWLAND_BELOW_M = 400.0
MOUNTAIN_ABOVE_M = 800.0

Ring = list[tuple[float, float]]  # (lon, lat), closed


@dataclass(frozen=True)
class Kraj:
    code: str  # NUTS 3, e.g. "CZ010"
    name: str
    rings: tuple[Ring, ...]  # exterior first, then holes
    bbox: tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max

    def contains(self, lon: float, lat: float) -> bool:
        lon_min, lat_min, lon_max, lat_max = self.bbox
        if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
            return False
        # even-odd rule over all rings handles holes (Praha inside Středočeský kraj)
        return sum(_crossings(ring, lon, lat) for ring in self.rings) % 2 == 1

    def distance_km(self, lon: float, lat: float) -> float:
        """Approximate distance from the point to the kraj's border."""
        return min(_ring_distance_km(ring, lon, lat) for ring in self.rings)


def _crossings(ring: Ring, x: float, y: float) -> int:
    count = 0
    for (x1, y1), (x2, y2) in pairwise(ring):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            count += 1
    return count


def _ring_distance_km(ring: Ring, lon: float, lat: float) -> float:
    # local equirectangular projection; accurate to well under 1 % over a few km
    kx, ky = 111.32 * math.cos(math.radians(lat)), 110.57
    best = math.inf
    for (x1, y1), (x2, y2) in pairwise(ring):
        ax, ay = (x1 - lon) * kx, (y1 - lat) * ky
        bx, by = (x2 - lon) * kx, (y2 - lat) * ky
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length2))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


@cache
def load_kraje() -> tuple[Kraj, ...]:
    doc = json.loads(
        files("meteoverdict").joinpath("data/kraje.geojson").read_text(encoding="utf-8")
    )
    kraje = []
    for feature in doc["features"]:
        geometry = feature["geometry"]
        if geometry["type"] != "Polygon":
            raise ValueError(f"unexpected geometry {geometry['type']} in kraje.geojson")
        rings = tuple([(float(x), float(y)) for x, y in ring] for ring in geometry["coordinates"])
        lons = [x for x, _ in rings[0]]
        lats = [y for _, y in rings[0]]
        props = feature["properties"]
        kraje.append(
            Kraj(props["code"], props["name"], rings, (min(lons), min(lats), max(lons), max(lats)))
        )
    return tuple(kraje)


def find_kraj(lon: float, lat: float, tolerance_km: float = BORDER_TOLERANCE_KM) -> Kraj | None:
    kraje = load_kraje()
    for kraj in kraje:
        if kraj.contains(lon, lat):
            return kraj
    distance, nearest = min((k.distance_km(lon, lat), i) for i, k in enumerate(kraje))
    return kraje[nearest] if distance <= tolerance_km else None


def elevation_class(elevation: float | None) -> str | None:
    if elevation is None or math.isnan(elevation):
        return None
    if elevation < LOWLAND_BELOW_M:
        return "lowland"
    return "upland" if elevation <= MOUNTAIN_ABOVE_M else "mountain"


def add_regions(stations: pl.DataFrame) -> pl.DataFrame:
    """Add ``kraj_code``, ``kraj`` and ``elevation_class``; drop stations outside Czechia."""
    found = [find_kraj(lon, lat) for lon, lat in stations.select("lon", "lat").iter_rows()]
    return stations.with_columns(
        pl.Series("kraj_code", [k.code if k else None for k in found], pl.String),
        pl.Series("kraj", [k.name if k else None for k in found], pl.String),
        pl.Series(
            "elevation_class",
            [elevation_class(e) for e in stations["elevation"].to_list()],
            pl.String,
        ),
    ).filter(pl.col("kraj_code").is_not_null())
