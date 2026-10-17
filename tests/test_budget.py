"""The Open-Meteo budget split across the scheduled workflows stays within the free tier
(docs/data-sources.md#open-meteo-budget)."""

import itertools
import re
from pathlib import Path

import yaml

from meteoverdict import outlook, runs

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
DAY, MONTH, HOUR = 10_000, 300_000, 5_000
#: the outlook's two runs a day, each refused above outlook.MAX_CALLS, plus retries
OUTLOOK_DAY = 1_700


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def runs_schedules() -> dict[str, tuple[float, float, float]]:
    """cron -> (base calls, shared from, shared to) from runs.yml's case statement."""
    script = workflow("runs.yml")["jobs"]["runs"]["steps"][-1]["run"]
    found = {}
    for cron, calls, start, end in re.findall(
        r'"([^"]+)"\) calls=(\d+); from=(\d+); to=(\d+)', script
    ):
        found[cron] = (float(calls), float(start), float(end))
    default = re.search(r"\*\) calls=(\d+); from=(\d+); to=(\d+)", script)
    found["*"] = tuple(float(v) for v in default.groups())
    return found


def test_the_shared_budget_is_the_backfills():
    shared = float(workflow("runs.yml")["env"]["SHARED_CALLS"])
    backfill = workflow("backfill.yml")["env"]["MAX_CALLS"]
    assert f"'{shared:.0f}'" in backfill
    parts = runs_schedules()
    # the two shared parts of runs.yml cover the share once, without overlap
    spans = sorted((s, e) for _, s, e in parts.values() if e > s)
    assert spans[0][0] == 0 and spans[-1][1] == shared
    assert all(a[1] == b[0] for a, b in itertools.pairwise(spans))


def test_a_day_and_a_month_stay_within_the_free_tier():
    on = workflow("runs.yml")[True]  # "on" is YAML's true
    crons = [c["cron"] for c in on["schedule"]]
    parts = runs_schedules()
    hours_per_cron = {c: len(c.split()[1].split(",")) for c in crons}
    fallback = sum(parts.get(c, parts["*"])[0] * hours_per_cron[c] for c in crons)
    assert fallback <= 400  # the bucket's gaps only: the newest runs cost no calls
    shared = float(workflow("runs.yml")["env"]["SHARED_CALLS"])
    assert 2 * outlook.MAX_CALLS <= OUTLOOK_DAY
    day = OUTLOOK_DAY + fallback + shared
    assert day <= 9_500
    # scheduled runs start up to ~5 h late: the 22:20 single runs can slip into the next
    # UTC day, which then sees one fallback more
    late = parts.get("20 4,16,22 * * *", parts["*"])[0]
    assert day + late <= DAY - 400
    assert 31 * day <= MONTH
    # no schedule asks for more than the hourly limit on its own
    for calls, start, end in parts.values():
        assert calls + (end - start) < min(HOUR, 4_800)


def test_fallback_runs_fit_one_or_two_models():
    # 100 calls: at least 1 a station at the 100 stations, one or two models a run
    assert runs.run_cost(100, 2) == 100 and runs.affordable(100, 19, 100) == 2
