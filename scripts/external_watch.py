"""Freshness of the public data, checked from outside the Spark (and the Mac, whose watchdog tells
through the Spark): what a visitor of meteoverdict.cz would get, and the release asset the measured
page stands on. Standard library only, so the workflow needs no install.

``python scripts/external_watch.py`` runs every check and exits 1 when any is stale and 2 when
one could not be read (unknown, never reported as stale). It prints one line per check
(``--only NAME`` runs one: ``index``, ``outlook``, ``ai``, ``observed-zip``). The workflow
``external-watch.yml`` runs it every 30 minutes and opens (or comments on) an issue;
``chmi-archive.yml`` runs ``--only observed-zip`` after its optional observed-map step, so that a
silent failure of that step turns the run red.

The limits follow the schedule: the fast cycle runs every 2 hours (the Spark tolerates two missed
cycles, MAX_STALENESS_H = 6), the observed map is rebuilt twice a day by chmi-archive.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

SITE = "https://meteoverdict.cz"
REPO = "JerryWoof/MeteoVerdict"
EXPECT_OKRESY = 77


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    error: bool = False  # could not be read: unknown, not stale


def age_hours(stamp: str, now: datetime | None = None) -> float:
    """Hours since an ISO stamp (``2026-11-02T12:13+00:00``, ``...Z`` or ``...:00Z``)."""
    then = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return ((now or datetime.now(UTC)) - then).total_seconds() / 3600


RETRY_STATUS = {403, 429}  # 403: GitHub's rate limit; 5xx are retried too


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRY_STATUS or exc.code >= 500
    return isinstance(exc, OSError)  # dropped connection, timeout, DNS


def fetch_json(
    url: str,
    token: str | None = None,
    timeout: int = 60,
    tries: int = 4,
    sleep: Callable[[float], None] = time.sleep,
):
    """The JSON at ``url``; retried with a growing pause on 403, 429, 5xx and dropped connections,
    because a rate limit or one bad moment is not an outage."""
    last: Exception | None = None
    for attempt in range(tries):
        request = urllib.request.Request(url, headers={"User-Agent": "meteoverdict-external-watch"})
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except ValueError as exc:
            last = exc
        except OSError as exc:
            last = exc
            if not _retryable(exc):
                break
        if attempt < tries - 1:
            sleep(5 * 3**attempt)  # 5, 15, 45 s
    raise RuntimeError(f"{url}: {last}")


def _stamp_check(name: str, doc: dict, key: str, max_hours: float, now: datetime | None) -> Result:
    stamp = doc.get(key) if isinstance(doc, dict) else None
    if not stamp:
        return Result(name, False, f"no {key!r} in the file")
    age = age_hours(stamp, now)
    return Result(name, age <= max_hours, f"{key} {stamp}, {age:.1f} h old (limit {max_hours:g} h)")


def check_index(doc: dict, now: datetime | None = None, max_hours: float = 6) -> Result:
    result = _stamp_check("index", doc, "generated", max_hours, now)
    okresy = len(doc.get("okresy", [])) if isinstance(doc, dict) else 0
    if okresy != EXPECT_OKRESY:
        return Result("index", False, f"{okresy} okresy, expected {EXPECT_OKRESY}; {result.detail}")
    return result


def check_outlook(doc: dict, now: datetime | None = None, max_hours: float = 6) -> Result:
    return _stamp_check("outlook", doc, "generated", max_hours, now)


def check_ai(doc: dict, now: datetime | None = None, max_hours: float = 8) -> Result:
    return _stamp_check("ai", doc, "generated", max_hours, now)


def check_observed_zip(release: dict, now: datetime | None = None, max_hours: float = 36) -> Result:
    """``observed-data.zip`` of the release data-latest, by its ``updated_at``."""
    for asset in release.get("assets", []) if isinstance(release, dict) else []:
        if asset.get("name") == "observed-data.zip":
            return _stamp_check("observed-zip", asset, "updated_at", max_hours, now)
    return Result("observed-zip", False, "observed-data.zip is not in the release data-latest")


CHECKS: dict[str, tuple[str, Callable]] = {
    "index": (f"{SITE}/api/v1/index.json", check_index),
    "outlook": (f"{SITE}/data/scores/outlook.json", check_outlook),
    "ai": (f"{SITE}/data/scores/ai/ai-forecast.json", check_ai),
    "observed-zip": (
        f"https://api.github.com/repos/{REPO}/releases/tags/data-latest",
        check_observed_zip,
    ),
}


def run(
    names: list[str], fetch: Callable = fetch_json, now: datetime | None = None
) -> list[Result]:
    token = os.environ.get("GITHUB_TOKEN")
    results = []
    for name in names:
        url, check = CHECKS[name]
        try:
            doc = fetch(url, token if "api.github.com" in url else None)
        except RuntimeError as exc:
            results.append(Result(name, False, f"cannot be read: {exc}", error=True))
            continue
        results.append(check(doc, now))
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--only", choices=sorted(CHECKS), action="append", help="run only this check")
    args = p.parse_args(argv)
    results = run(args.only or list(CHECKS))
    for r in results:
        label = "ERROR" if r.error else "ok   " if r.ok else "STALE"
        print(f"{label} {r.name}: {r.detail}")
    if any(not r.ok and not r.error for r in results):
        return 1  # something really is old
    return 2 if any(r.error for r in results) else 0  # unknown: could not be checked


if __name__ == "__main__":
    sys.exit(main())
