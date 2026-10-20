"""The Open-Meteo budget split across the scheduled workflows stays within the free tier
(docs/data-sources.md#open-meteo-budget)."""

import re
from pathlib import Path

import yaml

from meteoverdict import outlook, runs

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
DAY, MONTH, HOUR = 10_000, 300_000, 5_000
#: the outlook's API fallback, four runs a day (since 2026-10-20 the models come from the
#: bucket; before 3,400: four runs refused above outlook.MAX_CALLS, plus retries)
OUTLOOK_DAY = 800


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def default_calls(name: str) -> float:
    """The scheduled runs' MAX_CALLS (``${{ inputs.max_calls || 'N' }}``)."""
    value = workflow(name)["env"]["MAX_CALLS"]
    return float(re.fullmatch(r"\$\{\{ inputs\.max_calls \|\| '(\d+)' \}\}", value).group(1))


def schedules(name: str) -> list[str]:
    return [c["cron"] for c in workflow(name)[True]["schedule"]]  # "on" is YAML's true


def runs_a_day(name: str) -> int:
    return sum(len(c.split()[1].split(",")) for c in schedules(name))


def test_the_single_runs_use_only_their_fallback():
    # since 2026-10-17 the backfill spends the shared budget on the older single runs
    # itself: runs.yml asks for its 100 calls at every schedule and nothing more
    script = workflow("runs.yml")["jobs"]["runs"]["steps"][-1]["run"]
    assert '--max-calls "$MAX_CALLS"' in script
    assert "shared" not in script
    assert default_calls("runs.yml") == 100 and runs_a_day("runs.yml") == 4
    backfill = workflow("backfill.yml")["jobs"]["backfill"]["steps"][-1]["run"]
    assert "--older-windows" not in backfill and "--priority-from" not in backfill
    assert runs_a_day("backfill.yml") == 1


def test_a_day_and_a_month_stay_within_the_free_tier():
    fallback = default_calls("runs.yml") * runs_a_day("runs.yml")
    assert fallback <= 400  # the bucket's gaps only: the newest runs cost no calls
    shared = default_calls("backfill.yml")
    assert shared == 8_300
    assert runs_a_day("outlook.yml") == 4
    assert runs_a_day("outlook.yml") * outlook.MAX_FALLBACK_CALLS <= OUTLOOK_DAY
    day = OUTLOOK_DAY + fallback + shared
    assert day <= 9_500
    # scheduled runs start up to ~5 h late: the 22:20 single runs can slip into the next
    # UTC day, which then sees one fallback more (the 22:50 outlook is skipped then)
    assert day + default_calls("runs.yml") <= 9_600 <= DAY - 400
    assert 31 * day <= MONTH
    # no schedule asks for more than the hourly limit on its own (the backfill is paced
    # below 4,800 an hour by forecasts.Budget)
    assert default_calls("runs.yml") < min(HOUR, 4_800)
    # the backfill's pace and an outlook fallback in the same hour stay within the hour
    assert 4_800 + outlook.MAX_FALLBACK_CALLS <= HOUR


def test_fallback_runs_fit_one_or_two_models():
    # 100 calls: at least 1 a station at the 100 stations, one or two models a run
    assert runs.run_cost(100, 2) == 100 and runs.affordable(100, 19, 100) == 2


def test_the_outlook_runs_after_each_model_run_and_never_five_times_a_day():
    # 00/06/12/18 UTC runs are on Open-Meteo 3.5-6 h after their start
    assert schedules("outlook.yml") == ["50 4 * * *", "50 10 * * *", "50 16 * * *", "50 22 * * *"]
    steps = workflow("outlook.yml")["jobs"]["outlook"]["steps"]
    script = next(s for s in steps if s.get("name") == "Outlook")["run"]
    # a 22:50 run that starts after midnight UTC would be the next day's fifth: skipped
    assert '"$SCHEDULE" = "50 22 * * *"' in script and "exit 0" in script
    assert script.index("exit 0") < script.index("mvd outlook --github-release")
    # the Pages workflow deploys after every outlook run
    pages = workflow("pages.yml")[True]["workflow_run"]["workflows"]
    assert "Outlook" in pages
