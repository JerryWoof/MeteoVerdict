"""MeteoVerdict AI's live forecast per okres: the next days' hourly forecasts of every
model at the okres's forecast point (``outlook-models.zip`` from the release
data-latest, the same the Forecast tab shows), corrected by the model trained on all
days before today at each of the okres's stations (with that station's position,
elevation, recent error and the measured value at the issue hour), then averaged over
those stations: the AI counterpart of the combined forecast, which is also judged at
the okres's stations."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from meteoverdict import mos
from meteoverdict.blendtest import SCORE_VARIABLES
from mvai import data, gbm

#: the lead days the model is trained on; hours closer than a day take D+1
LEADS = (1, 5)


def okres_forecasts(path: Path) -> dict[str, dict]:
    """The okres files of ``outlook-models.zip`` by okres code."""
    with zipfile.ZipFile(path) as z:
        return {Path(n).stem: json.loads(z.read(n)) for n in z.namelist() if n.endswith(".json")}


def point_rows(doc: dict, variable: str, issued: datetime) -> pl.DataFrame:
    """One row per future hour of one okres: ``m_<model>`` and the lead day."""
    times = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in doc["time"]]
    columns = {"time": times}
    for model, values in doc["models"].items():
        series = values.get(variable)
        if series is not None and len(series) == len(times):
            columns[f"m_{model}"] = [np.nan if v is None else float(v) for v in series]
    rows = pl.DataFrame(columns).with_columns(pl.col("time").dt.cast_time_unit("us"))
    hours = (pl.col("time") - pl.lit(issued)).dt.total_hours()
    lead = (hours // 24).clip(*LEADS).cast(pl.Int8)
    return rows.filter(pl.col("time") > pl.lit(issued)).with_columns(lead.alias("lead_day"))


def station_context(
    wide: pl.DataFrame, measured: pl.DataFrame, stations: pl.DataFrame, issued: datetime
) -> pl.DataFrame:
    """Per station and hour of the day, what was known at ``issued``: the latest
    ``bias_<k>d`` and the last measured value at that hour, plus the station facts."""
    bias_cols = [f"bias_{k}d" for k in data.BIAS_DAYS]
    latest = (
        wide.filter(pl.col("time") <= pl.lit(issued))
        .drop_nulls(bias_cols[-1:])
        .sort("time")
        .group_by("station_id", pl.col("time").dt.hour().alias("hour"))
        .agg(pl.col(c).last() for c in bias_cols)
    )
    last_obs = (
        measured.filter(pl.col("time") <= pl.lit(issued))
        .sort("time")
        .group_by("station_id", pl.col("time").dt.hour().alias("hour"))
        .agg(pl.col("obs").last().alias("persist"))
    )
    facts = stations.select(
        pl.col("id").alias("station_id"),
        pl.col("lat").cast(pl.Float32),
        pl.col("lon").cast(pl.Float32),
        pl.col("elevation").cast(pl.Float32),
    )
    return latest.join(last_obs, on=["station_id", "hour"], how="left").join(facts, on="station_id")


def forecast(
    booster,
    cols: list[str],
    variable: str,
    docs: dict[str, dict],
    pools: pl.DataFrame,
    context: pl.DataFrame,
    issued: datetime,
) -> pl.DataFrame:
    """``okres``, ``time``, ``ai`` (the mean of the station predictions) and ``combined``
    (the Forecast tab's value at the point, for comparison)."""
    parts = []
    for okres, doc in docs.items():
        members = (
            pools.filter(
                (pl.col("region") == okres) & (pl.col("variable") == SCORE_VARIABLES[variable])
            )
            .select("station_id")
            .unique()
        )
        if members.is_empty():
            continue
        point = point_rows(doc, variable, issued)
        if point.is_empty():
            continue
        for c in cols:
            if c not in point.columns:
                point = point.with_columns(pl.lit(np.nan, pl.Float32).alias(c))
        members_now = pl.concat_list(cols).list.eval(pl.element().filter(pl.element().is_not_nan()))
        point = point.with_columns(
            members_now.list.len().alias("n_models"),
            members_now.list.mean().cast(pl.Float32).alias("ens_mean"),
            members_now.list.median().cast(pl.Float32).alias("ens_median"),
            members_now.list.std().cast(pl.Float32).alias("ens_std"),
            members_now.list.min().cast(pl.Float32).alias("ens_min"),
            members_now.list.max().cast(pl.Float32).alias("ens_max"),
            pl.col("time").dt.hour().cast(pl.Int8).alias("hour"),
        ).filter(pl.col("n_models") >= 3)
        rows = (
            point.join(members, how="cross")
            .join(context, on=["station_id", "hour"], how="inner")
            .with_columns((pl.col("persist") - pl.col("ens_median")).alias("persist_anom"))
        )
        if rows.is_empty():
            continue
        pred = gbm.predict(booster, rows, cols, variable)
        mean = pred.group_by("time").agg(pl.col("pred").mean().alias("ai"))
        times = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in doc["time"]]
        combined = doc.get("combined", {}).get(variable) or [None] * len(times)
        comb = pl.DataFrame(
            {"time": times, "combined": combined},
            schema={"time": pl.Datetime("us", "UTC"), "combined": pl.Float64},
        )
        parts.append(
            mean.join(comb, on="time", how="left").with_columns(pl.lit(okres).alias("okres"))
        )
    return pl.concat(parts).sort("okres", "time") if parts else pl.DataFrame()


def document(
    frames: dict[str, pl.DataFrame], issued: datetime, generated: str, names: dict[str, str]
) -> dict:
    """``ai-forecast.json``: per okres the hourly times and, per variable, the AI and
    the combined values (rounded to 0.1)."""
    okresy: dict[str, dict] = {}
    for variable, frame in frames.items():
        for (okres,), part in frame.group_by("okres"):
            part = part.sort("time")
            entry = okresy.setdefault(okres, {"name": names.get(okres, okres), "time": None})
            times = [t.strftime("%Y-%m-%dT%H:%MZ") for t in part["time"]]
            if entry["time"] is None:
                entry["time"] = times
            # align on the first variable's hours
            values = dict(zip(times, zip(part["ai"], part["combined"], strict=True), strict=True))
            entry[variable] = {
                "ai": [_round(values.get(t, (None, None))[0]) for t in entry["time"]],
                "combined": [_round(values.get(t, (None, None))[1]) for t in entry["time"]],
            }
    return {"generated": generated, "issued": issued.isoformat(), "okresy": okresy}


def _round(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 1)


def pools_of(scores_dir: Path, stations: pl.DataFrame, since: datetime) -> pl.DataFrame:
    """Each okres's stations (own and borrowed) per score variable, as the ranking."""
    files = sorted(scores_dir.glob("*.parquet"))
    scores = pl.concat([pl.scan_parquet(f) for f in files], how="diagonal_relaxed").filter(
        pl.col("date") >= since.date() - timedelta(days=30)
    )
    return mos.pools(scores, stations)
