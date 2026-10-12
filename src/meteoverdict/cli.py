"""Command-line interface for meteoverdict (``mvd``)."""

from __future__ import annotations

import json
import os
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
    forecasts,
    observations,
    partitions,
    quality,
    ranking,
    regions,
    scoring,
    stations,
    store,
)
from meteoverdict import backfill as backfill_mod
from meteoverdict import daily as daily_mod
from meteoverdict import models as catalogue
from meteoverdict import report as report_mod
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


def _publish_aggregates(
    files: list[Path],
    station_table: pl.DataFrame,
    data_dir: Path,
    out: Path,
    as_of: date | None,
    resamples: int,
) -> pl.DataFrame:
    """Aggregate and rank all score files; write aggregates.parquet and the JSON."""
    scores = pl.scan_parquet(files)
    table = aggregate.aggregate(scores, station_table, as_of)
    ranks = ranking.rank(scores, station_table, as_of, resamples=resamples)
    table = table.join(ranks, on=[*ranking.GROUP, "model"], how="left")
    table.write_parquet(data_dir / "aggregates.parquet", compression="zstd")
    names = {m.id: m.name for m in catalogue.load_models()}
    meta = aggregate.metadata(table, names, datetime.now(UTC))
    written = aggregate.write_json(table, out, meta)
    typer.echo(f"{table.height} rows, as of {meta['as_of']} → {len(written)} JSON files in {out}")
    return table


def _update_readme(aggregates_table: pl.DataFrame, readme_path: Path, site: Path) -> None:
    """Rewrite the README leaderboard and write ``site/badge.json``."""
    names = {m.id: m.name for m in catalogue.load_models()}
    now = datetime.now(UTC)
    block = report_mod.leaderboard(aggregates_table, names, updated=now)
    # the windows end on the last scored day
    scored = aggregates_table["to"].max() if aggregates_table.height else None
    site.mkdir(parents=True, exist_ok=True)
    (site / "badge.json").write_text(json.dumps(report_mod.badge(now, scored)), encoding="utf-8")
    text = readme_path.read_text(encoding="utf-8")
    try:
        updated = report_mod.replace_block(text, block)
    except ValueError as exc:
        typer.echo(f"mvd report: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    readme_path.write_text(updated, encoding="utf-8")
    typer.echo(f"updated the leaderboard in {readme_path}")


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


@app.command()
def report(
    readme: Annotated[
        bool, typer.Option("--readme", help="Rewrite the leaderboard block in README.md.")
    ] = False,
    data_dir: Annotated[Path, typer.Option(help="Folder with aggregates.parquet.")] = Path("data"),
    readme_path: Annotated[Path, typer.Option("--readme-path", help="README to update.")] = Path(
        "README.md"
    ),
    out: Annotated[Path, typer.Option(help="Folder for badge.json.")] = Path("site/data"),
) -> None:
    """Build the leaderboard from aggregated scores."""
    path = data_dir / "aggregates.parquet"
    if not path.exists():
        typer.echo(f"mvd report: {path} not found; run `mvd aggregate`", err=True)
        raise typer.Exit(code=1)
    table = pl.read_parquet(path)
    if not readme:
        names = {m.id: m.name for m in catalogue.load_models()}
        typer.echo(report_mod.leaderboard(table, names))
        return
    _update_readme(table, readme_path, out)


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
    readme_path: Annotated[Path, typer.Option("--readme-path", help="README to update.")] = Path(
        "README.md"
    ),
    resamples: Annotated[int, typer.Option(help="Bootstrap resamples for the ranking.")] = 1000,
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Sync data with GitHub Releases (GITHUB_TOKEN, GITHUB_REPOSITORY).",
        ),
    ] = False,
) -> None:
    """Daily pipeline: capture observations, re-score, aggregate, update README and JSON."""
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
        meta2 = fetch_current_meta(client, 2, datetime.now(UTC).date())
        points = observations.verification_stations(table, meta2)
        months = daily_mod.run(client, points, models, target, data_dir, log=typer.echo)
        if sync:
            sync.push(months)
            remote = store.remote_months(sync.store)
            store.download(sync.store, data_dir, remote, typer.echo, kinds=("scores",))
    files = sorted((data_dir / "scores").glob("*.parquet"))
    if not files:
        typer.echo("no scores yet; the leaderboard stays empty")
        return
    aggregates_table = _publish_aggregates(files, table, data_dir, out, None, resamples)
    _update_readme(aggregates_table, readme_path, out)
    if github_release:
        with httpx.Client(timeout=300, transport=httpx.HTTPTransport(retries=3)) as client:
            store.publish_latest(_release_store(client), data_dir, out)
        typer.echo(f"published aggregates and site data to the release {store.LATEST_TAG}")


@app.command()
def check(
    data_dir: Annotated[Path, typer.Option(help="Folder with obs/, fc/ and scores/.")] = Path(
        "data"
    ),
) -> None:
    """Data quality checks: exit 1 on stale data or many missing stations."""
    findings = quality.check(data_dir)
    text = quality.report(findings)
    typer.echo(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:  # shown on the workflow run page
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Data quality\n\n" + text.replace("\n", "\n\n") + "\n")
    if any(f.level == "error" for f in findings):
        raise typer.Exit(code=1)


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
) -> None:
    """Backfill history newest first, in 14-day windows, resumable (state in the data dir)."""
    first, last = start.date(), end.date() if end else _yesterday()
    _check_range(first, last, hint="--from/--to")
    if not stations_path.exists():
        raise typer.BadParameter(f"{stations_path} not found; run `mvd stations` first")
    table = pl.read_parquet(stations_path)
    models = [m for m in catalogue.load_models() if m.enabled]
    transport = httpx.HTTPTransport(retries=3)
    with httpx.Client(timeout=300, transport=transport, follow_redirects=True) as client:
        sync = None
        if github_release:
            sync = store.ReleaseSync(_release_store(client), data_dir, log=typer.echo)
            sync.pull_state()
        meta2 = fetch_current_meta(client, 2, datetime.now(UTC).date())
        points = observations.verification_stations(table, meta2)
        budget = forecasts.Budget(max_calls=max_calls)
        result = backfill_mod.run(
            client, points, models, first, last, data_dir, budget, sync, log=typer.echo
        )
    typer.echo(
        f"{result.windows_done} windows done, {budget.used:g} calls used"
        + (f"; stopped: {result.stopped} (run again to continue)" if result.stopped else "")
    )


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
