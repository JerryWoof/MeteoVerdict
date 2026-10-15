"""Raw data store: monthly observation, forecast and score files as GitHub Release assets.

Local layout ``<data>/{obs,fc,scores}/YYYY-MM.parquet`` maps to the assets
``{obs,fc,scores}-YYYY-MM.parquet`` of the release ``data-YYYY-MM``. Each asset's label
holds the file's SHA-256, so unchanged files are neither uploaded nor downloaded again.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from meteoverdict.releases import GitHubReleaseStore

KINDS = ("obs", "gauges", "fc", "scores")
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

RELEASE_NOTES = (
    "Hourly station observations (obs-YYYY-MM.parquet), daily rain-gauge totals "
    "(gauges-YYYY-MM.parquet), archived forecasts at the stations (fc-YYYY-MM.parquet) "
    "and daily scores (scores-YYYY-MM.parquet) for one month, written by "
    "`mvd fetch-obs`, `mvd fetch-gauges`, `mvd fetch-fc` and `mvd score` "
    "(format: docs/data-sources.md). Observations: Czech Hydrometeorological "
    "Institute (ČHMÚ), opendata.chmi.cz, CC BY 4.0. Forecasts: Open-Meteo.com, CC BY 4.0, "
    "from DWD, ECMWF, NOAA, Météo-France, GeoSphere Austria, KNMI, DMI, ČHMÚ, "
    "Environment and Climate Change Canada, the Japan Meteorological Agency, the China "
    "Meteorological Administration and the UK Met Office (CC BY-SA 4.0). "
    "Changes: hourly aggregation, station extraction, "
    "scoring. "
    "These files are published under CC BY-SA 4.0 "
    "(https://creativecommons.org/licenses/by-sa/4.0/); see docs/licensing.md."
)


def release_tag(month: str) -> str:
    return f"data-{month}"


def asset_name(kind: str, month: str) -> str:
    return f"{kind}-{month}.parquet"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_files(data_dir: Path) -> list[tuple[str, str, Path]]:
    """``(kind, month, path)`` for every monthly file under ``data_dir``."""
    found = []
    for kind in KINDS:
        folder = data_dir / kind
        if folder.exists():
            found += [
                (kind, p.stem, p) for p in sorted(folder.glob("*.parquet")) if MONTH.match(p.stem)
            ]
    return found


def upload(
    store: GitHubReleaseStore, data_dir: Path, log: Callable[[str], None] = lambda _: None
) -> list[str]:
    """Upload local monthly files whose content differs from the stored asset."""
    uploaded = []
    for kind, month, path in local_files(data_dir):
        tag, name, digest = release_tag(month), asset_name(kind, month), sha256(path)
        if store.assets(tag).get(name, {}).get("label") == digest:
            continue
        store.put(tag, name, path, label=digest)
        log(f"uploaded {name} ({path.stat().st_size // 1024} KB)")
        uploaded.append(name)
    return uploaded


def remote_months(store: GitHubReleaseStore) -> list[str]:
    """Months that have a ``data-YYYY-MM`` release."""
    return [t.removeprefix("data-") for t in store.tags("data-") if MONTH.match(t[5:])]


def download(
    store: GitHubReleaseStore,
    data_dir: Path,
    months: list[str],
    log: Callable[[str], None] = lambda _: None,
    kinds: tuple[str, ...] = KINDS,
) -> list[str]:
    """Download the stored files of ``months`` that are missing or different locally."""
    downloaded = []
    for month in months:
        assets = store.assets(release_tag(month))
        for kind in kinds:
            asset = assets.get(asset_name(kind, month))
            if asset is None:
                continue
            path = data_dir / kind / f"{month}.parquet"
            if path.exists() and sha256(path) == asset.get("label"):
                continue
            store.download(release_tag(month), asset["name"], path)
            log(f"downloaded {asset['name']}")
            downloaded.append(asset["name"])
    return downloaded


def month_range(first: str, last: str) -> list[str]:
    if not (MONTH.match(first) and MONTH.match(last)) or first > last:
        raise ValueError(f"bad month range {first}..{last} (use YYYY-MM)")
    months, (y, m) = [], map(int, first.split("-"))
    while f"{y:04d}-{m:02d}" <= last:
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


STATE_TAG = "data-state"
STATE_NAME = "backfill-state.json"


class ReleaseSync:
    """Backfill sync: month files and the backfill state in GitHub Releases."""

    def __init__(self, store: GitHubReleaseStore, data_dir: Path, log=lambda _: None) -> None:
        self.store, self.data_dir, self.log = store, data_dir, log

    def pull_state(self) -> None:
        if STATE_NAME in self.store.assets(STATE_TAG):
            self.store.download(STATE_TAG, STATE_NAME, self.data_dir / STATE_NAME)

    def pull(self, months: list[str]) -> None:
        download(self.store, self.data_dir, months, self.log)

    def push(self, months: list[str]) -> None:
        upload(self.store, self.data_dir, self.log)
        state = self.data_dir / STATE_NAME
        if state.exists():
            self.store.put(STATE_TAG, STATE_NAME, state, label=sha256(state))


LATEST_TAG = "data-latest"


def publish_latest(store: GitHubReleaseStore, data_dir: Path, site_dir: Path) -> None:
    """Replace ``aggregates.parquet`` and ``site-data.zip`` (all JSON) in ``data-latest``.

    The repository only commits the small summary levels; the web map takes the full
    set (okres and station levels) from here.
    """
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(shutil.make_archive(str(Path(tmp) / "site-data"), "zip", site_dir))
        store.put(LATEST_TAG, "site-data.zip", archive, label=sha256(archive))
    aggregates = data_dir / "aggregates.parquet"
    store.put(LATEST_TAG, "aggregates.parquet", aggregates, label=sha256(aggregates))


def publish_folder(store: GitHubReleaseStore, folder: Path, name: str) -> None:
    """Zip ``folder`` and replace the asset ``name`` in ``data-latest``."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(shutil.make_archive(str(Path(tmp) / Path(name).stem), "zip", folder))
        store.put(LATEST_TAG, name, archive, label=sha256(archive))
