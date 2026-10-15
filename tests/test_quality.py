import json
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import observations, partitions, quality
from meteoverdict.forecasts import KEYS as FC_KEYS
from meteoverdict.forecasts import SCHEMA as FC_SCHEMA

NOW = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)


def write_obs(data_dir, stations, newest: datetime, value=10.0):
    rows = [
        (s, newest - timedelta(hours=h), "temperature_2m", value, 0, "now")
        for s in stations
        for h in range(0, 24 * 10, 6)
    ]
    table = pl.DataFrame(rows, schema=observations.SCHEMA, orient="row")
    partitions.write_monthly(table, data_dir / "obs", ["station_id", "time", "variable"])


def write_fc(data_dir, newest: datetime):
    rows = [("s0", newest - timedelta(hours=h), "m", 1, 1.0, None, None) for h in range(24)]
    partitions.write_monthly(
        pl.DataFrame(rows, schema=FC_SCHEMA, orient="row"), data_dir / "fc", FC_KEYS
    )


def write_scores(data_dir, newest: date, mae_by_station: dict[str, float]):
    rows = [
        {
            "date": newest - timedelta(days=d),
            "station_id": s,
            "model": "m",
            "lead_day": 1,
            "variable": "temperature_2m",
            "n": 24,
            "sum_abs_err": mae * 24,
        }
        for s, mae in mae_by_station.items()
        for d in range(5)
    ]
    partitions.write_monthly(
        pl.DataFrame(rows), data_dir / "scores", ["date", "station_id"], "date"
    )


def healthy(tmp_path, stations=("s0", "s1", "s2", "s3", "s4")):
    write_obs(tmp_path, stations, NOW - timedelta(hours=5))
    write_fc(tmp_path, NOW - timedelta(days=8))
    write_scores(tmp_path, (NOW - timedelta(days=8)).date(), {s: 1.5 for s in stations})


def errors(findings):
    return [f.message for f in findings if f.level == "error"]


def test_healthy_data_passes(tmp_path):
    healthy(tmp_path)
    assert quality.check(tmp_path, now=NOW) == []
    assert quality.report([]) == "All data quality checks passed."


def test_no_observations_is_an_error(tmp_path):
    assert errors(quality.check(tmp_path, now=NOW)) == ["no observations in the last 100 days"]


def test_stale_observations_forecasts_and_scores(tmp_path):
    write_obs(tmp_path, ["s0"], NOW - timedelta(hours=40))
    write_fc(tmp_path, NOW - timedelta(days=30))
    write_scores(tmp_path, (NOW - timedelta(days=30)).date(), {"s0": 1.0})
    messages = errors(quality.check(tmp_path, now=NOW))
    assert any("older than 30 h" in m for m in messages)
    assert any(m.startswith("newest fc is") for m in messages)
    assert any(m.startswith("newest scores is") for m in messages)


def write_meta(path, generated: str, as_of: str):
    path.write_text(json.dumps({"generated": generated, "as_of": as_of}), encoding="utf-8")
    return path


def test_published_scores_more_than_21_days_behind_fail(tmp_path):
    healthy(tmp_path)
    meta = write_meta(tmp_path / "meta.json", "2026-10-15T10:06:16+00:00", "2026-09-20")
    messages = errors(quality.check(tmp_path, now=NOW, meta_path=meta))
    assert len(messages) == 1
    assert messages[0].startswith("published scores are as of 2026-09-20, 25 days before")


@pytest.mark.parametrize(
    ("as_of", "late"),
    [("2026-10-14", False), ("2026-09-30", False), ("2026-09-24", False), ("2026-09-23", True)],
)
def test_as_of_lag_limit(as_of, late):
    meta = {"generated": "2026-10-15T10:06:16+00:00", "as_of": as_of}
    assert (quality.as_of_lag(meta) is not None) == late


def test_missing_meta_is_a_warning(tmp_path):
    healthy(tmp_path)
    findings = quality.check(tmp_path, now=NOW, meta_path=tmp_path / "meta.json")
    assert errors(findings) == []
    assert any("as_of not checked" in f.message for f in findings)


def test_check_command_fails_on_late_meta(tmp_path):
    from typer.testing import CliRunner

    from meteoverdict.cli import app

    healthy(tmp_path)
    meta = write_meta(tmp_path / "meta.json", NOW.isoformat(), "2026-09-01")
    result = CliRunner().invoke(app, ["check", "--data-dir", str(tmp_path), "--meta", str(meta)])
    assert result.exit_code == 1
    assert "ERROR: published scores are as of 2026-09-01" in result.output


def test_too_many_silent_stations(tmp_path):
    healthy(tmp_path)
    # five more stations that reported until a week ago, then went silent
    write_obs(tmp_path, ["s5", "s6", "s7", "s8", "s9"], NOW - timedelta(days=7))
    findings = quality.check(tmp_path, now=NOW)
    assert any("only 50% of 10 stations" in m for m in errors(findings))
    assert any("5 stations without recent data: s5, s6" in f.message for f in findings)


def test_suspicious_station_is_a_warning(tmp_path):
    healthy(tmp_path)
    write_scores(
        tmp_path,
        (NOW - timedelta(days=8)).date(),
        {"s0": 1.2, "s1": 1.4, "s2": 1.5, "s3": 1.6, "s4": 9.0},
    )
    findings = quality.check(tmp_path, now=NOW)
    assert errors(findings) == []
    warning = next(f.message for f in findings if "temperature MAE" in f.message)
    assert "s4 (9.0 °C)" in warning and "s3" not in warning


@pytest.mark.parametrize(
    ("variable", "value", "kept"),
    [
        ("temperature_2m", -42.2, True),  # Czech record low
        ("temperature_2m", 85.0, False),
        ("wind_speed_10m", -1.0, False),
        ("wind_speed_10m", 40.0, True),
        ("precipitation", 250.0, False),
    ],
)
def test_implausible_observations_are_dropped(variable, value, kept):
    t = datetime(2026, 10, 1, 12, tzinfo=UTC)
    if variable == "precipitation":
        times = [t - timedelta(minutes=10 * i) for i in range(6)]
        rows = [("s", x, variable, value / 6, 0, "now") for x in times]
    else:
        rows = [("s", t, variable, value, 0, "now")]
    ten_minute = pl.DataFrame(rows, schema=observations.SCHEMA, orient="row")
    assert (observations.to_hourly(ten_minute).height == 1) == kept
