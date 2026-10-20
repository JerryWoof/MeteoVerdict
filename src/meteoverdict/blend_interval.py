"""An uncertainty range for the combined temperature forecast (docs/methodology.md#range).

The forecast of ``meteoverdict.outlook`` is one number per hour. Next to it we publish
the range the errors of that very forecast say it should have: for every okres, lead day
and synoptic hour (00, 06, 12, 18 UTC) a low and a high percentile of
``observed - combined`` over the last ``WINDOW_DAYS`` days (``LOW``, ``HIGH``), so that
``[combined + lo, combined + hi]`` holds the measured value in about 80 % of the cases.
The spread of the models is not used: it is far too narrow (an 80 % interval
of it held the truth 56 % of the time).

**The errors.** ``rebuild`` recomputes the combined temperature at the okres's stations
for past days, out of sample, the way ``meteoverdict.hindcast`` does (weights, bias
corrections and regression trained on the scores up to ``target - lead - 1``) and keeps
the error at every station and synoptic hour: ``ERRORS``, a Parquet file in the release
outlook-archive, extended by ``mvd blend-interval`` every day.

**The quantiles.** ``quantiles`` takes the errors of the target days ``last - 29`` …
``last`` (``last`` = the newest day with scores, the day before the run), per okres
(``level`` ``okres``) and for the whole of Czechia (``cz``). An okres has few stations
and its quantiles from 30 days are noisy, so ``blend`` shrinks each okres's quantile
towards the national one by ``n / (n + SHRINK_N)`` (``n`` = the okres's errors behind it);
an okres, lead day and hour without enough errors takes the national one. Hours between
the synoptic ones are interpolated linearly in the hour of the day (``interval_at``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from meteoverdict import blendtest, combine, mos

FILE = "blend-interval.json"
TAG = "outlook-archive"
ASSET = "blend-errors.parquet"
#: what the range is meant to hold of the measured values
LEVEL = 0.8
#: the percentiles taken: wider than the 10th and 90th, because the errors of the last 30
#: days are smaller than the next days' in autumn (the weather turns more changeable and
#: the inversions and fronts come): out of sample the 10th-90th held 70-75 %, these
#: 77-82 % (docs/methodology.md#range)
LOW = 0.07
HIGH = 0.93
WINDOW_DAYS = 30
#: errors of the okres (and lead, hour) needed before it counts at all, and the number at
#: which its own quantile weighs as much as the national one
MIN_N = 20
SHRINK_N = 200
LEADS = (1, 2, 3, 4, 5)
HOURS = mos.SLOTS
#: the days kept in the error archive: the window and the history a check needs
KEEP_DAYS = 100
SCHEMA = {
    "date": pl.Date,
    "okres": pl.String,
    "station_id": pl.String,
    "lead": pl.Int8,
    "hour": pl.Int8,
    "error": pl.Float32,
}
VARIABLE = "temperature_2m"


def rebuild(
    scores: pl.DataFrame,
    fc: pl.LazyFrame | pl.DataFrame,
    observations: pl.LazyFrame | pl.DataFrame,
    stations: pl.DataFrame,
    days: list[date],
    leads: tuple[int, ...] = LEADS,
    window: str = combine.WINDOW,
    min_training_days: int = blendtest.MIN_TRAINING_DAYS,
    log: Callable[[str], None] = lambda _: None,
) -> pl.DataFrame:
    """The errors (``SCHEMA``) of the combined temperature on the UTC ``days`` at
    ``leads``; a day, okres and lead without enough training or without observations is
    left out."""
    scores = scores.filter(pl.col("variable").is_in(list(blendtest.SCORE_VARIABLES.values())))
    if scores.is_empty() or not days:
        return pl.DataFrame(schema=SCHEMA)
    # a day's forecast at lead N is made on day - N; its scores are known to day - N - 1
    needed = sorted({d - timedelta(days=n + 1) for d in days for n in leads})
    needed = [a for a in needed if a <= scores["date"].max()]
    if not needed:
        return pl.DataFrame(schema=SCHEMA)
    length = int(window.removesuffix("d"))
    okres_pools = blendtest.pools(
        scores.filter(pl.col("date") > min(needed) - timedelta(days=length)), stations
    )
    pairs = mos.pairs(observations, fc, needed[0] - timedelta(days=length - 1), needed[-1])
    weights, _ = blendtest.training(
        scores, stations, needed, window, min_training_days, pairs, okres_pools
    )
    if weights.is_empty():
        return pl.DataFrame(schema=SCHEMA)
    # ``training`` dates the weights as_of + lead; the forecast is one day later
    weights = weights.with_columns((pl.col("date") + timedelta(days=1)).alias("date")).filter(
        pl.col("lead_day").is_in(list(leads))
    )
    log(f"blend interval training: {len(needed)} days, {weights.height} weight rows")
    members = (
        okres_pools.filter(pl.col("variable") == blendtest.SCORE_VARIABLES[VARIABLE])
        .select("region", "station_id")
        .unique()
    )
    fc = fc.lazy().filter(
        pl.col("station_id").is_in(members["station_id"].implode()),
        pl.col("lead_day").is_in(list(leads)),
        pl.col("time").dt.hour().is_in(list(HOURS)),
    )
    observed = (
        observations.lazy()
        .filter(pl.col("variable") == VARIABLE, pl.col("time").dt.hour().is_in(list(HOURS)))
        .select("station_id", "time", pl.col("value").alias("observed"))
        .drop_nulls("observed")
        .unique(["station_id", "time"], keep="last")
    )
    out = []
    for day in days:
        today = weights.filter(pl.col("date") == day)
        if today.is_empty():
            continue
        start = datetime.combine(day, datetime.min.time(), UTC)
        hours = fc.filter(pl.col("time").is_between(start, start + timedelta(hours=23))).collect()
        if hours.is_empty():
            continue
        combined = blendtest.combined_forecasts(hours, okres_pools, today, stations)
        errors = (
            combined.lazy()
            .select("station_id", "time", "lead_day", "model", VARIABLE)
            .drop_nulls(VARIABLE)
            .join(observed, on=["station_id", "time"])
            .select(
                pl.lit(day).alias("date"),
                pl.col("model").str.strip_prefix(blendtest.PREFIX).alias("okres"),
                "station_id",
                pl.col("lead_day").alias("lead"),
                pl.col("time").dt.hour().alias("hour"),
                (pl.col("observed") - pl.col(VARIABLE)).alias("error"),
            )
            .collect()
        )
        out.append(errors.cast(SCHEMA))
    if not out:
        return pl.DataFrame(schema=SCHEMA)
    result = pl.concat(out).sort("date", "okres", "lead", "hour", "station_id")
    log(f"blend interval: {result['date'].n_unique()} days, {result.height} errors")
    return result


def merge(path: Path, rows: pl.DataFrame, first: date) -> Path:
    """Replace the days of ``rows`` in the file and drop days before ``first``."""
    rows = rows.cast(SCHEMA)
    if path.exists():
        old = pl.read_parquet(path).cast(SCHEMA)
        rows = pl.concat([old.filter(~pl.col("date").is_in(rows["date"].unique().implode())), rows])
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.filter(pl.col("date") >= first).sort("date", "okres", "lead", "hour").write_parquet(
        path, compression="zstd", compression_level=10
    )
    return path


# --- quantiles ----------------------------------------------------------------------


def _q(frame: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    return frame.group_by(keys).agg(
        pl.col("error").cast(pl.Float64).quantile(LOW, "linear").alias("lo"),
        pl.col("error").cast(pl.Float64).quantile(HIGH, "linear").alias("hi"),
        pl.len().alias("n"),
    )


def quantiles(
    errors: pl.DataFrame, last: date, days: int = WINDOW_DAYS, shrink: float = SHRINK_N
) -> pl.DataFrame:
    """``okres`` (``CZ`` = Czechia), ``lead``, ``hour``, ``lo``, ``hi`` (the offsets to
    add to the forecast, °C), ``n`` (errors behind them) from the errors of the ``days``
    target days ending on ``last``; okresy shrunk towards Czechia (see the module)."""
    window = errors.filter(pl.col("date") > last - timedelta(days=days), pl.col("date") <= last)
    keys = ["lead", "hour"]
    cz = _q(window, keys).with_columns(pl.lit("CZ").alias("okres"))
    own = _q(window, ["okres", *keys]).filter(pl.col("n") >= MIN_N)
    mixed = (
        own.join(
            cz.select(*keys, pl.col("lo").alias("cz_lo"), pl.col("hi").alias("cz_hi")), on=keys
        )
        .with_columns((pl.col("n") / (pl.col("n") + shrink)).alias("s"))
        .with_columns(
            (pl.col("s") * pl.col("lo") + (1 - pl.col("s")) * pl.col("cz_lo")).alias("lo"),
            (pl.col("s") * pl.col("hi") + (1 - pl.col("s")) * pl.col("cz_hi")).alias("hi"),
        )
        .select(cz.columns)
    )
    return pl.concat([cz, mixed]).sort("okres", "lead", "hour")


def document(table: pl.DataFrame, last: date, now: datetime, days: int = WINDOW_DAYS) -> dict:
    """``blend-interval.json``: ``{"generated", "level", "days", "last", "hours",
    "okresy": {code: {"<lead>": {"lo": [4 values], "hi": [4 values]}}}}`` (``CZ`` =
    Czechia, the fallback); ``lo`` and ``hi`` in °C, one decimal, at ``hours`` (UTC)."""
    okresy: dict = {}
    for (code, lead), part in sorted(table.partition_by("okres", "lead", as_dict=True).items()):
        part = part.sort("hour")
        if part["hour"].to_list() != list(HOURS):
            continue
        okresy.setdefault(code, {})[str(lead)] = {
            "lo": [round(v, 1) for v in part["lo"].to_list()],
            "hi": [round(v, 1) for v in part["hi"].to_list()],
        }
    return {
        "generated": now.isoformat(timespec="minutes"),
        "level": LEVEL,
        "days": days,
        "last": last.isoformat(),
        "hours": list(HOURS),
        "okresy": okresy,
    }


def write(doc: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path


def load(path: Path, now: datetime | None = None, max_age_days: int = 7) -> dict | None:
    """The file, or None when it is missing, unreadable, empty or older than
    ``max_age_days`` (the outlook then has no range, it never fails)."""
    try:
        doc = json.loads(path.read_text("utf-8"))
        last = date.fromisoformat(doc["last"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not doc.get("okresy"):
        return None
    today = (now or datetime.now(UTC)).date()
    return doc if (today - last).days <= max_age_days else None


# --- applying it to the hourly forecast -------------------------------------------------


def interval_at(doc: dict, okres: str, lead: int, hour: float) -> tuple[float, float] | None:
    """The offsets (lo, hi) for an okres, lead day (1-5) and UTC ``hour`` (fractions
    allowed): linear in the hour between the synoptic ones, round the clock."""
    entry = doc["okresy"].get(okres, {}).get(str(lead)) or doc["okresy"].get("CZ", {}).get(
        str(lead)
    )
    if entry is None:
        return None
    hours = [*doc["hours"], doc["hours"][0] + 24]
    x = hour % 24 if hour % 24 >= hours[0] else hour % 24 + 24
    return tuple(float(np.interp(x, hours, [*entry[k], entry[k][0]])) for k in ("lo", "hi"))  # type: ignore[return-value]


def add_interval(hourly: pl.DataFrame, doc: dict | None, now: datetime) -> pl.DataFrame:
    """Add ``temperature_2m_lo`` and ``temperature_2m_hi`` (the combined temperature plus
    the offsets) to the combined hourly series; null without a ``doc``. The lead day of an
    hour is the one of ``outlook.with_lead_and_fade``."""
    if doc is None or hourly.is_empty():
        return hourly.with_columns(
            pl.lit(None, pl.Float64).alias("temperature_2m_lo"),
            pl.lit(None, pl.Float64).alias("temperature_2m_hi"),
        )
    grid = pl.DataFrame(
        [
            {"okres": code, "lead": int(lead), "hour": float(h), "lo": lo, "hi": hi}
            for code in doc["okresy"]
            for lead in doc["okresy"][code]
            for h in range(24)
            for lo, hi in [interval_at(doc, code, int(lead), h)]
        ],
        schema={
            "okres": pl.String,
            "lead": pl.Int64,
            "hour": pl.Int64,
            "lo": pl.Float64,
            "hi": pl.Float64,
        },
    )
    codes = [c for c in doc["okresy"] if c != "CZ"]
    cz = grid.filter(pl.col("okres") == "CZ").drop("okres")
    own = grid.filter(pl.col("okres").is_in(codes))
    hours = (pl.col("time") - pl.lit(now)).dt.total_hours()
    rows = hourly.with_columns(
        pl.min_horizontal(pl.lit(5), pl.max_horizontal(pl.lit(1), hours // 24))
        .cast(pl.Int64)
        .alias("lead"),
        pl.col("time").dt.hour().cast(pl.Int64).alias("hour"),
    )
    rows = rows.join(own, on=["okres", "lead", "hour"], how="left", maintain_order="left").join(
        cz, on=["lead", "hour"], how="left", suffix="_cz", maintain_order="left"
    )
    t = pl.col("temperature_2m")
    return rows.with_columns(
        (t + pl.coalesce("lo", "lo_cz")).alias("temperature_2m_lo"),
        (t + pl.coalesce("hi", "hi_cz")).alias("temperature_2m_hi"),
    ).drop("lead", "hour", "lo", "hi", "lo_cz", "hi_cz")
