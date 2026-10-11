import re
from datetime import date

import pytest
from typer.testing import CliRunner

from meteoverdict import cli
from meteoverdict.cli import app

runner = CliRunner()

# typer forces coloured rich output when GITHUB_ACTIONS is set, so compare plain text.
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    return ANSI.sub("", text)


COMMANDS = ["fetch-obs", "fetch-fc", "score", "report", "daily", "backfill"]


def test_no_args_shows_help_with_all_commands():
    result = runner.invoke(app, [])
    # click exits with 2 for "no command given" after printing help
    assert result.exit_code in (0, 2)
    for command in COMMANDS:
        assert command in plain(result.output)


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_has_help(command):
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "Usage" in plain(result.output)


@pytest.mark.parametrize(
    ("args", "item", "detail"),
    [
        (["fetch-obs", "--start", "2024-01-01", "--end", "2024-01-31"], "1.5", "2024-01-31"),
        (
            ["fetch-fc", "--start", "2024-01-01", "--end", "2024-01-02", "--model", "icon_d2"],
            "1.6",
            "icon_d2",
        ),
        (["fetch-fc", "--start", "2024-01-01", "--end", "2024-01-02"], "1.6", "all models"),
        (["score", "--start", "2024-01-01", "--end", "2024-01-01"], "2.3", "2024-01-01"),
        (["report"], "3.1", "print the leaderboard"),
        (["report", "--readme"], "3.1", "README.md"),
        (["daily", "--date", "2024-03-05"], "3.2", "2024-03-05"),
        (["backfill", "--from", "2024-01-01", "--to", "2024-02-29"], "2.6", "2024-02-29"),
    ],
)
def test_stub_commands_exit_1_and_name_roadmap_item(args, item, detail):
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert f"roadmap {item}" in result.stderr
    assert detail in result.stderr


def test_daily_and_backfill_default_to_yesterday(monkeypatch):
    monkeypatch.setattr(cli, "_yesterday", lambda: date(2025, 6, 30))
    assert "2025-06-30" in runner.invoke(app, ["daily"]).stderr
    assert (
        "2025-01-01..2025-06-30" in runner.invoke(app, ["backfill", "--from", "2025-01-01"]).stderr
    )


@pytest.mark.parametrize(
    ("args", "hint"),
    [
        (["fetch-obs", "--start", "2024-02-01", "--end", "2024-01-01"], "--start/--end"),
        (["backfill", "--from", "2024-02-01", "--to", "2024-01-01"], "--from/--to"),
    ],
)
def test_reversed_date_range_is_a_usage_error(args, hint):
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert hint in plain(result.output)


def test_malformed_date_is_rejected():
    result = runner.invoke(app, ["score", "--start", "01.01.2024", "--end", "2024-01-02"])
    assert result.exit_code == 2


def test_required_dates_are_enforced():
    assert runner.invoke(app, ["fetch-obs"]).exit_code == 2
    assert runner.invoke(app, ["backfill"]).exit_code == 2
