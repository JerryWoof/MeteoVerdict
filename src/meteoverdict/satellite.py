"""ČHMÚ's Meteosat images: archive them before they expire and keep the frames of the
radar page.

opendata.chmi.cz/meteorology/weather/satellite/geo/<product>/ has a JPG every 15 minutes
per product and region (``202610152030_geo_night-M_ce.jpg``: the scan starting at
20:30 UTC; regions ``cz``, ``ce``, ``eu``) for about 8 days. ``archive`` packs every file
of a complete UTC day into one uncompressed tar per product and region
(``night-M-ce-20261014.tar``) in the monthly release ``satellite-YYYY-MM``.

For the radar page the ``ce`` (Central Europe) images, which are Web Mercator (checked
by fitting coastlines and lakes, docs/data-sources.md#satellite-images), are cropped to
the area around Czechia (``CROP``) and saved as ``satellite/<product>/<stamp>.webp``.

Licence: the images are EUMETSAT "Advanced Image Products" ("Core" data, CC BY 4.0 under
the EUMETSAT Data Policy), processed and published by ČHMÚ (open data, CC BY 4.0).
"""

from __future__ import annotations

import io
import math
import re
import tempfile
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from PIL import Image

from meteoverdict import radar

BASE_URL = "https://opendata.chmi.cz/meteorology/weather/satellite/geo"
PRODUCTS = ("vis-ir", "night-M", "wv062")
REGIONS = ("ce", "cz", "eu")
WEB_REGION = "ce"
STEP = timedelta(minutes=15)
#: a day is archived once its last scan (23:45) is this old (files appear ~15 min late)
COMPLETE_AFTER = timedelta(hours=1)

#: The ``ce`` images: 1160 x 800 pixels, Web Mercator (EPSG:3857 sphere), square pixels
#: of 3114.2 m (2.0 km at 50° N). Edges fitted to the Natural Earth coastlines and lakes
#: on a cloud-free composite of 24 images (2026-10-08 … 15): mean distance 1.9 pixels,
#: Lake Constance, the Adriatic and the Baltic coasts within about a pixel.
CE_SIZE = (1160, 800)
CE_X0 = -190501.2  # west edge, Web Mercator metres
CE_Y0 = 7690826.1  # north edge
CE_PIXEL = 3114.2
#: the part the page shows (columns, rows: left, top, right, bottom): about 3.6-25.4° E,
#: 44.5-55.5° N, Czechia with a wide margin; leaves out the time label in the top right
CROP = (
    round((radar.EARTH_RADIUS * math.radians(3.5) - CE_X0) / CE_PIXEL),
    round((CE_Y0 - radar.mercator([0], [55.5])[1][0]) / CE_PIXEL),
    round((radar.EARTH_RADIUS * math.radians(25.5) - CE_X0) / CE_PIXEL),
    round((CE_Y0 - radar.mercator([0], [44.5])[1][0]) / CE_PIXEL),
)
#: WebP is about half the size of a JPEG of the same look (75 KB vs 140 KB at noon)
EXT = "webp"
WEBP_QUALITY = 70


def attribution(year: int) -> str:
    """The credit EUMETSAT asks for (Data Policy, Article 6.3) and ČHMÚ's."""
    return (
        f"Satellite images: contains modified EUMETSAT Meteosat data {year} (CC BY 4.0), "
        "processed by ČHMÚ (opendata.chmi.cz, CC BY 4.0); cropped and converted to WebP "
        "by MeteoVerdict."
    )


def _lon(x: float) -> float:
    return math.degrees(x / radar.EARTH_RADIUS)


def _lat(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(y / radar.EARTH_RADIUS)) - math.pi / 2)


def crop_bounds() -> list[list[float]]:
    """``[[west, south], [east, north]]`` of the cropped frames (pixel edges)."""
    left, top, right, bottom = CROP
    return [
        [round(_lon(CE_X0 + left * CE_PIXEL), 6), round(_lat(CE_Y0 - bottom * CE_PIXEL), 6)],
        [round(_lon(CE_X0 + right * CE_PIXEL), 6), round(_lat(CE_Y0 - top * CE_PIXEL), 6)],
    ]


def web_frame(jpg: bytes) -> bytes:
    """A ``ce`` image cropped to ``CROP``, as WebP."""
    image = Image.open(io.BytesIO(jpg))
    if image.size != CE_SIZE:
        raise ValueError(f"unexpected satellite image size {image.size}")
    out = io.BytesIO()
    image.crop(CROP).save(out, format="WEBP", quality=WEBP_QUALITY, method=6)
    return out.getvalue()


_NAME = re.compile(r"(\d{12})_geo_([A-Za-z0-9-]+)_([a-z]+)\.jpg")


@dataclass(frozen=True)
class SatFile:
    time: datetime  # scan start, UTC
    product: str
    region: str
    name: str


def parse_listing(html: str) -> list[SatFile]:
    files = []
    for name in re.findall(r'href="([^"/?]+)"', html):
        match = _NAME.fullmatch(name)
        if match:
            when = radar.parse_stamp(match[1])
            files.append(SatFile(when, match[2], match[3], name))
    return sorted(files, key=lambda f: (f.time, f.region))


def list_files(client: httpx.Client, product: str) -> list[SatFile]:
    response = client.get(f"{BASE_URL}/{product}/")
    response.raise_for_status()
    return [f for f in parse_listing(response.text) if f.product == product]


def file_url(f: SatFile) -> str:
    return f"{BASE_URL}/{f.product}/{f.name}"


def fetch_all(client: httpx.Client, files: list[SatFile], workers: int = 8) -> list[bytes]:
    if workers <= 1 or len(files) <= 1:
        return [radar.download(client, file_url(f)) for f in files]
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(lambda f: radar.download(client, file_url(f)), files))


# frames kept this long after they leave the window (see web_frames)
PRUNE_GRACE = timedelta(minutes=30)


def web_frames(
    client: httpx.Client,
    root: Path,
    since: datetime,
    until: datetime | None = None,
    listings: dict[str, list[SatFile]] | None = None,
    prune: bool = True,
    log: Callable[[str], None] = print,
) -> dict:
    """Bring ``root/satellite/<product>/<stamp>.webp`` up to date for scans in
    ``[since, until)``; returns the ``satellite`` entry of ``index.json``."""
    for product in PRODUCTS:
        folder = root / "satellite" / product
        folder.mkdir(parents=True, exist_ok=True)
        try:
            files = listings[product] if listings else list_files(client, product)
        except httpx.HTTPError as exc:  # keep what is there
            log(f"failed to list satellite {product}: {exc}")
            files = None
        have = {p.stem for p in folder.glob(f"*.{EXT}")}
        if files is not None:
            wanted = {
                radar.stamp(f.time): f
                for f in files
                if f.region == WEB_REGION and f.time >= since and (until is None or f.time < until)
            }
            missing = sorted(set(wanted) - have)
            try:
                contents = fetch_all(client, [wanted[s] for s in missing])
            except httpx.HTTPError as exc:
                log(f"failed to download satellite {product}: {exc}")
                contents = []
                missing = []
            for name, content in zip(missing, contents, strict=True):
                try:
                    (folder / f"{name}.{EXT}").write_bytes(web_frame(content))
                except (OSError, ValueError) as exc:  # a broken image: skip it
                    log(f"skipped satellite {product} {name}: {exc}")
            log(f"satellite {product}: {len(missing)} new, {len(wanted)} in the window")
        if prune:
            # a little past the window: a browser may still hold the previous index.json
            # (raw.githubusercontent caches it for minutes) and ask for its oldest frames
            for path in folder.glob(f"*.{EXT}"):
                if radar.parse_stamp(path.stem) < since - PRUNE_GRACE:
                    path.unlink()
    return index_entry(root)


def index_entry(root: Path) -> dict:
    """The ``satellite`` entry of ``index.json`` for the frames in ``root/satellite``."""
    entry = {}
    for product in PRODUCTS:
        folder = root / "satellite" / product
        frames = sorted(p.stem for p in folder.glob(f"*.{EXT}")) if folder.exists() else []
        entry[product] = {"bounds": crop_bounds(), "ext": EXT, "frames": frames}
    return entry


# --- archive -------------------------------------------------------------------------


def release_tag(day: date) -> str:
    return f"satellite-{day:%Y-%m}"


def asset_name(product: str, region: str, day: date) -> str:
    return f"{product}-{region}-{day:%Y%m%d}.tar"


def complete_days(times: Iterable[datetime], now: datetime) -> list[date]:
    days = {t.date() for t in times}
    return sorted(
        d
        for d in days
        if datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(days=1) <= now - COMPLETE_AFTER
    )


def archive(
    client: httpx.Client,
    store: radar.Store,
    now: datetime,
    products: tuple[str, ...] = PRODUCTS,
    regions: tuple[str, ...] = REGIONS,
    days: list[date] | None = None,
    log: Callable[[str], None] = print,
) -> radar.ArchiveResult:
    """Archive every complete day on the server not in ``store`` yet, one tar per product,
    region and day (the files as published), oldest first."""
    result = radar.ArchiveResult()
    listings: dict[str, list[SatFile]] = {}
    for product in products:
        try:
            listings[product] = list_files(client, product)
        except httpx.HTTPError as exc:
            log(f"failed to list satellite {product}: {exc}")
            result.failed.append(f"{product} listing")
            listings[product] = []
    times = [f.time for files in listings.values() for f in files]
    todo = complete_days(times, now) if days is None else sorted(days)
    have: dict[str, set[str]] = {}
    for day in todo:
        tag = release_tag(day)
        if tag not in have:
            have[tag] = store.names(tag)
        for product in products:
            for region in regions:
                name = asset_name(product, region, day)
                files = [
                    f for f in listings[product] if f.region == region and f.time.date() == day
                ]
                if name in have[tag]:
                    result.skipped += 1
                    continue
                if not files:
                    continue
                try:
                    contents = fetch_all(client, files)
                except httpx.HTTPError as exc:
                    log(f"failed to download {name}: {exc}")
                    result.failed.append(name)
                    continue
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / name
                    count = radar.write_tar(
                        path, [(f.name, c, f.time) for f, c in zip(files, contents, strict=True)]
                    )
                    radar._put(store, tag, name, path, f"files={count}", result, log)
    return result
