"""The training table: one row per station, valid hour and lead day, with every model's
forecast of a variable side by side (wide), the ensemble statistics, station facts and
what was known when the forecast was made (the station's recent error, persistence)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from meteoverdict import daily as daily_mod
from meteoverdict import models as catalogue
from meteoverdict import observations, partitions

VARIABLES = ("temperature_2m", "wind_speed_10m")
# days of a station's recent error of the ensemble median (known at issue time)
BIAS_DAYS = (3, 14)


def load(data_dir: Path, first: date, last: date, log=print) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """``(fc, obs)`` for ``first`` … ``last`` as ``mvd blend-test`` reads them: the stored
    D+N forecasts plus the recent days rebuilt from the single runs."""
    end = last + timedelta(days=1)
    obs = observations.scan(data_dir, first, end)
    fc = partitions.scan_months(data_dir / "fc", first, end)
    enabled = [m for m in catalogue.load_models() if m.enabled]
    fc, _ = daily_mod.add_fresh(data_dir, enabled, last, obs, fc, log)
    if obs is None or fc is None:
        raise SystemExit("no observations or forecasts")
    return fc, obs


def table(
    fc: pl.LazyFrame, obs: pl.LazyFrame, stations: pl.DataFrame, variable: str
) -> tuple[pl.DataFrame, list[str]]:
    """Wide rows of one variable and the model columns (``m_<model>``), with ``obs``
    (null where nothing was measured: rows to predict only)."""
    models = sorted(
        fc.filter(pl.col(variable).is_not_null()).select("model").unique().collect()["model"]
    )
    long = fc.filter(pl.col("model").is_in(models) & pl.col(variable).is_not_null()).select(
        "station_id", "time", "lead_day", "model", pl.col(variable).cast(pl.Float32)
    )
    wide = long.collect().pivot(
        on="model", index=["station_id", "time", "lead_day"], values=variable
    )
    cols = [f"m_{m}" for m in models]
    wide = wide.rename({m: f"m_{m}" for m in models if m in wide.columns})
    for c in cols:
        if c not in wide.columns:
            wide = wide.with_columns(pl.lit(None, pl.Float32).alias(c))
    members = pl.concat_list(cols).list.drop_nulls()
    wide = wide.with_columns(
        members.list.len().alias("n_models"),
        members.list.mean().cast(pl.Float32).alias("ens_mean"),
        members.list.median().cast(pl.Float32).alias("ens_median"),
        members.list.std().cast(pl.Float32).alias("ens_std"),
        members.list.min().alias("ens_min"),
        members.list.max().alias("ens_max"),
    ).filter(pl.col("n_models") >= 3)
    measured = (
        obs.filter(pl.col("variable") == variable)
        .select("station_id", "time", pl.col("value").cast(pl.Float32).alias("obs"))
        .collect()
        .unique(["station_id", "time"])
    )
    wide = wide.join(measured, on=["station_id", "time"], how="left")
    # persistence: the value measured at the same hour lead_day days earlier
    past = measured.rename({"obs": "persist"})
    wide = wide.with_columns(
        (pl.col("time") - pl.duration(days=pl.col("lead_day").cast(pl.Int64))).alias("_issue")
    ).join(past, left_on=["station_id", "_issue"], right_on=["station_id", "time"], how="left")
    wide = wide.with_columns((pl.col("persist") - pl.col("ens_median")).alias("persist_anom"))
    wide = recent_bias(wide)
    facts = stations.select(
        pl.col("id").alias("station_id"),
        pl.col("lat").cast(pl.Float32),
        pl.col("lon").cast(pl.Float32),
        pl.col("elevation").cast(pl.Float32),
    )
    doy = pl.col("time").dt.ordinal_day().cast(pl.Float32) * (2 * np.pi / 365.25)
    wide = wide.join(facts, on="station_id", how="left").with_columns(
        pl.col("time").dt.hour().cast(pl.Int8).alias("hour"),
        doy.sin().alias("doy_sin"),
        doy.cos().alias("doy_cos"),
        pl.col("time").dt.date().alias("date"),
    )
    return wide.drop("_issue"), cols


def recent_bias(wide: pl.DataFrame) -> pl.DataFrame:
    """``bias_<k>d``: the station's mean error (measured minus ensemble median) at the
    same hour over the k days up to the issue day (valid day minus lead day), from the
    D+1 forecasts, so only what was known when the forecast was made."""
    err = (
        wide.filter((pl.col("lead_day") == 1) & pl.col("obs").is_not_null())
        .select(
            "station_id",
            pl.col("time").dt.hour().alias("hour"),
            pl.col("time").dt.date().alias("day"),
            (pl.col("obs") - pl.col("ens_median")).alias("err"),
        )
        .sort("station_id", "hour", "day")
    )
    days = pl.date_range(err["day"].min(), err["day"].max(), eager=True).alias("day")
    grid = (
        err.select("station_id", "hour").unique().join(days.to_frame(), how="cross")
        .join(err, on=["station_id", "hour", "day"], how="left")
        .sort("station_id", "hour", "day")
    )  # fmt: skip
    for k in BIAS_DAYS:
        grid = grid.with_columns(
            pl.col("err")
            .rolling_mean(window_size=k, min_samples=max(1, k // 3))
            .over("station_id", "hour")
            .cast(pl.Float32)
            .alias(f"bias_{k}d")
        )
    known = grid.drop("err")
    issue_day = pl.col("time").dt.date() - pl.duration(days=pl.col("lead_day").cast(pl.Int64))
    return (
        wide.with_columns(issue_day.alias("_day"), pl.col("time").dt.hour().alias("_hour"))
        .join(known, left_on=["station_id", "_hour", "_day"],
              right_on=["station_id", "hour", "day"], how="left")
        .drop("_day", "_hour")
    )  # fmt: skip


def as_forecasts(rows: pl.DataFrame, variable: str, model: str) -> pl.DataFrame:
    """Predictions (``pred``) in the forecast table's layout (``forecasts.SCHEMA``)."""
    return rows.select(
        "station_id",
        "time",
        pl.lit(model).alias("model"),
        pl.col("lead_day").cast(pl.Int8),
        pl.col("pred").cast(pl.Float32).alias(variable),
    )


def midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)
