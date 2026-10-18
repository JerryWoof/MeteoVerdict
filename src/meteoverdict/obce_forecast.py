"""Forecast for every obec of an okres (test, roadmap: forecast for a place).

Each model's newest complete run from the bucket at the obec's own grid cell, its
temperature moved from the cell's terrain height to the obec's (``bucket.read_run``),
then combined with the weights and corrections of the obec's okres
(``outlook.combine_hourly``), exactly as the okres's own point. No Open-Meteo calls.

Only the okresy in ``ELEVATIONS_FILE`` (Litoměřice for now). The corrections are those
at the okres's forecast point (their elevation term is not moved to the obec).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from meteoverdict import bucket, models, outlook

ELEVATIONS_FILE = "obce-elevations.csv"
#: how far back to look for a model's newest complete run in the bucket
LOOKBACK_H = 30
#: a run younger than this is usually not complete in the bucket yet
MIN_AGE_H = 3
#: ``mvd obce-forecast`` writes ``obce-<okres>.json`` (release data-latest, site
#: ``data/forecast/obce/``)
NAME = "obce-{code}.json"


def places(code: str) -> pl.DataFrame:
    """``id`` (the obec's name), ``lat``, ``lon``, ``elevation``, ``population`` (ČSÚ, 1 Jan;
    null where unknown) of the okres ``code``."""
    source = files("meteoverdict").joinpath("data", ELEVATIONS_FILE)
    with source.open("rb") as f:
        table = pl.read_csv(f.read())
    return table.filter(pl.col("okres") == code).select(
        pl.col("name").alias("id"),
        "lat",
        "lon",
        pl.col("elevation").cast(pl.Float64),
        pl.col("population").cast(pl.Int64),
    )


def okresy() -> list[str]:
    source = files("meteoverdict").joinpath("data", ELEVATIONS_FILE)
    with source.open("rb") as f:
        return sorted(pl.read_csv(f.read())["okres"].unique().to_list())


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


def combined(rows: pl.DataFrame, weights: pl.DataFrame, code: str, now: datetime) -> pl.DataFrame:
    """One row per obec (``okres`` column = obec) and hour, as ``outlook.combine_hourly``,
    every obec with the weights of the okres ``code``."""
    fc = rows.select(
        pl.col("station_id").alias("okres"),
        pl.col("valid_time").alias("time"),
        "model",
        *outlook.COMBINED,
        *[pl.lit(None, pl.Float64).alias(v) for v in outlook.MEANS],
    ).filter(pl.col("time") >= start_of_day(now))
    own = weights.filter(pl.col("region") == code)
    obce = pl.DataFrame({"region": rows["station_id"].unique()})
    shared = obce.join(own.drop("region"), how="cross")
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
    for pid, lat, lon, elevation, population in points.select(
        "id", "lat", "lon", "elevation", "population"
    ).rows():
        frame = by_place.get((pid,))
        if frame is None:
            continue
        mine = model_rows.get((pid,), pl.DataFrame())
        places_out.append(
            {
                "name": pid,
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
        "test": True,
        "runs": {m: r.isoformat(timespec="minutes") for m, r in runs.rows()},
        "times": [t.isoformat(timespec="minutes") for t in times],
        "places": places_out,
    }


def forecast(
    store: bucket.Bucket,
    weights: pl.DataFrame,
    code: str,
    now: datetime | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> dict:
    now = now or datetime.now(UTC)
    points = places(code)
    wanted = set(weights.filter(pl.col("region") == code)["model"].unique().to_list())
    chosen = [m for m in models.enabled_models() if m.id in wanted]
    rows = newest_runs(store, chosen, points, now, log)
    if rows.is_empty():
        raise RuntimeError(f"{code}: no model run found in the bucket")
    hourly = combined(rows, weights, code, now)
    return document(code, points, rows, hourly, now)


def write(doc: dict, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / NAME.format(code=doc["okres"])
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    return path
