"""Forecast for every obec (roadmap: forecast for a place).

Each model's newest complete run from the bucket at the obec's own grid cell, its
temperature moved from the cell's terrain height to the obec's (``bucket.read_run``),
then combined with the weights and corrections of the obec's okres
(``outlook.combine_hourly``), exactly as the okres's own point. No Open-Meteo calls.

The obce of ``ELEVATIONS_FILE`` (all, about 6,250), read in one pass over the models
(row segments, ``bucket.segments``); one file per okres. The temperature and wind
corrections take the regression's elevation term at the obec's own height (at the
point's half strength, ``combine.POINT_LAPSE_FACTOR``), not at the okres's forecast
point: left out one station at a time this was better for every kind of station,
most in the mountains (docs/methodology.md, ``mvd obce-loso``).
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from meteoverdict import bucket, combine, models, outlook

ELEVATIONS_FILE = "obce-elevations.csv"
#: how far back to look for a model's newest complete run in the bucket
LOOKBACK_H = 30
#: a run younger than this is usually not complete in the bucket yet
MIN_AGE_H = 3
#: ``mvd obce-forecast`` writes ``obce-<okres>.json`` per okres, packed in ``ZIP_NAME``
#: (release data-latest; the site unpacks it into ``data/forecast/``)
NAME = "obce-{code}.json"
ZIP_NAME = "obce.zip"


def places(code: str | None = None) -> pl.DataFrame:
    """``id`` (``<okres>/<name>``), ``okres``, ``name``, ``lat``, ``lon``, ``elevation``,
    ``population`` (ČSÚ, 1 Jan; null where unknown) of the okres ``code``, or of all."""
    source = files("meteoverdict").joinpath("data", ELEVATIONS_FILE)
    with source.open("rb") as f:
        table = pl.read_csv(f.read())
    if code is not None:
        table = table.filter(pl.col("okres") == code)
    return table.select(
        pl.concat_str("okres", pl.lit("/"), "name").alias("id"),
        "okres",
        "name",
        "lat",
        "lon",
        pl.col("elevation").cast(pl.Float64),
        pl.col("population").cast(pl.Int64),
    )


def candidate_runs(model: models.Model, now: datetime) -> list[datetime]:
    """The model's run times from ``MIN_AGE_H`` to ``LOOKBACK_H`` hours ago, newest first."""
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=MIN_AGE_H)
    out = []
    for back in range(LOOKBACK_H - MIN_AGE_H + 1):
        run = start - timedelta(hours=back)
        if run.hour in model.run_hours:
            out.append(run)
    return out


def newest_runs(
    store: bucket.Bucket,
    chosen: list[models.Model],
    points: pl.DataFrame,
    now: datetime,
    log: Callable[[str], None] = lambda _: None,
) -> pl.DataFrame:
    """``runs.SCHEMA`` rows: every model's newest complete run at ``points``."""
    frames = []
    with ThreadPoolExecutor(16) as pool:
        for model in chosen:
            source = bucket.SOURCES.get(model.id)
            if source is None:
                log(f"{model.id}: not in the bucket")
                continue
            names = sorted({b for parts in source.files().values() for b, _ in parts})
            for run in candidate_runs(model, now):
                if store.meta(source.bucket, run) is None:
                    continue
                try:
                    cells = bucket.build_cells(store, points, run, names)
                except FileNotFoundError:
                    continue
                fetched = bucket.read_run(store, model, run, points, cells, pool)
                if fetched.rows is not None:
                    frames.append(fetched.rows)
                    log(f"{model.id}: run {run:%Y-%m-%d %H} UTC")
                    break
                log(f"{model.id}: run {run:%Y-%m-%d %H} UTC skipped ({fetched.reason})")
            else:
                log(f"{model.id}: no complete run in the last {LOOKBACK_H} h")
    return pl.concat(frames) if frames else pl.DataFrame()


def start_of_day(now: datetime) -> datetime:
    """Midnight of ``now``'s Prague day (UTC): the outlook's days start there, so the
    obce keep the day's earlier hours too (the newest runs reach back that far)."""
    local = now.astimezone(ZoneInfo("Europe/Prague"))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def at_obec_height(weights: pl.DataFrame) -> pl.DataFrame:
    """``weights`` (one okres's rows per obec, ``_elevation`` = the obec's height) with
    the slot corrections and ``correction`` taken at the obec's height. Unchanged where
    the regression's elevation term is missing (a weight file from before it was kept,
    no regression, precipitation, an obec without a height): the okres point's."""
    if not set(combine.ELEVATION_TERM_COLUMNS) <= set(weights.columns):
        return weights
    if "_elevation" not in weights.columns:
        return weights
    moved = pl.col("bias_00").is_not_null() & pl.col("_elevation").is_not_null()
    at = combine.slot_corrections(pl.col("_elevation"), combine.POINT_LAPSE_FACTOR)
    return weights.with_columns(
        pl.when(moved).then(expr).otherwise(pl.col(name)).alias(name)
        for expr, name in zip(at, combine.SLOT_CORRECTIONS, strict=True)
    ).with_columns(
        pl.when(moved)
        .then(pl.mean_horizontal(*combine.SLOT_CORRECTIONS))
        .otherwise(pl.col("correction"))
        .alias("correction")
    )


def combined(
    rows: pl.DataFrame, weights: pl.DataFrame, points: pl.DataFrame, now: datetime
) -> pl.DataFrame:
    """One row per obec (``okres`` column = the obec's id) and hour, as
    ``outlook.combine_hourly``, every obec with the weights of its okres (``points``),
    the corrections at the obec's ``elevation`` (``at_obec_height``)."""
    fc = rows.select(
        pl.col("station_id").alias("okres"),
        pl.col("valid_time").alias("time"),
        "model",
        *outlook.COMBINED,
        *[pl.lit(None, pl.Float64).alias(v) for v in outlook.MEANS],
    ).filter(pl.col("time") >= start_of_day(now))
    height = [pl.col("elevation").cast(pl.Float64).alias("_elevation")]
    shared = (
        points.select(
            pl.col("id").alias("region"),
            "okres",
            *(height if "elevation" in points.columns else []),
        )
        .join(weights.rename({"region": "okres"}), on="okres")
        .drop("okres")
    )
    # the elevation term is in the corrections now: no need to carry it per obec and hour
    shared = at_obec_height(shared).drop(
        "_elevation", *combine.ELEVATION_TERM_COLUMNS, strict=False
    )
    return outlook.combine_hourly(fc, shared, now)


def document(
    code: str, points: pl.DataFrame, rows: pl.DataFrame, hourly: pl.DataFrame, now: datetime
) -> dict:
    """The JSON of the page: the places, the hours and per obec the combined series and
    every model's temperature."""
    times = sorted(hourly["time"].unique().to_list())
    index = {t: i for i, t in enumerate(times)}

    def series(frame: pl.DataFrame, column: str, digits: int) -> list:
        out = [None] * len(times)
        for t, v in frame.select("time", column).rows():
            if t in index and v is not None:
                out[index[t]] = round(v, digits)
        return out

    runs = rows.group_by("model").agg(pl.col("run").max()).sort("model")
    by_place = hourly.partition_by("okres", as_dict=True)
    model_rows = rows.rename({"valid_time": "time"}).partition_by("station_id", as_dict=True)
    places_out = []
    for pid, name, lat, lon, elevation, population in points.select(
        "id", "name", "lat", "lon", "elevation", "population"
    ).rows():
        frame = by_place.get((pid,))
        if frame is None:
            continue
        mine = model_rows.get((pid,), pl.DataFrame())
        places_out.append(
            {
                "name": name,
                "lat": lat,
                "lon": lon,
                "elevation": elevation,
                "population": population,
                "temperature_2m": series(frame, "temperature_2m", 1),
                "precipitation": series(frame, "precipitation", 1),
                "wind_speed_10m": series(frame, "wind_speed_10m", 1),
                "models": {
                    m: series(part, "temperature_2m", 1)
                    for (m,), part in sorted(mine.partition_by("model", as_dict=True).items())
                },
            }
        )
    return {
        "okres": code,
        "generated": now.isoformat(timespec="minutes"),
        "runs": {m: r.isoformat(timespec="minutes") for m, r in runs.rows()},
        "times": [t.isoformat(timespec="minutes") for t in times],
        "places": places_out,
    }


def forecast(
    store: bucket.Bucket,
    weights: pl.DataFrame,
    now: datetime | None = None,
    log: Callable[[str], None] = lambda _: None,
    code: str | None = None,
) -> dict[str, dict]:
    """The page's document of every okres (or of ``code``) that has weights."""
    now = now or datetime.now(UTC)
    points = places(code).filter(pl.col("okres").is_in(weights["region"].unique().to_list()))
    wanted = set(
        weights.filter(pl.col("region").is_in(points["okres"].unique().to_list()))["model"]
    )
    chosen = [m for m in models.enabled_models() if m.id in wanted]
    log(f"{points.height} obce in {points['okres'].n_unique()} okresy, {len(chosen)} models")
    rows = newest_runs(store, chosen, points, now, log)
    if rows.is_empty():
        raise RuntimeError("no model run found in the bucket")
    hourly = combined(rows, weights, points, now)
    okres_of = dict(points.select("id", "okres").rows())
    hourly = hourly.with_columns(pl.col("okres").replace_strict(okres_of).alias("_okres"))
    rows = rows.with_columns(pl.col("station_id").replace_strict(okres_of).alias("_okres"))
    by_okres = {k[0]: v for k, v in hourly.partition_by("_okres", as_dict=True).items()}
    rows_by_okres = {k[0]: v for k, v in rows.partition_by("_okres", as_dict=True).items()}
    docs = {}
    for (okres,), own in sorted(points.partition_by("okres", as_dict=True).items()):
        if okres in by_okres:
            docs[okres] = document(okres, own, rows_by_okres[okres], by_okres[okres], now)
    return docs


def write(doc: dict, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / NAME.format(code=doc["okres"])
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    return path


def write_zip(paths: list[Path], path: Path) -> Path:
    """The okres files in one zip (one release asset instead of 77)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, p.name)
    return path
