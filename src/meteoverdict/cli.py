"""Command-line interface for meteoverdict (``mvd``)."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

import httpx
import polars as pl
import typer

from meteoverdict import (
    __version__,
    aggregate,
    aladin,
    blend,
    blendtest,
    bucket,
    chmi_archive,
    combine,
    farm,
    forecasts,
    fresh,
    frost,
    gauges,
    gusts,
    leads,
    mos,
    observations,
    observed_map,
    outlook,
    partitions,
    quality,
    radar,
    rain_calibration,
    ranking,
    regions,
    runs,
    satellite,
    scoring,
    station_check,
    station_pages,
    stations,
    store,
    sun_cloud_gust,
)
from meteoverdict import backfill as backfill_mod
from meteoverdict import daily as daily_mod
from meteoverdict import models as catalogue
from meteoverdict import report as report_mod
from meteoverdict.chmi import BASE_URL as CHMI_BASE_URL
from meteoverdict.chmi import ChmiFormatError, fetch_current_meta, parse_collection
from meteoverdict.releases import GitHubReleaseStore

app = typer.Typer(
    name="mvd",
    help="Verify weather models against ČHMÚ station observations, ranked per Czech region.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"mvd {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Which weather model gets Czechia right?"""


DateOption = Annotated[
    datetime,
    typer.Option(formats=["%Y-%m-%d"], help="Date in YYYY-MM-DD (UTC)."),
]


def _yesterday() -> date:
    return datetime.now(UTC).date() - timedelta(days=1)


def _check_range(start: date, end: date, hint: str = "--start/--end") -> None:
    if start > end:
        raise typer.BadParameter(f"start {start} is after end {end}", param_hint=hint)


@app.command("stations")
def stations_cmd(
    out: Annotated[Path, typer.Option(help="Where to write the station table.")] = Path(
        "data/stations.parquet"
    ),
) -> None:
    """Download ČHMÚ station metadata, map stations to kraje, write the table (Parquet)."""
    transport = httpx.HTTPTransport(retries=3)
    try:
        with httpx.Client(timeout=60, transport=transport, follow_redirects=True) as client:
            current, historical = stations.fetch_station_tables(client, datetime.now(UTC).date())
    except httpx.HTTPError as exc:
        typer.echo(f"mvd stations: could not download ČHMÚ metadata: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:  # invalid JSON or not the documented envelope
        typer.echo(f"mvd stations: unexpected ČHMÚ metadata format: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        table = stations.build_stations(current, historical)
    except ChmiFormatError as exc:
        typer.echo(f"mvd stations: unexpected ČHMÚ metadata format: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    table = regions.add_regions(table)
    stations.write_stations(table, out)
    active = int(table["active"].sum())
    kraje = table["kraj"].n_unique()
    okresy = table["okres"].n_unique()
    typer.echo(
        f"Wrote {table.height} stations ({active} active) "
        f"in {okresy} okresy and {kraje} kraje to {out}"
    )


ALADIN_RELEASE_NOTES = (
    "ČHMÚ ALADIN forecasts at ČHMÚ stations, one Parquet file per model run, archived by "
    "`mvd archive-aladin`. Source: Czech Hydrometeorological Institute (ČHMÚ), "
    "opendata.chmi.cz, licensed under CC BY 4.0 "
    "(https://creativecommons.org/licenses/by/4.0/). Changes: values taken at the grid point "
    "nearest to each station, temperature converted from K to °C. "
    "Format: docs/data-sources.md#aladin-archive."
)


@app.command("archive-aladin")
def archive_aladin(
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table from `mvd stations`.")
    ] = Path("data/stations.parquet"),
    out_dir: Annotated[
        Path | None, typer.Option(help="Write the archive files to this folder.")
    ] = None,
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Upload to GitHub Releases of $GITHUB_REPOSITORY using $GITHUB_TOKEN.",
        ),
    ] = False,
) -> None:
    """Archive ALADIN forecasts at the stations for every run still on the ČHMÚ server."""
    if (out_dir is None) == (not github_release):
        raise typer.BadParameter("use exactly one of --out-dir and --github-release")
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    table = pl.read_parquet(stations_path)
    transport = httpx.HTTPTransport(retries=3)
    with httpx.Client(timeout=300, transport=transport, follow_redirects=True) as client:
        if github_release:
            token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
            if not token or not repo:
                raise typer.BadParameter(
                    "--github-release needs GITHUB_TOKEN and GITHUB_REPOSITORY"
                )
            store = GitHubReleaseStore(client, repo, token, notes=ALADIN_RELEASE_NOTES)
        else:
            store = aladin.LocalStore(out_dir)
        result = aladin.archive(client, store, table, log=typer.echo)
    typer.echo(
        f"archived {len(result.archived)}, already there {result.skipped}, "
        f"failed {len(result.failed)}"
    )
    if result.failed:
        raise typer.Exit(code=1)


RADAR_RELEASE_NOTES = (
    "ČHMÚ weather radar composites, one tar per product and UTC day "
    "(e.g. maxz-hdf5-20261014.tar: the files of that day as published), plus derived "
    "files: merge1h-hourly-YYYYMMDD.npz (hourly MERGE precipitation grids), "
    "merge1h-stations-YYYYMMDD.parquet (that precipitation at the ČHMÚ stations) and "
    "web-YYYYMMDD.tar (the frames of the radar page), archived by `mvd archive-radar`. "
    "Source: Czech Hydrometeorological Institute (ČHMÚ), opendata.chmi.cz, licensed under "
    "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Changes: packed per day; "
    "derived files: grid cell of each station, PNG frames cropped to the data area with "
    "transparent frame and labels. Format: docs/data-sources.md#radar-archive."
)


def _now() -> datetime:
    return datetime.now(UTC)


@app.command("archive-radar")
def archive_radar(
    products: Annotated[
        str,
        typer.Option(
            help="observed (radar images, echo tops, MERGE), forecast (nowcasts), all, "
            "or comma-separated product keys (e.g. maxz-hdf5,merge1h-png)."
        ),
    ] = "observed",
    stations_path: Annotated[
        Path | None,
        typer.Option("--stations", help="Station table from `mvd stations` (MERGE at stations)."),
    ] = None,
    day: Annotated[
        list[datetime] | None,
        typer.Option(formats=["%Y-%m-%d"], help="Only this UTC day (repeatable)."),
    ] = None,
    no_derived: Annotated[
        bool, typer.Option("--no-derived", help="Only the raw files, no derived files.")
    ] = False,
    out_dir: Annotated[
        Path | None, typer.Option(help="Write to <dir>/radar-YYYY-MM/ (the release layout).")
    ] = None,
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Upload to GitHub Releases of $GITHUB_REPOSITORY using $GITHUB_TOKEN.",
        ),
    ] = False,
    redo: Annotated[
        list[str] | None,
        typer.Option(help="Make this asset again even if stored (e.g. web; repeatable)."),
    ] = None,
) -> None:
    """Archive ČHMÚ radar composites per product and day before they expire (~7 days)."""
    if (out_dir is None) == (not github_release):
        raise typer.BadParameter("use exactly one of --out-dir and --github-release")
    try:
        keys = radar.parse_products(products)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    table = None
    if stations_path is not None:
        if not stations_path.exists():
            raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
        table = pl.read_parquet(stations_path)
    days = sorted({d.date() for d in day}) if day else None
    transport = httpx.HTTPTransport(retries=3)
    with httpx.Client(timeout=120, transport=transport, follow_redirects=True) as client:
        if github_release:
            store_ = GitHubReleaseStore(client, *_github_credentials(), notes=RADAR_RELEASE_NOTES)
        else:
            store_ = radar.LocalStore(out_dir)
        result = radar.archive(
            client,
            store_,
            keys,
            _now(),
            table,
            days,
            not no_derived,
            log=typer.echo,
            redo=tuple(redo or ()),
        )
    total = sum(result.sizes.values())
    typer.echo(
        f"archived {len(result.archived)} ({total / 1e6:.1f} MB), already there "
        f"{result.skipped}, failed {len(result.failed)}"
    )
    if result.failed:
        raise typer.Exit(code=1)


@app.command("radar-live")
def radar_live(
    folder: Annotated[Path, typer.Option("--dir", help="The live folder (branch radar-live).")],
    hours: Annotated[float, typer.Option(help="Keep the frames of the last … hours.")] = 24,
    satellite_hours: Annotated[
        float | None, typer.Option(help="Keep the satellite images of the last … hours.")
    ] = None,
    cache: Annotated[
        Path | None,
        typer.Option(help="Keep the downloaded HDF5 files here (outside --dir) for the next run."),
    ] = None,
) -> None:
    """Update the radar page's live frames (last hours and the newest nowcast) in a folder."""
    folder.mkdir(parents=True, exist_ok=True)
    transport = httpx.HTTPTransport(retries=3)
    with httpx.Client(timeout=60, transport=transport, follow_redirects=True) as client:
        index = radar.update_live(client, folder, _now(), hours, typer.echo, cache, satellite_hours)
    satellite_frames = {k: len(v["frames"]) for k, v in index["satellite"].items()}
    typer.echo(
        f"{len(index['maxz'])} radar frames, {len(index['merge1h'])} MERGE frames, "
        f"{len(index['echotop'])} echo tops, {len(index['motion'])} motion fields, "
        f"{len(index['cells'])} cell sets, satellite {satellite_frames}, "
        f"nowcast {(index.get('nowcast') or {}).get('base', 'none')}"
    )


@app.command("mirror-radar")
def mirror_radar(
    out_dir: Annotated[Path, typer.Option(help="Local copy: <dir>/radar-YYYY-MM/<asset>.")],
    since: Annotated[str, typer.Option(help="First month (YYYY-MM); default all.")] = "",
    satellite_: Annotated[
        bool,
        typer.Option(
            "--satellite/--no-satellite",
            help="Also copy the satellite archive (releases satellite-YYYY-MM).",
        ),
    ] = False,
    only_satellite: Annotated[
        bool, typer.Option("--only-satellite", help="Copy only the satellite archive.")
    ] = False,
) -> None:
    """Copy the radar archive (releases radar-YYYY-MM) to a local disk, skipping copies."""
    prefixes = ("satellite-",) if only_satellite else ("radar-",)
    if satellite_ and not only_satellite:
        prefixes = ("radar-", "satellite-")
    with httpx.Client(timeout=600, transport=httpx.HTTPTransport(retries=3)) as client:
        store_ = GitHubReleaseStore(client, *_github_credentials())
        count = radar.mirror(store_, out_dir, since, log=typer.echo, prefixes=prefixes)
    typer.echo(f"downloaded {count} files to {out_dir}")


def satellite_release_notes(tag: str) -> str:
    """Notes of the release ``satellite-YYYY-MM``: EUMETSAT's credit names the year of
    the data (Data Policy, Article 6.3; docs/licensing.md)."""
    year = tag.removeprefix("satellite-")[:4]
    if not year.isdigit():
        year = f"{_now():%Y}"
    return (
        "Meteosat images published by ČHMÚ (opendata.chmi.cz/meteorology/weather/satellite/"
        "geo/), one uncompressed tar per product, region and UTC day (e.g. "
        "night-M-ce-20261014.tar: the JPG files of that day as published, every 15 "
        f"minutes), archived by `mvd archive-satellite`. Contains modified EUMETSAT "
        f"Meteosat data {year} (EUMETSAT Advanced Image Products, Core data, CC BY 4.0 "
        "under the EUMETSAT Data Policy), processed by the Czech Hydrometeorological "
        "Institute (ČHMÚ), CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). "
        "Changes: packed per day. Format: docs/data-sources.md#satellite-images."
    )


@app.command("archive-satellite")
def archive_satellite(
    products: Annotated[
        str, typer.Option(help="Comma-separated: vis-ir, night-M, wv062 (default all).")
    ] = ",".join(satellite.PRODUCTS),
    regions: Annotated[
        str, typer.Option(help="Comma-separated: ce, cz, eu (default all).")
    ] = ",".join(satellite.REGIONS),
    day: Annotated[
        list[datetime] | None,
        typer.Option(formats=["%Y-%m-%d"], help="Only this UTC day (repeatable)."),
    ] = None,
    out_dir: Annotated[
        Path | None, typer.Option(help="Write to <dir>/satellite-YYYY-MM/ (the release layout).")
    ] = None,
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Upload to GitHub Releases of $GITHUB_REPOSITORY using $GITHUB_TOKEN.",
        ),
    ] = False,
) -> None:
    """Archive ČHMÚ's Meteosat images per product, region and day before they expire (~8 days)."""
    if (out_dir is None) == (not github_release):
        raise typer.BadParameter("use exactly one of --out-dir and --github-release")
    keys = tuple(p.strip() for p in products.split(",") if p.strip())
    areas = tuple(r.strip() for r in regions.split(",") if r.strip())
    if not keys or set(keys) - set(satellite.PRODUCTS):
        raise typer.BadParameter(f"products: {', '.join(satellite.PRODUCTS)}")
    if not areas or set(areas) - set(satellite.REGIONS):
        raise typer.BadParameter(f"regions: {', '.join(satellite.REGIONS)}")
    days = sorted({d.date() for d in day}) if day else None
    transport = httpx.HTTPTransport(retries=3)
    with httpx.Client(timeout=120, transport=transport, follow_redirects=True) as client:
        if github_release:
            store_ = GitHubReleaseStore(
                client, *_github_credentials(), notes=satellite_release_notes
            )
        else:
            store_ = radar.LocalStore(out_dir)
        result = satellite.archive(client, store_, _now(), keys, areas, days, log=typer.echo)
    total = sum(result.sizes.values())
    typer.echo(
        f"archived {len(result.archived)} ({total / 1e6:.1f} MB), already there "
        f"{result.skipped}, failed {len(result.failed)}"
    )
    if result.failed:
        raise typer.Exit(code=1)


def _chmi_client(timeout: float = 300) -> httpx.Client:
    transport = httpx.HTTPTransport(retries=3)
    return httpx.Client(timeout=timeout, transport=transport, follow_redirects=True)


def _archive_releases(client: httpx.Client) -> GitHubReleaseStore:
    return GitHubReleaseStore(client, *_github_credentials(), notes=chmi_archive.RELEASE_NOTES)


@app.command("chmi-archive")
def chmi_archive_cmd(
    parts: Annotated[
        list[str],
        typer.Option(
            "--part",
            help="What to archive (repeatable): days (now/, every day), recent (changed "
            "months of recent/), history (closed years per station), months (closed "
            "10-minute and hourly months).",
        ),
    ] = ["days", "recent"],  # noqa: B006 (typer needs a list default)
    out_dir: Annotated[
        Path | None, typer.Option(help="Archive into this folder (<tag>/<name>).")
    ] = None,
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Archive into GitHub Releases of $GITHUB_REPOSITORY using $GITHUB_TOKEN.",
        ),
    ] = False,
    max_minutes: Annotated[
        float | None, typer.Option(help="Stop starting new files after this many minutes.")
    ] = None,
    first_year: Annotated[
        int, typer.Option(help="Oldest year of 10-minute and hourly months.")
    ] = chmi_archive.FIRST_MONTH_YEAR,
    station: Annotated[
        list[str] | None,
        typer.Option(help="Only these stations' history (WSI, repeatable; for trials)."),
    ] = None,
    workdir: Annotated[Path, typer.Option(help="Folder for temporary files.")] = Path(
        "data/chmi-work"
    ),
) -> None:
    """Archive all ČHMÚ climatological station data (every element) as Parquet."""
    if (out_dir is None) == (not github_release):
        raise typer.BadParameter("use exactly one of --out-dir and --github-release")
    unknown = set(parts) - set(chmi_archive.PARTS)
    if unknown:
        raise typer.BadParameter(f"unknown part {sorted(unknown)}; use {chmi_archive.PARTS}")
    with _chmi_client() as client:
        if github_release:
            target = chmi_archive.ReleaseStore(_archive_releases(client))
        else:
            target = chmi_archive.LocalStore(out_dir)
        result = chmi_archive.archive(
            client,
            target,
            workdir,
            parts,
            max_minutes=max_minutes,
            first_year=first_year,
            stations=set(station) if station else None,
            log=typer.echo,
        )
    typer.echo(
        f"archived {len(result.done)} files ({result.rows:,} rows, {result.bytes / 1e6:.0f} MB), "
        f"failed {len(result.failed)}, left for later {result.pending}, "
        f"unreadable files left out {result.unreadable}"
    )
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(
                f"## ČHMÚ archive ({', '.join(parts)})\n\n"
                f"- archived {len(result.done)} files, {result.rows:,} rows, "
                f"{result.bytes / 1e6:.0f} MB\n- failed {len(result.failed)}\n"
                f"- left for the next run: {result.pending}\n"
                f"- unreadable files left out: {result.unreadable}\n"
            )
    if result.failed:
        raise typer.Exit(code=1)


@app.command("chmi-mirror")
def chmi_mirror(
    dest: Annotated[Path, typer.Argument(help="Local folder; files go to <tag>/<name>.")],
) -> None:
    """Copy the whole ČHMÚ archive (releases chmi-*) to a local disk; unchanged files are
    skipped, so it can run again to update the copy. Read only towards GitHub."""
    with httpx.Client(timeout=600, transport=httpx.HTTPTransport(retries=3)) as client:
        copied = chmi_archive.mirror(_archive_releases(client), dest, log=typer.echo)
    typer.echo(f"copied {len(copied)} files to {dest}")


def _meta2_tables(client: httpx.Client) -> pl.DataFrame:
    """ČHMÚ's element metadata: the historical periods and today's list, stacked."""
    response = client.get(f"{CHMI_BASE_URL}/historical/metadata/meta2.json")
    response.raise_for_status()
    historical = parse_collection(response.json())
    current = fetch_current_meta(client, 2, datetime.now(UTC).date())
    cast = [pl.col(c).cast(pl.String) for c in ("HEIGHT",) if c in historical.columns]
    return pl.concat(
        [historical.with_columns(cast), current.with_columns(pl.col("HEIGHT").cast(pl.String))],
        how="diagonal_relaxed",
    )


@app.command("station-pages")
def station_pages_cmd(
    archive: Annotated[
        Path, typer.Option(help="Archive folder (<tag>/<name>), e.g. from chmi-archive.")
    ] = Path("data/chmi"),
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table from `mvd stations`.")
    ] = Path("data/stations.parquet"),
    out: Annotated[Path, typer.Option(help="Folder for the station JSON.")] = Path(
        "site/data/station"
    ),
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="First download the archive files needed from GitHub Releases.",
        ),
    ] = False,
    publish: Annotated[
        bool,
        typer.Option(help="Upload the JSON as station-data.zip to the release data-latest."),
    ] = False,
) -> None:
    """Per-station JSON with every element and its history, for web/station.html."""
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    table = pl.read_parquet(stations_path)
    today = datetime.now(UTC).date()
    with _chmi_client() as client:
        meta2 = _meta2_tables(client)
        if github_release:
            closed = chmi_archive.last_closed_year(client)
            years = list(range(closed + 1, today.year + 1))
            wanted = station_pages.wanted_assets(table["id"].to_list(), today, years)
            chmi_archive.sync(_archive_releases(client), archive, wanted, log=typer.echo)
    station_pages.build(archive, table, meta2, out, today, log=typer.echo)
    if publish:
        with httpx.Client(timeout=600, transport=httpx.HTTPTransport(retries=3)) as client:
            store.publish_folder(_release_store(client), out, "station-data.zip")
        typer.echo(f"published station-data.zip to the release {store.LATEST_TAG}")


@app.command("observed-map")
def observed_map_cmd(
    archive: Annotated[
        Path, typer.Option(help="Archive folder (<tag>/<name>), e.g. from chmi-archive.")
    ] = Path("data/chmi"),
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table from `mvd stations`.")
    ] = Path("data/stations.parquet"),
    parts_dir: Annotated[
        Path,
        typer.Option(help="Folder of the outlook's parts-of-day archive (outlook-parts-*)."),
    ] = Path("data/outlook-archive"),
    out: Annotated[Path, typer.Option(help="Folder for the day files.")] = Path("site/data")
    / observed_map.FOLDER,
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="First download the archive files and the outlook's parts archive needed "
            "from GitHub Releases (read only).",
        ),
    ] = False,
    publish: Annotated[
        bool,
        typer.Option(help=f"Upload the folder as {observed_map.ZIP} to the release data-latest."),
    ] = False,
) -> None:
    """What the weather was like: measured values per okres and part of day for the past
    days of the forecast map (web/tv.html), with our archived forecast beside them."""
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    if publish and not github_release:
        raise typer.BadParameter("--publish needs --github-release")
    now = datetime.now(UTC)
    today = observed_map.prague_today(now)
    if github_release:
        with httpx.Client(timeout=600, transport=httpx.HTTPTransport(retries=3)) as client:
            chmi_archive.sync(
                _archive_releases(client), archive, observed_map.wanted_assets(today), typer.echo
            )
            # flat folder: the files go to <parts_dir>/<tag>/<name>, read from there
            chmi_archive.sync(
                _release_store(client),
                parts_dir,
                observed_map.parts_archive_names(today),
                typer.echo,
            )
    parts = [
        parts_dir / tag / name
        for tag, name in observed_map.parts_archive_names(today)
        if (parts_dir / tag / name).exists()
    ] + [
        parts_dir / name
        for _, name in observed_map.parts_archive_names(today)
        if (parts_dir / name).exists()
    ]
    archived = (
        pl.concat([pl.read_parquet(p).cast(outlook.PARTS_ARCHIVE_SCHEMA) for p in parts])
        if parts
        else None
    )
    observed_map.build(
        archive,
        pl.read_parquet(stations_path),
        combine.okres_points(),
        out,
        today,
        parts_archive=archived,
        generated=now,
        log=typer.echo,
    )
    if publish:
        with httpx.Client(timeout=600, transport=httpx.HTTPTransport(retries=3)) as client:
            store.publish_folder(_release_store(client), out, observed_map.ZIP)
        typer.echo(f"published {observed_map.ZIP} to the release {store.LATEST_TAG}")


@app.command("leads")
def leads_cmd(
    days: Annotated[
        int, typer.Option(help="Score the archived ALADIN runs of the last N days.")
    ] = 30,
    runs_days: Annotated[
        int, typer.Option(help="Score the single runs of all models of the last N days.")
    ] = 90,
    archive_dir: Annotated[
        Path, typer.Option(help="Archived runs in <dir>/aladin-YYYY-MM/ (from the releases).")
    ] = Path("data/aladin"),
    data_dir: Annotated[Path, typer.Option(help="Folder with obs/ and runs/.")] = Path("data"),
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table, for the kraj level (optional).")
    ] = Path("data/stations.parquet"),
    out: Annotated[
        Path,
        typer.Option(
            help="The all-model JSON file; ALADIN from our archive goes beside it as "
            "leads-aladin.json and leads-aladin-kraj.json."
        ),
    ] = Path("site/data/leads.json"),
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Download the single runs (runs-YYYY-MM), the archived ALADIN runs "
            "(aladin-YYYY-MM) and observations (data-YYYY-MM) from GitHub Releases first "
            "(GITHUB_TOKEN, GITHUB_REPOSITORY).",
        ),
    ] = False,
    publish: Annotated[
        bool,
        typer.Option("--publish", help="Put the JSON files into the release data-latest."),
    ] = False,
    bands: Annotated[
        bool,
        typer.Option(
            help="Also rank the models by lead band (H+1-6 … H+49-72) over the last 90 days "
            "and every single run since --bands-since: leads-bands-<window>[-kraj].json.",
        ),
    ] = True,
    bands_since: Annotated[
        datetime | None,
        typer.Option(
            help="First run of the band ranking's 'all' window (default: 2026-06-23, the "
            "first run with ALADIN)."
        ),
    ] = None,
) -> None:
    """Error by lead hour, run by run: every model from Open-Meteo's single runs
    (H+1 … H+120) and ALADIN from our own archive (H+1 … H+72); with --bands also the
    ranking by lead band."""
    if publish and not github_release:
        raise typer.BadParameter("--publish needs --github-release")
    now = datetime.now(UTC)
    hour = now.replace(minute=0, second=0, microsecond=0)
    since, runs_since = hour - timedelta(days=days), hour - timedelta(days=runs_days)
    first = min(since, runs_since)
    if bands_since is None:
        bands_since = datetime.combine(runs.ALADIN_FROM, datetime.min.time(), tzinfo=UTC)
    elif bands_since.tzinfo is None:
        bands_since = bands_since.replace(tzinfo=UTC)
    months = partitions.months(
        min(first, bands_since).date() if bands else first.date(), now.date()
    )
    generated, names = datetime.now(UTC), _model_names()
    written, lines, delays = [], [], {}
    with httpx.Client(timeout=300, transport=httpx.HTTPTransport(retries=3)) as client:
        releases = _release_store(client) if github_release else None
        if releases:
            leads.download_archive(releases, archive_dir, months, since, typer.echo)
            runs.RunsSync(releases, data_dir, typer.echo).pull(months)
            store.download(releases, data_dir, months, typer.echo, kinds=("obs",))
        files = leads.archive_files(archive_dir, since)
        obs = partitions.scan_months(data_dir / "obs", since.date(), now.date())
        if files and obs is not None:
            archive = leads.read_archive(files)
            pairs = leads.pairs(leads.forecast_hours(archive), obs)
            station_table = pl.read_parquet(stations_path) if stations_path.exists() else None
            table = leads.lead_scores(pairs, station_table)
            delays = leads.publication_delays(archive)
            for path, part in (
                (out.with_name("leads-aladin.json"), table.filter(pl.col("region") == "cz")),
                (out.with_name("leads-aladin-kraj.json"), table.filter(pl.col("region") != "cz")),
            ):
                doc = leads.document(part, pairs, generated, delays, names)
                written.append(leads.write(doc, path))
            lines += ["ALADIN, our archive:", *leads.summary(table)]
            lines.append(f"{len(files)} archived run files, {pairs.height:,} pairs")
        single = leads.scan_runs(data_dir / "runs", runs_since, now)
        obs = partitions.scan_months(data_dir / "obs", runs_since.date(), now.date())
        if single is not None and obs is not None:
            models = [m for m in catalogue.load_models() if m.enabled]
            table, info = leads.run_lead_scores(single, obs, models)
            _echo_short_runs("mvd leads", info)
            if table.height:
                doc = leads.runs_document(table, info, generated, delays, names)
                written.append(leads.write(doc, out))
                lines += ["All models, Open-Meteo single runs:", *leads.summary(table)]
        if bands:
            written += _lead_bands(data_dir, bands_since, now, stations_path, out, generated, names)
        if not written:
            typer.echo(
                f"mvd leads: no runs with observations since {first:%Y-%m-%d %H} UTC", err=True
            )
            raise typer.Exit(code=1)
        if publish:
            for path in written:
                releases.put(store.LATEST_TAG, path.name, path)
    for line in lines:
        typer.echo(line)
    typer.echo(f"→ {', '.join(map(str, written))}")


def _lead_bands(
    data_dir: Path,
    since: datetime,
    now: datetime,
    stations_path: Path,
    out: Path,
    generated: datetime,
    names: dict[str, str],
) -> list[Path]:
    """The ranking by lead band (``leads.band_rankings``) into
    ``leads-bands-<window>.json`` and ``leads-bands-<window>-kraj.json`` beside ``out``."""
    single = leads.scan_runs(data_dir / "runs", since, now)
    obs = partitions.scan_months(data_dir / "obs", since.date(), now.date())
    if single is None or obs is None:
        typer.echo("mvd leads: no single runs or observations for the lead bands", err=True)
        return []
    station_table = (
        pl.read_parquet(stations_path) if stations_path.exists() else runs.load_stations()
    )
    models = [m for m in catalogue.load_models() if m.enabled]
    results = leads.band_rankings(single, obs, models, station_table, log=typer.echo)
    region_names = {k.code: k.name for k in regions.load_kraje()}
    region_names |= {"cz": "Česko", "main": "hlavní stanice (WMO)", "other": "ostatní stanice"}
    default = leads.band_default(results["90d"][0])
    written = []
    for window, (table, facts) in results.items():
        if table.height == 0:
            continue
        docs = leads.band_documents(table, facts, window, generated, region_names, names, default)
        for name, doc in docs.items():
            written.append(leads.write(doc, out.with_name(name)))
        cz = table.filter(
            pl.col("level") == "cz",
            pl.col("set") == "hourly",
            pl.col("variable") == "temperature_2m",
            pl.col("rank") == 1,
        )
        for band, model, mae, days in cz.select("band", "model", "mae", "days").rows():
            typer.echo(
                f"bands {window} {band}: best {model} temperature MAE {mae:.2f} ({days} days)"
            )
    typer.echo(f"bands: default lead on the page {default or 'D+1'}")
    return written


def _echo_short_runs(command: str, info: dict) -> None:
    """Print the models a single-run comparison left out for too few runs."""
    left_out = info.get("short_record") or {}
    if left_out:
        listed = ", ".join(f"{m} ({f['runs']} of {f['of']} runs)" for m, f in left_out.items())
        typer.echo(f"{command}: left out for too short a record: {listed}")


@app.command("farm")
def farm_cmd(
    runs_days: Annotated[
        int, typer.Option(help="Score the single runs of all models of the last N days.")
    ] = 90,
    data_dir: Annotated[Path, typer.Option(help="Folder with obs/ and runs/.")] = Path("data"),
    out: Annotated[Path, typer.Option(help="The JSON file.")] = Path("site/data/farm.json"),
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Download the single runs (runs-YYYY-MM) and observations (data-YYYY-MM) "
            "from GitHub Releases first (GITHUB_TOKEN, GITHUB_REPOSITORY).",
        ),
    ] = False,
    publish: Annotated[
        bool,
        typer.Option("--publish", help="Put farm.json into the release data-latest."),
    ] = False,
) -> None:
    """Event skill for farmers from the single runs: frost nights (<= 0 and -2 °C), gusts
    (>= 10, 15, 20 m/s in 3 h) and 3-hour rain (>= 0.5, 2, 5 mm) by lead time bin."""
    if publish and not github_release:
        raise typer.BadParameter("--publish needs --github-release")
    now = datetime.now(UTC)
    since = now.replace(minute=0, second=0, microsecond=0) - timedelta(days=runs_days)
    months = partitions.months(since.date(), now.date())
    with httpx.Client(timeout=300, transport=httpx.HTTPTransport(retries=3)) as client:
        releases = _release_store(client) if github_release else None
        if releases:
            runs.RunsSync(releases, data_dir, typer.echo).pull(months)
            store.download(releases, data_dir, months, typer.echo, kinds=("obs",))
        single = leads.scan_runs(data_dir / "runs", since, now)
        obs = partitions.scan_months(data_dir / "obs", since.date(), now.date())
        table = None
        if single is not None and obs is not None:
            models = [m for m in catalogue.load_models() if m.enabled]
            table, info = farm.farm_scores(single, obs, models)
            _echo_short_runs("mvd farm", info)
        if table is None or table.height == 0:
            typer.echo(
                f"mvd farm: no runs with observations since {since:%Y-%m-%d %H} UTC", err=True
            )
            raise typer.Exit(code=1)
        doc = farm.document(table, info, datetime.now(UTC), _model_names())
        path = farm.write(doc, out)
        if publish:
            releases.put(store.LATEST_TAG, path.name, path)
    for line in farm.summary(table):
        typer.echo(line)
    typer.echo(f"{info['runs']} runs, {info['stations']} stations → {path}")


@app.command("blend-test")
def blend_test_cmd(
    data_dir: Annotated[Path, typer.Option(help="Folder with obs/, gauges/, fc/ and scores/.")] = (
        Path("data")
    ),
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table from `mvd stations`.")
    ] = Path("data/stations.parquet"),
    out: Annotated[Path, typer.Option(help="The JSON file.")] = Path("site/data/blend-test.json"),
    days: Annotated[
        int, typer.Option(help="Test the last N scored days (training uses the window before).")
    ] = 180,
    window: Annotated[
        str, typer.Option(help="Training window of the weights, e.g. 90d (as live), 45d, 30d.")
    ] = combine.WINDOW,
    min_training_days: Annotated[
        int, typer.Option(help="Warm-up: scored training days needed before a day is tested.")
    ] = blendtest.MIN_TRAINING_DAYS,
    resamples: Annotated[int, typer.Option(help="Bootstrap resamples of whole days.")] = 1000,
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Download the months' observations, forecasts and scores from GitHub "
            "Releases first (GITHUB_TOKEN, GITHUB_REPOSITORY).",
        ),
    ] = False,
    publish: Annotated[
        bool, typer.Option("--publish", help="Put the JSON file into the release data-latest.")
    ] = False,
) -> None:
    """Out of sample: does our combined forecast beat the best single model? (roadmap 6.4)"""
    if publish and not github_release:
        raise typer.BadParameter("--publish needs --github-release")
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    if not (window.endswith("d") and window[:-1].isdigit() and int(window[:-1]) > 0):
        raise typer.BadParameter(f"window must be a number of days like 90d, not {window!r}")
    with httpx.Client(timeout=300, transport=httpx.HTTPTransport(retries=3)) as client:
        releases = _release_store(client) if github_release else None
        if releases:
            remote = store.remote_months(releases)
            store.download(releases, data_dir, remote, typer.echo, kinds=("scores",))
        files = sorted((data_dir / "scores").glob("*.parquet"))
        if not files:
            typer.echo(f"mvd blend-test: no scores in {data_dir / 'scores'}", err=True)
            raise typer.Exit(code=1)
        variables = list(blendtest.SCORE_VARIABLES.values())
        scores = (
            pl.concat([pl.scan_parquet(f) for f in files], how="diagonal_relaxed")
            .filter(pl.col("variable").is_in(variables))
            .collect()
        )
        last = scores["date"].max()
        first = max(scores["date"].min(), last - timedelta(days=days - 1))
        if releases:
            months = partitions.months(first, last + timedelta(days=1))
            store.download(releases, data_dir, months, typer.echo, kinds=("obs", "gauges", "fc"))
            # the single runs the latest days' D+N are rebuilt from, as in `mvd daily`
            oldest = last - timedelta(days=fresh.DAYS + catalogue.MAX_LEAD_DAY + 1)
            runs.RunsSync(releases, data_dir, typer.echo).pull(partitions.months(oldest, last))
        obs = observations.scan(data_dir, first, last + timedelta(days=1))
        fc = partitions.scan_months(data_dir / "fc", first, last + timedelta(days=1))
        # the fresh days were scored on D+N rebuilt from the single runs: the
        # combination needs the same forecasts (none without data/runs)
        enabled = [m for m in catalogue.load_models() if m.enabled]
        fc, _ = daily_mod.add_fresh(data_dir, enabled, last, obs, fc, typer.echo)
        if obs is None or fc is None:
            typer.echo("mvd blend-test: no observations or forecasts for the test period", err=True)
            raise typer.Exit(code=1)
        table = pl.read_parquet(stations_path)
        test_days, groups, models, info = blendtest.run(
            scores, fc, obs, table, first, last, window, min_training_days, resamples,
            log=typer.echo,
        )  # fmt: skip
        if not groups:
            typer.echo("mvd blend-test: nothing to test yet (warm-up)", err=True)
            raise typer.Exit(code=1)
        doc = blendtest.document(
            test_days, groups, models, info, _model_names(), datetime.now(UTC), window,
            min_training_days, resamples,
        )  # fmt: skip
        path = blendtest.write(doc, out)
        if publish:
            releases.put(store.LATEST_TAG, path.name, path)
    typer.echo(
        f"{doc['test_days']} test days {doc['from']} … {doc['to']} "
        f"({doc['warm_up_days']} scored days before them left out as warm-up)"
    )
    for line in blendtest.summary(groups):
        typer.echo(line)
    typer.echo(f"→ {path}")


@app.command("fetch-runs")
def fetch_runs(
    run: Annotated[
        list[str] | None,
        typer.Option(
            help="Run start, YYYY-MM-DDTHH (HH 00, 06, 12, 18); repeat for several. "
            "Default: every run of the bucket's window, then the API's work."
        ),
    ] = None,
    source: Annotated[
        str,
        typer.Option(
            help="bucket (Open-Meteo's open-data bucket, no API calls), api (the Single "
            "Runs API: the bucket's gaps and the older history) or all (bucket first)."
        ),
    ] = "all",
    mode: Annotated[
        str,
        typer.Option(
            help="The API's runs without --run: recent (the bucket's gaps within its "
            "window), history (older runs) or all (newest first)."
        ),
    ] = "all",
    data_dir: Annotated[
        Path, typer.Option(help="Folder for runs/YYYY-MM.parquet and runs-state.json.")
    ] = Path("data"),
    stations_path: Annotated[
        Path | None,
        typer.Option("--stations", help="Station subset CSV. Default: the committed one."),
    ] = None,
    max_calls: Annotated[
        float, typer.Option(help="Open-Meteo calls this run may use; it resumes next time.")
    ] = 100,
    bucket_minutes: Annotated[
        float, typer.Option(help="Time limit of the bucket's pass; it resumes next time.")
    ] = 40,
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Sync month files and progress with the releases runs-YYYY-MM and "
            "runs-state (GITHUB_TOKEN, GITHUB_REPOSITORY).",
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only print the runs to fetch and their cost.")
    ] = False,
) -> None:
    """Store single model runs (H+1 … H+120) at the station subset: from Open-Meteo's
    open-data bucket (every run of its window not stored yet), then from the Single
    Runs API within a call budget (the bucket's gaps, then the runs since the start of the
    month the bucket's window starts in; older runs come with `mvd backfill`)."""
    if mode not in ("recent", "history", "all"):
        raise typer.BadParameter("use recent, history or all", param_hint="--mode")
    if source not in ("bucket", "api", "all"):
        raise typer.BadParameter("use bucket, api or all", param_hint="--source")
    try:
        chosen = [runs.parse_run(r) for r in run] if run else None
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--run") from exc
    stations_table = runs.load_stations(stations_path)
    models = [m for m in catalogue.load_models() if m.enabled]
    now = datetime.now(UTC)
    modes = ("recent", "history") if mode == "all" else (mode,)
    bucket_result = bucket.Result()
    with httpx.Client(timeout=300, transport=httpx.HTTPTransport(retries=3)) as client:
        sync = None
        if github_release:
            notes_store = GitHubReleaseStore(
                client, *_github_credentials(), notes=runs.RELEASE_NOTES
            )
            sync = runs.RunsSync(notes_store, data_dir, log=typer.echo)
            sync.pull_state()
        if dry_run:
            state = runs.State.load(data_dir / runs.STATE_NAME)
            in_bucket = [
                (r, state.bucket_todo(r, runs.wanted(models, r)))
                for r in (chosen or runs.bucket_runs(now))
            ]
            typer.echo(
                f"bucket: {sum(len(m) for _, m in in_bucket)} model-runs to look for in "
                f"{sum(bool(m) for _, m in in_bucket)} runs"
            )
        elif source in ("bucket", "all"):
            limits = httpx.Limits(max_connections=128, max_keepalive_connections=128)
            with httpx.Client(timeout=60, limits=limits) as s3:
                bucket_result = bucket.collect(
                    bucket.Bucket(s3),
                    stations_table,
                    models,
                    data_dir,
                    now,
                    runs_=chosen,
                    sync=sync,
                    max_minutes=bucket_minutes,
                    log=typer.echo,
                )
            stored = sum(len(v) for v in bucket_result.stored.values())
            typer.echo(f"bucket: {stored} model-runs stored, {bucket_result.rows:,} rows")
            for failed, why in sorted(bucket_result.failed.items()):
                typer.echo(f"bucket error ({failed}): {why}", err=True)
        budget_note = f"{max_calls:g} calls"
        typer.echo(f"API budget: {budget_note}")
        if dry_run:
            state = runs.State.load(data_dir / runs.STATE_NAME)
            edge = runs.bucket_start(now)
            todo = chosen or [
                r
                for r in runs.api_runs(now)
                if ("recent" in modes and r >= edge) or ("history" in modes and r < edge)
            ]
            pending = [
                (r, state.todo(r, runs.wanted(models, r)))
                if chosen
                else (r, state.api_todo(r, runs.wanted(models, r), now))
                for r in todo
            ]
            pending = [(r, m) for r, m in pending if m]
            cost = sum(runs.run_cost(stations_table.height, len(m)) for _, m in pending)
            typer.echo(
                f"API: {len(pending)} runs to fetch at {stations_table.height} stations, about "
                f"{cost:g} Open-Meteo calls ({runs.run_cost(stations_table.height, len(models)):g}"
                f" per run of all {len(models)} models; budget {max_calls:g})"
            )
            return
        budget = forecasts.Budget(max_calls=max_calls)
        result = runs.Result()
        # a schedule with only shared calls: nothing when none are left
        if source in ("api", "all") and max_calls > 0:
            result = runs.collect(
                client,
                stations_table,
                models,
                data_dir,
                budget,
                now,
                runs=chosen,
                modes=modes,
                sync=sync,
                log=typer.echo,
            )
    typer.echo(
        f"API: {len(result.runs)} runs fetched, {budget.used:g} calls used"
        + (f"; stopped: {result.stopped} (run again to continue)" if result.stopped else "")
    )
    _job_summary(
        runs.summary(
            result,
            budget.used,
            data_dir,
            models,
            now,
            budget_note,
            bucket_lines=bucket.summary(bucket_result) if source != "api" else "",
        )
    )
    if result.failed:
        raise typer.Exit(code=1)


@app.command("bucket-cells")
def bucket_cells(
    run: Annotated[
        str | None,
        typer.Option(
            help="Run whose meta.json and files give the grids (YYYY-MM-DDTHH, "
            "00 UTC: every model has it). Default: yesterday's 00 UTC run."
        ),
    ] = None,
    out: Annotated[Path, typer.Option(help="The CSV.")] = Path("src/meteoverdict/data")
    / bucket.CELLS_FILE,
    stations_path: Annotated[
        Path | None,
        typer.Option("--stations", help="Station subset CSV. Default: the committed one."),
    ] = None,
) -> None:
    """Rebuild the grid cell of every run station in every bucket model (nearest cell,
    its model surface height) from Open-Meteo's open-data bucket. Needed after the
    station subset or a model's grid changes (the bucket's reader then reports a grid
    not in the cells file and the API is asked instead)."""
    chosen = (
        runs.parse_run(run)
        if run
        else datetime.combine(
            datetime.now(UTC).date() - timedelta(days=1), datetime.min.time(), UTC
        )
    )
    limits = httpx.Limits(max_connections=64, max_keepalive_connections=64)
    with httpx.Client(timeout=60, limits=limits) as client:
        cells = bucket.build_cells(
            bucket.Bucket(client), runs.load_stations(stations_path), chosen, log=typer.echo
        )
    bucket.write_cells(cells, out)
    typer.echo(f"{cells.height} cells of {cells['bucket_model'].n_unique()} models → {out}")


@app.command("import-runs")
def import_runs(
    harvest: Annotated[
        list[Path],
        typer.Argument(help="Month files of a bucket harvest (runs-YYYY-MM.parquet)."),
    ],
    data_dir: Annotated[
        Path, typer.Option(help="Folder for runs/YYYY-MM.parquet and runs-state.json.")
    ] = Path("data"),
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Merge into and upload the releases runs-YYYY-MM and runs-state.",
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Merge locally, upload nothing.")
    ] = False,
    report: Annotated[
        Path | None, typer.Option(help="Write the counts before and after as JSON here.")
    ] = None,
) -> None:
    """One-off: add a harvest of the bucket's per-run files (the same reading as
    ``mvd fetch-runs``, from before the bucket was used) to the month files. A model-run
    of the harvest replaces every stored row of it (the bucket is preferred for all
    models); model-runs the harvest has incomplete (``bucket.complete_runs``) are left out
    and, with every model-run of the harvested runs it lacks, recorded as missing in the
    bucket, so that the API is asked for them. Stations whose grid cell differs from
    the committed cells are read again from the bucket (dropped where it no longer has
    the run). Prints the counts before and after."""
    models = [m for m in catalogue.load_models() if m.enabled]
    stations_table = runs.load_stations()
    cells = bucket.load_cells()
    doc = {"months": {}, "excluded": [], "reread": {}}
    with httpx.Client(timeout=600, transport=httpx.HTTPTransport(retries=3)) as client:
        sync = None
        if github_release:
            notes_store = GitHubReleaseStore(
                client, *_github_credentials(), notes=runs.RELEASE_NOTES
            )
            sync = runs.RunsSync(notes_store, data_dir, log=typer.echo)
            sync.pull_state()
        state = runs.State.load(data_dir / runs.STATE_NAME)
        limits = httpx.Limits(max_connections=64, max_keepalive_connections=64)
        with httpx.Client(timeout=60, limits=limits) as s3:
            source = bucket.Bucket(s3)
            months, harvested = [], set()
            for path in sorted(harvest):
                raw = pl.read_parquet(path)
                rows = bucket.from_harvest(raw).collect()
                rows, reread = bucket.refresh_moved_cells(
                    raw, rows, cells, source, models, stations_table, log=typer.echo
                )
                for pair, n in reread.items():
                    total = doc["reread"].setdefault(pair, {"reread": 0, "dropped": 0})
                    total["reread"] += n["reread"]
                    total["dropped"] += n["dropped"]
                check = bucket.complete_runs(rows, models, stations_table.height)
                bad = check.filter(~pl.col("complete"))
                doc["excluded"] += [
                    {"run": f"{r:%Y-%m-%d %H}", "model": m, "reason": why}
                    for r, m, _, why in bad.rows()
                ]
                rows = rows.join(bad.select("run", "model"), on=["run", "model"], how="anti")
                harvested |= {(r, m) for r, m, ok, _ in check.rows()}
                for (month,), part in rows.group_by(
                    pl.col("run").dt.strftime("%Y-%m"), maintain_order=True
                ):
                    if sync:
                        sync.pull([month])
                    target = data_dir / "runs" / f"{month}.parquet"
                    stored = pl.read_parquet(target) if target.exists() else None
                    merged = bucket.merge(stored, part)
                    doc["months"][month] = {
                        "before": _runs_counts(stored),
                        "imported": _runs_counts(part),
                        "after": _runs_counts(merged),
                    }
                    target.parent.mkdir(parents=True, exist_ok=True)
                    merged.write_parquet(target, compression="zstd")
                    months.append(month)
                    for r, m in part.select("run", "model").unique().rows():
                        state.fetched.setdefault(runs.key(r), set()).add(m)
                    typer.echo(f"{month}: {json.dumps(doc['months'][month])}")
        first_run = min(r for r, _ in harvested)
        last_run = max(r for r, _ in harvested)
        gaps, now = 0, datetime.now(UTC)
        for r in runs._runs_between(last_run, first_run):
            if now - r < timedelta(hours=runs.BUCKET_FINAL_H):
                continue  # young: the bucket may still complete it (fetch-runs)
            k = runs.key(r)
            for m in state.todo(r, runs.wanted(models, r)):
                state.bucket_missing.setdefault(k, set()).add(m.id)
                gaps += 1
        state.save()
        doc["bucket_missing_added"] = gaps
        doc["runs"] = {"first": f"{first_run:%Y-%m-%d %H}", "last": f"{last_run:%Y-%m-%d %H}"}
        typer.echo(
            f"{len(doc['excluded'])} incomplete model-runs left out; {gaps} model-runs of "
            f"{first_run:%Y-%m-%d %H}..{last_run:%Y-%m-%d %H} UTC recorded as missing in the "
            "bucket (the API is asked for them)"
        )
        if report:
            report.write_text(json.dumps(doc, indent=1, default=str) + "\n", encoding="utf-8")
        if sync and not dry_run:
            sync.push(sorted(set(months)))
            typer.echo(f"uploaded {len(set(months))} month files and the state")


def _runs_counts(frame: pl.DataFrame | None) -> dict:
    """Rows and model-runs of a month file, by source (null: API before 2026-10-17)."""
    if frame is None or frame.height == 0:
        return {"rows": 0, "model_runs": 0, "runs": 0}
    if "source" not in frame.columns:
        frame = frame.with_columns(pl.lit(None, pl.String).alias("source"))
    by = frame.group_by(pl.col("source").fill_null("api (hourly, before 2026-10-17)")).agg(
        pl.len().alias("rows"), pl.struct("run", "model").n_unique().alias("model_runs")
    )
    return {
        "rows": frame.height,
        "model_runs": frame.select("run", "model").unique().height,
        "runs": frame["run"].n_unique(),
        "by_source": {r["source"]: [r["rows"], r["model_runs"]] for r in by.iter_rows(named=True)},
    }


store_app = typer.Typer(help="Raw data store in GitHub Releases (data-YYYY-MM).")
app.add_typer(store_app, name="store")
DataDir = Annotated[Path, typer.Option(help="Folder with obs/ and fc/ subfolders.")]


def _github_credentials() -> tuple[str, str]:
    """``(repo, token)`` from the environment."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        raise typer.BadParameter("needs GITHUB_TOKEN and GITHUB_REPOSITORY in the environment")
    return repo, token


def _job_summary(markdown: str) -> None:
    """Append to the GitHub Actions job summary (shown on the run page), if there is one."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(markdown)


def _release_store(client: httpx.Client) -> GitHubReleaseStore:
    return GitHubReleaseStore(client, *_github_credentials(), notes=store.RELEASE_NOTES)


@store_app.command("upload")
def store_upload(data_dir: DataDir = Path("data")) -> None:
    """Upload monthly obs/fc files that differ from what is stored."""
    with httpx.Client(timeout=600, transport=httpx.HTTPTransport(retries=3)) as client:
        done = store.upload(_release_store(client), data_dir, log=typer.echo)
    typer.echo(f"uploaded {len(done)} files")


@store_app.command("download")
def store_download(
    first: Annotated[str, typer.Option("--from", help="First month, YYYY-MM.")],
    last: Annotated[str | None, typer.Option("--to", help="Last month. Default: --from.")] = None,
    data_dir: DataDir = Path("data"),
) -> None:
    """Download stored monthly obs/fc files that are missing or different locally."""
    try:
        months = store.month_range(first, last or first)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    with httpx.Client(timeout=600, transport=httpx.HTTPTransport(retries=3)) as client:
        done = store.download(_release_store(client), data_dir, months, log=typer.echo)
    typer.echo(f"downloaded {len(done)} files")


class _OpenMeteoMeter:
    """Counts the requests to the Open-Meteo forecast API (``outlook.URL``) an httpx
    client sends, retries included, and their weighted calls (``outlook.cost``), so the
    daily budget can be checked from the log (an httpx ``request`` event hook)."""

    def __init__(self, url: str = outlook.URL) -> None:
        self.url = httpx.URL(url)
        self.requests = 0
        self.calls = 0.0

    def __call__(self, request: httpx.Request) -> None:
        if (request.url.host, request.url.path) != (self.url.host, self.url.path):
            return
        params = request.url.params
        points = len(params.get("latitude", "").split(","))
        models = len([m for m in params.get("models", "").split(",") if m])
        self.requests += 1
        self.calls += outlook.cost(points, max(models, 1))

    def line(self) -> str:
        return f"Open-Meteo: {self.calls:g} calls in {self.requests} requests"


@app.command("outlook")
def outlook_cmd(
    aggregates_path: Annotated[
        Path, typer.Option("--aggregates", help="aggregates.parquet from `mvd aggregate`.")
    ] = Path("data/aggregates.parquet"),
    out: Annotated[
        Path, typer.Option(help="The JSON file to write; outlook-hourly.json goes beside it.")
    ] = Path("site/data/outlook.json"),
    calibration_path: Annotated[
        Path,
        typer.Option(
            "--rain-calibration",
            help="rain-calibration.json from `mvd daily` (missing or too old: the raw share).",
        ),
    ] = Path("site/data") / rain_calibration.FILE,
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Take aggregates.parquet (and rain-calibration.json, frost.json) from and "
            "put outlook.json and outlook-hourly.json into the release data-latest "
            "(GITHUB_TOKEN, GITHUB_REPOSITORY); take the sunshine/cloud coefficients from "
            "there, archive the plain model means in the release outlook-archive and the "
            "models' nights in outlook-nights-YYYY-MM of data-YYYY-MM.",
        ),
    ] = False,
    frost_path: Annotated[
        Path, typer.Option("--frost", help="Frost calibration from `mvd frost-fit`.")
    ] = Path("data/frost.json"),
    data_dir: Annotated[
        Path, typer.Option(help="Folder for the archived nights (outlook-nights/).")
    ] = Path("data"),
    corrections_path: Annotated[
        Path,
        typer.Option(
            "--corrections",
            help="Sunshine/cloud/gust coefficients from `mvd sun-cloud-gust` "
            "(missing: the bootstrap in the package).",
        ),
    ] = Path("data/sun-cloud-gust.json"),
    archive_dir: Annotated[
        Path, typer.Option(help="Folder of the monthly archive of the plain model means.")
    ] = Path("data/outlook-archive"),
) -> None:
    """TV-style forecast for every okres: today's models combined by their okres scores."""
    meter = _OpenMeteoMeter()
    with httpx.Client(
        timeout=300,
        transport=httpx.HTTPTransport(retries=3),
        event_hooks={"request": [meter]},
    ) as client:
        releases = _release_store(client) if github_release else None
        weights_path = aggregates_path.with_name(combine.FORECAST_WEIGHTS_FILE)
        if releases:
            releases.download(store.LATEST_TAG, "aggregates.parquet", aggregates_path)
            if combine.FORECAST_WEIGHTS_FILE in releases.names(store.LATEST_TAG):
                releases.download(store.LATEST_TAG, combine.FORECAST_WEIGHTS_FILE, weights_path)
            if rain_calibration.FILE in releases.names(store.LATEST_TAG):
                releases.download(store.LATEST_TAG, rain_calibration.FILE, calibration_path)
            if sun_cloud_gust.NAME in releases.names(store.LATEST_TAG):
                releases.download(store.LATEST_TAG, sun_cloud_gust.NAME, corrections_path)
        corrections = sun_cloud_gust.load(corrections_path)
        if not aggregates_path.exists():
            raise typer.BadParameter(f"{aggregates_path} not found; run `mvd aggregate`")
        # the forecast's weights with the temperature and wind regression (mvd daily),
        # else the inverse-error weights of the okres scores alone
        if weights_path.exists():
            weights = pl.read_parquet(weights_path)
        else:
            weights = combine.forecast_weights(pl.read_parquet(aggregates_path))
        if weights.is_empty():
            typer.echo("mvd outlook: no okres weights yet", err=True)
            raise typer.Exit(code=1)
        points = combine.okres_points()
        calibration = rain_calibration.load(calibration_path, log=typer.echo)
        if releases and frost_path.name in releases.names(store.LATEST_TAG):
            releases.download(store.LATEST_TAG, frost_path.name, frost_path)
        frost_calibration = frost.Calibration.read(frost_path) if frost_path.exists() else None
        if frost_calibration is None:
            typer.echo(f"mvd outlook: no {frost_path}, the frost fields stay empty", err=True)
        nights: list[pl.DataFrame] = []
        forecasts: list[pl.DataFrame] = []
        single_runs = _outlook_runs(releases, data_dir)
        try:
            table, hourly = outlook.outlook(
                client,
                weights,
                points,
                sleep=time.sleep,
                calibration=calibration,
                corrections=corrections,
                frost_calibration=frost_calibration,
                nights=nights,
                single_runs=single_runs,
                forecasts=forecasts,
            )
        finally:  # also when it fails: the calls count against the daily budget
            typer.echo(meter.line())
            _job_summary(f"## Outlook\n\n- {meter.line()}\n")
        now = datetime.now(UTC)
        path = outlook.write(table, points, out, now)
        hourly_path = outlook.write_hourly(hourly, out.with_name("outlook-hourly.json"), now)
        # every model's own hourly forecast per okres (the detailed forecast page and the
        # model picker of the forecast map read these instead of asking Open-Meteo)
        fc = pl.concat(forecasts)
        models_folder = out.parent / outlook.MODELS_FOLDER
        model_paths = outlook.write_models(fc, hourly, models_folder, now)
        largest = max((p.stat().st_size for p in model_paths), default=0)
        typer.echo(
            f"{len(model_paths)} per-model files → {models_folder} (largest {largest:,} bytes)"
        )
        # every model's parts of day for all okresy, one file per model (the model
        # switch of the forecast map)
        parts_folder = out.parent / outlook.MODEL_PARTS_FOLDER
        days = table["day"].unique().sort().to_list()
        part_paths = outlook.write_model_parts(fc, weights, days, parts_folder, now)
        largest = max((p.stat().st_size for p in part_paths), default=0)
        typer.echo(
            f"{len(part_paths) - 1} per-model part-of-day files → {parts_folder} "
            f"(largest {largest:,} bytes)"
        )
        if releases:
            releases.put(store.LATEST_TAG, "outlook.json", path)
            releases.put(store.LATEST_TAG, "outlook-hourly.json", hourly_path)
            store.publish_folder(releases, models_folder, outlook.MODELS_ZIP)
            store.publish_folder(releases, parts_folder, outlook.MODEL_PARTS_ZIP)
        try:  # training data for the corrections; must not fail the outlook
            _archive_outlook(client, hourly, now, archive_dir, github_release)
        except Exception as exc:
            typer.echo(f"mvd outlook: archive not updated: {exc}", err=True)
        try:  # our own copy of everything fetched; must not fail the outlook
            _archive_outlook_models(client, fc, now, archive_dir, github_release)
        except Exception as exc:
            typer.echo(f"mvd outlook: model archive not updated: {exc}", err=True)
        try:  # what the map showed, for "forecast vs. measured"; must not fail the outlook
            _archive_outlook_parts(client, table, now, archive_dir, github_release)
        except Exception as exc:
            typer.echo(f"mvd outlook: parts archive not updated: {exc}", err=True)
        try:  # training data for the frost clear-calm term; must not fail the outlook
            _archive_outlook_nights(releases, nights, data_dir / frost.ARCHIVE_FOLDER)
        except (httpx.HTTPError, OSError) as exc:
            typer.echo(f"mvd outlook: archiving the nights failed: {exc}", err=True)
    typer.echo(f"{table['okres'].n_unique()} okresy, {table.height} rows → {path}")


def _outlook_runs(releases: GitHubReleaseStore | None, data_dir: Path) -> pl.LazyFrame | None:
    """The single runs of the last ``gusts.MAX_RUN_AGE_H`` hours for the outlook's gusts
    (with ``releases`` first downloaded from runs-YYYY-MM; no Open-Meteo calls); None
    when there are none or they cannot be had (the gusts then stay empty)."""
    now = datetime.now(UTC)
    since = now - timedelta(hours=gusts.MAX_RUN_AGE_H)
    try:
        if releases:
            runs.RunsSync(releases, data_dir, typer.echo).pull(
                partitions.months(since.date(), now.date())
            )
        found = leads.scan_runs(data_dir / "runs", since, now)
    except (httpx.HTTPError, OSError, RuntimeError) as exc:
        typer.echo(f"mvd outlook: no single runs, the gusts stay empty: {exc}", err=True)
        return None
    if found is None:
        typer.echo("mvd outlook: no single runs, the gusts stay empty", err=True)
    return found


def _archive_outlook_nights(
    releases: GitHubReleaseStore | None, nights: list[pl.DataFrame], folder: Path
) -> None:
    """Merge the models' nights at the okres points into ``folder/YYYY-MM.parquet`` (by
    run month) and, with ``releases``, into ``outlook-nights-YYYY-MM.parquet`` of the
    release ``data-YYYY-MM``: training data for the clear-calm term, no extra calls."""
    rows = [n for n in nights if n.height]
    if not rows:
        return
    merged = pl.concat(rows)
    for month in sorted({f"{run:%Y-%m}" for run in merged["run"].unique().to_list()}):
        name = frost.archive_name(month)
        if releases and name in releases.names(store.release_tag(month)):
            releases.download(store.release_tag(month), name, folder / f"{month}.parquet")
    for written in frost.write_archive(merged, folder):
        if releases:
            releases.put(store.release_tag(written.stem), frost.archive_name(written.stem), written)
        typer.echo(f"archived the outlook nights → {written}")


def _archive_outlook(
    client: httpx.Client, hourly: pl.DataFrame, now: datetime, folder: Path, github: bool
) -> None:
    """Add this run's plain model means of cloud and sunshine to the month file (and to
    the release outlook-archive)."""
    tag, name = sun_cloud_gust.archive_asset(f"{now:%Y-%m}")
    path = folder / name
    archive = None
    if github:
        archive = GitHubReleaseStore(
            client, *_github_credentials(), notes=sun_cloud_gust.ARCHIVE_NOTES
        )
        if name in archive.assets(tag):
            archive.download(tag, name, path)
    sun_cloud_gust.append_archive(path, sun_cloud_gust.archive_rows(hourly, now))
    if archive:
        archive.put(tag, name, path, label=store.sha256(path))
    typer.echo(f"archived the plain means → {path}")


def _archive_outlook_models(
    client: httpx.Client, fc: pl.DataFrame, now: datetime, folder: Path, github: bool
) -> None:
    """Merge this run's answer (every model, variable and hour at the okres points) into
    the day's ``outlook-models-YYYY-MM-DD.parquet`` (and the release
    ``outlook-models-YYYY-MM``): our own copy of what the outlook fetched, one run per
    ``issued``, no duplicates; a run moves only its day's file (a few MB)."""
    tag, name = outlook.model_archive_asset(now)
    path = folder / name
    archive = None
    if github:
        archive = GitHubReleaseStore(
            client, *_github_credentials(), notes=outlook.MODEL_ARCHIVE_NOTES
        )
        if name in archive.assets(tag):
            archive.download(tag, name, path)
    outlook.append_model_archive(path, outlook.model_archive_rows(fc, now))
    if archive:
        archive.put(tag, name, path, label=store.sha256(path))
    typer.echo(f"archived the models' forecasts → {path} ({path.stat().st_size:,} bytes)")


def _archive_outlook_parts(
    client: httpx.Client, table: pl.DataFrame, now: datetime, folder: Path, github: bool
) -> None:
    """Merge this run's parts of day (outlook.json's values) into the month's
    ``outlook-parts-YYYY-MM.parquet`` (and the release outlook-archive): the forecast
    the observed map compares with what was measured (``mvd observed-map``)."""
    tag, name = outlook.parts_archive_asset(now)
    path = folder / name
    archive = None
    if github:
        archive = GitHubReleaseStore(client, *_github_credentials())
        if name in archive.assets(tag):
            archive.download(tag, name, path)
    outlook.append_parts_archive(path, outlook.parts_archive_rows(table, now))
    if archive:
        archive.put(tag, name, path, label=store.sha256(path))
    typer.echo(f"archived the parts of day → {path} ({path.stat().st_size:,} bytes)")


@app.command("frost-fit")
def frost_fit_cmd(
    data_dir: Annotated[
        Path, typer.Option(help="Folder with fc/ and outlook-nights/ (monthly files).")
    ] = Path("data"),
    chmi_dir: Annotated[
        Path, typer.Option(help="ČHMÚ archive folder (<tag>/<name>), for chmi-daily-*.")
    ] = Path("data/chmi"),
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table from `mvd stations`.")
    ] = Path("data/stations.parquet"),
    out: Annotated[Path, typer.Option(help="The calibration file.")] = Path("data/frost.json"),
    nights: Annotated[
        int, typer.Option(help="Training window: the last N nights with observations.")
    ] = frost.WINDOW_NIGHTS,
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Download the D+N forecasts (data-YYYY-MM), the archived outlook nights "
            "and ČHMÚ's daily data (chmi-YYYY) from GitHub Releases first.",
        ),
    ] = False,
    publish: Annotated[
        bool, typer.Option("--publish", help="Put frost.json into the release data-latest.")
    ] = False,
) -> None:
    """Night-minimum corrections for the frost fields of the outlook: per model and lead
    day, per station, and the clear-calm term (docs/methodology.md#frost)."""
    if publish and not github_release:
        raise typer.BadParameter("--publish needs --github-release")
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    today = datetime.now(UTC).date()
    first = today - timedelta(days=nights + 3)
    months = partitions.months(first, today)
    archive_dir = data_dir / frost.ARCHIVE_FOLDER
    with httpx.Client(timeout=600, transport=httpx.HTTPTransport(retries=3)) as client:
        releases = _release_store(client) if github_release else None
        if releases:
            store.download(releases, data_dir, months, typer.echo, kinds=("fc",))
            for month in months:
                name = frost.archive_name(month)
                if name in releases.names(store.release_tag(month)):
                    releases.download(
                        store.release_tag(month), name, archive_dir / f"{month}.parquet"
                    )
            wanted = [chmi_archive.month_asset("daily", int(m[:4]), int(m[5:])) for m in months]
            chmi_archive.sync(_archive_releases(client), chmi_dir, wanted, log=typer.echo)
        daily = chmi_archive.scan(chmi_dir, "chmi-daily-*.parquet")
        fc = partitions.scan_months(data_dir / "fc", first, today)
        if daily is None or fc is None:
            typer.echo("mvd frost-fit: no forecasts or no ČHMÚ daily data", err=True)
            raise typer.Exit(code=1)
        start = datetime.combine(first, datetime.min.time(), UTC)
        obs = frost.observed_nights(daily.filter(pl.col("time") >= start))
        fc = fc.filter(pl.col("lead_day") <= frost.MAX_LEAD, pl.col("time") >= start)
        pairs = frost.forecast_pairs(fc, obs)
        if pairs.is_empty():
            typer.echo("mvd frost-fit: no forecast nights with observations", err=True)
            raise typer.Exit(code=1)
        calibration = frost.fit(pairs, pl.read_parquet(stations_path), window_nights=nights)
        archive = partitions.scan_months(archive_dir, first, today)
        if archive is not None:
            calibration.clear_calm = frost.refit_clear_calm(archive.collect(), obs, calibration)
        path = calibration.write(out)
        if publish:
            releases.put(store.LATEST_TAG, path.name, path)
    cc = calibration.clear_calm
    typer.echo(
        f"{calibration.first} … {calibration.last}: {calibration.stations.height} stations, "
        f"sigma {calibration.sigma:.2f} °C, clear-calm {cc['intercept']:+.2f} "
        f"{cc['cloud']:+.2f}·cloud {cc['wind']:+.2f}·wind ({cc['source']}) → {path}"
    )


@app.command("sun-cloud-gust")
def sun_cloud_gust_cmd(
    archive_dir: Annotated[
        Path, typer.Option(help="Folder of the outlook's monthly archive.")
    ] = Path("data/outlook-archive"),
    chmi_dir: Annotated[
        Path, typer.Option(help="ČHMÚ archive folder (<tag>/<name>), as chmi-archive.")
    ] = Path("data/chmi"),
    data_dir: Annotated[
        Path, typer.Option(help="Folder with runs/ (single runs) and obs/ (hourly gusts).")
    ] = Path("data"),
    out: Annotated[Path, typer.Option(help="The coefficients (JSON).")] = Path(
        "data/sun-cloud-gust.json"
    ),
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Download the archive, the ČHMÚ files, the single runs, the hourly "
            "observations (data-YYYY-MM) and the current coefficients from GitHub "
            "Releases first (read only).",
        ),
    ] = False,
    publish: Annotated[
        bool, typer.Option("--publish", help="Put the JSON into the release data-latest.")
    ] = False,
) -> None:
    """Refit the sunshine, cloud and gust corrections of the outlook on the last 60 days
    of its archived forecasts and ČHMÚ observations (needs 21 days, else keeps the
    current or bootstrap coefficients). No Open-Meteo calls."""
    if publish and not github_release:
        raise typer.BadParameter("--publish needs --github-release")
    now = datetime.now(UTC)
    today = now.date()
    first = today - timedelta(days=sun_cloud_gust.WINDOW_DAYS + sun_cloud_gust.MAX_LEAD + 1)
    months = partitions.months(first, today)
    with httpx.Client(timeout=600, transport=httpx.HTTPTransport(retries=3)) as client:
        releases = _release_store(client) if github_release else None
        if releases:
            if sun_cloud_gust.NAME in releases.names(store.LATEST_TAG):
                releases.download(store.LATEST_TAG, sun_cloud_gust.NAME, out)
            archive = GitHubReleaseStore(client, *_github_credentials())
            names = archive.assets(sun_cloud_gust.ARCHIVE_TAG)
            for month in months:
                tag, name = sun_cloud_gust.archive_asset(month)
                if name in names:
                    archive.download(tag, name, archive_dir / name)
            chmi_archive.sync(
                _archive_releases(client), chmi_dir, sun_cloud_gust.wanted_chmi(today), typer.echo
            )
            runs.RunsSync(releases, data_dir, typer.echo).pull(months)
            store.download(releases, data_dir, months, typer.echo, kinds=("obs",))
    with _chmi_client() as client:
        meta1 = fetch_current_meta(client, 1, today)
    station_table = meta1.select(
        pl.col("WSI").alias("id"),
        pl.col("GEOGR2").cast(pl.Float64).alias("lat"),  # GEOGR1 is longitude
        pl.col("GEOGR1").cast(pl.Float64).alias("lon"),
        pl.col("ELEVATION").cast(pl.Float64).alias("elevation"),
    ).unique("id")
    chmi_daily, chmi_hourly = sun_cloud_gust.read_chmi(chmi_dir, today)
    since = datetime.combine(first, datetime.min.time(), UTC)
    single = leads.scan_runs(data_dir / "runs", since, now)
    doc, info = sun_cloud_gust.fit_from_files(
        sun_cloud_gust.load(out),
        today,
        sun_cloud_gust.read_archive(archive_dir, today),
        chmi_daily,
        chmi_hourly,
        station_table,
        combine.okres_points(),
        runs.load_stations(),
        single,
        gusts.pairs(
            single,
            partitions.scan_months(data_dir / "obs", first, today),
            gusts.okres_stations(
                runs.load_stations(), combine.okres_points(), combine.point_elevations()
            )["station"].unique(),
        ),
    )
    sun_cloud_gust.write(doc, out)
    lines = [
        f"- {v}: {i['source']}, {i['days']} days, {i['pairs']} pairs, {i['okresy']} "
        + ("stations" if v == "gust_part" else "okresy with a station")
        for v, i in info.items()
    ]
    check = doc.get("gust_part", {}).get("check")
    if check:
        lines.append(
            f"- gust_part check {check['from']}…{check['to']}: MAE plain {check['raw_mae']} → "
            f"corrected {check['corrected_mae']} m/s ({check['pairs']} pairs); applied: "
            f"{doc['gust_part'].get('apply', True)}"
        )
    for line in lines:
        typer.echo(line)
    _job_summary("## Sunshine, cloud and gust corrections\n\n" + "\n".join(lines) + "\n")
    if publish:
        with httpx.Client(timeout=600, transport=httpx.HTTPTransport(retries=3)) as client:
            _release_store(client).put(store.LATEST_TAG, sun_cloud_gust.NAME, out)
    typer.echo(f"→ {out}")


@app.command("models")
def models_cmd(
    show_all: Annotated[
        bool, typer.Option("--all", help="Also list models that are disabled in models.yaml.")
    ] = False,
) -> None:
    """List the weather models from models.yaml."""
    for m in catalogue.load_models():
        if not (m.enabled or show_all):
            continue
        leads = f"D+1..D+{m.lead_days[-1]}"
        later = "".join(f", {var} from {day}" for var, day in m.variable_from.items())
        flag = "" if m.enabled else "  (disabled)"
        typer.echo(f"{m.id:32} {m.name:36} {leads:9} archive from {m.archive_from}{later}{flag}")


@app.command("fetch-obs")
def fetch_obs(
    start: DateOption,
    end: DateOption,
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table from `mvd stations`.")
    ] = Path("data/stations.parquet"),
    out_dir: Annotated[Path, typer.Option(help="Monthly Parquet files go here.")] = Path(
        "data/obs"
    ),
) -> None:
    """Fetch hourly ČHMÚ station observations (T2m, precipitation, wind) for a date range."""
    _check_range(start.date(), end.date())
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    table = pl.read_parquet(stations_path)
    transport = httpx.HTTPTransport(retries=3)
    try:
        with httpx.Client(timeout=120, transport=transport, follow_redirects=True) as client:
            meta2 = fetch_current_meta(client, 2, datetime.now(UTC).date())
            ids = observations.verification_stations(table, meta2)["id"]
            obs = observations.fetch_observations(client, ids, start.date(), end.date())
    except httpx.HTTPError as exc:
        typer.echo(f"mvd fetch-obs: download failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    written = observations.write_monthly(obs, out_dir)
    typer.echo(
        f"{obs.height} hourly values from {obs['station_id'].n_unique()} of {len(ids)} "
        f"stations → {', '.join(str(p) for p in written) or 'nothing'}"
    )


@app.command("fetch-gauges")
def fetch_gauges(
    start: DateOption,
    end: DateOption,
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table from `mvd stations`.")
    ] = Path("data/stations.parquet"),
    out_dir: Annotated[Path, typer.Option(help="Monthly Parquet files go here.")] = Path(
        "data/gauges"
    ),
) -> None:
    """Fetch daily precipitation of the manual rain gauges (06-06 UTC windows).

    Also reads ČHMÚ's historical file (2.5 MB per gauge) for months older than
    ``recent/``: run it once for the history, the scheduled runs keep it current.
    """
    _check_range(start.date(), end.date())
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    table = pl.read_parquet(stations_path)
    transport = httpx.HTTPTransport(retries=3)
    try:
        with httpx.Client(timeout=120, transport=transport, follow_redirects=True) as client:
            meta2 = fetch_current_meta(client, 2, datetime.now(UTC).date())
            ids = gauges.gauge_stations(table, meta2)["id"]
            rows = gauges.fetch_gauge_precipitation(client, ids, start.date(), end.date())
    except httpx.HTTPError as exc:
        typer.echo(f"mvd fetch-gauges: download failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    written = observations.write_monthly(rows, out_dir)
    typer.echo(
        f"{rows.height} daily values from {rows['station_id'].n_unique()} of {len(ids)} "
        f"gauges → {', '.join(str(p) for p in written) or 'nothing'}"
    )


@app.command("fetch-fc")
def fetch_fc(
    start: DateOption,
    end: DateOption,
    model: Annotated[
        list[str] | None,
        typer.Option(help="Model id from models.yaml; repeat for several. Default: all enabled."),
    ] = None,
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table from `mvd stations`.")
    ] = Path("data/stations.parquet"),
    out_dir: Annotated[Path, typer.Option(help="Monthly Parquet files go here.")] = Path("data/fc"),
    max_calls: Annotated[
        float, typer.Option(help="Stop before using more weighted Open-Meteo calls than this.")
    ] = 9000,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only print how many calls it would use.")
    ] = False,
) -> None:
    """Fetch archived forecasts from the Open-Meteo Previous Runs API for a date range."""
    _check_range(start.date(), end.date())
    known = {m.id: m for m in catalogue.load_models()}
    unknown = sorted(set(model or []) - set(known))
    if unknown:
        raise typer.BadParameter(
            f"unknown model(s) {', '.join(unknown)}; see `mvd models --all`", param_hint="--model"
        )
    chosen = [known[m] for m in model] if model else [m for m in known.values() if m.enabled]
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    table = pl.read_parquet(stations_path)
    transport = httpx.HTTPTransport(retries=3)
    with httpx.Client(timeout=180, transport=transport, follow_redirects=True) as client:
        try:
            meta2 = fetch_current_meta(client, 2, datetime.now(UTC).date())
        except httpx.HTTPError as exc:
            typer.echo(f"mvd fetch-fc: could not download ČHMÚ meta2: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        points = observations.verification_stations(table, meta2)
        estimate = forecasts.estimate_calls(points.height, chosen, start.date(), end.date())
        typer.echo(
            f"{len(chosen)} models x {points.height} stations, {start:%Y-%m-%d}..{end:%Y-%m-%d}: "
            f"about {estimate:g} Open-Meteo calls (budget {max_calls:g})"
        )
        if dry_run:
            return
        budget = forecasts.Budget(max_calls=max_calls)
        code = 0
        try:
            fc = forecasts.fetch_forecasts(
                client, points, chosen, start.date(), end.date(), budget, log=typer.echo
            )
        except forecasts.QuotaError as exc:
            typer.echo(f"mvd fetch-fc: stopped: {exc}", err=True)
            fc, code = exc.partial, 3
        except httpx.HTTPError as exc:
            typer.echo(f"mvd fetch-fc: download failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    written = partitions.write_monthly(fc, out_dir, forecasts.KEYS)
    typer.echo(
        f"{fc.height} rows, {budget.used:g} calls used → "
        f"{', '.join(str(p) for p in written) or 'nothing'}"
    )
    if code:
        raise typer.Exit(code=code)


@app.command()
def score(
    start: DateOption,
    end: DateOption,
    data_dir: Annotated[
        Path, typer.Option(help="Folder with obs/ and fc/; scores go to <data-dir>/scores.")
    ] = Path("data"),
    exclude_estimated: Annotated[
        bool, typer.Option(help="Ignore observations ČHMÚ marked as estimated (quality 3).")
    ] = False,
) -> None:
    """Score forecasts against observations into the daily scores table."""
    first, last = start.date(), end.date()
    _check_range(first, last)
    # daily precipitation of the last day ends at 24:00 = next day 00:00
    obs = observations.scan(data_dir, first, last + timedelta(days=1))
    fc = partitions.scan_months(data_dir / "fc", first, last + timedelta(days=1))
    if obs is None or fc is None:
        missing = "observations (mvd fetch-obs)" if obs is None else "forecasts (mvd fetch-fc)"
        typer.echo(f"mvd score: no {missing} in {data_dir} for that period", err=True)
        raise typer.Exit(code=1)
    models = catalogue.load_models()
    table = scoring.daily_scores(obs, fc, models, first, last, exclude_estimated)
    written = partitions.write_monthly(table, data_dir / "scores", scoring.KEYS, "date")
    typer.echo(
        f"{table.height} score rows for {table['station_id'].n_unique()} stations and "
        f"{table['model'].n_unique()} models → {', '.join(str(p) for p in written) or 'nothing'}"
    )


def _model_names() -> dict[str, str]:
    """Display names of the models and of the blend (their mean)."""
    return {m.id: m.name for m in [*catalogue.load_models(), blend.MODEL]}


def _forecast_weights(
    table: pl.DataFrame, scores: pl.LazyFrame, station_table: pl.DataFrame, data_dir: Path
) -> pl.DataFrame:
    """The forecast's weight table (``combine.forecast_weights``), with the temperature
    and wind regression fitted on the observations and forecasts of the last 90 days in
    ``data_dir`` where they are there (``mvd daily``); written to
    ``data_dir/forecast-weights.parquet`` for ``mvd outlook``."""
    coefficients = None
    if table.height:
        as_of = table.filter(pl.col("window") == combine.WINDOW)["to"].max()
        allowed = combine.weights(table).select("variable", "lead_day", "model").unique()
        if as_of is not None:
            # the forecasts of fc/ plus the recent days rebuilt from the single runs, as
            # scored by mvd daily (fresh), so the regression is as recent as the scores
            first, last = mos.training_span(as_of)
            fc = partitions.scan_months(data_dir / "fc", first, last)
            obs = observations.scan(data_dir, first, last)
            models = [m for m in catalogue.load_models() if m.enabled]
            fc, _ = daily_mod.add_fresh(data_dir, models, as_of, obs, fc)
            coefficients = mos.recent(data_dir, scores, station_table, as_of, allowed, fc)
    fitted = 0 if coefficients is None else coefficients["region"].n_unique()
    typer.echo(f"regression blend (temperature, wind): {fitted} okresy")
    forecast = combine.forecast_weights(table, coefficients)
    forecast.write_parquet(data_dir / combine.FORECAST_WEIGHTS_FILE, compression="zstd")
    return forecast


def _publish_aggregates(
    files: list[Path],
    station_table: pl.DataFrame,
    data_dir: Path,
    out: Path,
    as_of: date | None,
    resamples: int,
) -> pl.DataFrame:
    """Aggregate and rank all score files; write aggregates.parquet and the JSON."""
    # files written before a column was added lack it (see partitions.scan_months)
    scores = pl.concat([pl.scan_parquet(f) for f in files], how="diagonal_relaxed")
    table = aggregate.aggregate(scores, station_table, as_of)
    ranks = ranking.rank(scores, station_table, as_of, resamples=resamples)
    table = table.join(ranks, on=[*ranking.GROUP, "model"], how="left")
    table.write_parquet(data_dir / "aggregates.parquet", compression="zstd")
    forecast = _forecast_weights(table, scores, station_table, data_dir)
    names = _model_names()
    meta = aggregate.metadata(table, names, datetime.now(UTC))
    meta["sources"] = fresh.sources(scores)
    for window, left_out in meta["short_record"].items():
        listed = ", ".join(
            f"{m} ({f['days']} days, {f['coverage']:.0%}: {', '.join(f['variables'])})"
            for m, f in left_out.items()
        )
        typer.echo(f"{window}: left out for too short a record (not ranked, no weight): {listed}")
    written = [
        *aggregate.write_json(table, out, meta),
        aggregate.write_stations(station_table, out),
        *combine.write_forecast(table, out, forecast),
    ]
    if table.height:
        last = table["to"].max()
        written += aggregate.write_series(scores, out, last, ranking.RANKED_VARIABLES)
    typer.echo(f"{table.height} rows, as of {meta['as_of']} → {len(written)} JSON files in {out}")
    return table


def _write_badge(aggregates_table: pl.DataFrame, site: Path) -> None:
    """``site/badge.json``: when the scores were last updated, for the README badge."""
    scored = aggregates_table["to"].max() if aggregates_table.height else None
    site.mkdir(parents=True, exist_ok=True)
    badge = report_mod.badge(datetime.now(UTC), scored)
    (site / "badge.json").write_text(json.dumps(badge), encoding="utf-8")


@app.command("aggregate")
def aggregate_cmd(
    data_dir: Annotated[Path, typer.Option(help="Folder with scores/.")] = Path("data"),
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table from `mvd stations`.")
    ] = Path("data/stations.parquet"),
    out: Annotated[Path, typer.Option(help="Folder for the JSON files.")] = Path("site/data"),
    as_of: Annotated[
        datetime | None,
        typer.Option(
            formats=["%Y-%m-%d"], help="Last day of the windows. Default: last scored day."
        ),
    ] = None,
    resamples: Annotated[int, typer.Option(help="Bootstrap resamples for the ranking.")] = 1000,
) -> None:
    """Aggregate and rank daily scores per station, okres, kraj, elevation class and Czechia."""
    files = sorted((data_dir / "scores").glob("*.parquet"))
    if not files:
        typer.echo(f"mvd aggregate: no scores in {data_dir / 'scores'}; run `mvd score`", err=True)
        raise typer.Exit(code=1)
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    day = as_of.date() if as_of else None
    _publish_aggregates(files, pl.read_parquet(stations_path), data_dir, out, day, resamples)


@app.command("station-check")
def station_check_cmd(
    data_dir: Annotated[Path, typer.Option(help="Folder with scores/.")] = Path("data"),
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table from `mvd stations`.")
    ] = Path("data/stations.parquet"),
    out: Annotated[
        Path | None, typer.Option(help="Write the Markdown report here (default: print it).")
    ] = None,
    resamples: Annotated[int, typer.Option(help="Bootstrap resamples for the ranking.")] = 1000,
    top: Annotated[int, typer.Option(help="How many suspicious stations to list.")] = 10,
) -> None:
    """Does it matter which stations score the models? Rankings with only the main WMO
    stations, the automatic climate stations or the manual rain gauges against all
    stations, and stations whose errors stand out (docs/station-check.md)."""
    files = sorted((data_dir / "scores").glob("*.parquet"))
    if not files:
        typer.echo(f"mvd station-check: no scores in {data_dir / 'scores'}", err=True)
        raise typer.Exit(code=1)
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    table = pl.read_parquet(stations_path)
    with _chmi_client() as client:
        meta2 = _meta2_tables(client)
    kinds = station_check.networks(table, meta2)
    # files written before a column was added lack it (see partitions.scan_months)
    scores = pl.concat([pl.scan_parquet(f) for f in files], how="diagonal_relaxed")
    subsets = {"all": None, **station_check.subsets_by_network(kinds)}
    ranks = station_check.compare_subsets(scores, table, subsets, resamples=resamples)
    summary = station_check.summarize(ranks)
    errors = station_check.station_errors(scores)
    daily = station_check.daily_errors(scores)
    flagged = station_check.suspicious_stations(errors, daily, table, kinds)
    text = station_check.report(summary, flagged, top)
    if out:
        out.write_text(text, "utf-8")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@app.command()
def report(
    data_dir: Annotated[Path, typer.Option(help="Folder with aggregates.parquet.")] = Path("data"),
) -> None:
    """Print the best model per kraj from aggregated scores (a Markdown table)."""
    path = data_dir / "aggregates.parquet"
    if not path.exists():
        typer.echo(f"mvd report: {path} not found; run `mvd aggregate`", err=True)
        raise typer.Exit(code=1)
    typer.echo(report_mod.leaderboard(pl.read_parquet(path), _model_names()))


@app.command()
def daily(
    day: Annotated[
        datetime | None,
        typer.Option(
            "--date", formats=["%Y-%m-%d"], help="Day to process (UTC). Default: yesterday."
        ),
    ] = None,
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table from `mvd stations`.")
    ] = Path("data/stations.parquet"),
    data_dir: Annotated[Path, typer.Option(help="Folder for obs/, fc/ and scores/.")] = Path(
        "data"
    ),
    out: Annotated[Path, typer.Option(help="Folder for the web map JSON.")] = Path("site/data"),
    resamples: Annotated[int, typer.Option(help="Bootstrap resamples for the ranking.")] = 1000,
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Sync data with GitHub Releases (GITHUB_TOKEN, GITHUB_REPOSITORY).",
        ),
    ] = False,
) -> None:
    """Daily pipeline: capture observations, re-score, aggregate, write the JSON and badge."""
    target = day.date() if day else _yesterday()
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    table = pl.read_parquet(stations_path)
    models = [m for m in catalogue.load_models() if m.enabled]
    window = partitions.months(target - timedelta(days=daily_mod.RESCORE_DAYS), target)
    transport = httpx.HTTPTransport(retries=3)
    with httpx.Client(timeout=300, transport=transport, follow_redirects=True) as client:
        sync = None
        if github_release:
            sync = store.ReleaseSync(_release_store(client), data_dir, log=typer.echo)
            sync.pull(window)
            # the single runs the recent days' D+N are rebuilt from (read only)
            oldest = target - timedelta(days=fresh.DAYS + catalogue.MAX_LEAD_DAY + 1)
            runs.RunsSync(sync.store, data_dir, typer.echo).pull(partitions.months(oldest, target))
        meta2 = fetch_current_meta(client, 2, datetime.now(UTC).date())
        points = observations.verification_stations(table, meta2)
        months = daily_mod.run(
            client,
            points,
            models,
            target,
            data_dir,
            log=typer.echo,
            gauge_points=_gauge_points(table, meta2, points),
        )
        if sync:
            sync.push(months)
            remote = store.remote_months(sync.store)
            store.download(sync.store, data_dir, remote, typer.echo, kinds=("scores",))
    files = sorted((data_dir / "scores").glob("*.parquet"))
    if not files:
        typer.echo("no scores yet")
        return
    aggregates_table = _publish_aggregates(files, table, data_dir, out, None, resamples)
    _write_badge(aggregates_table, out)
    calibration = _refit_rain_calibration(table, data_dir, target, out)
    if github_release:
        with httpx.Client(timeout=300, transport=httpx.HTTPTransport(retries=3)) as client:
            releases = _release_store(client)
            store.publish_latest(releases, data_dir, out)
            if calibration:
                releases.put(store.LATEST_TAG, calibration.name, calibration)
        typer.echo(f"published aggregates and site data to the release {store.LATEST_TAG}")


def _refit_rain_calibration(
    station_table: pl.DataFrame, data_dir: Path, day: date, out: Path
) -> Path | None:
    """Refit the calibrated rain probability of the outlook on the verified 6-hour cases
    of the last ``rain_calibration.WINDOW_DAYS`` days (``out/rain-calibration.json``).
    Not fatal: on failure the outlook keeps the last published calibration until it is
    ``rain_calibration.MAX_AGE_DAYS`` old, then the raw share of models."""
    first = day - timedelta(days=rain_calibration.WINDOW_DAYS - 1)
    obs = observations.scan(data_dir, first, day + timedelta(days=1))
    fc = partitions.scan_months(data_dir / "fc", first, day + timedelta(days=1))
    if obs is None or fc is None:
        typer.echo("rain calibration: no forecasts or observations")
        return None
    try:
        calibration = rain_calibration.refit(
            fc, obs, station_table, combine.okres_points(), day, generated=datetime.now(UTC)
        )
    except Exception as exc:  # the daily scores matter more than this refit
        typer.echo(f"rain calibration failed: {type(exc).__name__}: {exc}", err=True)
        return None
    if calibration is None:
        typer.echo(f"rain calibration: fewer than {rain_calibration.MIN_DAYS} days of cases")
        return None
    path = rain_calibration.write(calibration, out / rain_calibration.FILE)
    info = calibration.info
    typer.echo(
        f"rain calibration: {calibration.days} days, {calibration.cases} cases "
        f"{calibration.first}..{calibration.last}; Brier in sample {info.get('brier')} "
        f"(raw share {info.get('brier_share')}), heavy rain flag at "
        f"{calibration.heavy_flag_at} → {path}"
    )
    return path


@app.command()
def check(
    data_dir: Annotated[Path, typer.Option(help="Folder with obs/, fc/ and scores/.")] = Path(
        "data"
    ),
    meta: Annotated[
        Path, typer.Option(help="Published meta.json: its as_of must be recent.")
    ] = Path("site/data/meta.json"),
) -> None:
    """Data quality checks: exit 1 on stale data or many missing stations."""
    findings = quality.check(data_dir, meta_path=meta)
    text = quality.report(findings)
    typer.echo(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:  # shown on the workflow run page
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Data quality\n\n" + text.replace("\n", "\n\n") + "\n")
    if any(f.level == "error" for f in findings):
        raise typer.Exit(code=1)


def _gauge_points(table: pl.DataFrame, meta2: pl.DataFrame, points: pl.DataFrame):
    """Rain gauges that are not verified hourly (closed stations are both)."""
    found = gauges.gauge_stations(table, meta2)
    return found.filter(~pl.col("id").is_in(points["id"].to_list()))


@app.command()
def backfill(
    start: Annotated[
        datetime,
        typer.Option("--from", formats=["%Y-%m-%d"], help="First day (UTC), e.g. 2024-01-01."),
    ],
    end: Annotated[
        datetime | None,
        typer.Option("--to", formats=["%Y-%m-%d"], help="Last day (UTC). Default: yesterday."),
    ] = None,
    stations_path: Annotated[
        Path, typer.Option("--stations", help="Station table from `mvd stations`.")
    ] = Path("data/stations.parquet"),
    data_dir: Annotated[Path, typer.Option(help="Folder for obs/, fc/ and scores/.")] = Path(
        "data"
    ),
    max_calls: Annotated[
        float, typer.Option(help="Open-Meteo calls this run may use; it resumes next time.")
    ] = 6000,
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Sync month files and progress with GitHub Releases (GITHUB_TOKEN, "
            "GITHUB_REPOSITORY).",
        ),
    ] = False,
    runs_history: Annotated[
        bool,
        typer.Option(
            help="With each window also the single runs' API history of its days (runs "
            "older than the month the bucket's window starts in, at the station subset of "
            "the single runs; with --github-release in the releases runs-YYYY-MM and "
            "runs-state, else in --data-dir).",
        ),
    ] = True,
    runs_stations: Annotated[
        Path | None,
        typer.Option(help="Station subset CSV of the single runs. Default: the committed one."),
    ] = None,
) -> None:
    """Backfill history newest first, in 14-day windows, resumable (state in the data
    dir): each window's D+N at every station and the rain gauges, then the single runs'
    API history of its days, before the next older window."""
    first, last = start.date(), end.date() if end else _yesterday()
    _check_range(first, last, hint="--from/--to")
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    table = pl.read_parquet(stations_path)
    models = [m for m in catalogue.load_models() if m.enabled]
    now = datetime.now(UTC)
    transport = httpx.HTTPTransport(retries=3)
    with httpx.Client(timeout=300, transport=transport, follow_redirects=True) as client:
        sync = runs_sync = None
        if github_release:
            sync = store.ReleaseSync(_release_store(client), data_dir, log=typer.echo)
            sync.pull_state()
        history = None
        if runs_history:
            if github_release:
                notes_store = GitHubReleaseStore(
                    client, *_github_credentials(), notes=runs.RELEASE_NOTES
                )
                runs_sync = runs.RunsSync(notes_store, data_dir, log=typer.echo)
                runs_sync.pull_state()
            history = backfill_mod.RunsHistory(runs.load_stations(runs_stations), now, runs_sync)
            typer.echo(
                f"single runs: with each window, runs before {runs.history_edge(now):%Y-%m-%d} "
                f"at {history.stations.height} stations"
            )
        meta2 = fetch_current_meta(client, 2, now.date())
        points = observations.verification_stations(table, meta2)
        budget = forecasts.Budget(max_calls=max_calls)
        result = backfill_mod.run(
            client,
            points,
            models,
            first,
            last,
            data_dir,
            budget,
            sync,
            log=typer.echo,
            gauge_points=_gauge_points(table, meta2, points),
            history=history,
        )
    typer.echo(
        f"{result.windows_done} windows done, {len(result.runs)} single runs, "
        f"{budget.used:g} calls used"
        + (f"; stopped: {result.stopped} (run again to continue)" if result.stopped else "")
    )
    job_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if job_summary:  # shown on the workflow run page
        runs_line = ""
        if history:
            state = runs.State.load(data_dir / runs.STATE_NAME)
            left = runs.backfill_pending(state, models, now)
            runs_line = (
                f"{left} runs before {runs.history_edge(now):%Y-%m-%d} still to fetch, back "
                f"to {runs.history_start(models)} (each model from its archive start)"
            )
        text = backfill_mod.summary(result, budget.used, data_dir, first, last, runs_line)
        with open(job_summary, "a", encoding="utf-8") as f:
            f.write(text)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
