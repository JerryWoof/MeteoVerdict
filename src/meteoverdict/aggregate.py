"""Aggregate daily scores per region and time window (roadmap 2.4).

Levels: ``station``, ``okres``, ``kraj``, ``elevation`` (lowland/upland/mountain) and
``cz`` (all stations). Windows, all ending at ``as_of`` (the last scored day): ``90d``
(the last 90 days), ``season`` (the meteorological season so far: DJF, MAM, JJA, SON)
and ``all``.

Fair comparison: for each window, variable, lead day and station, only the days that
**every** model covering that station has scores for are used. So a model with a short
archive (ALADIN) or gaps (UKMO) does not get easier or harder days than the others; a
model that cannot reach a station at all (ICON-D2 in the far east) is simply absent
there (its ``stations`` count in a region is then lower).
A region needs at least ``MIN_STATIONS`` stations; otherwise ``enough_stations`` is
false and it must not be ranked.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from meteoverdict import metrics

LEVELS = ("station", "okres", "kraj", "elevation", "cz")
WINDOWS = ("90d", "season", "all")
MIN_STATIONS = 3
_REGION = {
    "station": ("station_id", "station_name"),
    "okres": ("okres_code", "okres"),
    "kraj": ("kraj_code", "kraj"),
    "elevation": ("elevation_class", "elevation_class"),
}


def season_start(day: date) -> date:
    """First day of the meteorological season containing ``day``."""
    if day.month == 12:
        return date(day.year, 12, 1)
    if day.month <= 2:
        return date(day.year - 1, 12, 1)
    return date(day.year, (day.month // 3) * 3, 1)


def window_start(window: str, as_of: date, first_day: date) -> date:
    if window == "90d":
        return as_of - timedelta(days=89)
    if window == "season":
        return season_start(as_of)
    if window == "all":
        return first_day
    raise ValueError(f"unknown window {window!r}")


def common_days(scores: pl.LazyFrame) -> pl.LazyFrame:
    """Keep the station-days every model covering that station has scores for.

    Per variable, lead day and station, the models compared are those with any score at
    that station in the period: a model whose domain does not reach a station (ICON-D2
    in the far east) does not remove that station for the others, while a model that
    covers it but lacks a day (a short archive, a gap) removes that day for all.
    """
    group = ["variable", "lead_day", "station_id"]
    models = scores.group_by(group).agg(pl.col("model").n_unique().alias("models"))
    present = (
        scores.group_by(*group, "date")
        .agg(pl.col("model").n_unique().alias("present"))
        .join(models, on=group)
        .filter(pl.col("present") == pl.col("models"))
        .select(*group, "date")
    )
    return scores.join(present, on=[*group, "date"], how="semi")


def station_info(stations: pl.DataFrame) -> pl.LazyFrame:
    return stations.select(
        pl.col("id").alias("station_id"),
        pl.col("name").alias("station_name"),
        "okres_code",
        "okres",
        "kraj_code",
        "kraj",
        "elevation_class",
    ).lazy()


def region_columns(level: str) -> list[pl.Expr]:
    """``region`` and ``region_name`` for a level (needs the station_info columns)."""
    code, name = _REGION.get(level, (None, None))
    if code:
        return [pl.col(code).alias("region"), pl.col(name).alias("region_name")]
    return [pl.lit("cz").alias("region"), pl.lit("Česko").alias("region_name")]


def date_span(scores: pl.LazyFrame) -> tuple[date, date]:
    span = scores.select(pl.col("date").min().alias("first"), pl.col("date").max().alias("last"))
    first_day, last_day = span.collect().row(0)
    if first_day is None:
        raise ValueError("no scores to aggregate")
    return first_day, last_day


def _sum_columns(columns: list[str]) -> list[pl.Expr]:
    counts = [c for t in metrics.PRECIPITATION_THRESHOLDS for c in metrics.counts_columns(t)]
    return [pl.col(c).sum() for c in (*metrics.SUMS, *counts) if c in columns]


def _metrics(frame: pl.LazyFrame) -> pl.LazyFrame:
    frame = metrics.continuous_scores(frame)
    columns = set(frame.collect_schema().names())
    for threshold in metrics.PRECIPITATION_THRESHOLDS:
        if set(metrics.counts_columns(threshold)) <= columns:  # no daily rows, no counts
            frame = metrics.categorical_scores(frame, threshold)
    return frame


def aggregate(
    scores: pl.LazyFrame | pl.DataFrame,
    stations: pl.DataFrame,
    as_of: date | None = None,
    windows: tuple[str, ...] = WINDOWS,
) -> pl.DataFrame:
    """One row per level, region, window, variable, lead day and model."""
    scores = scores.lazy()
    first_day, last_day = date_span(scores)
    as_of = as_of or last_day
    info = station_info(stations)
    columns = scores.collect_schema().names()
    frames = []
    for window in windows:
        start = window_start(window, as_of, first_day)
        fair = common_days(scores.filter(pl.col("date").is_between(start, as_of)))
        fair = fair.join(info, on="station_id", how="inner")
        for level in LEVELS:
            frames.append(
                fair.with_columns(region_columns(level))
                .group_by("region", "region_name", "variable", "lead_day", "model")
                .agg(
                    *_sum_columns(columns),
                    pl.col("station_id").n_unique().alias("stations"),
                    pl.col("date").n_unique().alias("days"),
                )
                .with_columns(
                    pl.lit(level).alias("level"),
                    pl.lit(window).alias("window"),
                    pl.lit(start).alias("from"),
                    pl.lit(as_of).alias("to"),
                )
            )
    out = _metrics(pl.concat(frames, how="diagonal_relaxed")).with_columns(
        ((pl.col("level") == "station") | (pl.col("stations") >= MIN_STATIONS)).alias(
            "enough_stations"
        )
    )
    first = ["level", "region", "region_name", "window", "from", "to", "variable", "lead_day"]
    return out.collect().select(pl.col(first), pl.exclude(first)).sort([*first, "model"])


#: Columns published in the JSON files (the additive sums stay in Parquet).
JSON_COLUMNS = (
    "region",
    "region_name",
    "lead_day",
    "model",
    "stations",
    "days",
    "n",
    "mae",
    "bias",
    "rmse",
    "pod_0p1",
    "far_0p1",
    "ets_0p1",
    "pod_5",
    "far_5",
    "ets_5",
    "enough_stations",
    "rank",
    "diff_ci_low",
    "diff_ci_high",
    "tied_with_best",
    "clear_winner",
)


def write_json(table: pl.DataFrame, out_dir: Path, meta: dict) -> list[Path]:
    """Write ``out_dir/meta.json`` and ``out_dir/<window>/<level>/<variable>.json``.

    Each data file is ``{"columns": [...], "rows": [[...], ...]}`` with floats rounded to
    3 decimals, small enough for a static web page.
    """
    written = []
    out_dir.mkdir(parents=True, exist_ok=True)
    groups = table.partition_by(["window", "level", "variable"], as_dict=True)
    for (window, level, variable), part in sorted(groups.items()):
        columns = [c for c in JSON_COLUMNS if c in part.columns]
        rows = part.select(
            pl.col(c).round(3) if part.schema[c].is_float() else pl.col(c) for c in columns
        ).rows()
        path = out_dir / window / level / f"{variable}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"columns": columns, "rows": rows}, ensure_ascii=False, separators=(",", ":")
            ),
            encoding="utf-8",
        )
        written.append(path)
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), "utf-8")
    return [meta_path, *written]


def metadata(table: pl.DataFrame, models: dict[str, str], generated: datetime) -> dict:
    windows = table.select("window", "from", "to").unique().sort("window").rows(named=True)
    return {
        "generated": generated.isoformat(timespec="seconds"),
        "as_of": str(table["to"].max()),
        "windows": {w["window"]: {"from": str(w["from"]), "to": str(w["to"])} for w in windows},
        "levels": list(LEVELS),
        "variables": sorted(table["variable"].unique().to_list()),
        "models": models,
        "min_stations": MIN_STATIONS,
        "precipitation_thresholds_mm": list(metrics.PRECIPITATION_THRESHOLDS),
        "fair_comparison": "per window, variable and lead day only station-days all models cover",
        "ranking": (
            "by MAE; tied_with_best when the 95 % bootstrap interval (days resampled) of the "
            "MAE difference to the best model contains 0; clear_winner when nobody is tied; "
            "the blend (mean of all models) is not ranked, its difference and interval are "
            "relative to the best single model"
        ),
        "licence": "CC BY-SA 4.0, https://creativecommons.org/licenses/by-sa/4.0/",
        "attribution": (
            "Observations: ČHMÚ (opendata.chmi.cz, CC BY 4.0). Forecasts: Open-Meteo.com "
            "(CC BY 4.0) from DWD, ECMWF, NOAA, Météo-France, GeoSphere Austria, KNMI, DMI, "
            "ČHMÚ and the UK Met Office (CC BY-SA 4.0). Boundaries: ČÚZK (CC BY 4.0)."
        ),
    }
