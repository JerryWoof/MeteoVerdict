"""Aggregate daily scores per region and time window (roadmap 2.4).

Levels: ``station``, ``okres``, ``kraj``, ``elevation`` (lowland/upland/mountain) and
``cz`` (all stations). Windows, all ending at ``as_of`` (the last scored day): ``90d``
(the last 90 days), ``season`` (the meteorological season so far: DJF, MAM, JJA, SON)
and ``all``; and per season over all years (roadmap 5.1): ``djf``, ``mam``, ``jja`` and
``son``, every day of that season up to ``as_of``.

Fair comparison: for each window, variable, lead day and region, only the station-days
that **every** model present in that region has scores for are used. So a model with a
short archive (ALADIN) or gaps (UKMO) does not get easier or harder days than the
others, and all models in a region are compared on the same stations: where a model
cannot reach some stations (ICON-D2 at six stations in the far east), those stations
are left out of that region's comparison for every model, and still compared among the
other models at the station level.
A region needs at least ``MIN_STATIONS`` stations; otherwise ``enough_stations`` is
false and it must not be ranked. An okres with too few stations of its own borrows the
nearest ones of its neighbours (``meteoverdict.neighbours``, roadmap 6.1); ``borrowed``
counts them.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from meteoverdict import metrics, neighbours

LEVELS = ("station", "okres", "kraj", "elevation", "cz")
#: meteorological seasons and their months
SEASONS = {"djf": (12, 1, 2), "mam": (3, 4, 5), "jja": (6, 7, 8), "son": (9, 10, 11)}
WINDOWS = ("90d", "season", "all", *SEASONS)
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
    """First day of a window: ``90d`` (or any ``<N>d``, the last N days), ``season``
    or ``all``."""
    if window.endswith("d") and window[:-1].isdigit() and int(window[:-1]) > 0:
        return as_of - timedelta(days=int(window[:-1]) - 1)
    if window == "season":
        return season_start(as_of)
    if window == "all":
        return first_day
    raise ValueError(f"unknown window {window!r}")


def window_days(window: str, as_of: date, first_day: date) -> tuple[date, pl.Expr]:
    """First day of a window and the filter on ``date`` that selects its days."""
    if window in SEASONS:
        months = pl.col("date").dt.month().is_in(SEASONS[window])
        return first_day, pl.col("date").is_between(first_day, as_of) & months
    start = window_start(window, as_of, first_day)
    return start, pl.col("date").is_between(start, as_of)


def common_days(scores: pl.LazyFrame, by: str = "station_id") -> pl.LazyFrame:
    """Keep the station-days every model present in the group ``by`` has scores for.

    Per variable, lead day and group (a station, or ``region`` after
    ``region_columns``), the models compared are those with any score in that group in
    the period; a station-day is kept only if all of them have a score there.
    """
    group = ["variable", "lead_day", by]
    keys = list(dict.fromkeys([*group, "station_id", "date"]))
    models = scores.group_by(group).agg(pl.col("model").n_unique().alias("models"))
    present = (
        scores.group_by(keys)
        .agg(pl.col("model").n_unique().alias("present"))
        .join(models, on=group)
        .filter(pl.col("present") == pl.col("models"))
        .select(keys)
    )
    return scores.join(present, on=keys, how="semi")


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


def okres_distances(stations: pl.DataFrame) -> pl.DataFrame | None:
    """Station-to-okres distances for borrowing, or None without station coordinates."""
    if not {"lon", "lat"} <= set(stations.columns):
        return None
    return neighbours.distances(stations)


#: rounds of replacing stations the fair comparison drops (each round is one more scan)
POOL_ROUNDS = 3


def okres_pools(in_window: pl.LazyFrame, distance: pl.DataFrame) -> pl.DataFrame:
    """``neighbours.pools`` for the stations with scores in ``in_window``.

    A station counts only if it survives the fair comparison (``common_days``) at the
    first lead day, where all models are present: a station that some of the okres's
    models never reach (fewer models fetched for a rain gauge, ICON-D2 in the far east)
    would otherwise fill a place in the pool and then be dropped. Such stations are
    excluded from that okres and replaced by the next nearest ones.
    """
    available = in_window.select("variable", "station_id").unique().collect()
    keys = ["variable", "region", "station_id"]
    excluded = pl.DataFrame(schema={k: pl.String for k in keys})
    pool = neighbours.pools(distance, available, MIN_STATIONS)
    first = in_window.filter(pl.col("lead_day") == pl.col("lead_day").min())
    for _ in range(POOL_ROUNDS):
        joined = first.drop("okres_code", "okres").join(
            pool.lazy(), on=["variable", "station_id"], how="inner"
        )
        kept = common_days(joined, by="region").select(keys).unique().collect()
        short = (
            pool.select("variable", "region")
            .unique()
            .join(kept.group_by("variable", "region").len(), on=["variable", "region"], how="left")
            .filter(pl.col("len").fill_null(0) < MIN_STATIONS)
        )
        dropped = (
            pool.select(keys)
            .join(kept, on=keys, how="anti")
            .join(short, on=["variable", "region"], how="semi")
        )
        if dropped.is_empty():
            break
        excluded = pl.concat([excluded, dropped])
        pool = neighbours.pools(distance, available, MIN_STATIONS, exclude=excluded)
    return pool


def with_regions(
    in_window: pl.LazyFrame, level: str, distance: pl.DataFrame | None
) -> pl.LazyFrame:
    """Rows of ``in_window`` with ``region``, ``region_name`` and ``borrowed``.

    At the okres level with ``distance`` (from ``okres_distances``), a station's rows
    appear once for every okres whose pool it is in (``neighbours.pools``).
    """
    if level == "okres" and distance is not None:
        pool = okres_pools(in_window, distance)
        return in_window.drop("okres_code", "okres").join(
            pool.lazy(), on=["variable", "station_id"], how="inner"
        )
    return in_window.with_columns(*region_columns(level), pl.lit(False).alias("borrowed"))


def date_span(scores: pl.LazyFrame) -> tuple[date, date]:
    span = scores.select(pl.col("date").min().alias("first"), pl.col("date").max().alias("last"))
    first_day, last_day = span.collect().row(0)
    if first_day is None:
        raise ValueError("no scores to aggregate")
    return first_day, last_day


def _sum_columns(columns: list[str]) -> list[pl.Expr]:
    counts = [c for t in metrics.THRESHOLDS for c in metrics.counts_columns(t)]
    return [metrics.total(c) for c in (*metrics.SUMS, *counts) if c in columns]


def _metrics(frame: pl.LazyFrame) -> pl.LazyFrame:
    frame = metrics.continuous_scores(frame)
    columns = set(frame.collect_schema().names())
    for threshold in metrics.THRESHOLDS:
        if set(metrics.counts_columns(threshold)) <= columns:  # no daily rows, no counts
            frame = metrics.categorical_scores(frame, threshold)
    return frame


def aggregate(
    scores: pl.LazyFrame | pl.DataFrame,
    stations: pl.DataFrame,
    as_of: date | None = None,
    windows: tuple[str, ...] = WINDOWS,
    levels: tuple[str, ...] = LEVELS,
) -> pl.DataFrame:
    """One row per level, region, window, variable, lead day and model."""
    scores = scores.lazy()
    first_day, last_day = date_span(scores)
    as_of = as_of or last_day
    info = station_info(stations)
    distance = okres_distances(stations)
    columns = scores.collect_schema().names()
    frames = []
    for window in windows:
        start, days = window_days(window, as_of, first_day)
        in_window = scores.filter(days).join(info, on="station_id", how="inner")
        for level in levels:
            fair = common_days(with_regions(in_window, level, distance), by="region")
            frames.append(
                fair.group_by("region", "region_name", "variable", "lead_day", "model")
                .agg(
                    *_sum_columns(columns),
                    pl.col("station_id").n_unique().alias("stations"),
                    pl.col("station_id").filter("borrowed").n_unique().alias("borrowed"),
                    pl.col("date").n_unique().alias("days"),
                )
                .with_columns(
                    pl.lit(level).alias("level"),
                    pl.lit(window).alias("window"),
                    # the window may start before the first scored day
                    pl.lit(max(start, first_day)).alias("from"),
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
    "borrowed",
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
    "pod_20",
    "far_20",
    "ets_20",
    "pod_30",
    "far_30",
    "ets_30",
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
    3 decimals, small enough for a static web page. Columns that are empty in a file
    (e.g. event scores for temperature) are left out, and so is the native-period
    precipitation, whose periods differ between models (``aggregates.parquet`` keeps it).
    """
    written = []
    out_dir.mkdir(parents=True, exist_ok=True)
    table = table.filter(pl.col("variable") != "precipitation")
    groups = table.partition_by(["window", "level", "variable"], as_dict=True)
    for (window, level, variable), part in sorted(groups.items()):
        columns = [
            c
            for c in JSON_COLUMNS
            if c in part.columns and (c == "region" or part[c].null_count() < part.height)
        ]
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
        "borrow_max_km": neighbours.MAX_KM,
        "precipitation_thresholds_mm": list(metrics.PRECIPITATION_THRESHOLDS),
        "heat_thresholds_c": list(metrics.HEAT_THRESHOLDS),
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


#: Station columns for the web map's dots (``stations.json``).
STATION_COLUMNS = ("id", "name", "lat", "lon", "elevation", "okres_code", "kraj_code", "active")


def write_stations(stations: pl.DataFrame, out_dir: Path) -> Path:
    """``out_dir/stations.json``: position and region of every station, same layout."""
    columns = [c for c in STATION_COLUMNS if c in stations.columns]
    rows = stations.select(
        pl.col(c).round(5) if stations.schema[c].is_float() else pl.col(c) for c in columns
    ).rows()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "stations.json"
    doc = {"columns": columns, "rows": rows}
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path


#: Daily error series per station for the web map's charts (roadmap 4.4)
SERIES_DAYS = 90
SERIES_LEAD_DAYS = (1, 2)


def write_series(
    scores: pl.LazyFrame | pl.DataFrame,
    out_dir: Path,
    as_of: date,
    variables: tuple[str, ...],
) -> list[Path]:
    """``out_dir/series/<station>.json``: each model's daily MAE over the last 90 days.

    ``{"from": …, "to": …, "series": {variable: {lead day: {model: [MAE or null]}}}}``,
    one value per day, rounded to 2 decimals; D+1 and D+2 only, to keep the files small.
    """
    first = as_of - timedelta(days=SERIES_DAYS - 1)
    daily = (
        scores.lazy()
        .filter(
            pl.col("date").is_between(first, as_of),
            pl.col("lead_day").is_in(SERIES_LEAD_DAYS),
            pl.col("variable").is_in(variables),
        )
        .group_by("station_id", "variable", "lead_day", "model", "date")
        .agg((metrics.total("sum_abs_err") / metrics.total("n")).alias("mae"))
        .collect()
    )
    days = [first + timedelta(days=i) for i in range(SERIES_DAYS)]
    folder = out_dir / "series"
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for (station,), part in daily.partition_by("station_id", as_dict=True).items():
        series: dict = {}
        groups = part.partition_by(["variable", "lead_day", "model"], as_dict=True)
        for (variable, lead_day, model), rows in sorted(groups.items()):
            values = dict(zip(rows["date"], rows["mae"], strict=True))
            series.setdefault(variable, {}).setdefault(str(lead_day), {})[model] = [
                None if values.get(d) is None else round(values[d], 2) for d in days
            ]
        doc = {"from": str(first), "to": str(as_of), "series": series}
        path = folder / f"{station}.json"
        path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        written.append(path)
    return written
