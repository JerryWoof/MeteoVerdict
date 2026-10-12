"""Rank every okres: borrow the nearest stations where an okres has too few (roadmap 6.1).

About a third of the okresy have fewer than ``aggregate.MIN_STATIONS`` stations measuring
temperature, half for wind, and one has none at all. Rather than leaving them grey, an
okres's pool is its own stations plus, if that is not enough, the nearest stations of
neighbouring okresy, closest to its border first, until it has ``MIN_STATIONS``. Only
stations at most ``MAX_KM`` from the border are borrowed, so an okres far from any
station still has too few. Pools are built per variable (stations measure different
things) from the stations that have scores in the window.

Only the okres level borrows; stations, kraje, elevation classes and Czechia keep their
own stations. A borrowed station still counts in its own okres too.
"""

from __future__ import annotations

from functools import cache

import numpy as np
import polars as pl

from meteoverdict.regions import load_regions

MAX_KM = 30.0
POOL_SCHEMA = {
    "variable": pl.String,
    "region": pl.String,
    "region_name": pl.String,
    "station_id": pl.String,
    "borrowed": pl.Boolean,
}


def _segments(region) -> np.ndarray:
    """All border segments of a region as an array of (lon1, lat1, lon2, lat2)."""
    parts = [
        np.column_stack([ring[:-1], ring[1:]])
        for polygon in region.polygons
        for ring in (np.asarray(r, dtype=float) for r in polygon)
    ]
    return np.concatenate(parts)


def border_distances_km(lon: np.ndarray, lat: np.ndarray, segments: np.ndarray) -> np.ndarray:
    """Distance of each point to the nearest segment (the same local projection as
    ``regions.Region.distance_km``)."""
    kx = 111.32 * np.cos(np.radians(lat))[:, None]
    ky = 110.57
    ax = (segments[None, :, 0] - lon[:, None]) * kx
    ay = (segments[None, :, 1] - lat[:, None]) * ky
    dx = (segments[None, :, 2] - lon[:, None]) * kx - ax
    dy = (segments[None, :, 3] - lat[:, None]) * ky - ay
    length2 = dx * dx + dy * dy
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.where(length2 == 0, 0.0, np.clip(-(ax * dx + ay * dy) / length2, 0.0, 1.0))
    return np.hypot(ax + t * dx, ay + t * dy).min(axis=1)


@cache
def _okres_segments() -> tuple[tuple[str, str, np.ndarray], ...]:
    return tuple((r.code, r.name, _segments(r)) for r in load_regions("okres"))


def distances(stations: pl.DataFrame) -> pl.DataFrame:
    """Distance (km) of every station to every okres; 0 for the okres it belongs to.

    Columns ``region``, ``region_name``, ``station_id``, ``distance_km``. Needs the
    station columns ``id``, ``lon``, ``lat`` and ``okres_code``.
    """
    lon = stations["lon"].to_numpy().astype(float)
    lat = stations["lat"].to_numpy().astype(float)
    own = stations["okres_code"].to_list()
    frames = []
    for code, name, segments in _okres_segments():
        km = border_distances_km(lon, lat, segments)
        km = np.where([o == code for o in own], 0.0, km)
        frames.append(
            pl.DataFrame(
                {
                    "region": code,
                    "region_name": name,
                    "station_id": stations["id"],
                    "distance_km": km,
                }
            )
        )
    return pl.concat(frames)


def pools(
    distance: pl.DataFrame,
    available: pl.DataFrame,
    min_stations: int,
    max_km: float = MAX_KM,
    exclude: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """The stations each okres is scored with, per variable.

    ``distance`` comes from ``distances``; ``available`` has ``variable`` and
    ``station_id`` (stations with scores). An okres keeps all its own stations and, if
    they are fewer than ``min_stations``, adds the nearest others within ``max_km``
    (ties broken by station id) until it has ``min_stations``. ``exclude`` (``variable``,
    ``region``, ``station_id``) leaves stations out of one okres's pool: those
    the fair comparison would drop anyway, so that the okres borrows others instead.
    """
    candidates = (
        available.select("variable", "station_id")
        .unique()
        .join(distance, on="station_id")
        .filter(pl.col("distance_km") <= max_km)
    )
    if exclude is not None:
        candidates = candidates.join(exclude, on=["variable", "region", "station_id"], how="anti")
    candidates = candidates.with_columns((pl.col("distance_km") > 0).alias("borrowed")).sort(
        "variable", "region", "borrowed", "distance_km", "station_id"
    )
    # own stations sort first, so a borrowed station's position counts the own ones
    order = pl.int_range(pl.len()).over("variable", "region")
    picked = candidates.filter(pl.col("borrowed").not_() | (order < min_stations))
    return picked.select(list(POOL_SCHEMA)).cast(POOL_SCHEMA)
