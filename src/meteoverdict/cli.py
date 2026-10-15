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
    combine,
    farm,
    forecasts,
    gauges,
    leads,
    observations,
    outlook,
    partitions,
    quality,
    ranking,
    regions,
    runs,
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
) -> None:
    """Error by lead hour, run by run: every model from Open-Meteo's single runs
    (H+1 … H+120) and ALADIN from our own archive (H+1 … H+72)."""
    if publish and not github_release:
        raise typer.BadParameter("--publish needs --github-release")
    now = datetime.now(UTC)
    hour = now.replace(minute=0, second=0, microsecond=0)
    since, runs_since = hour - timedelta(days=days), hour - timedelta(days=runs_days)
    first = min(since, runs_since)
    months = partitions.months(first.date(), now.date())
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
            if table.height:
                doc = leads.runs_document(table, info, generated, delays, names)
                written.append(leads.write(doc, out))
                lines += ["All models, Open-Meteo single runs:", *leads.summary(table)]
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
        obs = observations.scan(data_dir, first, last + timedelta(days=1))
        fc = partitions.scan_months(data_dir / "fc", first, last + timedelta(days=1))
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
            "Default: the recent runs, then the history."
        ),
    ] = None,
    mode: Annotated[
        str, typer.Option(help="Without --run: recent, history or all (recent first).")
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
    ] = 450,
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
    history_from: Annotated[
        datetime | None,
        typer.Option(
            formats=["%Y-%m-%d"],
            help="Oldest day (00 UTC run) of the history. Default: the first run with "
            "ALADIN (runs.HISTORY_FROM).",
        ),
    ] = None,
    shared_calls: Annotated[
        float,
        typer.Option(
            help="The daily budget shared with the D+N backfill: what the backfill leaves "
            "of it today (its state in the release data-state with --github-release, else "
            "backfill-state.json in --data-dir) can be added to --max-calls; nothing if "
            "the state cannot be read.",
        ),
    ] = 0,
    shared_from: Annotated[
        float, typer.Option(help="This run's part of what is left starts here …")
    ] = 0,
    shared_to: Annotated[
        float | None, typer.Option(help="… and ends here (default: --shared-calls).")
    ] = None,
    backfill_from: Annotated[
        datetime,
        typer.Option(formats=["%Y-%m-%d"], help="The backfill's --from (for the shared budget)."),
    ] = datetime(2024, 1, 1),
) -> None:
    """Fetch single model runs (H+1 … H+120) at the station subset from Open-Meteo's
    Single Runs API, resumable within a call budget."""
    if mode not in ("recent", "history", "all"):
        raise typer.BadParameter("use recent, history or all", param_hint="--mode")
    try:
        chosen = [runs.parse_run(r) for r in run] if run else None
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--run") from exc
    stations_table = runs.load_stations(stations_path)
    models = [m for m in catalogue.load_models() if m.enabled]
    now = datetime.now(UTC)
    first = history_from.date() if history_from else runs.HISTORY_FROM
    modes = ("recent", "history") if mode == "all" else (mode,)
    with httpx.Client(timeout=300, transport=httpx.HTTPTransport(retries=3)) as client:
        sync = None
        if github_release:
            notes_store = GitHubReleaseStore(
                client, *_github_credentials(), notes=runs.RELEASE_NOTES
            )
            sync = runs.RunsSync(notes_store, data_dir, log=typer.echo)
            sync.pull_state()
        max_calls, budget_note = runs.shared_budget(
            max_calls,
            shared_calls,
            (shared_from, shared_calls if shared_to is None else shared_to),
            lambda: _backfill_state(client if github_release else None, data_dir),
            models,
            backfill_from.date(),
            now.date(),
        )
        typer.echo(f"budget: {budget_note}")
        if dry_run:
            state = runs.State.load(data_dir / runs.STATE_NAME)
            todo = chosen or [
                *(runs.recent_runs(now) if "recent" in modes else []),
                *(runs.history_runs(now, first) if "history" in modes else []),
            ]
            pending = [(r, state.todo(r, runs.wanted(models, r))) for r in todo]
            pending = [(r, m) for r, m in pending if m]
            cost = sum(runs.run_cost(stations_table.height, len(m)) for _, m in pending)
            typer.echo(
                f"{len(pending)} runs to fetch at {stations_table.height} stations, about "
                f"{cost:g} Open-Meteo calls ({runs.run_cost(stations_table.height, len(models)):g}"
                f" per run of all {len(models)} models; budget {max_calls:g})"
            )
            return
        budget = forecasts.Budget(max_calls=max_calls)
        result = runs.Result()
        if max_calls > 0:  # a schedule with only shared calls: nothing when none are left
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
                first=first,
            )
    typer.echo(
        f"{len(result.runs)} runs fetched, {budget.used:g} calls used"
        + (f"; stopped: {result.stopped} (run again to continue)" if result.stopped else "")
    )
    job_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if job_summary:  # shown on the workflow run page
        with open(job_summary, "a", encoding="utf-8") as f:
            f.write(runs.summary(result, budget.used, data_dir, models, now, first, budget_note))
    if result.failed:
        raise typer.Exit(code=1)


def _backfill_state(client: httpx.Client | None, data_dir: Path) -> backfill_mod.State:
    """The backfill's progress: from the release data-state (``client``), else local."""
    path = data_dir / store.STATE_NAME
    if client is not None:
        releases = _release_store(client)
        if store.STATE_NAME not in releases.assets(store.STATE_TAG):
            raise FileNotFoundError(f"{store.STATE_NAME} not in the release {store.STATE_TAG}")
        path = data_dir / "backfill" / store.STATE_NAME  # apart from any local backfill
        releases.download(store.STATE_TAG, store.STATE_NAME, path)
    if not path.exists():
        raise FileNotFoundError(path)
    return backfill_mod.State.load(path)


def _runs_state(client: httpx.Client | None, data_dir: Path) -> runs.State:
    """The single runs' progress: from the release runs-state (``client``), else local."""
    path = data_dir / runs.STATE_NAME
    if client is not None:
        releases = _release_store(client)
        if runs.STATE_NAME not in releases.assets(runs.STATE_TAG):
            raise FileNotFoundError(f"{runs.STATE_NAME} not in the release {runs.STATE_TAG}")
        path = data_dir / "runs-check" / runs.STATE_NAME  # apart from any local runs
        releases.download(runs.STATE_TAG, runs.STATE_NAME, path)
    if not path.exists():
        raise FileNotFoundError(path)
    return runs.State.load(path)


store_app = typer.Typer(help="Raw data store in GitHub Releases (data-YYYY-MM).")
app.add_typer(store_app, name="store")
DataDir = Annotated[Path, typer.Option(help="Folder with obs/ and fc/ subfolders.")]


def _github_credentials() -> tuple[str, str]:
    """``(repo, token)`` from the environment."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        raise typer.BadParameter("needs GITHUB_TOKEN and GITHUB_REPOSITORY in the environment")
    return repo, token


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


@app.command("outlook")
def outlook_cmd(
    aggregates_path: Annotated[
        Path, typer.Option("--aggregates", help="aggregates.parquet from `mvd aggregate`.")
    ] = Path("data/aggregates.parquet"),
    out: Annotated[
        Path, typer.Option(help="The JSON file to write; outlook-hourly.json goes beside it.")
    ] = Path("site/data/outlook.json"),
    github_release: Annotated[
        bool,
        typer.Option(
            "--github-release",
            help="Take aggregates.parquet from and put outlook.json and "
            "outlook-hourly.json into the release data-latest (GITHUB_TOKEN, "
            "GITHUB_REPOSITORY).",
        ),
    ] = False,
) -> None:
    """TV-style forecast for every okres: today's models combined by their okres scores."""
    with httpx.Client(timeout=300, transport=httpx.HTTPTransport(retries=3)) as client:
        releases = _release_store(client) if github_release else None
        if releases:
            releases.download(store.LATEST_TAG, "aggregates.parquet", aggregates_path)
        if not aggregates_path.exists():
            raise typer.BadParameter(f"{aggregates_path} not found; run `mvd aggregate`")
        weights = combine.weights(pl.read_parquet(aggregates_path))
        if weights.is_empty():
            typer.echo("mvd outlook: no okres weights yet", err=True)
            raise typer.Exit(code=1)
        points = combine.okres_points()
        table, hourly = outlook.outlook(client, weights, points, sleep=time.sleep)
        now = datetime.now(UTC)
        path = outlook.write(table, points, out, now)
        hourly_path = outlook.write_hourly(hourly, out.with_name("outlook-hourly.json"), now)
        if releases:
            releases.put(store.LATEST_TAG, "outlook.json", path)
            releases.put(store.LATEST_TAG, "outlook-hourly.json", hourly_path)
    typer.echo(f"{table['okres'].n_unique()} okresy, {table.height} rows → {path}")


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
    names = _model_names()
    meta = aggregate.metadata(table, names, datetime.now(UTC))
    written = [
        *aggregate.write_json(table, out, meta),
        aggregate.write_stations(station_table, out),
        *combine.write_forecast(table, out),
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
    older_windows: Annotated[
        str,
        typer.Option(
            help="Windows older than the current ones (last 90 days): always, never, or "
            "after-runs-history (only once the single-runs history is complete: its state "
            "in the release runs-state with --github-release, else runs-state.json in "
            "--data-dir; never if it cannot be read).",
        ),
    ] = "always",
) -> None:
    """Backfill history newest first, in 14-day windows, resumable (state in the data dir)."""
    if older_windows not in ("always", "never", "after-runs-history"):
        raise typer.BadParameter(
            "use always, never or after-runs-history", param_hint="--older-windows"
        )
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
        older, why = older_windows == "always", "--older-windows never"
        if older_windows == "after-runs-history":
            older, why = runs.history_done(
                lambda: _runs_state(client if github_release else None, data_dir),
                models,
                datetime.now(UTC),
            )
        typer.echo(f"older windows: {'allowed' if older else 'held back'} ({why})")
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
            older=older,
            held_back="" if older else why,
        )
    typer.echo(
        f"{result.windows_done} windows done, {budget.used:g} calls used"
        + (f"; stopped: {result.stopped} (run again to continue)" if result.stopped else "")
    )
    job_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if job_summary:  # shown on the workflow run page
        text = backfill_mod.summary(result, budget.used, data_dir, first, last)
        with open(job_summary, "a", encoding="utf-8") as f:
            f.write(text)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
