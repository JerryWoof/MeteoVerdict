"""Our forecast for the past days of the measured page, rebuilt out of sample.

The forecast map's own parts of day are archived only since October 2026
(``outlook.parts_archive_asset``). For the "forecast vs. measured" comparison of every
day the measured page offers (``observed_map``), the combined forecast is rebuilt here
the way the out-of-sample test does it (``meteoverdict.blendtest``), with only what
was known before it was issued:

1. **Training.** For a day ``d`` at lead ``N`` the weights, bias corrections and
   regression blend (``blendtest.training``: ``combine.weights`` and ``mos``, as the
   live forecast) come from the okres scores of the 90-day window ending on
   ``d - N - 1``: the D+N forecast for ``d`` is made during ``d - N`` and that day's own
   scores are published only the next morning (one day stricter than the blend test).
2. **The forecasts** are the models' stored D+N forecasts at the okres's stations
   (``fc-YYYY-MM.parquet``; the newest days rebuilt from the single runs, as the daily
   scoring), combined hour by hour with those weights (``blendtest.combined_forecasts``)
   at the okres's stations (its own and borrowed ones, ``aggregate.with_regions``) and
   averaged over them per hour.
3. **Parts of day** as the forecast map (``outlook.summarise``): Prague parts and day,
   ``tmin``, ``tmax``, ``precipitation``, ``wind`` (highest hourly), and
   ``rain_probability`` the share of the okres's models whose own total (mean over the
   okres's stations) is at least ``outlook.WET_MM`` (uncalibrated). The stored D+N have
   no cloud cover, so the symbol is only rain, sleet, snow or showers; null otherwise
   (the map's sky symbol cannot be rebuilt).

These are **not** the forecasts the map showed; the measured page labels them as rebuilt
("zpětně spočítaná předpověď") and prefers a stored run of the same lead.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from meteoverdict import blend, blendtest, combine, mos, outlook

PRAGUE = ZoneInfo(outlook.TIME_ZONE)
LEADS = (1, 2, 3)
#: published in the release outlook-archive, read by ``mvd observed-map``
TAG = outlook.PARTS_ARCHIVE_TAG
ASSET = "outlook-hindcast.parquet"
COLUMNS = outlook.PARTS_ARCHIVE_COLUMNS
SCHEMA = {
    "lead": pl.Int8,
    "trained_to": pl.Date,
    "okres": pl.String,
    "day": pl.Date,
    "part": pl.String,
    **{c: pl.Float32 for c in COLUMNS if c != "symbol"},
    "symbol": pl.String,
}
#: the stored D+N variables the rebuilt forecast has
VARIABLES = ("temperature_2m", "precipitation", "wind_speed_10m")


def as_of(day: date, lead: int) -> date:
    """The last day of scores a forecast for ``day`` at ``lead`` may use."""
    return day - timedelta(days=lead + 1)


def _prague_hours(day: date) -> tuple[datetime, datetime]:
    """UTC bounds of the hours a Prague day needs: its hours, and the hour ending at its
    end (precipitation is the hour ending at the time)."""
    start = datetime.combine(day, time(), PRAGUE).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(), PRAGUE).astimezone(UTC)
    return start, end + timedelta(hours=1)


def okres_hourly(combined: pl.DataFrame) -> pl.DataFrame:
    """The combined forecast at an okres's stations (``blendtest.combined_forecasts``)
    → one row per okres, lead day and hour: the mean over its stations."""
    return (
        combined.with_columns(pl.col("model").str.strip_prefix(blendtest.PREFIX).alias("okres"))
        .group_by("okres", "lead_day", "time")
        .agg(pl.col(v).mean() for v in VARIABLES)
    )


def model_totals(
    fc: pl.DataFrame, okres_pools: pl.DataFrame, weights: pl.DataFrame
) -> pl.DataFrame:
    """Each weighted model's precipitation per okres, lead day and hour, as the mean
    over the okres's precipitation stations (for the share of wet models)."""
    score = blendtest.SCORE_VARIABLES["precipitation"]
    members = okres_pools.filter(pl.col("variable") == score).select("region", "station_id")
    allowed = (
        weights.filter(pl.col("variable") == "precipitation")
        .select("region", "lead_day", "model")
        .unique()
    )
    return (
        fc.filter(pl.col("model") != blend.ID)
        .drop_nulls("precipitation")
        .join(members, on="station_id")
        .join(allowed, on=["region", "lead_day", "model"])
        .group_by("region", "lead_day", "model", "time")
        .agg(pl.col("precipitation").mean())
        .rename({"region": "okres"})
    )


def chances(totals: pl.DataFrame) -> pl.DataFrame:
    """Share of wet models per okres, lead day, Prague day and part (and the whole
    day), as ``outlook.probability`` without a calibration."""
    rows = outlook._local(totals, hour_ending=True)
    frames = []
    for period in ("part", "day"):
        keys = ["okres", "lead_day", "day"] + (["part"] if period == "part" else [])
        sums = (
            rows.drop_nulls("part" if period == "part" else "day")
            .group_by(*keys, "model")
            .agg(pl.col("precipitation").sum().alias("fc"), pl.len().alias("hours"))
            .filter(pl.col("hours") == pl.col("hours").max().over(keys))
            .group_by(keys)
            .agg((pl.col("fc") >= outlook.WET_MM).mean().alias("rain_probability"))
        )
        if period == "day":
            sums = sums.with_columns(pl.lit("day").alias("part"))
        frames.append(sums.select("okres", "lead_day", "day", "part", "rain_probability"))
    return pl.concat(frames)


def parts(hourly: pl.DataFrame, wet: pl.DataFrame, day: date) -> pl.DataFrame:
    """Parts of day of a Prague ``day`` per okres and lead (``outlook.summarise``)."""
    out = []
    for lead in sorted(hourly["lead_day"].unique().to_list()):
        rows = hourly.filter(pl.col("lead_day") == lead).with_columns(
            pl.lit(None, pl.Float64).alias("cloud_cover"),
            pl.lit(None, pl.Float64).alias("sunshine_duration"),
        )
        share = (
            wet.filter(pl.col("lead_day") == lead)
            .drop("lead_day")
            .with_columns(pl.col("rain_probability").alias("model_share"))
        )
        table = outlook.summarise(rows, share).filter(pl.col("day") == day)
        out.append(table.with_columns(pl.lit(lead).alias("lead")))
    if not out:
        return pl.DataFrame(schema=SCHEMA)
    table = pl.concat(out, how="diagonal_relaxed")
    return table.select(
        "lead",
        pl.lit(None, pl.Date).alias("trained_to"),
        "okres",
        "day",
        "part",
        *[(pl.col(c) if c in table.columns else pl.lit(None)).alias(c) for c in COLUMNS],
    )


def rebuild(
    scores: pl.DataFrame,
    fc: pl.LazyFrame | pl.DataFrame,
    observations: pl.LazyFrame | pl.DataFrame | None,
    stations: pl.DataFrame,
    days: list[date],
    leads: tuple[int, ...] = LEADS,
    window: str = combine.WINDOW,
    min_training_days: int = blendtest.MIN_TRAINING_DAYS,
    regression: bool = True,
    log: Callable[[str], None] = lambda _: None,
) -> pl.DataFrame:
    """The rebuilt parts of day (``SCHEMA``) of the Prague ``days`` at ``leads``; a day,
    okres and lead without enough training (``min_training_days``) or forecasts is left
    out."""
    scores = scores.filter(pl.col("variable").is_in(list(blendtest.SCORE_VARIABLES.values())))
    if scores.is_empty() or not days:
        return pl.DataFrame(schema=SCHEMA)
    # a UTC date's weights at lead N are trained up to date - N - 1 (``as_of``); a Prague
    # day also needs the evening hours of the UTC day before
    needed = sorted({as_of(d - timedelta(days=k), n) for d in days for n in leads for k in (0, 1)})
    last_scored = scores["date"].max()
    needed = [a for a in needed if a <= last_scored]
    okres_pools = blendtest.pools(
        scores.filter(pl.col("date") > min(needed) - timedelta(days=90)), stations
    )
    pairs = None
    if regression and observations is not None:
        length = int(window.removesuffix("d"))
        pairs = mos.pairs(observations, fc, needed[0] - timedelta(days=length - 1), needed[-1])
    weights, _ = blendtest.training(
        scores, stations, needed, window, min_training_days, pairs, okres_pools
    )
    if weights.is_empty():
        return pl.DataFrame(schema=SCHEMA)
    # ``training`` dates the weights as_of + lead (the blend test); one day later here
    weights = weights.with_columns(
        (pl.col("date") + timedelta(days=1)).alias("date"),
        (pl.col("as_of")).alias("trained_to"),
    ).filter(pl.col("lead_day").is_in(list(leads)))
    log(f"hindcast training: {len(needed)} days, {weights.height} weight rows")
    members = okres_pools["station_id"].unique().to_list()
    fc = fc.lazy().filter(pl.col("station_id").is_in(members), pl.col("lead_day").is_in(leads))
    out = []
    for day in days:
        start, end = _prague_hours(day)
        dates = [start.date(), (end - timedelta(hours=1)).date(), day]
        today = weights.filter(pl.col("date").is_in(dates))
        if today.is_empty():
            continue
        hours = fc.filter(pl.col("time").is_between(start, end)).collect()
        if hours.is_empty():
            continue
        combined = blendtest.combined_forecasts(hours, okres_pools, today, stations)
        if combined.is_empty():
            continue
        hourly = okres_hourly(combined)
        on_day = today.filter(pl.col("date") == day)
        wet = chances(model_totals(hours, okres_pools, on_day))
        table = parts(hourly, wet, day)
        trained = (
            on_day.group_by(pl.col("region").alias("okres"), pl.col("lead_day").alias("lead"))
            .agg(pl.col("trained_to").max().alias("_trained"))
            .with_columns(pl.col("lead").cast(pl.Int8))
        )
        table = (
            table.cast({"lead": pl.Int8})
            .join(trained, on=["okres", "lead"], how="inner")
            .with_columns(pl.col("_trained").alias("trained_to"))
            .drop("_trained")
        )
        out.append(table.select(list(SCHEMA)).cast(SCHEMA))
    if not out:
        return pl.DataFrame(schema=SCHEMA)
    result = pl.concat(out).sort("day", "okres", "lead", "part")
    log(
        f"hindcast: {result['day'].n_unique()} days, {result['okres'].n_unique()} okresy, "
        f"{result.height} rows"
    )
    return result


def merge(path: Path, rows: pl.DataFrame, first: date) -> Path:
    """Replace the days of ``rows`` in the file and drop days before ``first``."""
    rows = rows.cast(SCHEMA)
    if path.exists():
        old = pl.read_parquet(path).cast(SCHEMA)
        rows = pl.concat([old.filter(~pl.col("day").is_in(rows["day"].unique().implode())), rows])
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.filter(pl.col("day") >= first).sort("day", "okres", "lead", "part").write_parquet(
        path, compression="zstd", compression_level=10
    )
    return path
