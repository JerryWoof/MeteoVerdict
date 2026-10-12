from datetime import UTC, date, datetime, timedelta

import polars as pl

from meteoverdict import daily, forecasts, observations, partitions, report
from meteoverdict.cli import app
from meteoverdict.models import load_models

ICON = next(m for m in load_models() if m.id == "dwd_icon_d2")
DAY = date(2026, 10, 11)


def hours(start: date, days: int) -> list[datetime]:
    first = datetime.combine(start, datetime.min.time(), UTC)
    return [first + timedelta(hours=h) for h in range(24 * days)]


def obs_rows(times, value=10.0, source="now"):
    rows = [(s, t, "temperature_2m", value, 5, source) for t in times for s in ("a", "b", "c")]
    return pl.DataFrame(rows, schema=observations.SCHEMA, orient="row")


def write_forecasts(data_dir, start: date, days: int):
    rows = [
        (s, t, ICON.id, 1, 11.0, None, None) for t in hours(start, days) for s in ("a", "b", "c")
    ]
    forecasts_table = pl.DataFrame(rows, schema=forecasts.SCHEMA, orient="row")
    partitions.write_monthly(forecasts_table, data_dir / "fc", forecasts.KEYS)


def test_run_captures_observations_and_rescores(tmp_path, monkeypatch):
    asked = []

    def fake_obs(client, ids, start, end):
        asked.append((start, end))
        return obs_rows(hours(start, (end - start).days + 1))

    monkeypatch.setattr(daily.observations, "fetch_observations", fake_obs)
    write_forecasts(tmp_path, DAY - timedelta(days=5), 6)
    points = pl.DataFrame({"id": ["a", "b", "c"]})
    months = daily.run(None, points, [ICON], DAY, tmp_path)
    assert asked == [(DAY - timedelta(days=2), DAY)]  # what now/ still keeps
    scores = pl.read_parquet(tmp_path / "scores" / "2026-10.parquet")
    # observations exist for the last 3 days only, so only those days are scored
    assert sorted(set(scores["date"])) == [DAY - timedelta(days=d) for d in (2, 1, 0)]
    assert months[-1] == "2026-10" and len(months) >= 4


def test_daily_command_publishes_the_leaderboard(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from meteoverdict import cli

    stations_file = tmp_path / "stations.parquet"
    pl.DataFrame(
        {
            "id": ["a", "b", "c"],
            "name": ["A", "B", "C"],
            "active": [True] * 3,
            "okres_code": ["CZ0201"] * 3,
            "okres": ["Benešov"] * 3,
            "kraj_code": ["CZ020"] * 3,
            "kraj": ["Středočeský kraj"] * 3,
            "elevation_class": ["lowland"] * 3,
        }
    ).write_parquet(stations_file)
    meta2 = pl.DataFrame(
        {"OBS_TYPE": ["10M"] * 3, "WSI": ["a", "b", "c"], "EG_EL_ABBREVIATION": ["T"] * 3}
    )
    monkeypatch.setattr(cli, "fetch_current_meta", lambda client, n, today: meta2)
    monkeypatch.setattr(
        daily.observations,
        "fetch_observations",
        lambda client, ids, start, end: obs_rows(hours(start, (end - start).days + 1)),
    )
    write_forecasts(tmp_path, DAY - timedelta(days=5), 6)
    readme = tmp_path / "README.md"
    readme.write_text(f"# t\n{report.START}\nsoon\n{report.END}\n", encoding="utf-8")
    args = [
        "daily", "--date", "2026-10-11", "--stations", str(stations_file),
        "--data-dir", str(tmp_path), "--out", str(tmp_path / "site"),
        "--readme-path", str(readme), "--resamples", "50",
    ]  # fmt: skip
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    text = readme.read_text(encoding="utf-8")
    assert "soon" not in text and "DWD ICON-D2" in text
    assert (tmp_path / "site" / "meta.json").exists()
    assert (tmp_path / "aggregates.parquet").exists()
