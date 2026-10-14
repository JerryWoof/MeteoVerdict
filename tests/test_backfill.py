from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import backfill, forecasts, observations
from meteoverdict.models import load_models

MODELS = [m for m in load_models() if m.id in ("dwd_icon_d2", "ecmwf_ifs025")]
POINTS = pl.DataFrame({"id": ["s"], "lat": [50.0], "lon": [14.4], "elevation": [300.0]})
FIRST, LAST = date(2026, 8, 1), date(2026, 9, 30)
# 61 days: four complete 14-day windows (1 Aug … 25 Sep) and an incomplete tail
WINDOWS = [
    (date(2026, 8, 1) + timedelta(days=14 * i), date(2026, 8, 14) + timedelta(days=14 * i))
    for i in range(4)
]


def hourly(start: date, end: date) -> list[datetime]:
    t, out = datetime.combine(start, datetime.min.time(), UTC), []
    while t.date() <= end:
        out.append(t)
        t += timedelta(hours=1)
    return out


class Fake:
    """Stands in for ČHMÚ and Open-Meteo; records what was asked."""

    def __init__(
        self,
        quota_after: int | None = None,
        now_month: str | None = None,
        error: type[forecasts.QuotaError] = forecasts.QuotaError,
    ):
        self.error = error
        self.obs_calls: list[tuple[date, date]] = []
        self.fc_calls: list[tuple[str, date, date]] = []
        self.gauge_fc_calls: list[tuple[str, date, date]] = []
        self.gauge_obs_calls: list[tuple[date, date]] = []
        self.quota_after = quota_after
        self.now_month = now_month

    def observations(self, client, ids, start, end):
        self.obs_calls.append((start, end))
        source = "now" if self.now_month == f"{start:%Y-%m}" else "recent"
        rows = [("s", t, "temperature_2m", 10.0, 0, source) for t in hourly(start, end)]
        return pl.DataFrame(rows, schema=observations.SCHEMA, orient="row")

    def forecasts(self, client, points, models, start, end, budget, uncovered=None, **ask):
        (model,) = models
        if self.quota_after is not None and len(self.fc_calls) >= self.quota_after:
            error = self.error("Daily API request limit exceeded.")
            error.partial = pl.DataFrame(schema=forecasts.SCHEMA)
            raise error
        if ask:  # rain gauges: precipitation only, 28-day requests
            assert ask == {"variables": ("precipitation",), "max_days": forecasts.GAUGE_DAYS}
            self.gauge_fc_calls.append((model.id, start, end))
            rows = [("g", t, model.id, 1, None, 0.5, None) for t in hourly(start, end)]
            return pl.DataFrame(rows, schema=forecasts.SCHEMA, orient="row")
        self.fc_calls.append((model.id, start, end))
        rows = [("s", t, model.id, 1, 11.0, None, None) for t in hourly(start, end)]
        return pl.DataFrame(rows, schema=forecasts.SCHEMA, orient="row")

    def gauges(self, client, ids, start, end, historical=True):
        assert not historical  # the 2.5 MB historical files are imported once, not here
        self.gauge_obs_calls.append((start, end))
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        rows = [
            (
                "g",
                datetime.combine(d, datetime.min.time(), UTC) + timedelta(days=1, hours=6),
                "precipitation_24h",
                10.0,
                0,
                "recent",
            )
            for d in days
        ]
        return pl.DataFrame(rows, schema=observations.SCHEMA, orient="row")


@pytest.fixture
def fake(monkeypatch):
    def install(**kwargs):
        f = Fake(**kwargs)
        monkeypatch.setattr(backfill.observations, "fetch_observations", f.observations)
        monkeypatch.setattr(backfill.forecasts, "fetch_forecasts", f.forecasts)
        monkeypatch.setattr(backfill.gauges, "fetch_gauge_precipitation", f.gauges)
        return f

    return install


GAUGES = pl.DataFrame({"id": ["g"], "lat": [49.0], "lon": [16.0], "elevation": [250.0]})


def run(tmp_path, sync=None, gauges=None, last=LAST):
    budget = forecasts.Budget(max_calls=1e9)
    return backfill.run(
        None, POINTS, MODELS, FIRST, last, tmp_path, budget, sync, gauge_points=gauges
    )


def test_newest_windows_first_and_everything_scored(tmp_path, fake):
    f = fake()
    result = run(tmp_path)
    assert backfill.complete_windows(FIRST, LAST) == WINDOWS
    assert result.windows_done == 4 and result.stopped == ""
    assert f.fc_calls[0][1] == WINDOWS[-1][0]  # newest complete window first
    assert all(e <= date(2026, 9, 25) for _, _, e in f.fc_calls)  # incomplete tail skipped
    # 14-day windows run across the month boundary
    assert (date(2026, 8, 29), date(2026, 9, 11)) in [(s, e) for _, s, e in f.fc_calls]
    assert {p.name for p in (tmp_path / "scores").iterdir()} == {
        "2026-08.parquet",
        "2026-09.parquet",
    }
    scores = pl.concat([pl.read_parquet(p) for p in (tmp_path / "scores").iterdir()])
    assert scores["date"].min() == FIRST and scores["date"].max() == date(2026, 9, 25)
    # each month's observations were fetched once
    assert sorted(f.obs_calls) == [
        (date(2026, 8, 1), date(2026, 8, 31)),
        (date(2026, 9, 1), date(2026, 9, 30)),
    ]


def test_open_meteo_failing_after_retries_stops_cleanly(tmp_path, fake):
    # an empty answer failed backfill run 38231929911 (12 Oct 2026) and lost the window
    fake(quota_after=3, error=forecasts.UnavailableError)
    result = run(tmp_path)
    assert result.stopped and result.windows_done < len(WINDOWS)
    state = backfill.State.load(tmp_path / "backfill-state.json")
    assert len(state.fc_done) == 3  # finished model-windows are kept for the next run


def test_stops_at_the_quota_and_resumes(tmp_path, fake):
    first = fake(quota_after=3)
    result = run(tmp_path)
    assert "Daily API request limit" in result.stopped
    done_before = len(first.fc_calls)
    second = fake()
    run(tmp_path)
    asked_again = {(m, s) for m, s, _ in first.fc_calls} & {(m, s) for m, s, _ in second.fc_calls}
    assert not asked_again  # finished model-windows are not fetched twice
    assert done_before + len(second.fc_calls) == 2 * len(WINDOWS)
    assert run(tmp_path).windows_done == 0  # nothing left


def test_a_month_only_in_now_is_not_final(tmp_path, fake):
    fake(now_month="2026-09")
    run(tmp_path)
    state = backfill.State.load(tmp_path / "backfill-state.json")
    assert state.obs_months == {"2026-08"}
    september = [s for s in state.scored if s.startswith("2026-09")]
    assert september == []  # windows that need September observations stay open


def test_sync_pulls_before_and_pushes_after_each_window(tmp_path, fake):
    fake()

    class Recorder:
        def __init__(self):
            self.calls = []

        def pull(self, months):
            self.calls.append(("pull", tuple(months)))

        def push(self, months):
            self.calls.append(("push", tuple(months)))

    sync = Recorder()
    run(tmp_path, sync)
    assert sync.calls[0] == ("pull", ("2026-09",))  # 12-25 Sep; the next day is in September too
    assert sync.calls[1][0] == "push"
    assert len(sync.calls) == 2 * len(WINDOWS)


def test_a_window_seen_while_incomplete_is_done_again_once_complete(tmp_path, fake):
    # an earlier version marked the incomplete newest window as done; its keys must not
    # stop the complete window from being fetched
    old = backfill.State(tmp_path / "backfill-state.json", fc_done={"dwd_icon_d2|2026-09-12"})
    old.save()
    f = fake()
    run(tmp_path)
    assert ("dwd_icon_d2", date(2026, 9, 12), date(2026, 9, 25)) in f.fc_calls


def test_gauge_forecasts_come_in_28_day_windows(tmp_path, fake):
    f = fake()
    assert run(tmp_path, gauges=GAUGES).windows_done == 4
    # 1-28 Aug and 29 Aug-25 Sep; each fetched once for both 14-day windows in it
    assert sorted(f.gauge_fc_calls) == sorted(
        (m.id, s, e)
        for m in MODELS
        for s, e in [(date(2026, 8, 1), date(2026, 8, 28)), (date(2026, 8, 29), date(2026, 9, 25))]
    )
    # gauge totals have their own month files, next to the hourly observations
    stored = pl.concat([pl.read_parquet(p) for p in (tmp_path / "gauges").iterdir()])
    assert set(stored["station_id"]) == {"g"}
    hourly = pl.concat([pl.read_parquet(p) for p in (tmp_path / "obs").iterdir()])
    assert set(hourly["station_id"]) == {"s"}
    scores = pl.concat([pl.read_parquet(p) for p in (tmp_path / "scores").iterdir()])
    gauge = scores.filter(pl.col("station_id") == "g")
    assert set(gauge["variable"]) == {"precipitation_24h"}
    # 24 hours of 0.5 mm forecast against 10 mm measured
    assert gauge["sum_err"].to_list() == pytest.approx([2.0] * gauge.height)
    # 1 Aug … 24 Sep: 25 Sep would need forecasts up to 26 Sep 06:00
    assert gauge.height == len(MODELS) * 55


def test_gauge_months_are_final_only_after_the_publication_delay(tmp_path, fake):
    fake()
    run(tmp_path, gauges=GAUGES, last=date(2026, 11, 15))
    state = backfill.State.load(tmp_path / "backfill-state.json")
    assert "2026-08" in state.gauge_months  # ended 76 days before the last day
    assert "2026-09" not in state.gauge_months  # 46 days: the daily run keeps updating it


def test_windows_scored_before_the_gauges_get_their_gauge_forecasts(tmp_path, fake):
    fake()
    run(tmp_path)
    f = fake()
    # the newer window of each 28-day gauge window fetches it and re-scores both halves
    assert run(tmp_path, gauges=GAUGES).windows_done == 2
    assert f.fc_calls == []  # station forecasts are not fetched again
    assert len(f.gauge_fc_calls) == 2 * len(MODELS)
    assert run(tmp_path, gauges=GAUGES).windows_done == 0
    scores = pl.concat([pl.read_parquet(p) for p in (tmp_path / "scores").iterdir()])
    gauge = scores.filter(pl.col("station_id") == "g")
    assert gauge["date"].min() == FIRST and gauge["date"].max() == date(2026, 9, 24)


def test_sync_covers_the_months_of_the_gauge_window(tmp_path, fake):
    fake()
    pulls = []

    class Recorder:
        def pull(self, months):
            pulls.append(tuple(months))

        def push(self, months):
            pass

    run(tmp_path, Recorder(), gauges=GAUGES)
    assert pulls[0] == ("2026-08", "2026-09")  # 12-25 Sep is in the window 29 Aug-25 Sep


def test_summary_for_the_job_page(tmp_path, fake):
    fake(quota_after=3)
    result = run(tmp_path)
    text = backfill.summary(result, 1234.5, tmp_path, FIRST, LAST)
    assert text.startswith("## Backfill\n")
    assert "1234.5 Open-Meteo calls" in text
    assert "of 4 14-day windows scored since 2026-08-01" in text
    assert "Stopped: Daily API request limit exceeded." in text


def test_pending_windows_and_the_day_of_the_last_calls(tmp_path, fake):
    state = backfill.State.load(tmp_path / "backfill-state.json")
    assert backfill.pending_windows(MODELS, FIRST, LAST, state) == WINDOWS[::-1]
    fake()
    budget = forecasts.Budget(max_calls=1e9)
    backfill.run(
        None,
        POINTS,
        MODELS,
        FIRST,
        LAST,
        tmp_path,
        budget,
        gauge_points=GAUGES,
        today=date(2026, 10, 1),
    )
    state = backfill.State.load(tmp_path / "backfill-state.json")
    assert state.calls_on == "2026-10-01"
    assert backfill.pending_windows(MODELS, FIRST, LAST, state) == []
    # the gauges' 28-day windows still owe their forecasts: pending, though scored
    state.fc_done = {k for k in state.fc_done if not k.startswith("gauges|")}
    assert backfill.pending_windows(MODELS, FIRST, LAST, state) == WINDOWS[::-1]
    assert backfill.pending_windows(MODELS, FIRST, LAST, state, gauges=False) == []
    # a run with nothing to fetch keeps the day of the last calls
    backfill.run(
        None,
        POINTS,
        MODELS,
        FIRST,
        LAST,
        tmp_path,
        budget,
        gauge_points=GAUGES,
        today=date(2026, 10, 2),
    )
    assert backfill.State.load(tmp_path / "backfill-state.json").calls_on == "2026-10-01"


def test_stopped_run_records_the_day_of_its_calls(tmp_path, fake):
    fake(quota_after=1)
    budget = forecasts.Budget(max_calls=1e9)
    backfill.run(None, POINTS, MODELS, FIRST, LAST, tmp_path, budget, today=date(2026, 10, 3))
    assert backfill.State.load(tmp_path / "backfill-state.json").calls_on == "2026-10-03"
