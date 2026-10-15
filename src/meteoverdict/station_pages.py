"""Per-station JSON for the station page (web/station.html), built from the ČHMÚ archive.

One file per station, ``<out>/<WSI>.json``, plus ``<out>/index.json`` (all stations,
for the search). Each file holds every element the archive has for the station, in
four views (docs/data-sources.md#station-pages):

* ``10min``: the last 3 days of 10-minute values,
* ``1hour``: the last 30 days hourly (hourly elements, and 10-minute elements at the
  full hour),
* ``daily``: the last ``DAILY_YEARS`` years, one value per day and element,
* ``monthly``: the whole history, one value per month and element (ČHMÚ's own monthly
  statistics),
* ``phenomena``: the whole history, days per year with each phenomenon.

A series is ``{"start", "step", "values": {element: [...]}, "how": {element: label}}``:
value ``i`` is at ``start + i * step`` (``step`` "10min", "1h", "1d", "1mo" or "1y"), null
where there is none. Values are rounded to one decimal.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from meteoverdict import chmi_archive

TEN_MINUTE_DAYS = 3
HOURLY_DAYS = 30
DAILY_YEARS = 3
#: 10-minute sums: their hourly counterparts (SRA1H, SSV1H) are hourly elements already
TEN_MINUTE_SUMS = {"SRA10M", "SSV10M"}
#: preferred daily VTYPE / monthly TIMEFUNCTION, then statistic (MDFUNCTION)
VTYPE_ORDER = ("AVG", "SUM")
FUNC_ORDER = ("AVG", "SUM", "MAX", "MIN")
OPEN_END = "3999"  # ČHMÚ's END_DATE of a period that has not ended


def _rank(value: str | None, order: tuple[str, ...]) -> tuple[int, str]:
    value = value or ""
    return (order.index(value) if value in order else len(order), value)


def pick_series(rows: pl.DataFrame) -> dict[str, tuple[str | None, str | None]]:
    """For each element, the (vtype, func) shown: the mean where there is one, else the
    sum, maximum or minimum, else the first in alphabetical order (e.g. day counts)."""
    if rows.height == 0:
        return {}
    combos = rows.select("element", "vtype", "func").unique()
    best: dict[str, tuple[str | None, str | None]] = {}
    for element, vtype, func in combos.iter_rows():
        key = (_rank(func, FUNC_ORDER), _rank(vtype, VTYPE_ORDER))
        old = best.get(element)
        if old is None or key < (_rank(old[1], FUNC_ORDER), _rank(old[0], VTYPE_ORDER)):
            best[element] = (vtype, func)
    return best


def _label(vtype: str | None, func: str | None) -> str:
    return " ".join(p for p in (vtype, func) if p)


def _round(v: float | None) -> float | int | None:
    if v is None or math.isnan(v):
        return None
    r = round(v, 1)
    return int(r) if r == int(r) else r


def grid(rows: pl.DataFrame, start: datetime, end: datetime, every: str) -> dict:
    """Rows (``time``, ``element``, ``value``, unique per time and element) on a regular
    time grid ``start`` … ``end``; elements with no value at all are left out."""
    times = pl.datetime_range(start, end, every, eager=True, time_zone="UTC").alias("time")
    frame = pl.DataFrame(times).with_columns(pl.col("time").dt.cast_time_unit("ms"))
    values: dict[str, list] = {}
    for element in sorted(rows["element"].unique().to_list()) if rows.height else []:
        series = rows.filter(pl.col("element") == element).select("time", "value")
        joined = frame.join(series, on="time", how="left")["value"].to_list()
        if any(v is not None for v in joined):
            values[element] = [_round(v) for v in joined]
    step = {"10m": "10min", "1h": "1h", "1d": "1d", "1mo": "1mo", "1y": "1y"}[every]
    return {"start": start.isoformat().replace("+00:00", "Z"), "step": step, "values": values}


def _floor(t: datetime, minutes: int) -> datetime:
    return t.replace(minute=t.minute - t.minute % minutes, second=0, microsecond=0)


def ten_minute_view(fine: pl.DataFrame) -> dict | None:
    """The last ``TEN_MINUTE_DAYS`` days of 10-minute values up to the newest one."""
    rows = fine.filter(pl.col("resolution") == "10min", pl.col("value").is_not_null())
    if rows.height == 0:
        return None
    end = rows["time"].max()
    start = end - timedelta(days=TEN_MINUTE_DAYS) + timedelta(minutes=10)
    rows = rows.filter(pl.col("time") >= start)
    return grid(rows, start, end, "10m")


def hourly_view(fine: pl.DataFrame) -> dict | None:
    """The last ``HOURLY_DAYS`` days hourly: hourly elements, plus 10-minute elements at
    the full hour (not the 10-minute sums, whose hourly totals are hourly elements)."""
    hourly = fine.filter(pl.col("resolution") == "1hour")
    instant = fine.filter(
        pl.col("resolution") == "10min",
        pl.col("time").dt.minute() == 0,
        ~pl.col("element").is_in(list(TEN_MINUTE_SUMS)),
    )
    rows = pl.concat([hourly, instant]).filter(pl.col("value").is_not_null())
    if rows.height == 0:
        return None
    end = rows["time"].max()
    start = _floor(end - timedelta(days=HOURLY_DAYS) + timedelta(hours=1), 60)
    rows = rows.filter(pl.col("time") >= start).unique(["time", "element"], keep="first")
    return grid(rows, start, end, "1h")


def _chosen(rows: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, str]]:
    """Only the chosen (vtype, func) of each element, and its label."""
    picked = pick_series(rows)
    if not picked:
        return rows.clear(), {}
    choice = pl.DataFrame(
        {
            "element": list(picked),
            "vtype": [v for v, _ in picked.values()],
            "func": [f for _, f in picked.values()],
        },
        schema={"element": pl.String, "vtype": pl.String, "func": pl.String},
    )
    kept = rows.join(choice, on=["element", "vtype", "func"], how="semi", nulls_equal=True)
    return kept, {e: _label(v, f) for e, (v, f) in picked.items() if _label(v, f)}


def daily_view(daily: pl.DataFrame, today: date) -> dict | None:
    """The last ``DAILY_YEARS`` years, one value per day and element (by UTC date)."""
    rows = daily.filter(pl.col("value").is_not_null())
    if rows.height == 0:
        return None
    first = date(today.year - DAILY_YEARS, 1, 1)
    rows = rows.with_columns(pl.col("time").dt.truncate("1d")).filter(
        pl.col("time").dt.date() >= first
    )
    if rows.height == 0:
        return None
    rows, how = _chosen(rows)
    rows = rows.unique(["time", "element"], keep="first")
    start = rows["time"].min()
    out = grid(rows, start, rows["time"].max(), "1d")
    out["how"] = {e: h for e, h in how.items() if e in out["values"]}
    return out


def monthly_view(monthly: pl.DataFrame) -> dict | None:
    """The whole history, one value per month and element."""
    rows = monthly.filter(pl.col("value").is_not_null())
    if rows.height == 0:
        return None
    rows, how = _chosen(rows)
    rows = rows.unique(["time", "element"], keep="first")
    out = grid(rows, rows["time"].min(), rows["time"].max(), "1mo")
    out["how"] = {e: h for e, h in how.items() if e in out["values"]}
    return out


def phenomena_view(phenomena: pl.DataFrame) -> dict | None:
    """Days per year with each phenomenon (thunderstorm, hail, fog, …). A year in which
    the station reported any phenomenon counts 0 for the others; other years are null."""
    if phenomena.height == 0:
        return None
    days = phenomena.select(pl.col("time").dt.truncate("1d"), "element").unique()
    counts = (
        days.with_columns(pl.col("time").dt.truncate("1y"))
        .group_by("time", "element")
        .agg(pl.len().cast(pl.Float64).alias("value"))
    )
    out = grid(counts, counts["time"].min(), counts["time"].max(), "1y")
    years = list(zip(*out["values"].values(), strict=True))
    reported = [any(v is not None for v in year) for year in years]
    for code, values in out["values"].items():
        out["values"][code] = [0 if v is None and reported[i] else v for i, v in enumerate(values)]
    return out


def element_table(meta2: pl.DataFrame, wsi: str) -> dict[str, dict]:
    """Elements of a station from ČHMÚ's ``meta2`` tables: name, unit, sensor height,
    kinds of observation (10M, 1H, DLY, PHENO) and the first and last day.

    ``meta2`` may stack the historical file (one row per period, with BEGIN_DATE and
    END_DATE) and today's file (no dates: an element measured today, so still open).
    """
    rows = meta2.filter(pl.col("WSI") == wsi)
    for column in ("BEGIN_DATE", "END_DATE", "HEIGHT", "UN_DESCRIPTION", "NAME"):
        if column not in rows.columns:
            rows = rows.with_columns(pl.lit(None, pl.String).alias(column))
    rows = rows.with_columns(pl.col("HEIGHT").cast(pl.Float64, strict=False))
    out: dict[str, dict] = {}
    for (code,), group in rows.sort("BEGIN_DATE", descending=True, nulls_last=True).group_by(
        "EG_EL_ABBREVIATION", maintain_order=True
    ):
        newest = group.row(0, named=True)
        code = code.strip('"')  # phenomena codes come quoted: "BO"
        name = (newest["NAME"] or "").strip('"')
        name_en = None
        if "PHENO" in group["OBS_TYPE"].to_list():  # bilingual: "bouřka/storm"
            name, _, name_en = name.partition("/")
        begins = [b for b in group["BEGIN_DATE"].to_list() if b]
        ends = group["END_DATE"].to_list()
        still_open = any(e is None or e.startswith(OPEN_END) for e in ends)
        out[code] = {
            "name": name or None,
            "name_en": name_en or None,
            "unit": (newest["UN_DESCRIPTION"] or "").strip() or None,
            "height": newest["HEIGHT"],
            "types": sorted(set(group["OBS_TYPE"].to_list())),
            "since": min(begins)[:10] if begins else None,
            "until": None if still_open or not ends else max(ends)[:10],
        }
    return out


def station_doc(
    info: dict,
    elements: dict[str, dict],
    fine: pl.DataFrame,
    daily: pl.DataFrame,
    monthly: pl.DataFrame,
    today: date,
    generated: datetime,
    phenomena: pl.DataFrame | None = None,
) -> dict:
    """The JSON document of one station."""
    series = {
        "10min": ten_minute_view(fine),
        "1hour": hourly_view(fine),
        "daily": daily_view(daily, today),
        "monthly": monthly_view(monthly),
        "phenomena": phenomena_view(phenomena) if phenomena is not None else None,
    }
    series = {k: v for k, v in series.items() if v}
    present = {e for s in series.values() for e in s["values"]}
    for code in present - set(elements):
        elements[code] = {"name": None, "name_en": None, "unit": None, "height": None, "types": []}
    for code, entry in elements.items():
        entry["views"] = [k for k, s in series.items() if code in s["values"]]
    return {
        "generated": generated.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "station": info,
        "elements": dict(sorted(elements.items())),
        "series": series,
        "source": "ČHMÚ, opendata.chmi.cz, CC BY 4.0",
    }


# --- reading the archive ------------------------------------------------------------------
def _scan(root: Path, pattern: str) -> pl.LazyFrame | None:
    files = sorted(root.glob(f"*/{pattern}"))
    return pl.scan_parquet(files) if files else None


def _months_between(first: date, last: date) -> list[tuple[int, int]]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def read_fine(root: Path, today: date, stations: list[str]) -> pl.DataFrame:
    """10-minute and hourly rows of the last ``HOURLY_DAYS`` + 1 days: checked month
    files first, then the captured days (``chmi-now-…``) for what they lack."""
    first = today - timedelta(days=HOURLY_DAYS + 1)
    since = datetime.combine(first, datetime.min.time(), UTC)
    all_ten_minutes = since + timedelta(days=HOURLY_DAYS - TEN_MINUTE_DAYS)
    keep = (
        pl.col("station").is_in(stations)
        & (pl.col("time") >= since)
        & (
            (pl.col("resolution") == "1hour")
            | (pl.col("time") >= all_ten_minutes)
            | (pl.col("time").dt.minute() == 0)
        )
    )
    parts = []
    for year, month in _months_between(first, today):
        for res in chmi_archive.MONTH_RESOLUTIONS:
            tag, name = chmi_archive.month_asset(res, year, month)
            if (root / tag / name).exists():
                parts.append(pl.scan_parquet(root / tag / name).filter(keep))
    days = [first + timedelta(days=i) for i in range((today - first).days + 1)]
    for day in days:
        tag, name = chmi_archive.day_asset(day)
        if (root / tag / name).exists():
            parts.append(pl.scan_parquet(root / tag / name).filter(keep))
    if not parts:
        return pl.DataFrame(schema=chmi_archive.SCHEMA)
    return (
        pl.concat(parts)
        .unique(["station", "resolution", "time", "element"], keep="first", maintain_order=True)
        .collect()
    )


def build(
    root: Path,
    stations: pl.DataFrame,
    meta2: pl.DataFrame,
    out: Path,
    today: date | None = None,
    log: Callable[[str], None] = print,
) -> list[Path]:
    """Write ``<out>/<WSI>.json`` for every station in ``stations`` with any data, and
    ``<out>/index.json``."""
    today = today or datetime.now(UTC).date()
    generated = datetime.now(UTC)
    out.mkdir(parents=True, exist_ok=True)
    ids = stations["id"].to_list()
    fine = read_fine(root, today, ids)
    fine_by = fine.partition_by("station", as_dict=True) if fine.height else {}
    recent_daily = _recent(root, "daily")
    recent_monthly = _recent(root, "monthly")
    recent_phenomena = _recent(root, "phenomena")
    written, index = [], []
    for info in stations.sort("name").iter_rows(named=True):
        wsi = info["id"]
        daily = _with_recent(root, "daily", wsi, recent_daily)
        monthly = _with_recent(root, "monthly", wsi, recent_monthly)
        phenomena = _with_recent(root, "phenomena", wsi, recent_phenomena)
        station_fine = fine_by.get((wsi,), fine.clear())
        if not (daily.height or monthly.height or station_fine.height or phenomena.height):
            continue
        station = {
            k: info.get(k)
            for k in ("id", "gh_id", "name", "lat", "lon", "elevation", "okres", "kraj", "active")
        }
        doc = station_doc(
            station,
            element_table(meta2, wsi),
            station_fine,
            daily,
            monthly,
            today,
            generated,
            phenomena,
        )
        path = out / f"{wsi}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
        written.append(path)
        index.append(index_entry(info, doc))
    (out / "index.json").write_text(
        json.dumps({"generated": doc_time(generated), "stations": index}, ensure_ascii=False),
        "utf-8",
    )
    total = sum(p.stat().st_size for p in written)
    log(f"wrote {len(written)} station files, {total / 1e6:.1f} MB")
    return written


def index_entry(info: dict, doc: dict) -> dict:
    """A station in ``index.json``, for the search and the station map: where it is, its
    views, and the elements it has values of (not the ceilometer's or phenomena, which
    the map does not filter by)."""
    elements = [
        code
        for code, entry in doc["elements"].items()
        if entry.get("views") and not code.startswith("C-") and "PHENO" not in entry["types"]
    ]
    return {
        "id": info["id"],
        "name": info.get("name"),
        "okres": info.get("okres"),
        "kraj": info.get("kraj"),
        "lat": info.get("lat"),
        "lon": info.get("lon"),
        "elevation": info.get("elevation"),
        "active": info.get("active"),
        "views": list(doc["series"]),
        "elements": elements,
    }


def doc_time(t: datetime) -> str:
    return t.isoformat(timespec="seconds").replace("+00:00", "Z")


def _recent(root: Path, resolution: str) -> pl.DataFrame:
    scan = _scan(root, f"chmi-{resolution}-*.parquet")
    return scan.collect() if scan is not None else pl.DataFrame(schema=chmi_archive.SCHEMA)


def _with_recent(root: Path, resolution: str, wsi: str, recent: pl.DataFrame) -> pl.DataFrame:
    """History rows of the station plus recent month rows after the history ends."""
    tag, name = chmi_archive.history_asset(wsi)
    parts = []
    end = None
    if (root / tag / name).exists():
        history = pl.read_parquet(root / tag / name).filter(pl.col("resolution") == resolution)
        parts.append(history)
        end = history["time"].max() if history.height else None
    late = recent.filter(pl.col("station") == wsi)
    if end is not None:
        late = late.filter(pl.col("time") > end)
    parts.append(late)
    return pl.concat(parts)


def wanted_assets(
    station_ids: list[str], today: date, recent_years: list[int]
) -> list[tuple[str, str]]:
    """Archive files the station pages read: each station's history, the 10-minute and
    hourly months and captured days of the last ``HOURLY_DAYS`` + 1 days, and the
    daily and monthly month files of ``recent_years`` (years not in the history yet)."""
    first = today - timedelta(days=HOURLY_DAYS + 1)
    wanted = [chmi_archive.history_asset(wsi) for wsi in station_ids]
    for year, month in _months_between(first, today):
        wanted += [chmi_archive.month_asset(r, year, month) for r in chmi_archive.MONTH_RESOLUTIONS]
    wanted += [
        chmi_archive.day_asset(first + timedelta(days=i)) for i in range((today - first).days + 1)
    ]
    for year in recent_years:
        for month in range(1, 13):
            wanted += [
                chmi_archive.month_asset(r, year, month) for r in ("daily", "monthly", "phenomena")
            ]
    return wanted
