"""Station → okres, kraj (region) and elevation class.

Boundaries come from ``data/okresy.geojson`` (77 okresy) and ``data/kraje.geojson``
(14 kraje): ČÚZK, CC BY 4.0, simplified by scripts/build_regions.py (borders shift by
at most ~0.6 km). A station gets the okres whose polygon contains it, or the nearest
okres if it is at most ``BORDER_TOLERANCE_KM`` outside the national border; otherwise
it is outside Czechia. Its kraj follows from the okres code (``CZ0201`` → ``CZ020``),
so the two levels always agree.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from itertools import pairwise
from typing import Literal

import polars as pl

BORDER_TOLERANCE_KM = 2.0

#: Elevation classes (ROADMAP "Scope v1"): lowland < 400 m, upland 400 to 800 m, mountain > 800 m.
LOWLAND_BELOW_M = 400.0
MOUNTAIN_ABOVE_M = 800.0

Level = Literal["kraj", "okres"]
_FILES = {"kraj": "data/kraje.geojson", "okres": "data/okresy.geojson"}

Ring = list[tuple[float, float]]  # (lon, lat), closed
Polygon = tuple[Ring, ...]  # exterior first, then holes


@dataclass(frozen=True)
class Region:
    code: str  # NUTS 3 for kraje ("CZ010"), LAU 1 for okresy ("CZ0201")
    name: str
    polygons: tuple[Polygon, ...]
    bbox: tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max

    def contains(self, lon: float, lat: float) -> bool:
        lon_min, lat_min, lon_max, lat_max = self.bbox
        if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
            return False
        # even-odd rule over the rings of each polygon handles holes
        # (Praha in Středočeský kraj, Brno-město in Brno-venkov)
        return any(
            sum(_crossings(ring, lon, lat) for ring in polygon) % 2 == 1
            for polygon in self.polygons
        )

    def distance_km(self, lon: float, lat: float) -> float:
        """Approximate distance from the point to the region's border."""
        return min(
            _ring_distance_km(ring, lon, lat) for polygon in self.polygons for ring in polygon
        )


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
def load_regions(level: Level) -> tuple[Region, ...]:
    doc = json.loads(files("meteoverdict").joinpath(_FILES[level]).read_text(encoding="utf-8"))
    regions = []
    for feature in doc["features"]:
        geometry = feature["geometry"]
        if geometry["type"] == "Polygon":
            raw = [geometry["coordinates"]]
        elif geometry["type"] == "MultiPolygon":
            raw = geometry["coordinates"]
        else:
            raise ValueError(f"unexpected geometry {geometry['type']} in {_FILES[level]}")
        polygons = tuple(
            tuple([(float(x), float(y)) for x, y in ring] for ring in polygon) for polygon in raw
        )
        lons = [x for polygon in polygons for x, _ in polygon[0]]
        lats = [y for polygon in polygons for _, y in polygon[0]]
        props = feature["properties"]
        regions.append(
            Region(
                props["code"], props["name"], polygons, (min(lons), min(lats), max(lons), max(lats))
            )
        )
    return tuple(regions)


def load_kraje() -> tuple[Region, ...]:
    return load_regions("kraj")


def find_region(
    lon: float, lat: float, level: Level, tolerance_km: float = BORDER_TOLERANCE_KM
) -> Region | None:
    regions = load_regions(level)
    for region in regions:
        if region.contains(lon, lat):
            return region
    if tolerance_km <= 0:
        return None
    distance, nearest = min((r.distance_km(lon, lat), i) for i, r in enumerate(regions))
    return regions[nearest] if distance <= tolerance_km else None


def find_kraj(lon: float, lat: float, tolerance_km: float = BORDER_TOLERANCE_KM) -> Region | None:
    return find_region(lon, lat, "kraj", tolerance_km)


def elevation_class(elevation: float | None) -> str | None:
    if elevation is None or math.isnan(elevation):
        return None
    if elevation < LOWLAND_BELOW_M:
        return "lowland"
    return "upland" if elevation <= MOUNTAIN_ABOVE_M else "mountain"


def add_regions(stations: pl.DataFrame) -> pl.DataFrame:
    """Add okres, kraj and elevation class columns; drop stations outside Czechia."""
    kraje = {k.code: k.name for k in load_kraje()}
    okresy = [
        find_region(lon, lat, "okres") for lon, lat in stations.select("lon", "lat").iter_rows()
    ]
    return stations.with_columns(
        pl.Series("okres_code", [o.code if o else None for o in okresy], pl.String),
        pl.Series("okres", [o.name if o else None for o in okresy], pl.String),
        pl.Series("kraj_code", [o.code[:5] if o else None for o in okresy], pl.String),
        pl.Series("kraj", [kraje[o.code[:5]] if o else None for o in okresy], pl.String),
        pl.Series(
            "elevation_class",
            [elevation_class(e) for e in stations["elevation"].to_list()],
            pl.String,
        ),
    ).filter(pl.col("okres_code").is_not_null())
