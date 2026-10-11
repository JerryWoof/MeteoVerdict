"""Command-line interface for meteoverdict (``mvd``)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, NoReturn

import httpx
import typer

from meteoverdict import __version__, regions, stations
from meteoverdict import models as catalogue
from meteoverdict.chmi import ChmiFormatError

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
    typer.echo(f"Wrote {table.height} stations ({active} active) in {kraje} kraje to {out}")


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
        flag = "" if m.enabled else "  (disabled)"
        typer.echo(f"{m.id:32} {m.name:36} {leads:9} archive from {m.archive_from}{flag}")


@app.command("fetch-obs")
def fetch_obs(start: DateOption, end: DateOption) -> None:
    """Fetch hourly ČHMÚ station observations (T2m, precipitation, wind) for a date range."""
    _check_range(start.date(), end.date())
    _not_implemented("fetch-obs", "1.5", f"fetch observations {start:%Y-%m-%d}..{end:%Y-%m-%d}")


@app.command("fetch-fc")
def fetch_fc(
    start: DateOption,
    end: DateOption,
    model: Annotated[
        list[str] | None,
        typer.Option(help="Model id from models.yaml; repeat for several. Default: all."),
    ] = None,
) -> None:
    """Fetch archived forecasts from the Open-Meteo Previous Runs API for a date range."""
    _check_range(start.date(), end.date())
    known = {m.id for m in catalogue.load_models()}
    unknown = sorted(set(model or []) - known)
    if unknown:
        raise typer.BadParameter(
            f"unknown model(s) {', '.join(unknown)}; see `mvd models --all`", param_hint="--model"
        )
    models = ", ".join(model) if model else "all models"
    _not_implemented("fetch-fc", "1.6", f"fetch {models} for {start:%Y-%m-%d}..{end:%Y-%m-%d}")


@app.command()
def score(start: DateOption, end: DateOption) -> None:
    """Score forecasts against observations into the daily scores table."""
    _check_range(start.date(), end.date())
    _not_implemented("score", "2.3", f"score {start:%Y-%m-%d}..{end:%Y-%m-%d}")


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
