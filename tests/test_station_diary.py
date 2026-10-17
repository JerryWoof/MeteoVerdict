import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from meteoverdict import chmi_archive as ca
from meteoverdict import station_diary as sd

RUZYNE = "0-20000-0-11518"


def at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def daily(items: list[tuple]) -> pl.DataFrame:
    """(day, hour, element, vtype, value[, quality[, flag]]) → daily archive rows."""
    return pl.DataFrame(
        [
            {
                "station": RUZYNE,
                "resolution": "daily",
                "time": at(d, h),
                "element": e,
                "vtype": v,
                "func": None,
                "value": x,
                "flag": rest[1] if len(rest) > 1 else None,
                "flag2": None,
                "quality": rest[0] if rest else 0,
            }
            for d, h, e, v, x, *rest in items
        ],
        schema=ca.SCHEMA,
    )


def phenomena(items: list[tuple[date, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"station": RUZYNE, "resolution": "phenomena", "time": at(d, 0), "element": code}
            for d, code in items
        ],
        schema=ca.SCHEMA,
    )


D1, D2, D3 = date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)


def test_rows_take_chmi_day_records_of_each_element():
    rows = sd.diary_rows(
        daily(
            [
                # the maximum of the climate day ending 21:00 CET (20 UTC), stamped then
                (D1, 20, "TMA", "20:00", 14.4),
                (D1, 20, "TMI", "20:00", 2.1),
                # the observation-time temperatures are not the mean: only AVG is
                (D1, 6, "T", "06:00", 2.6),
                (D1, 0, "T", "AVG", 8.4),
                # precipitation stamped 06 UTC of the day it fell from (until 07 CET next day)
                (D1, 6, "SRA", "06:00", 0.0, 0, "T"),
                (D1, 6, "SCE", "06:00", 0.0),
                (D1, 0, "SSV", "00:00", 8.4),
                (D1, 0, "Fmax", "00:00", 7.4),
                (D1, 6, "H", "06:00", 80.0),  # not a diary element
            ]
        )
    )
    got = {r["field"]: r["value"] for r in rows.iter_rows(named=True)}
    expected = {"tx": 14.4, "tn": 2.1, "t": 8.4, "r": 0.0, "sce": 0.0, "ssv": 8.4, "g": 7.4}
    assert got == {k: pytest.approx(v, abs=1e-4) for k, v in expected.items()}
    assert set(rows["day"].to_list()) == {D1}  # all on the day ČHMÚ gives them


def test_rows_respect_quality():
    rows = sd.diary_rows(
        daily(
            [
                (D1, 6, "SRA", "06:00", 1.0, 0),  # checked
                (D2, 6, "SRA", "06:00", 2.0, 1),  # suspect: dropped
                (D3, 6, "SRA", "06:00", 3.0, 2),  # poor: dropped
                (D1, 20, "TMA", "20:00", 10.0, 3),  # estimated: kept
                (D2, 20, "TMA", "20:00", 11.0, 5),  # not checked yet: kept
                (D3, 20, "TMA", "20:00", None, 4),  # missing
            ]
        )
    )
    assert sorted((r["day"], r["field"]) for r in rows.iter_rows(named=True)) == [
        (D1, "r"),
        (D1, "tx"),
        (D2, "tx"),
    ]


def test_decade_file_with_gaps_flags_and_phenomena():
    rows = sd.diary_rows(
        daily(
            [
                (date(2020, 1, 1), 20, "TMA", "20:00", 5.0),
                (date(2020, 1, 3), 20, "TMA", "20:00", 7.0, 5),
                (date(2020, 1, 2), 6, "SRA", "06:00", 0.0, 0, "T"),
                (date(2020, 1, 2), 6, "SCE", "06:00", 0.0, 0, "P"),
                (date(2019, 12, 31), 20, "TMA", "20:00", 1.0),  # the decade before
            ]
        )
    )
    pheno = sd.phenomena_days(
        phenomena(
            [
                (date(2020, 1, 2), "BO"),
                (date(2020, 1, 2), "DE"),
                (date(2020, 1, 4), "ML"),
                (date(2020, 1, 4), "RO"),  # dew: left out
            ]
        )
    )
    doc = sd.chunk_doc(2020, rows, pheno)
    assert doc["start"] == "2020-01-01"
    assert doc["days"] == 4  # up to the last day with anything (the fog)
    assert doc["values"] == {
        "tx": [5, None, 7, None],
        "r": [None, 0, None, None],
        "sce": [None, 0, None, None],
    }
    assert doc["phenomena"] == {"BO": [1], "DE": [1], "ML": [3]}
    assert doc["flags"] == {"r": {"T": [1]}, "sce": {"P": [1]}}
    assert doc["unchecked"] == [2]
    assert sd.chunk_doc(2030, rows, pheno) is None


def test_write_gzipped_decades(tmp_path: Path):
    rows = daily(
        [
            (date(1999, 12, 31), 6, "SRA", "06:00", 1.2),
            (date(2001, 6, 1), 6, "SRA", "06:00", 0.5),
            (date(2026, 10, 15), 6, "SRA", "06:00", 3.0),
        ]
    )
    folder = tmp_path / "diary" / RUZYNE
    folder.mkdir(parents=True)
    (folder / "1980.json.gz").write_bytes(b"old")  # a decade no longer there
    summary = sd.write(tmp_path, RUZYNE, rows, phenomena([(date(2026, 10, 16), "ML")]))
    assert summary == {
        "first": "1999-12-31",
        "last": "2026-10-15",
        "decade": 10,
        "chunks": [1990, 2000, 2020],  # none for the 2010s
        "fields": ["r"],
        "phenomena": ["ML"],
    }
    assert sorted(p.name for p in folder.iterdir()) == [
        "1990.json.gz",
        "2000.json.gz",
        "2020.json.gz",
    ]
    doc = json.loads(gzip.decompress((folder / "2020.json.gz").read_bytes()))
    assert doc["values"]["r"][-2] == 3  # 2026-10-15
    assert doc["phenomena"] == {"ML": [doc["days"] - 1]}
    # the same data give the same bytes
    before = (folder / "2000.json.gz").read_bytes()
    sd.write(tmp_path, RUZYNE, rows, phenomena([(date(2026, 10, 16), "ML")]))
    assert (folder / "2000.json.gz").read_bytes() == before


def test_no_diary_without_daily_values(tmp_path: Path):
    empty = daily([(D1, 6, "SRA", "06:00", None, 4)])
    assert sd.write(tmp_path, RUZYNE, empty, phenomena([])) is None
    assert not list((tmp_path / "diary" / RUZYNE).glob("*.json.gz"))
