"""MeteoVerdict AI v0: gradient-boosted trees (XGBoost on the GPU) that correct the
ensemble median of all models from every model's forecast, the ensemble spread, station
facts, time of day and season, and what was known at issue time (recent error,
persistence). One model per variable for all stations and lead days."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import xgboost as xgb

# no calendar features: with months (not years) of history the trees would tie the
# season's corrections to the date and carry summer's into autumn (v0: +0.35 °C warm)
EXTRA = [
    "n_models", "ens_mean", "ens_median", "ens_std", "ens_min", "ens_max",
    "persist_anom", "bias_3d", "bias_14d",
    "lat", "lon", "elevation", "hour", "lead_day",
]  # fmt: skip
PARAMS = {
    "device": "cuda",
    "tree_method": "hist",
    "objective": "reg:absoluteerror",  # the site's scores are MAE
    "max_depth": 8,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 50,
}
ROUNDS = 400
# recent days count more: the errors change with the season and the weather regime
HALF_LIFE_DAYS = 14


def features(model_cols: list[str]) -> list[str]:
    return [*(f"d_{c}" for c in model_cols), *EXTRA]


def matrix(rows: pl.DataFrame, model_cols: list[str]) -> np.ndarray:
    """Each model as its difference to the ensemble median, then the other features."""
    deviations = [(pl.col(c) - pl.col("ens_median")).alias(f"d_{c}") for c in model_cols]
    return rows.select(*deviations, *EXTRA).to_numpy().astype(np.float32)


def fit(train: pl.DataFrame, model_cols: list[str], issue: date) -> xgb.Booster:
    x = matrix(train, model_cols)
    y = (train["obs"] - train["ens_median"]).to_numpy().astype(np.float32)
    age = train.select((pl.lit(issue) - pl.col("date")).dt.total_days())[:, 0].to_numpy()
    weight = np.power(0.5, age / HALF_LIFE_DAYS).astype(np.float32)
    return xgb.train(PARAMS, xgb.DMatrix(x, label=y, weight=weight, missing=np.nan), ROUNDS)


def predict(booster: xgb.Booster, rows: pl.DataFrame, model_cols: list[str], variable: str):
    x = matrix(rows, model_cols)
    pred = rows["ens_median"].to_numpy() + booster.predict(xgb.DMatrix(x, missing=np.nan))
    if variable == "wind_speed_10m":
        pred = np.maximum(pred, 0.0)
    return rows.with_columns(pl.Series("pred", pred.astype(np.float32)))


VERSION = "v1"
KEYS = ["station_id", "time", "lead_day"]


def hindcast(
    wide: pl.DataFrame,
    cols: list[str],
    variable: str,
    first: date,
    last: date,
    log=print,
    cache: Path | None = None,
) -> pl.DataFrame:
    """Out-of-sample predictions for ``first`` … ``last``, exactly as live: for every
    issue day i one model trained on the days before i, predicting the hours of day
    i + N at lead day N (what the forecast made on day i covers). With ``cache``, the
    predictions of an issue day are kept (``<cache>/<VERSION>/<variable>/<day>.parquet``)
    and reused, so the daily run trains only the new day; an issue day whose target
    days are not all measured yet is not kept."""
    issue_day = pl.col("date") - pl.duration(days=pl.col("lead_day").cast(pl.Int64))
    wide = wide.with_columns(issue_day.alias("_issue_day"))
    max_lead = int(wide["lead_day"].max())
    out = []
    issue = first - timedelta(days=max_lead)
    while issue <= last - timedelta(days=1):
        train = wide.filter((pl.col("date") < issue) & pl.col("obs").is_not_null())
        test = wide.filter((pl.col("_issue_day") == issue) & pl.col("date").is_between(first, last))
        kept = cache / VERSION / variable / f"{issue}.parquet" if cache else None
        if kept is not None and kept.exists():
            out.append(pl.read_parquet(kept).join(test.select(KEYS), on=KEYS, how="semi"))
        elif train.height < 10_000 or test.is_empty():
            log(f"{variable} issued {issue}: skipped ({train.height} training rows)")
        else:
            booster = fit(train, cols, issue)
            pred = predict(booster, test, cols, variable).select(*KEYS, "pred")
            out.append(pred)
            if kept is not None and issue + timedelta(days=max_lead) <= last:
                kept.parent.mkdir(parents=True, exist_ok=True)
                pred.write_parquet(kept)
            log(f"{variable} issued {issue}: trained on {train.height:,} rows, "
                f"{test.height:,} predicted")  # fmt: skip
        issue += timedelta(days=1)
    return pl.concat(out) if out else pl.DataFrame()
