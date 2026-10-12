"""README leaderboard (roadmap 3.1).

The block between ``<!-- LEADERBOARD:START -->`` and ``<!-- LEADERBOARD:END -->`` in
README.md is generated from ``data/aggregates.parquet``: one row per kraj (and Czechia),
the best model per variable at one lead day over one window. Models that are not
significantly worse than the best (``tied_with_best``) are listed with "≈".
"""

from __future__ import annotations

from datetime import date, datetime

import polars as pl

from meteoverdict.regions import load_kraje

START = "<!-- LEADERBOARD:START -->"
END = "<!-- LEADERBOARD:END -->"
COLUMNS = {
    "temperature_2m": "Temperature (2 m)",
    "wind_speed_10m": "Wind (10 m)",
    "precipitation_daily": "Precipitation (daily)",
}
MAX_TIED = 3
WINDOW_TEXT = {"90d": "last 90 days", "season": "this season", "all": "all time"}


def _cell(rows: pl.DataFrame, names: dict[str, str]) -> str:
    if rows.height == 0:
        return "no data"
    if not rows["enough_stations"][0]:
        return "too few stations"
    ranked = rows.filter(pl.col("rank").is_not_null()).sort("rank")
    if ranked.height == 0:
        return "no data"
    best = names.get(ranked["model"][0], ranked["model"][0])
    tied = [names.get(m, m) for m in ranked.filter(pl.col("tied_with_best"))["model"]]
    if not tied:
        return f"**{best}** ({ranked['mae'][0]:.2f})"
    shown = " ≈ ".join([best, *tied[:MAX_TIED]])
    more = f" ≈ +{len(tied) - MAX_TIED}" if len(tied) > MAX_TIED else ""
    return f"{shown}{more}"


#: Scores older than this many days make the badge orange (see quality.MAX_FC_AGE_DAYS).
STALE_DAYS = 21


def badge(updated: datetime, scores_up_to: date | None) -> dict:
    """shields.io endpoint JSON (https://shields.io/badges/endpoint-badge)."""
    stale = scores_up_to is None or (updated.date() - scores_up_to).days > STALE_DAYS
    message = f"{updated:%Y-%m-%d}" + (f", scores to {scores_up_to}" if scores_up_to else "")
    return {
        "schemaVersion": 1,
        "label": "last updated",
        "message": message,
        "color": "orange" if stale else "brightgreen",
    }


def leaderboard(
    aggregates: pl.DataFrame,
    names: dict[str, str],
    window: str = "90d",
    lead_day: int = 1,
    updated: datetime | None = None,
) -> str:
    """Markdown block for the README."""
    part = aggregates.filter(
        pl.col("window") == window,
        pl.col("lead_day") == lead_day,
        pl.col("level").is_in(["cz", "kraj"]),
        pl.col("variable").is_in(list(COLUMNS)),
    )
    if part.height == 0:
        return "_No scores yet: the daily pipeline fills this table._"
    span = part.select(pl.col("from").min(), pl.col("to").max()).row(0)
    # every kraj, in the official order of their codes (Praha first), even without data
    regions = [("cz", "cz", "Česko")] + [("kraj", k.code, k.name) for k in load_kraje()]
    regions.sort(key=lambda r: (r[0] != "cz", r[1]))
    lines = [
        f"Best model per region, forecasts for the next day (D+{lead_day}), "
        f"{WINDOW_TEXT.get(window, window)} ({span[0]} to {span[1]}). Mean absolute error in "
        'brackets (°C, m/s, mm/day); "≈" lists models whose difference from the best is '
        "not significant (95 % bootstrap interval).",
        "",
        "| Region | " + " | ".join(COLUMNS.values()) + " |",
        "|---|" + "---|" * len(COLUMNS),
    ]
    for level, region, name in regions:
        here = part.filter(pl.col("level") == level, pl.col("region") == region)
        cells = [_cell(here.filter(pl.col("variable") == v), names) for v in COLUMNS]
        label = f"**{name}**" if level == "cz" else name
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    if updated is not None:
        lines += ["", f"_Last updated {updated:%Y-%m-%d %H:%M} UTC; scores up to {span[1]}._"]
    lines += [
        "",
        "Forecasts: [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0; UK Met Office data "
        "CC BY-SA 4.0). Observations: [ČHMÚ](https://opendata.chmi.cz/) (CC BY 4.0). "
        "Table: CC BY-SA 4.0.",
    ]
    return "\n".join(lines)


def replace_block(readme: str, block: str) -> str:
    """Put ``block`` between the leaderboard markers, leaving the rest unchanged."""
    if (
        readme.count(START) != 1
        or readme.count(END) != 1
        or readme.index(START) > readme.index(END)
    ):
        raise ValueError("README must contain the leaderboard markers once, in order")
    head, rest = readme.split(START)
    _, tail = rest.split(END)
    return f"{head}{START}\n{block}\n{END}{tail}"
