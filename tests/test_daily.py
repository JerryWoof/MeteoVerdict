import json
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import daily, forecasts, observations, partitions, runs
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


def test_run_says_which_days_were_not_scored_and_why(tmp_path, monkeypatch):
    # 15 Oct 2026: forecasts reached 4 Oct (backfill window 21 Sep..4 Oct), observations
    # were captured from 10 Oct; "re-scored ..10-14" hid that nothing after 30 Sep was
    day = date(2026, 10, 14)
    monkeypatch.setattr(
        daily.observations,
        "fetch_observations",
        lambda client, ids, start, end: obs_rows(hours(start, (end - start).days + 1)),
    )
    observations.write_monthly(obs_rows(hours(date(2026, 9, 28), 3)), tmp_path / "obs")
    observations.write_monthly(obs_rows(hours(date(2026, 10, 10), 2)), tmp_path / "obs")
    write_forecasts(tmp_path, date(2026, 9, 28), 7)
    logged = []
    daily.run(None, pl.DataFrame({"id": ["a", "b", "c"]}), [ICON], day, tmp_path, logged.append)
    assert not (tmp_path / "scores" / "2026-10.parquet").exists()
    assert logged[-2].endswith("last scored day 2026-09-30")
    assert logged[-1] == (
        "nothing scored after 2026-09-30: forecasts for 2026-10-01..2026-10-04, "
        "observations for 2026-10-10..2026-10-14"
    )


def test_recent_days_are_scored_from_the_single_runs(tmp_path, monkeypatch):
    # forecasts of the backfill reach 4 Oct; the single runs (4 a day) cover the rest
    day = date(2026, 10, 15)
    eu = next(m for m in load_models() if m.id == "dwd_icon_eu")
    monkeypatch.setattr(
        daily.observations,
        "fetch_observations",
        lambda client, ids, start, end: obs_rows(hours(start, (end - start).days + 1)),
    )
    observations.write_monthly(obs_rows(hours(date(2026, 10, 3), 2)), tmp_path / "obs")
    rows = [(s, t, eu.id, 1, 11.0, None, None) for t in hours(date(2026, 10, 1), 4) for s in "abc"]
    previous = pl.DataFrame(rows, schema=forecasts.SCHEMA, orient="row")
    partitions.write_monthly(previous, tmp_path / "fc", forecasts.KEYS)
    first = datetime(2026, 10, 8, tzinfo=UTC)
    single = [
        (first + timedelta(hours=6 * r), eu.id, s, lead,
         first + timedelta(hours=6 * r + lead), 12.0, 0.0, 3.0, None)
        for r in range(4 * 8)
        for lead in range(1, 121)
        for s in "abc"
    ]  # fmt: skip
    table = pl.DataFrame(single, schema=runs.HOURLY_SCHEMA, orient="row")
    partitions.write_monthly(table, tmp_path / "runs", runs.KEYS, "run")
    logged = []
    daily.run(None, pl.DataFrame({"id": list("abc")}), [eu], day, tmp_path, logged.append)
    scores = pl.read_parquet(tmp_path / "scores" / "2026-10.parquet")
    by_source = scores.group_by("source").agg(
        pl.col("date").min().alias("from"), pl.col("date").max().alias("to")
    )
    assert sorted(by_source.rows()) == [
        ("previous_runs", date(2026, 10, 3), date(2026, 10, 4)),
        ("single_runs", day - timedelta(days=2), day),  # observations of the last 3 days
    ]
    fresh_rows = scores.filter(pl.col("source") == "single_runs", pl.col("model") == eu.id)
    assert set(fresh_rows["lead_day"]) == {1, 2, 3, 4}
    # 12 °C forecast against 10 °C observed
    ranked = fresh_rows.filter(pl.col("variable") == "temperature_2m")
    assert (ranked["sum_err"] / ranked["n"]).to_list() == pytest.approx([2.0] * ranked.height)
    assert any(
        line.startswith("rebuilt D+N from the single runs for 3 stations") for line in logged
    )
    assert logged[-1].endswith(f"last scored day {day}")


def test_day_ranges():
    days = [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)]
    assert daily.day_ranges(days) == "2026-10-01..2026-10-02, 2026-10-05"
    assert daily.day_ranges([]) == "no day"


def test_daily_command_publishes_the_scores_and_the_badge(tmp_path, monkeypatch):
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
    args = [
        "daily", "--date", "2026-10-11", "--stations", str(stations_file),
        "--data-dir", str(tmp_path), "--out", str(tmp_path / "site"),
        "--resamples", "50",
    ]  # fmt: skip
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    badge = json.loads((tmp_path / "site" / "badge.json").read_text())
    assert badge["label"] == "last updated"
    assert (tmp_path / "site" / "meta.json").exists()
    assert (tmp_path / "aggregates.parquet").exists()
    # the forecast's weights for mvd outlook (6 days: too few for the regression)
    weights = pl.read_parquet(tmp_path / "forecast-weights.parquet")
    assert weights.height and weights["mos_weight"].null_count() == weights.height


def test_run_refreshes_recent_rain_gauge_months(tmp_path, monkeypatch):
    asked = []

    def fake_gauges(client, ids, start, end, historical=True):
        asked.append((list(ids), start, end, historical))
        row = ("g", datetime(2026, 9, 2, 6, tzinfo=UTC), "precipitation_24h", 4.0, 0, "recent")
        return pl.DataFrame([row], schema=observations.SCHEMA, orient="row")

    monkeypatch.setattr(daily.observations, "fetch_observations", lambda *a: obs_rows([]))
    monkeypatch.setattr(daily.gauges, "fetch_gauge_precipitation", fake_gauges)
    gauge_points = pl.DataFrame({"id": ["g"]})
    daily.run(None, pl.DataFrame({"id": ["a"]}), [ICON], DAY, tmp_path, gauge_points=gauge_points)
    # 62 days back from 11 Oct is 10 Aug: whole months from August, recent/ only
    assert asked == [(["g"], date(2026, 8, 1), DAY, False)]
    stored = pl.read_parquet(tmp_path / "gauges" / "2026-09.parquet")
    assert stored["station_id"].to_list() == ["g"]
    assert not (tmp_path / "obs" / "2026-09.parquet").exists()
    both = observations.scan(tmp_path, date(2026, 9, 1), DAY).collect()
    assert both["variable"].to_list() == ["precipitation_24h"]
