"""The station diary: what the weather was like at a station, day by day.

From ČHMÚ's daily climate records (``daily`` rows of the archive) and the days with
weather phenomena, one small file per station and decade,
``<out>/diary/<WSI>/<decade>.json.gz`` (gzipped JSON, ten years each), read by the
"Weather at the station" overview of web/station.html
(docs/data-sources.md#station-diary).

A day is the date ČHMÚ gives the record; each value covers ČHMÚ's own window for its
element, checked against the 10-minute and hourly data of Praha-Ruzyně (September 2026,
all 26 days of the test equal):

========  ==========  ==================================================================
field     element     window (CET = UTC+1 all year, as ČHMÚ keeps it)
========  ==========  ==================================================================
``tx``    TMA 20:00   maximum temperature, 21:00 CET the day before → 21:00 CET
``tn``    TMI 20:00   minimum temperature, the same window
``t``     T AVG       mean temperature, (T07 + T14 + 2 * T21) / 4 CET
``r``     SRA 06:00   precipitation, 07:00 CET of the day → 07:00 CET the next day
``sno``   SNO 06:00   new snow, the same window as the precipitation
``sce``   SCE 06:00   snow depth at 07:00 CET of the day
``ssv``   SSV 00:00   sunshine (hours), the calendar day
``g``     Fmax 00:00  maximum gust (m/s), 00:00-24:00 CET
========  ==========  ==================================================================

Phenomena (thunderstorm, fog, hail, …) are the days the observer recorded them.

Values of quality 1 (suspect), 2 (poor) and 4 (missing) are left out, as everywhere in
the project; 0 (checked), 3 (estimated) and 5 (not checked yet) are kept, and the days
with an unchecked value are listed (``unchecked``), so the page can say so.
"""

from __future__ import annotations

import gzip
import json
import math
from datetime import date
from pathlib import Path

import polars as pl

#: diary field → (ČHMÚ element, VTYPE of the daily record)
FIELDS: dict[str, tuple[str, str]] = {
    "tx": ("TMA", "20:00"),
    "tn": ("TMI", "20:00"),
    "t": ("T", "AVG"),
    "r": ("SRA", "06:00"),
    "sno": ("SNO", "06:00"),
    "sce": ("SCE", "06:00"),
    "ssv": ("SSV", "00:00"),
    "g": ("Fmax", "00:00"),
}
#: ČHMÚ quality codes kept (observations.KEEP_QUALITY): checked, estimated, not checked yet
KEEP_QUALITY = (0, 3, 5)
UNCHECKED = 5
#: ČHMÚ flags (meta3) worth showing: an unmeasurable trace of precipitation, a dusting or
#: patchy snow cover, new snow that fell and melted
FLAGS: dict[str, tuple[str, ...]] = {"r": ("T",), "sce": ("P", "N"), "sno": ("R", "P")}
#: phenomena kept (all of ČHMÚ's: BO thunderstorm, DE rain, SN snow, KR hail, ML fog,
#: MS freezing rain, LE glaze, NA rime, JI hoarfrost, SV strong wind), not RO dew
PHENOMENA = ("BO", "DE", "SN", "KR", "ML", "MS", "LE", "NA", "JI", "SV")
#: years per file
DECADE = 10


def _round(v: float | None) -> float | int | None:
    if v is None or math.isnan(v):
        return None
    r = round(v, 1)
    return int(r) if r == int(r) else r


def diary_rows(daily: pl.DataFrame) -> pl.DataFrame:
    """One row per day (``day``, a date) and diary field (``field``) with ``value``,
    ``flag`` and ``quality``, from the station's daily archive rows; bad quality and
    missing values left out."""
    choice = pl.DataFrame(
        {
            "element": [e for e, _ in FIELDS.values()],
            "vtype": [v for _, v in FIELDS.values()],
            "field": list(FIELDS),
        }
    )
    return (
        daily.filter(pl.col("value").is_not_null(), pl.col("quality").is_in(KEEP_QUALITY))
        .join(choice, on=["element", "vtype"], how="inner")
        .select(pl.col("time").dt.date().alias("day"), "field", "value", "flag", "quality")
        .unique(["day", "field"], keep="first", maintain_order=True)
        .sort("day", "field")
    )


def phenomena_days(phenomena: pl.DataFrame) -> pl.DataFrame:
    """Distinct (``day``, ``code``) of the recorded phenomena."""
    if phenomena.height == 0:
        return pl.DataFrame(schema={"day": pl.Date, "code": pl.String})
    return (
        phenomena.filter(pl.col("element").is_in(PHENOMENA))
        .select(pl.col("time").dt.date().alias("day"), pl.col("element").alias("code"))
        .unique()
        .sort("day", "code")
    )


def decade_of(year: int) -> int:
    return year - year % DECADE


def chunk_doc(first_year: int, rows: pl.DataFrame, phenomena: pl.DataFrame) -> dict | None:
    """The diary of the ``DECADE`` years from 1 January ``first_year``: ``start`` (the
    first day), ``days``, ``values`` (field → one value a day from ``start``, null where
    there is none; fields with no value left out), ``phenomena`` and ``flags`` (code →
    day numbers, 0 = ``start``) and ``unchecked`` (days with a value ČHMÚ has not
    checked yet). None when the decade has nothing."""
    first = date(first_year, 1, 1)
    end = date(first_year + DECADE, 1, 1)
    in_range = (pl.col("day") >= first) & (pl.col("day") < end)
    rows = rows.filter(in_range)
    phenomena = phenomena.filter(in_range)
    if rows.height == 0 and phenomena.height == 0:
        return None
    last = max(d for d in (rows["day"].max(), phenomena["day"].max()) if d is not None)
    days = (last - first).days + 1
    index = (pl.col("day") - pl.lit(first)).dt.total_days().alias("i")
    values: dict[str, list] = {}
    flags: dict[str, dict[str, list[int]]] = {}
    for field in FIELDS:
        part = rows.filter(pl.col("field") == field).with_columns(index)
        if part.height == 0:
            continue
        column: list = [None] * days
        for i, v in zip(part["i"].to_list(), part["value"].to_list(), strict=True):
            column[i] = _round(v)
        values[field] = column
        for flag in FLAGS.get(field, ()):
            marked = part.filter(pl.col("flag") == flag)["i"].to_list()
            if marked:
                flags.setdefault(field, {})[flag] = marked
    doc: dict = {"start": first.isoformat(), "days": days, "values": values}
    if phenomena.height:
        with_index = phenomena.with_columns(index)
        doc["phenomena"] = {
            code: with_index.filter(pl.col("code") == code)["i"].to_list()
            for code in sorted(with_index["code"].unique().to_list())
        }
    if flags:
        doc["flags"] = flags
    unchecked = rows.filter(pl.col("quality") == UNCHECKED).with_columns(index)["i"]
    if unchecked.len():
        doc["unchecked"] = sorted(set(unchecked.to_list()))
    return doc


def chunk_name(first_year: int) -> str:
    return f"{first_year}.json.gz"


def write(out: Path, wsi: str, daily: pl.DataFrame, phenomena: pl.DataFrame) -> dict | None:
    """Write ``<out>/diary/<WSI>/<decade>.json.gz`` (gzipped JSON, ``chunk_doc``) for
    every decade with data, replacing what was there. Returns the summary for the
    station file: ``first`` and ``last`` day with a value, ``chunks`` (first years of
    the decade files), ``fields`` (with any value) and ``phenomena`` (any recorded), or
    None when the station has no diary."""
    rows = diary_rows(daily)
    pheno = phenomena_days(phenomena)
    folder = out / "diary" / wsi
    for old in folder.glob("*.json.gz"):
        old.unlink()
    if rows.height == 0 and pheno.height == 0:
        return None
    days = pl.concat([rows["day"], pheno["day"]])
    folder.mkdir(parents=True, exist_ok=True)
    chunks = []
    for first_year in range(decade_of(days.min().year), days.max().year + 1, DECADE):
        doc = chunk_doc(first_year, rows, pheno)
        if doc is None:
            continue
        text = json.dumps(doc, separators=(",", ":")).encode()
        # mtime 0: the same data give the same bytes (no needless changes)
        (folder / chunk_name(first_year)).write_bytes(gzip.compress(text, 9, mtime=0))
        chunks.append(first_year)
    span = rows["day"] if rows.height else days
    return {
        "first": span.min().isoformat(),
        "last": span.max().isoformat(),
        "decade": DECADE,
        "chunks": chunks,
        "fields": [f for f in FIELDS if f in set(rows["field"].to_list())],
        "phenomena": sorted(set(pheno["code"].to_list())),
    }
