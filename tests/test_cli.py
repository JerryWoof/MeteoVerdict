import json
import re
from datetime import date
from pathlib import Path

import httpx
import polars as pl
import pytest
from typer.testing import CliRunner

from meteoverdict import aladin, cli, stations
from meteoverdict.chmi import parse_collection
from meteoverdict.cli import app

runner = CliRunner()

# typer forces coloured rich output when GITHUB_ACTIONS is set, so compare plain text.
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    return ANSI.sub("", text)


COMMANDS = [
    "stations",
    "models",
    "archive-aladin",
    "fetch-obs",
    "fetch-fc",
    "score",
    "report",
    "daily",
    "backfill",
]


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


def test_stations_writes_parquet(monkeypatch, tmp_path):
    fixtures = Path(__file__).parent / "fixtures" / "chmi"
    tables = tuple(
        parse_collection(json.loads((fixtures / name).read_text(encoding="utf-8")))
        for name in ("meta1-20261011.json", "meta1-historical.json")
    )
    monkeypatch.setattr(stations, "fetch_station_tables", lambda client, today: tables)
    out = tmp_path / "stations.parquet"
    result = runner.invoke(app, ["stations", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "Wrote 3 stations (3 active) in 3 okresy and 2 kraje" in result.stdout
    table = pl.read_parquet(out)
    assert table["kraj_code"].to_list() == ["CZ041", "CZ041", "CZ010"]
    assert table["okres"].to_list() == ["Cheb", "Karlovy Vary", "území Hlavního města Prahy"]
    assert table["elevation_class"].to_list() == ["upland", "upland", "lowland"]


def test_stations_reports_download_errors(monkeypatch, tmp_path):
    def fail(client, today):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(stations, "fetch_station_tables", fail)
    result = runner.invoke(app, ["stations", "--out", str(tmp_path / "s.parquet")])
    assert result.exit_code == 1
    assert "could not download" in result.stderr


def test_stations_reports_unexpected_format(monkeypatch, tmp_path):
    bad = pl.DataFrame({"WSI": ["x"]})
    monkeypatch.setattr(stations, "fetch_station_tables", lambda client, today: (bad, bad))
    result = runner.invoke(app, ["stations", "--out", str(tmp_path / "s.parquet")])
    assert result.exit_code == 1
    assert "unexpected ČHMÚ metadata format" in result.stderr
    assert not (tmp_path / "s.parquet").exists()


def test_models_lists_enabled_models_with_lead_days():
    result = runner.invoke(app, ["models"])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    icon_d2 = next(line for line in lines if line.startswith("dwd_icon_d2 "))
    assert "D+1..D+1" in icon_d2
    assert "archive from 2024-01-19" in icon_d2
    arpege = next(line for line in lines if line.startswith("meteofrance_arpege_europe "))
    assert "wind_speed_10m from 2026-08-07" in arpege
    assert not any("knmi_harmonie_arome_europe" in line for line in lines)


def test_models_all_includes_disabled():
    result = runner.invoke(app, ["models", "--all"])
    assert "knmi_harmonie_arome_europe" in result.stdout
    assert "(disabled)" in result.stdout


def test_fetch_fc_rejects_unknown_model():
    args = ["fetch-fc", "--start", "2024-01-01", "--end", "2024-01-02", "--model", "icon_d3"]
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert "icon_d3" in plain(result.output)


def test_archive_aladin_needs_exactly_one_destination(tmp_path):
    stations_file = tmp_path / "s.parquet"
    pl.DataFrame({"id": ["a"], "lat": [50.0], "lon": [14.4]}).write_parquet(stations_file)
    base = ["archive-aladin", "--stations", str(stations_file)]
    assert runner.invoke(app, base).exit_code == 2
    both = [*base, "--out-dir", str(tmp_path), "--github-release"]
    assert runner.invoke(app, both).exit_code == 2


def test_archive_aladin_github_needs_token(tmp_path, monkeypatch):
    stations_file = tmp_path / "s.parquet"
    pl.DataFrame({"id": ["a"], "lat": [50.0], "lon": [14.4]}).write_parquet(stations_file)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = runner.invoke(
        app, ["archive-aladin", "--stations", str(stations_file), "--github-release"]
    )
    assert result.exit_code == 2
    assert "GITHUB_TOKEN" in plain(result.output)


def test_archive_aladin_reports_and_fails_on_failed_runs(tmp_path, monkeypatch):
    stations_file = tmp_path / "s.parquet"
    pl.DataFrame({"id": ["a"], "lat": [50.0], "lon": [14.4]}).write_parquet(stations_file)
    result_obj = aladin.ArchiveResult(["x.parquet"], 3, ["y.parquet"])
    monkeypatch.setattr(aladin, "archive", lambda client, store, table, log: result_obj)
    args = ["archive-aladin", "--stations", str(stations_file), "--out-dir", str(tmp_path)]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "archived 1, already there 3, failed 1" in result.stdout


def test_archive_aladin_needs_the_station_table(tmp_path):
    args = ["archive-aladin", "--stations", str(tmp_path / "nope.parquet"), "--out-dir", "x"]
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert "mvd stations" in plain(result.output)


def test_fetch_obs_selects_automatic_and_inactive_stations(monkeypatch, tmp_path):
    from meteoverdict import observations

    stations_file = tmp_path / "s.parquet"
    pl.DataFrame({"id": ["auto", "manual", "closed"], "active": [True, True, False]}).write_parquet(
        stations_file
    )
    meta2 = pl.DataFrame({"OBS_TYPE": ["10M"], "WSI": ["auto"], "EG_EL_ABBREVIATION": ["T"]})
    monkeypatch.setattr(cli, "fetch_current_meta", lambda client, n, today: meta2)
    asked = {}

    def fake_fetch(client, ids, start, end):
        asked["ids"] = sorted(ids)
        return pl.DataFrame(schema=observations.SCHEMA)

    monkeypatch.setattr(observations, "fetch_observations", fake_fetch)
    args = ["fetch-obs", "--start", "2026-09-05", "--end", "2026-09-05"]
    result = runner.invoke(
        app, [*args, "--stations", str(stations_file), "--out-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert asked["ids"] == ["auto", "closed"]
    assert "0 hourly values from 0 of 2 stations" in result.stdout


def fc_setup(monkeypatch, tmp_path):
    from meteoverdict import forecasts

    stations_file = tmp_path / "s.parquet"
    pl.DataFrame(
        {"id": ["a"], "active": [True], "lat": [50.0], "lon": [14.4], "elevation": [300.0]}
    ).write_parquet(stations_file)
    meta2 = pl.DataFrame({"OBS_TYPE": ["10M"], "WSI": ["a"], "EG_EL_ABBREVIATION": ["T"]})
    monkeypatch.setattr(cli, "fetch_current_meta", lambda client, n, today: meta2)
    base = ["fetch-fc", "--start", "2026-10-09", "--end", "2026-10-09"]
    return forecasts, [*base, "--stations", str(stations_file), "--out-dir", str(tmp_path / "fc")]


def test_fetch_fc_dry_run_prints_the_estimate(monkeypatch, tmp_path):
    forecasts, args = fc_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(forecasts, "fetch_forecasts", lambda *a, **k: pytest.fail("no fetch"))
    result = runner.invoke(app, [*args, "--model", "chmi_aladin_cz_1km", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert (
        "1 models x 1 stations, 2026-10-09..2026-10-09: about 1 Open-Meteo calls" in result.stdout
    )


def test_fetch_fc_saves_partial_results_when_the_quota_ends(monkeypatch, tmp_path):
    from datetime import UTC, datetime

    forecasts, args = fc_setup(monkeypatch, tmp_path)
    row = {
        "station_id": "a",
        "time": datetime(2026, 10, 9, tzinfo=UTC),
        "model": "chmi_aladin_cz_1km",
        "lead_day": 1,
        "temperature_2m": 9.0,
        "precipitation": 0.0,
        "wind_speed_10m": 2.0,
    }

    def quota(*args, **kwargs):
        error = forecasts.QuotaError("Daily API request limit exceeded.")
        error.partial = pl.DataFrame([row], schema=forecasts.SCHEMA)
        raise error

    monkeypatch.setattr(forecasts, "fetch_forecasts", quota)
    result = runner.invoke(app, args)
    assert result.exit_code == 3
    assert "Daily API request limit" in result.stderr
    assert pl.read_parquet(tmp_path / "fc" / "2026-10.parquet").height == 1
