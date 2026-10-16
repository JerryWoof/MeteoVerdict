"""Data quality checks that fail loudly (roadmap 3.3).

``mvd check`` runs after the daily pipeline; any error makes the workflow fail (GitHub
then notifies the owner) and stops the daily commit. Warnings are reported only.

* stale data: newest observation older than ``MAX_OBS_AGE_H`` hours, newest forecast or
  score older than ``MAX_FC_AGE_DAYS`` days (complete backfill windows lag up to 14);
* stale publication: the published scores (``meta.json``) end more than
  ``MAX_AS_OF_LAG_DAYS`` days before they were generated, so the ranking and the
  combination weights miss the latest days (in October 2026 ``as_of`` stayed at 30 Sep
  while the daily run "re-scored" up to 14 Oct, as no October day had both forecasts
  and observations yet: normal for up to ~20 days, as forecasts come in 14-day windows);
* models left out for too short a record: the models the published 90-day comparison
  leaves out because they have scores on fewer than ``aggregate.MIN_COVERAGE`` of its
  days (``meta.json`` ``short_record``; a warning: normal for a few weeks after a model is
  added, as the backfill reaches back);
* missing stations: under ``MIN_REPORTING`` of the verified stations reported in the
  last ``RECENT_DAYS`` days (the stations missing are listed as a warning);
* suspicious stations: temperature MAE over the last 90 days (all models) above
  ``SUSPICIOUS_FACTOR`` x the network median and above ``SUSPICIOUS_MIN_MAE`` °C, a sign
  of a broken sensor or wrong station metadata rather than of bad forecasts.

Implausible observation values are already dropped when observations are read
(``observations.PLAUSIBLE``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from meteoverdict import metrics, partitions

MAX_OBS_AGE_H = 30
MAX_FC_AGE_DAYS = 21
# forecasts arrive in complete 14-day backfill windows, and scheduled runs start hours
# late: a lag of up to ~20 days is normal, more means scoring or publishing is stuck
MAX_AS_OF_LAG_DAYS = 21
RECENT_DAYS = 3
MIN_REPORTING = 0.8
SUSPICIOUS_FACTOR = 3.0
SUSPICIOUS_MIN_MAE = 3.0
LIST_AT_MOST = 15
#: a model left out for more variables than this is reported with their number only
LIST_VARIABLES = 3


@dataclass(frozen=True)
class Finding:
    level: str  # "error" or "warning"
    message: str


def _scan(data_dir: Path, kind: str, first: date, last: date) -> pl.LazyFrame | None:
    return partitions.scan_months(data_dir / kind, first, last)


def _listing(ids: list[str]) -> str:
    shown = ", ".join(ids[:LIST_AT_MOST])
    return shown + (f" and {len(ids) - LIST_AT_MOST} more" if len(ids) > LIST_AT_MOST else "")


EXPECTED_DAYS = 30  # a station is expected to report if it did in the last 30 days


def as_of_lag(meta: dict) -> Finding | None:
    """An error when ``meta["as_of"]`` (last scored day) is more than
    ``MAX_AS_OF_LAG_DAYS`` days before ``meta["generated"]``."""
    as_of = date.fromisoformat(meta["as_of"])
    generated = datetime.fromisoformat(meta["generated"]).date()
    lag = (generated - as_of).days
    if lag <= MAX_AS_OF_LAG_DAYS:
        return None
    return Finding(
        "error",
        f"published scores are as of {as_of}, {lag} days before they were generated "
        f"({generated}); more than {MAX_AS_OF_LAG_DAYS} days means the latest days have "
        "no forecasts or no observations",
    )


def short_records(meta: dict, window: str = "90d") -> Finding | None:
    """A warning listing the models ``meta["short_record"]`` says the ``window``
    comparison leaves out (no ranking, no combination weight) for too short a record."""
    left_out = (meta.get("short_record") or {}).get(window) or {}
    if not left_out:
        return None
    every = set(meta.get("variables") or []) - {"precipitation"}
    listed = []
    for model, facts in sorted(left_out.items()):
        variables = facts.get("variables") or []
        if not variables or set(variables) >= every:
            where = ""
        elif len(variables) > LIST_VARIABLES:
            where = f"{len(variables)} variables: "
        else:
            where = f"{', '.join(variables)}: "
        listed.append(f"{model} ({where}{facts['days']} days, {facts['coverage']:.0%})")
    need = meta.get("min_coverage")
    share = f"{need:.0%} of the days" if isinstance(need, int | float) else "enough days"
    return Finding(
        "warning",
        f"{len(listed)} models left out of the {window} comparison and weights for too "
        f"short a record (need {share}): {_listing(listed)}",
    )


def check(
    data_dir: Path,
    station_ids: list[str] | None = None,
    now: datetime | None = None,
    meta_path: Path | None = None,
) -> list[Finding]:
    """Run all checks; ``station_ids`` defaults to the stations that reported recently;
    ``meta_path``: the published ``meta.json`` whose ``as_of`` is checked."""
    now = now or datetime.now(UTC)
    today = now.date()
    findings: list[Finding] = []
    if meta_path is not None:
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if (late := as_of_lag(meta)) is not None:
                findings.append(late)
            if (short := short_records(meta)) is not None:
                findings.append(short)
        else:
            findings.append(Finding("warning", f"{meta_path} not found; as_of not checked"))
    first = today - timedelta(days=100)

    obs = _scan(data_dir, "obs", first, today)
    if obs is None:
        return [*findings, Finding("error", "no observations in the last 100 days")]
    if station_ids is None:
        expected_since = now - timedelta(days=EXPECTED_DAYS)
        station_ids = (
            obs.filter(pl.col("time") >= expected_since)
            .select("station_id")
            .unique()
            .collect()["station_id"]
            .to_list()
        )
    newest_obs = obs.select(pl.col("time").max()).collect().item()
    if newest_obs is None or now - newest_obs > timedelta(hours=MAX_OBS_AGE_H):
        findings.append(
            Finding("error", f"newest observation is {newest_obs}, older than {MAX_OBS_AGE_H} h")
        )
    since = now - timedelta(days=RECENT_DAYS)
    reporting = set(
        obs.filter(pl.col("time") >= since).select("station_id").unique().collect()["station_id"]
    )
    missing = sorted(set(station_ids) - reporting)
    share = 1 - len(missing) / len(station_ids) if station_ids else 1.0
    if share < MIN_REPORTING:
        findings.append(
            Finding(
                "error",
                f"only {share:.0%} of {len(station_ids)} stations reported in the last "
                f"{RECENT_DAYS} days (need {MIN_REPORTING:.0%})",
            )
        )
    if missing:
        findings.append(
            Finding("warning", f"{len(missing)} stations without recent data: {_listing(missing)}")
        )

    for kind, column in (("fc", "time"), ("scores", "date")):
        scan = _scan(data_dir, kind, first, today)
        newest = scan.select(pl.col(column).max()).collect().item() if scan is not None else None
        newest_day = newest.date() if isinstance(newest, datetime) else newest
        if newest_day is None or (today - newest_day).days > MAX_FC_AGE_DAYS:
            findings.append(
                Finding(
                    "error", f"newest {kind} is {newest_day}, older than {MAX_FC_AGE_DAYS} days"
                )
            )

    scores = _scan(data_dir, "scores", first, today)
    if scores is not None:
        per_station = (
            scores.filter(
                pl.col("variable") == "temperature_2m", pl.col("date") >= today - timedelta(90)
            )
            .group_by("station_id")
            .agg((metrics.total("sum_abs_err") / metrics.total("n")).alias("mae"))
            .collect()
        )
        if per_station.height >= 5:
            median = per_station["mae"].median()
            limit = max(SUSPICIOUS_FACTOR * median, SUSPICIOUS_MIN_MAE)
            odd = per_station.filter(pl.col("mae") > limit).sort("mae", descending=True)
            if odd.height:
                listed = [f"{s} ({m:.1f} °C)" for s, m in odd.rows()]
                findings.append(
                    Finding(
                        "warning",
                        f"{odd.height} stations with a temperature MAE above {limit:.1f} °C "
                        f"(network median {median:.1f} °C), check sensor or metadata: "
                        f"{_listing(listed)}",
                    )
                )
    return findings


def report(findings: list[Finding]) -> str:
    if not findings:
        return "All data quality checks passed."
    return "\n".join(f"{f.level.upper()}: {f.message}" for f in findings)
