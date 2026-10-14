import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import polars as pl
import pytest
from typer.testing import CliRunner

from meteoverdict import aladin, cli, stations
from meteoverdict import backfill as backfill_mod
from meteoverdict.chmi import parse_collection
from meteoverdict.cli import app
from meteoverdict.models import load_models

runner = CliRunner()

# typer forces coloured rich output when GITHUB_ACTIONS is set, so compare plain text.
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    return ANSI.sub("", text)


COMMANDS = [
    "stations",
    "models",
    "archive-aladin",
    "leads",
    "fetch-runs",
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


def test_daily_without_scores_stops_after_capturing(monkeypatch, tmp_path):
    from meteoverdict import daily

    stations_file = tmp_path / "s.parquet"
    # a: automatic, g: manual rain gauge, x: closed (verified hourly, so not a gauge here)
    stations = {"id": ["a", "g", "x"], "active": [True, True, False]}
    pl.DataFrame(stations).write_parquet(stations_file)
    meta2 = pl.DataFrame({"OBS_TYPE": ["10M"], "WSI": ["a"], "EG_EL_ABBREVIATION": ["T"]})
    monkeypatch.setattr(cli, "fetch_current_meta", lambda client, n, today: meta2)
    monkeypatch.setattr(cli, "_yesterday", lambda: date(2025, 6, 30))
    seen = {}

    def fake_run(client, points, models, day, data_dir, log, gauge_points):
        seen["day"], seen["points"] = day, points["id"].to_list()
        seen["gauges"] = gauge_points["id"].to_list()
        return ["2025-06"]

    monkeypatch.setattr(daily, "run", fake_run)
    args = ["daily", "--stations", str(stations_file), "--data-dir", str(tmp_path)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert seen == {"day": date(2025, 6, 30), "points": ["a", "x"], "gauges": ["g"]}
    assert "no scores yet" in result.stdout


def test_backfill_needs_the_station_table(tmp_path):
    args = ["backfill", "--from", "2025-01-01", "--stations", str(tmp_path / "none.parquet")]
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert "mvd stations" in plain(result.output)


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


def test_store_needs_github_credentials(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = runner.invoke(app, ["store", "upload"])
    assert result.exit_code == 2
    assert "GITHUB_TOKEN" in plain(result.output)


def test_store_download_rejects_a_bad_month():
    result = runner.invoke(app, ["store", "download", "--from", "2026-13"])
    assert result.exit_code == 2
    assert "bad month range" in plain(result.output)


def test_score_needs_observations_and_forecasts(tmp_path):
    result = runner.invoke(
        app, ["score", "--start", "2026-09-01", "--end", "2026-09-01", "--data-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "no observations (mvd fetch-obs)" in result.stderr


def test_score_writes_monthly_scores(tmp_path):
    from datetime import UTC, datetime, timedelta

    from meteoverdict.forecasts import SCHEMA as FC_SCHEMA
    from meteoverdict.observations import SCHEMA as OBS_SCHEMA

    times = [datetime(2026, 9, 30, tzinfo=UTC) + timedelta(hours=h) for h in range(25)]
    obs = pl.DataFrame(
        [("s", t, "temperature_2m", 10.0, 0, "recent") for t in times],
        schema=OBS_SCHEMA,
        orient="row",
    )
    fc = pl.DataFrame(
        [("s", t, "dwd_icon_d2", 1, 11.0, None, None) for t in times],
        schema=FC_SCHEMA,
        orient="row",
    )
    for kind, frame in (("obs", obs), ("fc", fc)):
        (tmp_path / kind).mkdir()
        frame.filter(pl.col("time").dt.month() == 9).write_parquet(
            tmp_path / kind / "2026-09.parquet"
        )
        frame.filter(pl.col("time").dt.month() == 10).write_parquet(
            tmp_path / kind / "2026-10.parquet"
        )
    args = ["score", "--start", "2026-09-30", "--end", "2026-09-30", "--data-dir", str(tmp_path)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    scores = pl.read_parquet(tmp_path / "scores" / "2026-09.parquet")
    assert scores.select("variable", "n").rows() == [
        ("temperature_2m", 4),
        *[(f"temperature_2m_{h}utc", 1) for h in ("00", "06", "12", "18")],
        ("temperature_2m_hourly", 24),
        ("temperature_max", 1),
    ]


def test_aggregate_needs_scores(tmp_path):
    result = runner.invoke(app, ["aggregate", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "mvd score" in result.stderr


def test_report_needs_aggregates(tmp_path):
    result = runner.invoke(app, ["report", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "mvd aggregate" in result.stderr


def test_report_prints_the_best_models(tmp_path):
    pl.DataFrame(
        {
            "level": ["cz"], "region": ["cz"], "region_name": ["Česko"], "window": ["90d"],
            "from": [date(2026, 7, 3)], "to": [date(2026, 9, 30)],
            "variable": ["temperature_2m"], "lead_day": [1], "model": ["dwd_icon_eu"],
            "mae": [1.4], "rank": [1], "tied_with_best": [False], "enough_stations": [True],
        }
    ).write_parquet(tmp_path / "aggregates.parquet")  # fmt: skip
    result = runner.invoke(app, ["report", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "**DWD ICON-EU** (1.40)" in result.stdout


def test_check_fails_loudly_and_writes_the_job_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    result = runner.invoke(app, ["check", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "ERROR: no observations" in result.stdout
    assert "## Data quality" in summary.read_text(encoding="utf-8")


def test_fetch_gauges_asks_for_manual_and_inactive_stations(monkeypatch, tmp_path):
    from meteoverdict import gauges, observations

    stations_file = tmp_path / "s.parquet"
    pl.DataFrame({"id": ["auto", "gauge"], "active": [True, True]}).write_parquet(stations_file)
    meta2 = pl.DataFrame({"OBS_TYPE": ["10M"], "WSI": ["auto"], "EG_EL_ABBREVIATION": ["T"]})
    monkeypatch.setattr(cli, "fetch_current_meta", lambda client, n, today: meta2)
    asked = {}

    def fake(client, ids, start, end):
        asked["ids"] = list(ids)
        return pl.DataFrame(schema=observations.SCHEMA)

    monkeypatch.setattr(gauges, "fetch_gauge_precipitation", fake)
    args = ["fetch-gauges", "--start", "2026-08-01", "--end", "2026-08-31"]
    result = runner.invoke(
        app, [*args, "--stations", str(stations_file), "--out-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert asked["ids"] == ["gauge"]


def test_aggregate_reads_score_files_of_different_ages(tmp_path):
    stations = {
        "id": ["s1", "s2", "s3"], "name": ["A", "B", "C"], "lat": [50.0] * 3,
        "lon": [14.4] * 3, "active": [True] * 3, "okres_code": ["CZ0201"] * 3,
        "okres": ["Benešov"] * 3, "kraj_code": ["CZ020"] * 3,
        "kraj": ["Středočeský kraj"] * 3, "elevation_class": ["lowland"] * 3,
    }  # fmt: skip
    pl.DataFrame(stations).write_parquet(tmp_path / "stations.parquet")
    (tmp_path / "scores").mkdir()
    for month, extra in (("2026-08", {}), ("2026-09", {"a_30": [0] * 6})):
        pl.DataFrame(
            {
                "date": [date(int(month[:4]), int(month[5:]), 10)] * 6,
                "station_id": ["s1", "s2", "s3"] * 2,
                "model": ["a"] * 3 + ["b"] * 3,
                "lead_day": [1] * 6, "variable": ["temperature_2m"] * 6, "period_h": [0] * 6,
                "n": [24] * 6, "sum_err": [1.0] * 6, "sum_abs_err": [24.0] * 3 + [48.0] * 3,
                "sum_sq_err": [30.0] * 6, **extra,
            }
        ).write_parquet(tmp_path / "scores" / f"{month}.parquet")  # fmt: skip
    args = [
        "aggregate", "--data-dir", str(tmp_path), "--stations", str(tmp_path / "stations.parquet"),
        "--out", str(tmp_path / "site"), "--resamples", "20",
    ]  # fmt: skip
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    doc = json.loads((tmp_path / "site" / "stations.json").read_text(encoding="utf-8"))
    assert [r[0] for r in doc["rows"]] == ["s1", "s2", "s3"]


def test_leads_publish_needs_github_release():
    result = runner.invoke(app, ["leads", "--publish"])
    assert result.exit_code == 2


def test_leads_without_archive_fails(tmp_path):
    args = ["leads", "--archive-dir", str(tmp_path / "a"), "--data-dir", str(tmp_path)]
    result = runner.invoke(app, args)
    assert result.exit_code == 1


def test_leads_writes_the_json(tmp_path):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    run = now.replace(hour=now.hour // 6 * 6) - timedelta(hours=12)
    steps = list(range(0, 4))
    folder = tmp_path / "aladin" / f"aladin-{run:%Y-%m}"
    folder.mkdir(parents=True)
    for model, offset in (("chmi_aladin_cz_1km", 1.0), ("chmi_aladin_central_europe_2km", 2.0)):
        pl.DataFrame(
            {
                "model": model,
                "run": [run] * 4,
                "lead_h": pl.Series(steps, dtype=pl.Int16),
                "station_id": "a",
                "temperature_2m": [10.0 + offset] * 4,
                "wind_speed_10m": [2.0] * 4,
                "precipitation_accum": [None, 0.0, 0.0, 0.0],
                "valid_time": [run + timedelta(hours=h) for h in steps],
            }
        ).write_parquet(folder / f"{model}_{run:%Y%m%d%H}.parquet")
    obs_rows = pl.DataFrame(
        {
            "station_id": "a",
            "time": [run + timedelta(hours=h) for h in steps],
            "variable": "temperature_2m",
            "value": [10.0] * 4,
        }
    )
    (tmp_path / "obs").mkdir()
    obs_rows.write_parquet(tmp_path / "obs" / f"{run:%Y-%m}.parquet")
    stations_file = tmp_path / "s.parquet"
    pl.DataFrame({"id": ["a"], "kraj_code": ["CZ010"], "kraj": ["Praha"]}).write_parquet(
        stations_file
    )
    out = tmp_path / "site" / "leads.json"
    args = [
        "leads", "--archive-dir", str(tmp_path / "aladin"), "--data-dir", str(tmp_path),
        "--stations", str(stations_file), "--out", str(out),
    ]  # fmt: skip
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert not out.exists()  # no single runs: only our ALADIN archive
    doc = json.loads((tmp_path / "site" / "leads-aladin.json").read_text())
    rows = [dict(zip(doc["columns"], r, strict=True)) for r in doc["rows"]]
    h1 = [r for r in rows if r["lead_h"] == 1 and r["run_hour"] == "all"]
    assert {r["model"]: r["mae"] for r in h1} == {
        "chmi_aladin_cz_1km": 1.0,
        "chmi_aladin_central_europe_2km": 2.0,
    }
    kraj = json.loads((tmp_path / "site" / "leads-aladin-kraj.json").read_text())
    assert kraj["regions"] == {"CZ010": "Praha"}
    assert "H+1 1.00 (1 runs, 1 pairs)" in plain(result.output)


def test_leads_scores_every_model_from_the_single_runs(tmp_path):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    run = now.replace(hour=now.hour // 6 * 6) - timedelta(hours=12)
    steps = [1, 2, 3]
    rows = pl.concat(
        pl.DataFrame(
            {
                "run": [run] * 3,
                "model": model,
                "station_id": "a",
                "lead_h": pl.Series(steps, dtype=pl.Int16),
                "valid_time": [run + timedelta(hours=h) for h in steps],
                "temperature_2m": pl.Series([10.0 + offset] * 3, dtype=pl.Float32),
                "precipitation": pl.Series([0.0] * 3, dtype=pl.Float32),
                "wind_speed_10m": pl.Series([2.0] * 3, dtype=pl.Float32),
            }
        )
        for model, offset in (("dwd_icon_eu", 1.0), ("ncep_gfs_global", 2.0))
    )
    (tmp_path / "runs").mkdir()
    rows.write_parquet(tmp_path / "runs" / f"{run:%Y-%m}.parquet")
    (tmp_path / "obs").mkdir()
    pl.DataFrame(
        {
            "station_id": "a",
            "time": [run + timedelta(hours=h) for h in steps],
            "variable": "temperature_2m",
            "value": [10.0] * 3,
        }
    ).write_parquet(tmp_path / "obs" / f"{run:%Y-%m}.parquet")
    out = tmp_path / "site" / "leads.json"
    args = [
        "leads",
        "--archive-dir",
        str(tmp_path / "none"),
        "--data-dir",
        str(tmp_path),
        "--out",
        str(out),
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    doc = json.loads(out.read_text())
    rows = [dict(zip(doc["columns"], r, strict=True)) for r in doc["rows"]]
    h1 = {r["model"]: r["mae"] for r in rows if r["lead_h"] == 1 and r["run_hour"] == "all"}
    assert h1 == {"dwd_icon_eu": 1.0, "ncep_gfs_global": 2.0}
    assert doc["models"]["dwd_icon_eu"]["name"] == "DWD ICON-EU"
    assert not (tmp_path / "site" / "leads-aladin.json").exists()


@pytest.mark.parametrize(
    ("args", "hint"),
    [(["--run", "2026-10-12T05"], "--run"), (["--mode", "sometimes"], "--mode")],
)
def test_fetch_runs_rejects_bad_options(args, hint):
    result = runner.invoke(app, ["fetch-runs", *args])
    assert result.exit_code == 2
    assert hint in plain(result.output)


def test_fetch_runs_dry_run_prints_the_cost(tmp_path):
    args = ["fetch-runs", "--dry-run", "--data-dir", str(tmp_path), "--run", "2026-10-12T06"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "1 runs to fetch at 100 stations, about 330 Open-Meteo calls" in plain(result.output)


def test_fetch_runs_extra_budget_needs_a_readable_backfill_state(tmp_path):
    args = ["fetch-runs", "--dry-run", "--data-dir", str(tmp_path), "--run", "2026-10-12T06"]
    result = runner.invoke(app, [*args, "--extra-calls-if-backfill-idle", "3000"])
    assert result.exit_code == 0, result.output
    out = plain(result.output)
    assert "budget: 450 calls (normal; extra 3000 not used: backfill state not readable" in out
    assert "budget 450)" in out


def test_fetch_runs_extra_budget_when_the_backfill_is_idle(tmp_path):
    today = datetime.now(UTC).date()
    first = today - timedelta(days=40)
    models = [m for m in load_models() if m.enabled]
    state = backfill_mod.State(tmp_path / "backfill-state.json")
    for start, end in backfill_mod.complete_windows(first, today):
        state.fc_done |= {backfill_mod.fc_key(m, start, end) for m in models}
        span = backfill_mod.gauge_window(first, today, start)
        if span:
            state.fc_done |= {backfill_mod.gauge_key(m, *span) for m in models}
    state.save()
    args = ["fetch-runs", "--dry-run", "--data-dir", str(tmp_path), "--run", "2026-10-12T06"]
    extra = ["--extra-calls-if-backfill-idle", "3000", "--backfill-from", f"{first}"]
    result = runner.invoke(app, [*args, *extra])
    assert result.exit_code == 0, result.output
    assert "budget: 3450 calls (450 normal + 3000 extra: backfill idle" in plain(result.output)


def test_fetch_runs_without_budget_does_nothing(monkeypatch, tmp_path):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    args = ["fetch-runs", "--data-dir", str(tmp_path), "--max-calls", "0"]
    result = runner.invoke(app, [*args, "--extra-calls-if-backfill-idle", "3000"])
    assert result.exit_code == 0, result.output
    assert "0 runs fetched, 0 calls used" in plain(result.output)
    text = summary.read_text()
    assert "- Budget: 0 calls (normal; extra 3000 not used: backfill state not readable" in text
    assert not (tmp_path / "runs").exists()


def test_fetch_runs_github_needs_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = runner.invoke(app, ["fetch-runs", "--github-release", "--data-dir", str(tmp_path)])
    assert result.exit_code == 2
