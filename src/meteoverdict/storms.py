"""What the radar page derives from the ČHMÚ composites (HDF5): echo-top frames, motion
fields between frames and storm cells, plus the colour scales of its layers.

All grids are the ČHMÚ composite grid (``radar.GRID_*``: Web Mercator, 598 x 378 cells
of 1555.7 m, rows north → south). See docs/data-sources.md#radar-live-data-contract.

* **Echo top** (``echotop/<stamp>.png``): the ECHO_TOP composite (highest altitude with
  ≥ 4 dBZ) as an 8-bit palette PNG in 2 km steps (``ECHOTOP_SCALE``).
* **Motion** (``motion/<stamp>.json``): how the echoes moved from the previous frame to
  this one, estimated by dense optical flow (OpenCV DIS, as the "Dense" model of
  rainymotion, Ayzel et al. 2019, GMD 12, 1387-1402) on the reflectivity, averaged into
  coarse blocks weighted by the echoes, empty blocks filled from their neighbours.
* **Cells** (``cells/<stamp>.json``): contiguous areas ≥ 40 dBZ of at least 5 km², with
  their strongest echo, echo top, motion, a hail flag (≥ 55 dBZ and echo top ≥ 10 km)
  and the track of the last 30 minutes; ids stay the same from frame to frame while a
  cell overlaps its predecessor moved by its motion.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import datetime

import cv2
import h5py
import numpy as np
from PIL import Image

from meteoverdict import radar

# --- colour scales -------------------------------------------------------------------

#: ČHMÚ's reflectivity scale (radar/scl/scl-dbz-mmh.png, the palette of the PNG
#: composites): lower edge in dBZ, colour, rain rate at that edge by Marshall-Palmer
#: (Z = 200 R^1.6, mm/h), what it means in English and Czech.
_DBZ_COLOURS = (
    (4, "#380070"),
    (8, "#3000a8"),
    (12, "#0000fc"),
    (16, "#006cc0"),
    (20, "#00a000"),
    (24, "#00bc00"),
    (28, "#34d800"),
    (32, "#9cdc00"),
    (36, "#e0dc00"),
    (40, "#fcb000"),
    (44, "#fc8400"),
    (48, "#fc5800"),
    (52, "#fc0000"),
    (56, "#a00000"),
    (60, "#fcfcfc"),
)
_WORDS = (  # from this dBZ on
    (4, "drizzle", "mrholení"),
    (16, "light", "slabé"),
    (28, "moderate", "mírné"),
    (40, "heavy", "silné"),
    (48, "very heavy", "velmi silné"),
    (56, "hail possible", "možné kroupy"),
)


def rain_rate(dbz: float) -> float:
    """Marshall-Palmer rain rate (mm/h) of a reflectivity: Z = 200 R^1.6."""
    return (10 ** (dbz / 10) / 200) ** (1 / 1.6)


def _words(dbz: float) -> tuple[str, str]:
    return next((en, cs) for edge, en, cs in reversed(_WORDS) if dbz >= edge)


MAXZ_SCALE = [
    [dbz, colour, round(rain_rate(dbz), 2 if dbz < 30 else 1), *_words(dbz)]
    for dbz, colour in _DBZ_COLOURS
]
#: ČHMÚ's MERGE scale (radar/scl/scl-mm.png): lower edge in mm, colour
MERGE1H_SCALE = [
    [0.1, "#380070"],
    [0.3, "#3000a8"],
    [0.6, "#0000fc"],
    [1, "#006cc0"],
    [2, "#00a000"],
    [4, "#00bc00"],
    [6, "#34d800"],
    [10, "#9cdc00"],
    [15, "#e0dc00"],
    [20, "#fcb000"],
    [30, "#fc8400"],
    [40, "#fc5800"],
    [60, "#fc0000"],
    [80, "#a00000"],
    [100, "#fcfcfc"],
]
#: Echo top (km above sea level, lower edge of each 2 km step), ours: blues and greens
#: for shallow rain, yellow to dark red from 8 km, where thunderstorms reach.
ECHOTOP_SCALE = [
    [0, "#a6bddb"],
    [2, "#3690c0"],
    [4, "#02818a"],
    [6, "#78c679"],
    [8, "#fed976"],
    [10, "#fd8d3c"],
    [12, "#e31a1c"],
    [14, "#800026"],
]
SCALES = {"maxz": MAXZ_SCALE, "merge1h": MERGE1H_SCALE, "echotop": ECHOTOP_SCALE}

# --- reading the composites ----------------------------------------------------------


@dataclass
class Composite:
    time: datetime
    values: np.ndarray  # float32, rows north → south; NaN = no data, undetect → ``floor``
    quantity: str


def read_composite(content: bytes) -> Composite:
    """A MAX_Z (``DBZH``, dBZ; no echo → -32) or ECHO_TOP (``HGHT``, km; no echo → 0)
    composite."""
    with h5py.File(io.BytesIO(content), "r") as f:
        what, data_what = radar._attrs(f["dataset1/what"]), radar._attrs(f["dataset1/data1/what"])
        quantity = data_what["quantity"]
        codes = f["dataset1/data1/data"][()]
    when = datetime.strptime(what["enddate"] + what["endtime"], "%Y%m%d%H%M%S")
    gain, offset = float(data_what["gain"]), float(data_what["offset"])
    values = codes.astype(np.float32) * gain + offset
    if quantity == "HGHT":
        values /= 1000.0  # m → km
        floor = 0.0
    elif quantity == "DBZH":
        floor = -32.0
    else:
        raise ValueError(f"unexpected quantity {quantity}")
    values[codes == data_what["undetect"]] = floor
    values[codes == data_what["nodata"]] = np.nan
    return Composite(when.replace(tzinfo=radar.UTC), values, quantity)


def _palette_png(index: np.ndarray, colours: list[str]) -> bytes:
    """An 8-bit PNG: index 0 transparent, 1… the colours."""
    image = Image.fromarray(index.astype(np.uint8), mode="P")
    palette = [0, 0, 0]
    for colour in colours:
        palette += [int(colour[i : i + 2], 16) for i in (1, 3, 5)]
    image.putpalette(palette)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True, transparency=0)
    return out.getvalue()


def echotop_png(top: Composite) -> bytes:
    """The echo top in ``ECHOTOP_SCALE`` colours, transparent without echo or data."""
    km = top.values
    edges = np.array([edge for edge, _ in ECHOTOP_SCALE], dtype=np.float32)
    index = np.searchsorted(edges, np.nan_to_num(km, nan=0.0), side="right")
    index[~(km > 0)] = 0  # no echo (0), no data (NaN)
    return _palette_png(index, [c for _, c in ECHOTOP_SCALE])


# --- motion --------------------------------------------------------------------------

MOTION_BLOCK = 32  # about this many grid cells per block (~50 km): 19 x 12 blocks
MOTION_MIN_DBZ = 10.0  # the optical flow sees echoes from this reflectivity on
WEIGHT_MIN_DBZ = 10.0  # the blocks average the flow where echoes are this strong (full at 30)
#: with echoes on less than this share of the grid, the motion away from them shrinks
CONFIDENT_SHARE = 0.005
MAX_GAP_S = 15 * 60  # no motion over a longer gap between frames


def _intensity(dbz: np.ndarray) -> np.ndarray:
    """Reflectivity as an 8-bit image for the optical flow: 10 → 0, 60 dBZ → 255."""
    scaled = (np.nan_to_num(dbz, nan=-32.0) - MOTION_MIN_DBZ) * (255 / 50)
    return cv2.GaussianBlur(np.clip(scaled, 0, 255).astype(np.uint8), (5, 5), 1.0)


def dense_flow(previous: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Per-cell displacement (columns, rows) of the echoes from ``previous`` to ``current``
    (dBZ grids): an echo at (x, y) before is at (x + u, y + v) now."""
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    return dis.calc(_intensity(previous), _intensity(current), None)


def _smooth_fill(values: np.ndarray, weights: np.ndarray, sigma: float) -> np.ndarray:
    """Weighted Gaussian average (normalized convolution); NaN where no weight near."""
    blur = lambda a: cv2.GaussianBlur(a, (0, 0), sigma, borderType=cv2.BORDER_REPLICATE)  # noqa: E731
    total = blur(weights.astype(np.float32))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(total > 1e-3, blur((values * weights).astype(np.float32)) / total, np.nan)


def coarse_motion(
    flow: np.ndarray, previous: np.ndarray, current: np.ndarray, block: int = MOTION_BLOCK
) -> tuple[np.ndarray, np.ndarray]:
    """``(u, v)`` on ``round(598 / block)`` x ``round(378 / block)`` blocks spanning the
    grid evenly, in grid cells per frame step, weighted by the echoes and smoothed; where
    there are no echoes the values come from the nearby blocks, else the mean motion of
    all echoes (shrunk to zero when there are few), else zero."""
    rows, cols = current.shape
    nx, ny = max(1, round(cols / block)), max(1, round(rows / block))
    echo = np.maximum(np.nan_to_num(previous, nan=-32), np.nan_to_num(current, nan=-32))
    weight = np.clip((echo - WEIGHT_MIN_DBZ) / 20.0, 0.0, 1.0).astype(np.float32)
    confidence = min(1.0, float(weight.mean()) / CONFIDENT_SHARE)

    def block_mean(a: np.ndarray) -> np.ndarray:
        return cv2.resize(a.astype(np.float32), (nx, ny), interpolation=cv2.INTER_AREA)

    w = block_mean(weight)
    out = []
    for k in range(2):
        s = block_mean(flow[..., k] * weight)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.where(w > 0, s / np.maximum(w, 1e-9), 0.0)
        # blocks with few echoes lean on their neighbours; empty ones take them over
        trust = np.clip(w / 0.25, 0.0, 1.0)
        overall = confidence * float(s.sum() / w.sum()) if w.sum() > 0 else 0.0
        near = _smooth_fill(mean, w, 1.5)
        near = np.where(np.isnan(near), _smooth_fill(mean, w, 6.0), near)
        near = np.where(np.isnan(near), overall, near)
        field = trust * mean + (1 - trust) * near
        out.append(cv2.GaussianBlur(field.astype(np.float32), (3, 3), 0.8))
    return out[0], out[1]


def motion_json(u: np.ndarray, v: np.ndarray, dt_s: int) -> dict:
    ny, nx = u.shape
    return {
        "nx": nx,
        "ny": ny,
        "dt_s": dt_s,
        "u": [round(float(x), 1) + 0.0 for x in u.ravel()],  # + 0.0: no -0.0
        "v": [round(float(x), 1) + 0.0 for x in v.ravel()],
    }


# --- cells ---------------------------------------------------------------------------

CELL_DBZ = 40.0
CELL_MIN_KM2 = 5.0
HAIL_DBZ = 55.0
HAIL_TOP_KM = 10.0
TRACK_MINUTES = 30
#: a cell keeps the id of a previous one it overlaps after moving that one by the motion;
#: without overlap, of the nearest moved previous cell within this distance
MATCH_KM = 8.0


def cell_lonlat(row: np.ndarray, col: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Longitude and latitude of grid positions (fractional rows/columns, cell centres
    at +0.5)."""
    x0, y0 = radar.mercator(np.array([radar.GRID_WEST]), np.array([radar.GRID_NORTH]))
    x = x0[0] + np.asarray(col, dtype=float) * 1555.7
    y = y0[0] - np.asarray(row, dtype=float) * 1555.7
    lon = np.degrees(x / radar.EARTH_RADIUS)
    lat = np.degrees(2 * np.arctan(np.exp(y / radar.EARTH_RADIUS)) - math.pi / 2)
    return lon, lat


def _row_km(rows: int) -> np.ndarray:
    """True size (km) of a grid cell side in each row (Mercator: 1.5557 km x cos φ)."""
    _, lat = cell_lonlat(np.arange(rows) + 0.5, np.zeros(rows))
    return 1.5557 * np.cos(np.radians(lat))


@dataclass
class _Cell:
    label: int
    row: float
    col: float
    record: dict


def find_cells(dbz: np.ndarray, top: np.ndarray | None, flow: np.ndarray | None, dt_s: int):
    """Labels of the cells and one record per cell (without id and track)."""
    mask = (np.nan_to_num(dbz, nan=-32) >= CELL_DBZ).astype(np.uint8)
    count, labels, _, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    side = _row_km(dbz.shape[0])
    area_px = np.broadcast_to((side**2)[:, None], dbz.shape)
    cells: list[_Cell] = []
    for label in range(1, count):
        inside = labels == label
        area = float(area_px[inside].sum())
        if area < CELL_MIN_KM2:
            labels[inside] = 0
            continue
        rr, cc = np.nonzero(inside)
        z = 10 ** (dbz[rr, cc] / 10)  # centroid weighted by linear reflectivity
        row, col = float((rr * z).sum() / z.sum()), float((cc * z).sum() / z.sum())
        lon, lat = cell_lonlat(np.array([row + 0.5]), np.array([col + 0.5]))
        echotop = None
        if top is not None:  # tops lean downwind: look one cell around too
            near = cv2.dilate(inside.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            values = top[near]
            values = values[~np.isnan(values)]
            echotop = round(float(values.max()), 1) if values.size else None
        speed, direction = None, None
        if flow is not None and dt_s > 0:
            u, v = float(flow[..., 0][inside].mean()), float(flow[..., 1][inside].mean())
            km = side[min(round(row), len(side) - 1)]
            east, north = u * km, -v * km
            speed = round(math.hypot(east, north) / dt_s * 3600)
            direction = round(math.degrees(math.atan2(east, north)) % 360) if speed else None
        max_dbz = float(np.nanmax(dbz[inside]))
        record = {
            "lon": round(float(lon[0]), 4),
            "lat": round(float(lat[0]), 4),
            "max_dbz": round(max_dbz, 1),
            "echotop_km": echotop,
            "area_km2": round(area),
            "speed_kmh": speed,
            "dir_deg": direction,
            "hail": bool(max_dbz >= HAIL_DBZ and echotop is not None and echotop >= HAIL_TOP_KM),
        }
        cells.append(_Cell(label, row, col, record))
    return labels, cells


def _shift(labels: np.ndarray, du: float, dv: float) -> np.ndarray:
    matrix = np.float32([[1, 0, du], [0, 1, dv]])
    return cv2.warpAffine(
        labels.astype(np.float32),
        matrix,
        (labels.shape[1], labels.shape[0]),
        flags=cv2.INTER_NEAREST,
        borderValue=0,
    ).astype(np.int32)


def storm_cells(
    when: datetime,
    dbz: np.ndarray,
    top: np.ndarray | None,
    previous: tuple[datetime, np.ndarray, list[dict]] | None = None,
    flow: np.ndarray | None = None,
) -> list[dict]:
    """The cells of a frame, as in ``cells/<stamp>.json``.

    ``previous``: time, dBZ grid and cells (``cells/<stamp>.json``) of the frame before,
    for stable ids and tracks; ``flow``: ``dense_flow(previous dBZ, dbz)``.
    """
    usable = previous is not None and 0 < (when - previous[0]).total_seconds() <= MAX_GAP_S
    dt_s = int((when - previous[0]).total_seconds()) if usable else 0
    labels, cells = find_cells(dbz, top, flow if usable else None, dt_s)
    prefix = radar.stamp(when)
    ids: dict[int, str] = {}
    tracks: dict[int, list] = {}
    if usable and cells:
        _, before_dbz, before_cells = previous
        before_labels, before = find_cells(before_dbz, None, None, 0)
        # the previous cells as published, by position (the same algorithm made them)
        known = {}
        for cell in before:
            match = min(
                before_cells,
                key=lambda c: (
                    (c["lon"] - cell.record["lon"]) ** 2 + (c["lat"] - cell.record["lat"]) ** 2
                ),
                default=None,
            )
            if (
                match
                and abs(match["lon"] - cell.record["lon"]) + abs(match["lat"] - cell.record["lat"])
                < 0.02
            ):
                known[cell.label] = match
        claims: list[tuple[int, int, int]] = []  # overlap, current label, previous label
        for cell in before:
            if cell.label not in known:
                continue
            inside = before_labels == cell.label
            if flow is not None:
                du = float(flow[..., 0][inside].mean())
                dv = float(flow[..., 1][inside].mean())
            else:
                du = dv = 0.0
            moved = _shift(np.where(inside, cell.label, 0), du, dv) == cell.label
            hit = labels[moved]
            for label in np.unique(hit[hit > 0]):
                claims.append((int((hit == label).sum()), int(label), cell.label))
            cell.row, cell.col = cell.row + dv, cell.col + du  # moved centroid
        taken: set[int] = set()
        for _, label, before_label in sorted(claims, reverse=True):
            if label in ids or before_label in taken:
                continue
            ids[label] = known[before_label]["id"]
            tracks[label] = known[before_label].get("track", [])
            taken.add(before_label)
        side = float(_row_km(dbz.shape[0]).mean())
        for cell in cells:
            if cell.label in ids:
                continue
            options = [
                (math.hypot(b.row - cell.row, b.col - cell.col) * side, b.label)
                for b in before
                if b.label in known and b.label not in taken
            ]
            if options:
                distance, before_label = min(options)
                if distance <= MATCH_KM:
                    ids[cell.label] = known[before_label]["id"]
                    tracks[cell.label] = known[before_label].get("track", [])
                    taken.add(before_label)
    steps = TRACK_MINUTES * 60 // max(dt_s or 300, 60)
    out = []
    for n, cell in enumerate(sorted(cells, key=lambda c: -c.record["max_dbz"]), start=1):
        record = {"id": ids.get(cell.label, f"{prefix}-{n}"), **cell.record}
        track = [*tracks.get(cell.label, []), [record["lon"], record["lat"]]]
        record["track"] = track[-(steps + 1) :]
        out.append(record)
    return out
