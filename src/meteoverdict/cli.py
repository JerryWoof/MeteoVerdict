"""Command-line interface for meteoverdict (``mvd``)."""

from __future__ import annotations

from typing import Annotated

import typer

from meteoverdict import __version__

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


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
