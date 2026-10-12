from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import backfill, forecasts, observations
from meteoverdict.models import load_models

MODELS = [m for m in load_models() if m.id in ("dwd_icon_d2", "ecmwf_ifs025")]
POINTS = pl.DataFrame({"id": ["s"], "lat": [50.0], "lon": [14.4], "elevation": [300.0]})
FIRST, LAST = date(2026, 8, 1), date(2026, 9, 30)


def hourly(start: date, end: date) -> list[datetime]:
    t, out = datetime.combine(start, datetime.min.time(), UTC), []
    while t.date() <= end:
        out.append(t)
        t += timedelta(hours=1)
    return out


class Fake:
    """Stands in for ČHMÚ and Open-Meteo; records what was asked."""

    def __init__(self, quota_after: int | None = None, now_month: str | None = None):
        self.obs_calls: list[tuple[date, date]] = []
        self.fc_calls: list[tuple[str, date, date]] = []
        self.quota_after = quota_after
        self.now_month = now_month

    def observations(self, client, ids, start, end):
        self.obs_calls.append((start, end))
        source = "now" if self.now_month == f"{start:%Y-%m}" else "recent"
        rows = [("s", t, "temperature_2m", 10.0, 0, source) for t in hourly(start, end)]
        return pl.DataFrame(rows, schema=observations.SCHEMA, orient="row")

    def forecasts(self, client, points, models, start, end, budget):
        (model,) = models
        if self.quota_after is not None and len(self.fc_calls) >= self.quota_after:
            error = forecasts.QuotaError("Daily API request limit exceeded.")
            error.partial = pl.DataFrame(schema=forecasts.SCHEMA)
            raise error
        self.fc_calls.append((model.id, start, end))
        rows = [("s", t, model.id, 1, 11.0, None, None) for t in hourly(start, end)]
        return pl.DataFrame(rows, schema=forecasts.SCHEMA, orient="row")


@pytest.fixture
def fake(monkeypatch):
    def install(**kwargs):
        f = Fake(**kwargs)
        monkeypatch.setattr(backfill.observations, "fetch_observations", f.observations)
        monkeypatch.setattr(backfill.forecasts, "fetch_forecasts", f.forecasts)
        return f

    return install


def run(tmp_path, sync=None):
    return backfill.run(
        None, POINTS, MODELS, FIRST, LAST, tmp_path, forecasts.Budget(max_calls=1e9), sync
    )


def test_newest_windows_first_and_everything_scored(tmp_path, fake):
    f = fake()
    result = run(tmp_path)
    windows = list(forecasts.windows(FIRST, LAST))
    assert result.windows_done == len(windows) and result.stopped == ""
    assert f.fc_calls[0][1] == windows[-1][0]  # newest window first
    # 14-day windows run across the month boundary
    assert (date(2026, 8, 29), date(2026, 9, 11)) in [(s, e) for _, s, e in f.fc_calls]
    assert {p.name for p in (tmp_path / "scores").iterdir()} == {
        "2026-08.parquet",
        "2026-09.parquet",
    }
    scores = pl.concat([pl.read_parquet(p) for p in (tmp_path / "scores").iterdir()])
    assert scores["date"].min() == FIRST and scores["date"].max() == LAST
    # each month's observations were fetched once
    assert sorted(f.obs_calls) == [
        (date(2026, 8, 1), date(2026, 8, 31)),
        (date(2026, 9, 1), date(2026, 9, 30)),
    ]


def test_stops_at_the_quota_and_resumes(tmp_path, fake):
    first = fake(quota_after=3)
    result = run(tmp_path)
    assert "Daily API request limit" in result.stopped
    done_before = len(first.fc_calls)
    second = fake()
    run(tmp_path)
    asked_again = {(m, s) for m, s, _ in first.fc_calls} & {(m, s) for m, s, _ in second.fc_calls}
    assert not asked_again  # finished model-windows are not fetched twice
    assert done_before + len(second.fc_calls) == 2 * len(list(forecasts.windows(FIRST, LAST)))
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
    assert sync.calls[0] == ("pull", ("2026-09", "2026-10"))  # incl. the next day's month
    assert sync.calls[1][0] == "push"
    assert len(sync.calls) == 2 * len(list(forecasts.windows(FIRST, LAST)))
