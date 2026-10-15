import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from meteoverdict import chmi_archive as ca
from meteoverdict import station_pages as sp

LIBUS = "0-20000-0-11520"
UTC0 = datetime(2026, 10, 14, tzinfo=UTC)


def rows(resolution: str, items: list[tuple]) -> pl.DataFrame:
    """(time, element, vtype, func, value) → archive rows of Libuš."""
    return pl.DataFrame(
        [
            {
                "station": LIBUS,
                "resolution": resolution,
                "time": t,
                "element": e,
                "vtype": v,
                "func": f,
                "value": x,
                "flag": None,
                "flag2": None,
                "quality": 0,
            }
            for t, e, v, f, x in items
        ],
        schema=ca.SCHEMA,
    )


def test_pick_series_prefers_mean_then_sum_then_max():
    table = rows(
        "monthly",
        [
            (UTC0, "T", "AVG", "AVG", 1.0),
            (UTC0, "T", "06:00", "AVG", 0.0),
            (UTC0, "T", "AVG", "MAX", 5.0),
            (UTC0, "SRA", "06:00", "SUM", 30.0),
            (UTC0, "SRA", "06:00", "GE(10)", 1.0),
            (UTC0, "Fmax", "00:00", "MAX", 20.0),
            (UTC0, "Fmax", "00:00", "GE(10)", 3.0),
            (UTC0, "TMInoc", "06:00", "GE(20)", 0.0),
        ],
    )
    assert sp.pick_series(table) == {
        "T": ("AVG", "AVG"),
        "SRA": ("06:00", "SUM"),
        "Fmax": ("00:00", "MAX"),
        "TMInoc": ("06:00", "GE(20)"),
    }
    daily = rows("daily", [(UTC0, "T", "06:00", None, 1.0), (UTC0, "T", "AVG", None, 2.0)])
    assert sp.pick_series(daily) == {"T": ("AVG", None)}


def test_grid_fills_gaps_and_rounds():
    table = rows(
        "10min",
        [
            (UTC0, "T", None, None, 9.04),
            (UTC0 + timedelta(minutes=20), "T", None, None, 10.0),
            (UTC0, "X", None, None, None),
        ],
    ).filter(pl.col("value").is_not_null())
    out = sp.grid(table, UTC0, UTC0 + timedelta(minutes=20), "10m")
    assert out == {"start": "2026-10-14T00:00:00Z", "step": "10min", "values": {"T": [9, None, 10]}}
    assert sp._round(1.26) == 1.3
    assert sp._round(float("nan")) is None


def test_views_cover_their_periods():
    ten = [
        (UTC0 - timedelta(days=d, minutes=10 * i), "T", None, None, float(i))
        for d in range(5)
        for i in range(0, 144, 3)
    ]
    hourly = [
        (UTC0 - timedelta(days=40) + timedelta(hours=h), "SRA1H", None, None, 0.1)
        for h in range(0, 24 * 40, 5)
    ]
    fine = pl.concat(
        [
            rows("10min", [*ten, (UTC0, "SRA10M", None, None, 0.2)]),
            rows("1hour", hourly),
        ]
    )
    view = sp.ten_minute_view(fine)
    first = datetime.fromisoformat(view["start"])
    assert UTC0 - first == timedelta(days=3) - timedelta(minutes=10)
    assert len(view["values"]["T"]) == 3 * 144
    assert "SRA10M" in view["values"]
    hourly_view = sp.hourly_view(fine)
    assert "SRA10M" not in hourly_view["values"]  # its hourly total is SRA1H
    assert set(hourly_view["values"]) == {"T", "SRA1H"}
    assert len(hourly_view["values"]["T"]) == 30 * 24
    assert sp.ten_minute_view(fine.clear()) is None
    assert sp.hourly_view(fine.clear()) is None


def test_daily_and_monthly_views():
    days = [
        (datetime(2022, 12, 31, 6, tzinfo=UTC), "SRA", "06:00", None, 3.0),
        (datetime(2023, 1, 1, tzinfo=UTC), "T", "AVG", None, -1.0),
        (datetime(2023, 1, 1, 6, tzinfo=UTC), "T", "06:00", None, -3.0),
        (datetime(2023, 1, 1, 6, tzinfo=UTC), "SRA", "06:00", None, 1.5),
        (datetime(2023, 1, 3, tzinfo=UTC), "T", "AVG", None, 0.5),
    ]
    view = sp.daily_view(rows("daily", days), date(2026, 10, 15))
    assert view["start"] == "2023-01-01T00:00:00Z"
    assert view["values"] == {"SRA": [1.5, None, None], "T": [-1, None, 0.5]}
    assert view["how"] == {"SRA": "06:00", "T": "AVG"}
    months = [
        (datetime(1961, 11, 1, tzinfo=UTC), "T", "AVG", "AVG", 3.1),
        (datetime(1962, 1, 1, tzinfo=UTC), "T", "AVG", "AVG", -2.2),
    ]
    monthly = sp.monthly_view(rows("monthly", months))
    assert monthly["step"] == "1mo"
    assert monthly["values"]["T"] == [3.1, None, -2.2]
    assert monthly["how"] == {"T": "AVG AVG"}


def test_element_table_from_meta2():
    meta2 = pl.DataFrame(
        {
            "OBS_TYPE": ["DLY", "DLY", "10M", "10M", "DLY"],
            "WSI": [LIBUS] * 4 + ["other"],
            "BEGIN_DATE": [
                "1971-01-01T00:00:00Z",
                "1990-01-01T00:00:00Z",
                "2004-01-01T00:00:00Z",
                None,
                "x",
            ],
            "END_DATE": [
                "1989-12-31T23:59:00Z",
                "2010-05-31T23:59:00Z",
                "3999-12-31T23:59:00Z",
                None,
                "x",
            ],
            "EG_EL_ABBREVIATION": ["SNO", "SNO", "T", "T", "T"],
            "NAME": ["Nový sníh", "Nový sníh", "Teplota", "Teplota", "x"],
            "UN_DESCRIPTION": ["cm", "cm", "°C", "°C", "x"],
            "HEIGHT": ["0", "0", "2", "2", "x"],
        }
    )
    table = sp.element_table(meta2, LIBUS)
    assert table["SNO"] == {
        "name": "Nový sníh",
        "name_en": None,
        "unit": "cm",
        "height": 0.0,
        "types": ["DLY"],
        "since": "1971-01-01",
        "until": "2010-05-31",
    }
    assert table["T"]["until"] is None  # still measured
    assert table["T"]["types"] == ["10M"]
    assert table["T"]["since"] == "2004-01-01"


def write_archive(root: Path, today: date) -> None:
    """A tiny archive in the release layout: history, a recent month, a captured day."""
    history = pl.concat(
        [
            rows("daily", [(datetime(2025, 12, 31, tzinfo=UTC), "T", "AVG", None, 1.0)]),
            rows("monthly", [(datetime(2025, 12, 1, tzinfo=UTC), "T", "AVG", "AVG", 2.0)]),
        ]
    )
    ca.write(history, root / "chmi-history-0" / f"chmi-history-{LIBUS}.parquet")
    recent = rows(
        "daily",
        [
            (datetime(2025, 12, 31, tzinfo=UTC), "T", "AVG", None, 99.0),  # in history already
            (datetime(2026, 1, 1, tzinfo=UTC), "T", "AVG", None, 3.0),
        ],
    )
    ca.write(recent, root / "chmi-2026" / "chmi-daily-2026-01.parquet")
    day = today - timedelta(days=1)
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    fine = rows(
        "10min", [(start + timedelta(minutes=10 * i), "T", None, None, 5.0) for i in range(144)]
    )
    ca.write(fine, root / "chmi-now-2026" / f"chmi-now-{day}.parquet")


def test_build_station_files(tmp_path: Path):
    today = date(2026, 10, 15)
    write_archive(tmp_path / "archive", today)
    stations = pl.DataFrame(
        {
            "id": [LIBUS, "0-20000-0-99999"],
            "gh_id": ["P1PLIB01", "X"],
            "name": ["Praha, Libuš", "Nowhere"],
            "lat": [50.0, 49.0],
            "lon": [14.4, 15.0],
            "elevation": [302.0, 500.0],
            "okres": ["Praha", "X"],
            "kraj": ["Praha", "X"],
            "active": [True, False],
        }
    )
    meta2 = pl.DataFrame(
        {
            "OBS_TYPE": ["10M"],
            "WSI": [LIBUS],
            "EG_EL_ABBREVIATION": ["T"],
            "NAME": ["Teplota"],
            "UN_DESCRIPTION": ["°C"],
            "HEIGHT": ["2"],
        }
    )
    written = sp.build(
        tmp_path / "archive", stations, meta2, tmp_path / "out", today, log=lambda _: None
    )
    assert [p.name for p in written] == [f"{LIBUS}.json"]  # no data for the other one
    doc = json.loads((tmp_path / "out" / f"{LIBUS}.json").read_text())
    assert doc["station"]["name"] == "Praha, Libuš"
    assert set(doc["series"]) == {"10min", "1hour", "daily", "monthly"}
    assert doc["series"]["daily"]["values"]["T"] == [1, 3]  # history, then recent after it
    assert doc["series"]["monthly"]["values"]["T"] == [2]
    assert doc["elements"]["T"]["views"] == ["10min", "1hour", "daily", "monthly"]
    assert doc["elements"]["T"]["unit"] == "°C"
    assert "CC BY 4.0" in doc["source"]
    index = json.loads((tmp_path / "out" / "index.json").read_text())
    assert [s["id"] for s in index["stations"]] == [LIBUS]
    entry = index["stations"][0]
    assert (entry["lat"], entry["lon"], entry["kraj"]) == (50.0, 14.4, "Praha")
    assert "T" in entry["elements"]
    assert entry["network"] == "main"  # a WMO id
    assert doc["station"]["network"] == "main"
    assert not any(code.startswith("C-") for code in entry["elements"])


def test_wanted_assets():
    wanted = sp.wanted_assets([LIBUS], date(2026, 10, 15), [2026])
    assert ("chmi-history-0", f"chmi-history-{LIBUS}.parquet") in wanted
    assert ("chmi-2026", "chmi-10min-2026-09.parquet") in wanted
    assert ("chmi-now-2026", "chmi-now-2026-10-14.parquet") in wanted
    assert ("chmi-2026", "chmi-daily-2026-01.parquet") in wanted
    assert ("chmi-2026", "chmi-10min-2026-08.parquet") not in wanted


def test_phenomena_days_per_year():
    items = [
        (datetime(2001, 5, 1, tzinfo=UTC), "BO", None, None, None),
        (datetime(2001, 5, 1, tzinfo=UTC), "BO", None, None, None),  # same day once
        (datetime(2001, 6, 2, tzinfo=UTC), "BO", None, None, None),
        (datetime(2001, 1, 3, tzinfo=UTC), "SN", None, None, None),
        (datetime(2003, 7, 3, tzinfo=UTC), "KR", None, None, None),
    ]
    view = sp.phenomena_view(rows("phenomena", items))
    assert view["step"] == "1y"
    assert view["start"] == "2001-01-01T00:00:00Z"
    # 2002: nothing reported at all, so unknown; 2003: hail only, so 0 storms
    assert view["values"] == {"BO": [2, None, 0], "KR": [0, None, 1], "SN": [1, None, 0]}
    assert sp.phenomena_view(rows("phenomena", [])) is None


def test_phenomena_names_from_meta2():
    meta2 = pl.DataFrame(
        {
            "OBS_TYPE": ["PHENO"],
            "WSI": [LIBUS],
            "BEGIN_DATE": ["1961-01-01T00:00:00Z"],
            "END_DATE": ["3999-12-31T23:59:00Z"],
            "EG_EL_ABBREVIATION": ['"BO"'],
            "NAME": ['"bouřka/storm"'],
            "UN_DESCRIPTION": ["kód"],
            "HEIGHT": ["6"],
        }
    )
    entry = sp.element_table(meta2, LIBUS)["BO"]
    assert (entry["name"], entry["name_en"]) == ("bouřka", "storm")
