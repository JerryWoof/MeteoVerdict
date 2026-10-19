import json
from datetime import date

import polars as pl
import pytest

from meteoverdict import monthly

NAMES = {"a": "Model A", "b": "Model B", "blend": "Mean of all models"}


def row(level, region, lead, model, rank, mae, tied=False, clear=False, variable="temperature_2m"):
    return {
        "level": level,
        "region": region,
        "variable": variable,
        "lead_day": lead,
        "model": model,
        "rank": rank,
        "mae": mae,
        "bias": 0.1,
        "stations": 5,
        "days": 30,
        "tied_with_best": tied,
        "clear_winner": clear,
        "diff_to_best": 0.0,
        "diff_ci_low": -0.1,
        "diff_ci_high": 0.1,
        "short_record": False,
        "enough_stations": True,
    }


def test_month_bounds():
    assert monthly.month_bounds("2026-09") == (date(2026, 9, 1), date(2026, 9, 30))
    assert monthly.month_bounds("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))
    assert monthly.month_bounds("2024-02")[1] == date(2024, 2, 29)
    with pytest.raises(ValueError):
        monthly.month_bounds("2026-13")


def test_summarize_ranks_ties_and_wins():
    table = pl.DataFrame(
        [
            row("cz", "CZ", 1, "a", 1, 1.0),
            row("cz", "CZ", 1, "b", 2, 1.1, tied=True),
            row("cz", "CZ", 1, "blend", None, 0.95),
            row("okres", "CZ0201", 1, "a", 1, 1.0, clear=True),
            row("okres", "CZ0201", 1, "b", 2, 1.2),
            row("okres", "CZ0202", 1, "b", 1, 1.0),
            row("okres", "CZ0202", 1, "a", 2, 1.1, tied=True),
        ]
    )
    out = monthly.summarize(table, NAMES)
    lead = out["variables"]["temperature_2m"]["leads"]["1"]
    assert lead["best"] == "a"
    assert lead["tied_with_best"] == ["b"]
    assert not lead["clear_winner"]  # b is tied with a
    assert [m["model"] for m in lead["models"]] == ["a", "b"]  # the mean is kept apart
    assert lead["mean_of_all"]["mae"] == 0.95
    wins = out["wins"]["temperature_2m/1"]
    assert wins["okresy_total"] == 2
    got = {m["model"]: (m["okresy"], m["clear"]) for m in wins["models"]}
    assert got == {"a": (1, 1), "b": (1, 0)}
    json.dumps(out)  # serialisable


def test_write_index(tmp_path):
    for month in ("2026-08", "2026-09"):
        monthly.write({"month": month}, tmp_path)
    assert json.loads((tmp_path / "index.json").read_text())["months"] == ["2026-09", "2026-08"]
