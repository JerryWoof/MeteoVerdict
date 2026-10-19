"""Monthly accuracy report (``mvd monthly-report``): which model forecast Czechia best in
one calendar month, from the same scores, fair sample and tie rule as the web pages.

The month is scored as a window of its own: the scores of its days are aggregated and
ranked with the code of ``aggregate`` and ``ranking`` (same fair station-days, 80 %
coverage rule and day-resampling for ties), so the report says nothing the daily scores
would not. The result is one JSON file per month (``reports/YYYY-MM.json``) plus
``reports/index.json``; ``web/report.html`` draws it, in Czech and English.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from meteoverdict import aggregate, blend, ranking

#: Variables in the report; precipitation is the 06-06 UTC total, which also covers the
#: manual rain gauges (as ``report.COLUMNS``).
VARIABLES = {
    "temperature_2m": "°C",
    "wind_speed_10m": "m/s",
    "precipitation_24h": "mm",
}
LEADS = (1, 2, 3, 4, 5)
#: Lead days whose okres wins are counted (the extremes of what most users read)
WIN_LEADS = (1, 3)
#: Months with fewer scored days than this are not a month's report
MIN_DAYS = 20


def month_bounds(month: str) -> tuple[date, date]:
    """First and last day of ``YYYY-MM``."""
    first = date.fromisoformat(f"{month}-01")
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def _model_rows(part: pl.DataFrame, names: dict[str, str]) -> list[dict]:
    rows = []
    for r in part.sort(pl.col("rank").fill_null(10**6), "mae").iter_rows(named=True):
        rows.append(
            {
                "model": r["model"],
                "name": names.get(r["model"], r["model"]),
                "mae": _rounded(r["mae"]),
                "bias": _rounded(r["bias"]),
                "rank": r["rank"],
                "tied_with_best": bool(r["tied_with_best"]),
                "diff_to_best": _rounded(r["diff_to_best"]),
                "ci_low": _rounded(r["diff_ci_low"]),
                "ci_high": _rounded(r["diff_ci_high"]),
                "short_record": bool(r["short_record"]),
            }
        )
    return rows


def summarize(table: pl.DataFrame, names: dict[str, str]) -> dict:
    """The report's numbers from the aggregated and ranked month (``level`` ``cz`` and
    ``okres`` rows of one window)."""
    cz = table.filter(pl.col("level") == "cz")
    variables: dict[str, dict] = {}
    for variable, unit in VARIABLES.items():
        leads: dict[str, dict] = {}
        for lead in LEADS:
            part = cz.filter(pl.col("variable") == variable, pl.col("lead_day") == lead)
            if part.is_empty():
                continue
            models = _model_rows(part, names)
            ranked = [m for m in models if m["rank"] is not None]
            best = ranked[0] if ranked else None
            mean = next((m for m in models if m["model"] == blend.ID), None)
            first = part.row(0, named=True)
            leads[str(lead)] = {
                "stations": first["stations"],
                "days": first["days"],
                "models": [m for m in models if m["model"] != blend.ID],
                "best": best["model"] if best else None,
                "tied_with_best": [m["model"] for m in ranked if m["tied_with_best"]],
                "clear_winner": bool(best) and not any(m["tied_with_best"] for m in ranked),
                "mean_of_all": mean,
            }
        variables[variable] = {"unit": unit, "leads": leads}
    okresy = table.filter((pl.col("level") == "okres") & pl.col("enough_stations"))
    wins: dict[str, dict] = {}
    for variable in VARIABLES:
        for lead in WIN_LEADS:
            here = okresy.filter(pl.col("variable") == variable, pl.col("lead_day") == lead)
            first_place = here.filter(pl.col("rank") == 1)
            rows = [
                {
                    "model": r["model"],
                    "name": names.get(r["model"], r["model"]),
                    "okresy": r["n"],
                    "clear": r["clear"],
                }
                for r in first_place.group_by("model")
                .agg(pl.len().alias("n"), pl.col("clear_winner").sum().alias("clear"))
                .sort("n", "model", descending=[True, False])
                .iter_rows(named=True)
            ]
            wins[f"{variable}/{lead}"] = {"okresy_total": here["region"].n_unique(), "models": rows}
    return {"variables": variables, "wins": wins}


def build(
    scores: pl.LazyFrame,
    stations: pl.DataFrame,
    month: str,
    names: dict[str, str],
    resamples: int = ranking.RESAMPLES,
    generated: datetime | None = None,
) -> dict:
    """Score, rank and summarise the days of ``month`` (``YYYY-MM``)."""
    first, last = month_bounds(month)
    in_month = scores.filter(pl.col("date").is_between(first, last))
    days = in_month.select(pl.col("date").n_unique()).collect().item()
    if days < MIN_DAYS:
        raise ValueError(f"{month}: only {days} scored days (need {MIN_DAYS}); is the month over?")
    levels = ("okres", "cz")
    table = aggregate.aggregate(
        in_month, stations, last, windows=("all",), levels=levels, corrected=False
    )
    ranks = ranking.rank(
        in_month, stations, last, windows=("all",), resamples=resamples, levels=levels
    )
    table = table.join(ranks, on=[*ranking.GROUP, "model"], how="left")
    sources = in_month.select(pl.col("source").unique()).collect().to_series().to_list()
    span = table.select(pl.col("from").min(), pl.col("to").max()).row(0)
    return {
        "month": month,
        "from": str(span[0]),
        "to": str(span[1]),
        "scored_days": days,
        "generated": (generated or datetime.now(UTC)).isoformat(timespec="seconds"),
        "resamples": resamples,
        "sources": sorted(s for s in sources if s),
        **summarize(table, names),
    }


def write(report: dict, out_dir: Path) -> list[Path]:
    """``YYYY-MM.json`` and the updated ``index.json`` (months newest first)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{report['month']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    months = sorted({p.stem for p in out_dir.glob("????-??.json")}, reverse=True)
    index = out_dir / "index.json"
    index.write_text(json.dumps({"months": months}, indent=1) + "\n", encoding="utf-8")
    return [path, index]
