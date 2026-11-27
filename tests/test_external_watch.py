"""scripts/external_watch.py: the staleness decisions and the run over fetched documents."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "external_watch", Path(__file__).resolve().parents[1] / "scripts" / "external_watch.py"
)
watch = importlib.util.module_from_spec(SPEC)
sys.modules["external_watch"] = watch
SPEC.loader.exec_module(watch)

NOW = datetime(2026, 11, 2, 14, 0, tzinfo=UTC)


def test_age_of_the_stamps_the_site_uses():
    assert watch.age_hours("2026-11-02T12:13+00:00", NOW) == pytest.approx(1.783, abs=0.001)
    assert watch.age_hours("2026-11-02T12:00:00Z", NOW) == 2
    assert watch.age_hours("2026-11-02T12:00", NOW) == 2  # no zone: UTC


def index(generated, n=77):
    return {"generated": generated, "okresy": [{"code": f"CZ{i}"} for i in range(n)]}


def test_index_fresh_and_stale():
    assert watch.check_index(index("2026-11-02T12:13+00:00"), NOW).ok
    stale = watch.check_index(index("2026-11-02T06:00+00:00"), NOW)
    assert not stale.ok and "8.0 h old" in stale.detail


def test_index_with_lost_okresy_or_no_stamp():
    r = watch.check_index(index("2026-11-02T12:13+00:00", 70), NOW)
    assert not r.ok and "70 okresy" in r.detail
    assert not watch.check_index({"okresy": []}, NOW).ok
    assert not watch.check_index([], NOW).ok


def test_ai_has_a_longer_limit_than_the_outlook():
    doc = {"generated": "2026-11-02T06:30+00:00"}  # 7.5 h
    assert not watch.check_outlook(doc, NOW).ok
    assert watch.check_ai(doc, NOW).ok


def release(updated):
    return {
        "assets": [
            {"name": "outlook.json", "updated_at": "2026-11-02T12:00:00Z"},
            {"name": "observed-data.zip", "updated_at": updated},
        ]
    }


def test_observed_zip_the_incident_of_22_october():
    assert watch.check_observed_zip(release("2026-11-01T20:00:00Z"), NOW).ok
    r = watch.check_observed_zip(release("2026-10-23T08:15:00Z"), NOW)
    assert not r.ok and "old" in r.detail
    assert not watch.check_observed_zip({"assets": []}, NOW).ok


def test_run_reports_each_check_and_an_unreachable_file():
    docs = {
        watch.CHECKS["index"][0]: index("2026-11-02T12:13+00:00"),
        watch.CHECKS["observed-zip"][0]: release("2026-10-23T08:15:00Z"),
    }

    def fetch(url, token=None):
        if url not in docs:
            raise RuntimeError("503")
        return docs[url]

    results = {r.name: r for r in watch.run(["index", "outlook", "observed-zip"], fetch, NOW)}
    assert results["index"].ok
    assert not results["outlook"].ok and "cannot be read" in results["outlook"].detail
    assert results["outlook"].error and not results["observed-zip"].error
    assert not results["observed-zip"].ok


def test_main_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(watch, "run", lambda names: [watch.Result("a", True, "x")])
    assert watch.main([]) == 0
    monkeypatch.setattr(
        watch, "run", lambda names: [watch.Result("a", True, "x"), watch.Result("b", False, "y")]
    )
    assert watch.main([]) == 1
    assert "STALE b: y" in capsys.readouterr().out
    # an unreadable file alone is unknown (2); a really stale one wins (1)
    err = watch.Result("c", False, "z", error=True)
    monkeypatch.setattr(watch, "run", lambda names: [watch.Result("a", True, "x"), err])
    assert watch.main([]) == 2
    assert "ERROR c: z" in capsys.readouterr().out
    monkeypatch.setattr(watch, "run", lambda names: [err, watch.Result("b", False, "y")])
    assert watch.main([]) == 1


class FakeResponse:
    def __init__(self, body=b"{}"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self.body


def http_error(code):
    import urllib.error

    return urllib.error.HTTPError("u", code, "x", {}, None)


def test_fetch_retries_rate_limit_and_5xx_with_backoff(monkeypatch):
    calls = iter([http_error(403), http_error(429), http_error(502), FakeResponse(b'{"a": 1}')])
    pauses = []

    def fake_urlopen(request, timeout):
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(watch.urllib.request, "urlopen", fake_urlopen)
    assert watch.fetch_json("https://x.test/a", "tok", sleep=pauses.append) == {"a": 1}
    assert pauses == [5, 15, 45]


def test_fetch_does_not_retry_a_404(monkeypatch):
    n = []

    def fake_urlopen(request, timeout):
        n.append(1)
        raise http_error(404)

    monkeypatch.setattr(watch.urllib.request, "urlopen", fake_urlopen)
    try:
        watch.fetch_json("https://x.test/a", sleep=lambda s: None)
    except RuntimeError as exc:
        assert "404" in str(exc)
    assert len(n) == 1
