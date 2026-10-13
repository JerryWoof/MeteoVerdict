"""Run-based verification of ALADIN by lead hour (H+1 … H+72).

The D+N scores (``scoring``) take Open-Meteo's ``_previous_dayN``: for each hour the
value of a run at least 24·N hours older, so they say nothing about the first hours of
a run. Here we take every archived ALADIN run (``aladin``: station values for steps
0-72 h), pair each lead hour with the observation at its valid time (run + lead) and
average the errors by lead hour:

* ``temperature_2m``, ``wind_speed_10m``: the instant value at the valid time against
  the observation at that full hour;
* ``precipitation``: the difference of the accumulated precipitation between lead
  ``h - 1`` and ``h`` (lead 0 has no accumulation, so lead 1 is its accumulation), i.e.
  mm in the hour ending at the valid time, against the observed hourly sum ending
  there. Small negative differences (GRIB packing) count as 0.

Lead 0 (the analysis) is not scored. Both domains are compared on the same sample:
only the run, station, lead hour and variable that every model in the data has a pair
for. Sums are kept additive (``metrics``), so MAE, bias and RMSE come from the sums
of each group. See docs/methodology.md#run-based-verification-by-lead-hour.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from meteoverdict import metrics

VARIABLES = ("temperature_2m", "wind_speed_10m", "precipitation")
MAX_LEAD_H = 72
#: Hourly precipitation event: at least 0.1 mm in the hour.
THRESHOLD = 0.1
RUN_HOURS = ("00", "06", "12", "18")

UNITS = {
    "temperature_2m": "°C, instant value at the valid time",
    "wind_speed_10m": "m/s, instant value at the valid time",
    "precipitation": "mm in the hour ending at the valid time",
}

#: Archive file name: ``<model>_<YYYYMMDDHH>.parquet`` (see ``aladin.archive_name``).
ARCHIVE_NAME = re.compile(r"^(?P<model>[a-z0-9_]+)_(?P<run>\d{10})\.parquet$")

FORECAST_COLUMNS = ["model", "run", "lead_h", "station_id", "valid_time"]
PAIR_KEYS = ["run", "station_id", "lead_h", "variable"]
COUNTS = metrics.counts_columns(THRESHOLD)  # a_0p1 (hits), b_ (false alarms), c_ (misses), d_
COLUMNS = [
    "region", "run_hour", "model", "variable", "lead_h",
    "runs", "stations", "n", "mae", "bias", "rmse", *COUNTS,
]  # fmt: skip


def run_of(name: str) -> tuple[str, datetime] | None:
    """``(model, run time)`` of an archive file name, or None for other files."""
    match = ARCHIVE_NAME.match(name)
    if match is None:
        return None
    run = datetime.strptime(match["run"], "%Y%m%d%H").replace(tzinfo=UTC)
    return match["model"], run


def archive_files(folder: Path, since: datetime | None = None) -> list[Path]:
    """Archived runs under ``folder/<tag>/`` (the ``aladin.LocalStore`` layout), from
    ``since`` on, sorted by name."""
    found = []
    for path in sorted(folder.glob("aladin-*/*.parquet")):
        parsed = run_of(path.name)
        if parsed is not None and (since is None or parsed[1] >= since):
            found.append(path)
    return found


def download_archive(store, folder: Path, months: list[str], since: datetime, log=print) -> int:
    """Download the archived runs from ``since`` on from the releases ``aladin-YYYY-MM``
    of ``months`` into ``folder/<tag>/``; files already there with the same size are
    kept (an archived run never changes). Returns the number downloaded."""
    done = 0
    for month in months:
        tag = f"aladin-{month}"
        for name, asset in sorted(store.assets(tag).items()):
            parsed = run_of(name)
            if parsed is None or parsed[1] < since:
                continue
            path = folder / tag / name
            if path.exists() and path.stat().st_size == asset.get("size"):
                continue
            store.download(tag, name, path)
            done += 1
    log(f"downloaded {done} archived ALADIN runs")
    return done


def read_archive(files: list[Path]) -> pl.LazyFrame:
    """The archived runs as one frame; files written before ``published`` existed get
    null there."""
    frames = [pl.scan_parquet(p) for p in files]
    return pl.concat(frames, how="diagonal_relaxed")


def forecast_hours(archive: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Archive rows → one row per model, run, lead hour 1…72, station and variable with
    the ``forecast`` value (hourly precipitation from the accumulation)."""
    run_keys = ["model", "run", "station_id"]
    frame = (
        archive.lazy()
        .filter(pl.col("lead_h").is_between(0, MAX_LEAD_H))
        .sort([*run_keys, "lead_h"])
        .with_columns(
            pl.col("precipitation_accum").shift(1).over(run_keys).alias("_prev"),
            pl.col("lead_h").shift(1).over(run_keys).alias("_prev_lead"),
        )
        .with_columns(
            pl.when(pl.col("lead_h") == 1)
            .then(pl.col("precipitation_accum"))
            .when(pl.col("_prev_lead") == pl.col("lead_h") - 1)
            .then(pl.col("precipitation_accum") - pl.col("_prev"))
            .otherwise(None)
            .clip(lower_bound=0.0)
            .alias("precipitation")
        )
        .filter(pl.col("lead_h") >= 1)
    )
    return (
        frame.select(*FORECAST_COLUMNS, *VARIABLES)
        .unpivot(index=FORECAST_COLUMNS, variable_name="variable", value_name="forecast")
        .with_columns(pl.col("forecast").cast(pl.Float64), pl.col("lead_h").cast(pl.Int16))
        .drop_nulls("forecast")
    )


def pairs(
    forecasts: pl.LazyFrame | pl.DataFrame, observations: pl.LazyFrame | pl.DataFrame
) -> pl.DataFrame:
    """Forecast-observation pairs on station, valid time and variable, restricted to the
    sample every model has (same runs, stations, lead hours and variables)."""
    obs = (
        observations.lazy()
        .filter(pl.col("variable").is_in(VARIABLES))
        .select(
            "station_id",
            pl.col("time").alias("valid_time"),
            "variable",
            pl.col("value").cast(pl.Float64).alias("observed"),
        )
        .unique(["station_id", "valid_time", "variable"], keep="first")
    )
    joined = forecasts.lazy().join(obs, on=["station_id", "valid_time", "variable"])
    n_models = forecasts.lazy().select(pl.col("model").n_unique()).collect().item()
    return (
        joined.filter(pl.col("model").n_unique().over(PAIR_KEYS) == n_models)
        .with_columns(pl.col("run").dt.strftime("%H").alias("run_hour"))
        .collect()
    )


def _scores(pairs_: pl.DataFrame, by: list[str]) -> pl.DataFrame:
    rain = pl.col("variable") == "precipitation"
    counts = metrics.contingency_counts(THRESHOLD)
    table = pairs_.group_by(by).agg(
        pl.col("run").n_unique().alias("runs"),
        pl.col("station_id").n_unique().alias("stations"),
        *metrics.error_sums(),
        *counts,
    )
    return metrics.continuous_scores(table).with_columns(
        pl.when(rain).then(pl.col(c)).otherwise(None).alias(c) for c in COUNTS
    )


def lead_scores(pairs_: pl.DataFrame, stations: pl.DataFrame | None = None) -> pl.DataFrame:
    """Scores by lead hour: Czechia (``region`` "cz") for all runs (``run_hour``
    "all") and for each run hour, and, with a station table, each kraj for all runs
    (``region`` = kraj code, plus ``region_name``)."""
    keys = ["model", "variable", "lead_h"]
    all_runs = pairs_.with_columns(pl.lit("all").alias("run_hour"))
    frames = [
        _scores(
            pl.concat([all_runs, pairs_.select(all_runs.columns)]), ["run_hour", *keys]
        ).with_columns(pl.lit("cz").alias("region"), pl.lit("Česko").alias("region_name"))
    ]
    if stations is not None and {"kraj_code", "kraj"} <= set(stations.columns):
        by_kraj = all_runs.join(
            stations.select(
                pl.col("id").alias("station_id"),
                pl.col("kraj_code").alias("region"),
                pl.col("kraj").alias("region_name"),
            ),
            on="station_id",
        ).drop_nulls("region")
        frames.append(_scores(by_kraj, ["region", "region_name", "run_hour", *keys]))
    order = {h: i for i, h in enumerate(["all", *RUN_HOURS])}
    return (
        pl.concat(frames, how="diagonal_relaxed")
        .with_columns(pl.col("run_hour").replace_strict(order, return_dtype=pl.Int8).alias("_o"))
        .sort("region", "_o", "model", "variable", "lead_h")
        .drop("_o")
    )


def publication_delays(archive: pl.LazyFrame | pl.DataFrame) -> dict[str, float | None]:
    """Median hours from run start to publication per model (null before ``published``
    was recorded)."""
    frame = archive.lazy()
    if "published" not in frame.collect_schema().names():
        frame = frame.with_columns(pl.lit(None, pl.Datetime("us", "UTC")).alias("published"))
    runs = (
        frame.select("model", "run", "published")
        .unique(["model", "run"])
        .group_by("model")
        .agg(
            ((pl.col("published") - pl.col("run")).dt.total_seconds() / 3600)
            .median()
            .alias("delay")
        )
        .collect()
    )
    return {m: None if d is None else round(d, 2) for m, d in runs.iter_rows()}


def document(
    table: pl.DataFrame,
    pairs_: pl.DataFrame,
    generated: datetime,
    delays: dict[str, float | None] | None = None,
    names: dict[str, str] | None = None,
) -> dict:
    """``leads.json`` / ``leads-kraj.json``: header and ``{"columns", "rows"}``."""
    regions = (
        dict(table.select("region", "region_name").unique().sort("region").iter_rows())
        if table.height
        else {}
    )
    rounded = table.select(
        pl.col(c).round(3) if c in ("mae", "bias", "rmse") else pl.col(c) for c in COLUMNS
    )
    models = {}
    for model in sorted(pairs_["model"].unique().to_list()) if pairs_.height else []:
        mine = pairs_.filter(pl.col("model") == model)
        models[model] = {
            "name": (names or {}).get(model, model),
            "runs": mine["run"].n_unique(),
            "pairs": mine.height,
            "publication_delay_h": (delays or {}).get(model),
        }
    runs = pairs_["run"] if pairs_.height else pl.Series([], dtype=pl.Datetime("us", "UTC"))
    stamp = "%Y-%m-%dT%H:%MZ"
    return {
        "generated": generated.strftime(stamp),
        "about": (
            "ALADIN verified run by run: each lead hour H+1…H+72 of every archived run "
            "against the ČHMÚ station observation at its valid time (run + lead). Both "
            "domains on the same runs, stations and hours. Not the D+N scores."
        ),
        "first_run": runs.min().strftime(stamp) if runs.len() else None,
        "last_run": runs.max().strftime(stamp) if runs.len() else None,
        "models": models,
        "variables": UNITS,
        "regions": regions,
        "column_notes": {
            "region": "cz (Czechia) or a kraj code (NUTS 3)",
            "run_hour": "all, or the run's start hour in UTC (00, 06, 12, 18)",
            "lead_h": "hours after the run's start; the valid time is run + lead_h",
            "runs": "runs with at least one pair",
            "stations": "stations with at least one pair",
            "n": "pairs (station x run)",
            "mae, bias, rmse": "forecast - observed, in the variable's unit",
            f"{COUNTS[0]}, {COUNTS[1]}, {COUNTS[2]}, {COUNTS[3]}": (
                f"precipitation >= {THRESHOLD} mm in the hour: hits, false alarms, misses, "
                "correct negatives (null for other variables)"
            ),
        },
        "columns": COLUMNS,
        "rows": rounded.rows(),
    }


def summary(table: pl.DataFrame, variable: str = "temperature_2m", hours=(1, 6, 12, 24, 48, 72)):
    """Lines like ``chmi_aladin_cz_1km  H+1 0.81 (12 runs, 5,400 pairs) …`` for Czechia."""
    cz = table.filter(
        pl.col("region") == "cz", pl.col("run_hour") == "all", pl.col("variable") == variable
    )
    lines = []
    for model in sorted(cz["model"].unique().to_list()):
        parts = []
        for h in hours:
            row = cz.filter(pl.col("model") == model, pl.col("lead_h") == h)
            if row.height:
                r = row.row(0, named=True)
                parts.append(f"H+{h} {r['mae']:.2f} ({r['runs']} runs, {r['n']:,} pairs)")
        lines.append(f"{model}: {variable} MAE " + "; ".join(parts))
    return lines


def write(doc: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path
