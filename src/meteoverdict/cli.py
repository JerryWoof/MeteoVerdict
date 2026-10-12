"""Command-line interface for meteoverdict (``mvd``)."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, NoReturn

import httpx
import polars as pl
import typer

from meteoverdict import (
    __version__,
    aladin,
    forecasts,
    observations,
    partitions,
    regions,
    scoring,
    stations,
    store,
)
from meteoverdict import models as catalogue
from meteoverdict.chmi import ChmiFormatError, fetch_current_meta
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


def _not_implemented(command: str, roadmap_item: str, detail: str) -> NoReturn:
    typer.echo(
        f"mvd {command}: not implemented yet (roadmap {roadmap_item}). Would {detail}.",
        err=True,
    )
    raise typer.Exit(code=1)


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


store_app = typer.Typer(help="Raw data store in GitHub Releases (data-YYYY-MM).")
app.add_typer(store_app, name="store")
DataDir = Annotated[Path, typer.Option(help="Folder with obs/ and fc/ subfolders.")]


def _release_store(client: httpx.Client) -> GitHubReleaseStore:
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        raise typer.BadParameter("needs GITHUB_TOKEN and GITHUB_REPOSITORY in the environment")
    return GitHubReleaseStore(client, repo, token, notes=store.RELEASE_NOTES)


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
    obs = partitions.scan_months(data_dir / "obs", first, last + timedelta(days=1))
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


@app.command()
def report(
    readme: Annotated[
        bool, typer.Option("--readme", help="Rewrite the leaderboard block in README.md.")
    ] = False,
) -> None:
    """Build the leaderboard from aggregated scores."""
    _not_implemented("report", "3.1", "update README.md" if readme else "print the leaderboard")


@app.command()
def daily(
    day: Annotated[
        datetime | None,
        typer.Option(
            "--date", formats=["%Y-%m-%d"], help="Day to process (UTC). Default: yesterday."
        ),
    ] = None,
) -> None:
    """Run the daily pipeline: fetch-obs, fetch-fc, score and report for one day."""
    target = day.date() if day else _yesterday()
    _not_implemented("daily", "3.2", f"run the pipeline for {target}")


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
) -> None:
    """Backfill history month by month (resumable)."""
    last = end.date() if end else _yesterday()
    _check_range(start.date(), last, hint="--from/--to")
    _not_implemented("backfill", "2.6", f"backfill {start:%Y-%m-%d}..{last}")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
