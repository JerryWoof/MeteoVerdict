from datetime import UTC, date, datetime

import polars as pl
import pytest

from meteoverdict import report

NAMES = {
    "a": "Model A",
    "b": "Model B",
    "c": "Model C",
    "d": "Model D",
    "e": "Model E",
    "f": "Model F",
}


def row(region, variable, model, rank, mae, tied=False, enough=True, level="kraj"):
    return {
        "level": level,
        "region": region,
        "region_name": region,
        "window": "90d",
        "from": date(2026, 7, 3),
        "to": date(2026, 9, 30),
        "variable": variable,
        "lead_day": 1,
        "model": model,
        "mae": mae,
        "rank": rank,
        "tied_with_best": tied,
        "enough_stations": enough,
    }


def table(rows):
    return pl.DataFrame(rows)


def line_of(block, name):
    return next(line for line in block.splitlines() if line.startswith(f"| {name} "))


def test_clear_winner_shows_its_mae():
    block = report.leaderboard(
        table(
            [
                row("cz", "temperature_2m", "a", 1, 1.234, level="cz"),
                row("cz", "temperature_2m", "b", 2, 1.6, level="cz"),
            ]
        ),
        NAMES,
    )
    assert "| **Česko** | **Model A** (1.23) | no data | no data |" in block
    assert "2026-07-03 to 2026-09-30" in block


def test_ties_are_listed_and_shortened():
    rows = [row("CZ064", "wind_speed_10m", "a", 1, 1.0)] + [
        row("CZ064", "wind_speed_10m", m, i + 2, 1.1, tied=True) for i, m in enumerate("bcde")
    ]
    block = report.leaderboard(table(rows), NAMES)
    assert "Model A ≈ Model B ≈ Model C ≈ Model D ≈ +1" in line_of(block, "Jihomoravský kraj")


def test_too_few_stations_and_every_kraj_in_code_order():
    block = report.leaderboard(
        table([row("CZ020", "temperature_2m", "a", 1, 1.0, enough=False)]), NAMES
    )
    assert "too few stations" in line_of(block, "Středočeský kraj")
    names = [line.split("|")[1].strip() for line in block.splitlines() if line.startswith("| ")][1:]
    assert names[:3] == ["**Česko**", "Hlavní město Praha", "Středočeský kraj"]
    assert len(names) == 15  # Czechia and the 14 kraje
    assert "[Open-Meteo.com](https://open-meteo.com/)" in block  # required next to the data


def test_no_scores_yet():
    empty = table([row("cz", "temperature_2m", "a", 1, 1.0)]).filter(pl.lit(False))
    assert "No scores yet" in report.leaderboard(empty, NAMES)


def test_replace_block_keeps_the_rest():
    readme = f"intro\n{report.START}\nold\n{report.END}\noutro\n"
    assert (
        report.replace_block(readme, "new") == f"intro\n{report.START}\nnew\n{report.END}\noutro\n"
    )
    with pytest.raises(ValueError):
        report.replace_block("no markers", "new")
    with pytest.raises(ValueError):
        report.replace_block(f"{report.END}{report.START}", "new")


def test_badge_turns_orange_when_scores_are_stale():
    now = datetime(2026, 10, 12, 5, 30, tzinfo=UTC)
    fresh = report.badge(now, date(2026, 10, 1))
    assert fresh == {
        "schemaVersion": 1,
        "label": "last updated",
        "message": "2026-10-12, scores to 2026-10-01",
        "color": "brightgreen",
    }
    assert report.badge(now, date(2026, 9, 1))["color"] == "orange"
    assert report.badge(now, None)["message"] == "2026-10-12"


def test_leaderboard_says_when_it_was_updated():
    block = report.leaderboard(
        table([row("cz", "temperature_2m", "a", 1, 1.0, level="cz")]),
        NAMES,
        updated=datetime(2026, 10, 12, 5, 30, tzinfo=UTC),
    )
    assert "_Last updated 2026-10-12 05:30 UTC; scores up to 2026-09-30._" in block


def test_the_blend_is_summarised_below_the_table_not_ranked_in_it():
    def blend(region, diff, high, level="kraj"):
        r = row(region, "temperature_2m", "blend", None, 1.0, level=level)
        return {**r, "diff_to_best": diff, "diff_ci_high": high}

    rows = [
        {**row("cz", "temperature_2m", "a", 1, 1.2, level="cz"), "diff_to_best": 0.0},
        blend("cz", -0.2, -0.1, level="cz"),
        {**row("CZ064", "temperature_2m", "a", 1, 1.0), "diff_to_best": 0.0},
        blend("CZ064", -0.05, 0.02),
        blend("CZ010", 0.1, 0.2),
    ]
    block = report.leaderboard(table(rows), NAMES)
    assert "| **Česko** | **Model A** (1.20) |" in block
    assert (
        "The mean of all models beats the best single model in: temperature (2 m) 2 of 3 "
        "(1 significantly)." in block
    )


def test_no_blend_line_without_blend_rows():
    block = report.leaderboard(table([row("cz", "temperature_2m", "a", 1, 1.2, level="cz")]), NAMES)
    assert "mean of all models" not in block
