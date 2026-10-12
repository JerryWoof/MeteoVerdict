import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import polars as pl
import pytest

from meteoverdict import observations as obs
from meteoverdict.chmi import parse_collection

FIXTURES = Path(__file__).parent / "fixtures" / "chmi"
LIBUS = "0-20000-0-11520"
SEPTEMBER = json.loads((FIXTURES / f"10m-{LIBUS}-202609.json").read_text(encoding="utf-8"))
OCT_10 = json.loads((FIXTURES / f"10m-{LIBUS}-20261010.json").read_text(encoding="utf-8"))


def at(h: int, day: date, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, h, minute, tzinfo=UTC)


def values(table: pl.DataFrame, variable: str) -> dict[datetime, float]:
    rows = table.filter(pl.col("variable") == variable).select("time", "value").rows()
    return {t: round(v, 2) for t, v in rows}


def server(files: dict[str, dict]) -> tuple[httpx.Client, list[str]]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        for suffix, body in files.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, json=body)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_urls():
    assert obs.month_urls(LIBUS, 2025, 3) == [
        ("recent", f"{obs.BASE_URL}/recent/data/10min/03/10m-{LIBUS}-202503.json"),
        ("historical", f"{obs.BASE_URL}/historical/data/10min/2025/10m-{LIBUS}-202503.json"),
    ]
    assert obs.day_url(LIBUS, date(2026, 10, 10)).endswith(
        "/now/data/10m-0-20000-0-11520-20261010.json"
    )


def test_normalize_keeps_our_elements_and_good_quality():
    raw = parse_collection(SEPTEMBER)
    rows = obs.normalize(raw, "recent")
    assert set(rows["variable"]) == {"temperature_2m", "wind_speed_10m", "precipitation"}
    assert rows.schema == pl.Schema(obs.SCHEMA)
    # the real file has a missing Casmax ("" with QUALITY 4); Casmax is not ours anyway
    assert "" in raw["VAL"].cast(pl.String).to_list()
    # estimated values (QUALITY 3) are kept
    assert 3 in rows["quality"].to_list()


def test_normalize_drops_missing_and_suspect_values():
    # rows shaped like the real ones; "" with QUALITY 4 is how ČHMÚ marks missing values
    raw = pl.DataFrame(
        [
            [LIBUS, "T", "2026-09-15T20:40:00Z", "", "", 4.0],
            [LIBUS, "T", "2026-09-15T20:50:00Z", "12.5", "", 1.0],
            [LIBUS, "T", "2026-09-15T21:00:00Z", "12.4", "", 0.0],
        ],
        schema=["STATION", "ELEMENT", "DT", "VAL", "FLAG", "QUALITY"],
        orient="row",
    )
    rows = obs.normalize(raw, "recent")
    assert rows["value"].to_list() == pytest.approx([12.4])


def test_hourly_values_from_the_real_september_file():
    day = date(2026, 9, 5)
    hourly = obs.to_hourly(obs.normalize(parse_collection(SEPTEMBER), "recent"))
    rain = values(hourly, "precipitation")
    # ČHMÚ's own hourly SRA1H for these hours: 0.4, 0.1, 1.6, 0.5 mm
    assert [rain[at(h, day)] for h in (2, 3, 4, 5)] == [0.4, 0.1, 1.6, 0.5]
    # 2026-09-04 23:00 has only one 10-minute slot in the fixture: no hourly sum
    assert at(23, date(2026, 9, 4)) not in rain
    temperature = values(hourly, "temperature_2m")
    assert set(temperature) == {at(h, day) for h in range(6)} | {
        at(23, date(2026, 9, 4)),
        at(12, date(2026, 9, 17)),
        at(13, date(2026, 9, 17)),
    }
    assert all(t.minute == 0 for t in values(hourly, "wind_speed_10m"))


def test_fetch_uses_monthly_files_and_falls_back_to_now():
    client, seen = server({f"-{LIBUS}-202609.json": SEPTEMBER, f"-{LIBUS}-20261010.json": OCT_10})
    table = obs.fetch_observations(client, [LIBUS], date(2026, 9, 5), date(2026, 9, 5))
    assert set(table["source"]) == {"recent"}
    assert table["time"].min() == at(0, date(2026, 9, 5))  # day before read, not returned
    assert table["time"].max() <= at(23, date(2026, 9, 5))

    client, seen = server({f"-{LIBUS}-20261010.json": OCT_10})
    table = obs.fetch_observations(
        client, [LIBUS], date(2026, 10, 10), date(2026, 10, 10), today=date(2026, 10, 12)
    )
    assert set(table["source"]) == {"now"}
    assert values(table, "precipitation").keys() == {
        at(4, date(2026, 10, 10)),
        at(5, date(2026, 10, 10)),
    }
    # recent and historical monthly files were tried first, then the day files
    assert [p.rsplit("/", 1)[1] for p in seen if p.endswith("-202610.json")] == [
        f"10m-{LIBUS}-202610.json",
        f"10m-{LIBUS}-202610.json",
    ]
    assert any(p.endswith("20261009.json") for p in seen)


def test_partly_published_month_continues_with_now():
    client, seen = server({f"-{LIBUS}-202609.json": SEPTEMBER})
    obs.fetch_observations(
        client, [LIBUS], date(2026, 9, 17), date(2026, 9, 18), today=date(2026, 9, 19)
    )
    # the September file ends on 2026-09-17, so only 18 September is asked for in now/
    assert [p for p in seen if "/now/" in p] == [
        f"/meteorology/climate/now/data/10m-{LIBUS}-20260918.json"
    ]


def test_server_errors_are_not_swallowed():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(httpx.HTTPStatusError):
        obs.fetch_observations(client, [LIBUS], date(2026, 9, 5), date(2026, 9, 5))


def test_automatic_station_ids():
    meta2 = pl.DataFrame(
        {
            "OBS_TYPE": ["10M", "10M", "1H", "1H"],
            "WSI": ["a", "b", "b", "c"],
            "EG_EL_ABBREVIATION": ["T", "D", "SRA1H", "SRA1H"],
        }
    )
    assert obs.automatic_station_ids(meta2) == {"a"}  # b only has wind direction


def test_write_monthly_replaces_matching_rows(tmp_path):
    first = obs.to_hourly(obs.normalize(parse_collection(SEPTEMBER), "now"))
    obs.write_monthly(first, tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {"2026-09.parquet"}
    newer = first.head(3).with_columns(
        pl.lit("recent").alias("source"), pl.lit(99.0, pl.Float32).alias("value")
    )
    obs.write_monthly(newer, tmp_path)
    merged = pl.read_parquet(tmp_path / "2026-09.parquet")
    assert merged.height == first.height
    assert merged.filter(pl.col("source") == "recent")["value"].to_list() == [99.0] * 3


def test_old_days_are_not_looked_for_in_now():
    client, seen = server({})
    table = obs.fetch_observations(
        client, ["closed"], date(2024, 3, 1), date(2024, 3, 31), today=date(2026, 10, 12)
    )
    assert table.height == 0
    assert not [p for p in seen if "/now/" in p]
    assert len(seen) == 4  # Feb (day before start) and March, recent + historical each


def test_no_stations_gives_an_empty_table():
    client, seen = server({})
    table = obs.fetch_observations(client, [], date(2026, 9, 5), date(2026, 9, 5))
    assert table.height == 0 and table.schema == pl.Schema(obs.SCHEMA)
    assert seen == []
