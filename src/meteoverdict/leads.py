"""Run-based verification by lead hour: every model (H+1 … H+120) and ALADIN alone.

The D+N scores (``scoring``) take Open-Meteo's ``_previous_dayN``: for each hour the
value of a run at least 24·N hours older, so they say nothing about the first hours of
a run. Here each lead hour of a run is paired with the observation at its valid time
(run + lead), and errors are averaged by lead hour. Two sources:

**All models** (``run_lead_scores``, ``leads.json``): the single runs from Open-Meteo
(``runs``: ~100 stations, 00/06/12/18 UTC, leads 1-120, at the station elevation).
Temperature and wind are instant values at the valid time, precipitation is
Open-Meteo's hourly value (mm in the hour ending at the valid time). Only a model's
native output hours are scored (``Model.native_hour``; hourly precipitation only where
the output is hourly). The **fair set**: for each lead hour, variable and run hour,
the models compared are those that reach that lead (their usual run length for that
run hour, from the data); only the (run, station) pairs that every one of them has are
used. So the set of models shrinks with the lead hour as short models end; for "all"
run hours a model must reach the lead in every run hour.

**ALADIN from our own archive** (``forecast_hours``/``pairs``, ``leads-aladin.json``):
every archived ALADIN run (``aladin``: station values for steps 0-72 h, nearest grid
point, no elevation correction):

* ``temperature_2m``, ``wind_speed_10m``: the instant value at the valid time against
  the observation at that full hour;
* ``precipitation``: the difference of the accumulated precipitation between lead
  ``h - 1`` and ``h`` (lead 0 has no accumulation, so lead 1 is its accumulation), i.e.
  mm in the hour ending at the valid time, against the observed hourly sum ending
  there. Small negative differences (GRIB packing) count as 0.

Both domains are compared on the same sample there: only the run, station, lead hour
and variable that every model in the data has a pair for. The archive also records when
ČHMÚ published each run (``publication_delays``), shown on the all-model chart.

**Ranking by lead band** (``band_rankings``, ``leads-bands-<window>[-kraj].json``): the
same single runs pooled over H+1-6, H+7-12, H+13-24, H+25-48 and H+49-72, on two fair
sets per band (``band_required``), with bias-corrected MAE, hourly precipitation ETS,
gusts and bootstrap intervals over days, for Czechia, the station kinds and kraje.

Lead 0 (the analysis) is not scored. Sums are kept additive (``metrics``), so MAE, bias
and RMSE come from the sums of each group.
See docs/methodology.md#run-based-verification-by-lead-hour.
"""

from __future__ import annotations

import json
import re
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from meteoverdict import metrics, partitions
from meteoverdict import runs as runs_mod
from meteoverdict.models import Model
from meteoverdict.stations import MAIN_PREFIX

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


# --- every model, from Open-Meteo's single runs (``runs``) ---------------------------

#: Group keys of the all-model table (``stratum`` is written as ``run_hour``).
RUN_KEYS = ["stratum", "model", "variable", "lead_h"]
RUN_INDEX = ["run", "model", "station_id", "lead_h", "valid_time"]
#: Columns of ``leads.json`` rows (Czechia only, so no region columns).
RUN_COLUMNS = [c for c in COLUMNS if c != "region"]


def scan_runs(folder: Path, since: datetime, until: datetime) -> pl.LazyFrame | None:
    """The single runs (``runs/YYYY-MM.parquet``) started from ``since`` to ``until``."""
    frame = partitions.scan_months(folder, since.date(), until.date())
    if frame is None:
        return None
    return frame.filter(pl.col("run").is_between(since, until))


def horizons(forecasts: pl.LazyFrame | pl.DataFrame) -> pl.DataFrame:
    """``model``, ``run_hour``, ``horizon_h``: the usual last lead hour of each model's
    runs of each run hour (median over runs of the last lead with temperature)."""
    return (
        forecasts.lazy()
        .filter(pl.col("temperature_2m").is_not_null())
        .group_by("model", "run")
        .agg(pl.col("lead_h").max().alias("last"))
        .with_columns(pl.col("run").dt.strftime("%H").alias("run_hour"))
        .group_by("model", "run_hour")
        .agg(pl.col("last").median().floor().cast(pl.Int16).alias("horizon_h"))
        .sort("model", "run_hour")
        .collect()
    )


def _native(model: Model | None, lead_h: int, variable: str) -> bool:
    if model is None:
        return True
    if variable == "precipitation":  # hourly sums only where the output is hourly
        return model.step_at(lead_h) == 1
    return model.native_hour(lead_h)


def required(horizon_table: pl.DataFrame, models: list[Model]) -> pl.DataFrame:
    """The fair set's models: ``stratum`` (run hour or "all"), ``lead_h``, ``variable``,
    ``model`` for every model that reaches the lead with native output, and
    ``n_required`` (their number)."""
    catalogue = {m.id: m for m in models}
    reach: dict[tuple[str, str], int] = {
        (m, h): int(n) for m, h, n in horizon_table.select("model", "run_hour", "horizon_h").rows()
    }
    hours = sorted({h for _, h in reach})
    by_stratum: dict[str, dict[str, int]] = {}
    for (model, hour), last in reach.items():
        by_stratum.setdefault(hour, {})[model] = last
    for model in {m for m, _ in reach}:
        by_stratum.setdefault("all", {})[model] = min(reach.get((model, h), 0) for h in hours)
    rows = [
        (stratum, lead, variable, model)
        for stratum, lasts in by_stratum.items()
        for model, last in lasts.items()
        for lead in range(1, min(last, runs_mod.MAX_LEAD_H) + 1)
        for variable in VARIABLES
        if _native(catalogue.get(model), lead, variable)
    ]
    table = pl.DataFrame(
        rows,
        schema={
            "stratum": pl.String,
            "lead_h": pl.Int16,
            "variable": pl.String,
            "model": pl.String,
        },
        orient="row",
    )
    return table.with_columns(
        pl.len().over("stratum", "lead_h", "variable").cast(pl.UInt32).alias("n_required")
    )


def run_pairs(
    forecasts: pl.DataFrame, observations: pl.DataFrame, required_: pl.DataFrame
) -> pl.DataFrame:
    """Forecast-observation pairs of some runs in the fair set, once per stratum (the
    run's own hour and "all"): only required models, only (run, station, lead,
    variable) that all of them have."""
    long = (
        forecasts.lazy()
        .unpivot(
            index=RUN_INDEX, on=list(VARIABLES), variable_name="variable", value_name="forecast"
        )
        .drop_nulls("forecast")
        .with_columns(pl.col("forecast").cast(pl.Float64), pl.col("lead_h").cast(pl.Int16))
        .join(observations.lazy(), on=["station_id", "valid_time", "variable"])
    )
    found = []
    for stratum in (pl.col("run").dt.strftime("%H"), pl.lit("all")):
        found.append(
            long.with_columns(stratum.alias("stratum"))
            .join(required_.lazy(), on=["stratum", "lead_h", "variable", "model"])
            .filter(
                pl.len().over("stratum", "run", "station_id", "lead_h", "variable")
                == pl.col("n_required")
            )
            .drop("n_required")
        )
    return pl.concat(found).collect()


def _obs_values(
    observations: pl.LazyFrame | pl.DataFrame,
    stations: list[str],
    variables: tuple[str, ...] | list[str] = VARIABLES,
) -> pl.DataFrame:
    return (
        observations.lazy()
        .filter(pl.col("variable").is_in(list(variables)), pl.col("station_id").is_in(stations))
        .select(
            "station_id",
            pl.col("time").alias("valid_time"),
            "variable",
            pl.col("value").cast(pl.Float64).alias("observed"),
        )
        .unique(["station_id", "valid_time", "variable"], keep="first")
        .collect()
    )


def run_lead_scores(
    forecasts: pl.LazyFrame | pl.DataFrame,
    observations: pl.LazyFrame | pl.DataFrame,
    models: list[Model],
    chunk_runs: int = 24,
) -> tuple[pl.DataFrame, dict]:
    """Scores of every model by lead hour on the fair set (``COLUMNS``, region "cz"),
    and facts about the sample: ``models`` (runs, pairs, horizon per run hour),
    ``first_run``, ``last_run``, ``stations``, ``short_record`` (the models left out for
    too few runs, ``runs.short_records``). Runs are processed ``chunk_runs`` at a
    time (the sums are additive), so months of runs fit in memory."""
    forecasts = forecasts.lazy()
    cover = runs_mod.coverage(forecasts)
    compared = cover.filter("covered").select("model")
    forecasts = forecasts.join(compared.lazy(), on="model", how="semi")
    horizon_table = horizons(forecasts)
    required_ = required(horizon_table, models)
    run_list = sorted(forecasts.select("run").unique().collect()["run"].to_list())
    stations = forecasts.select("station_id").unique().collect()["station_id"].to_list()
    observed = _obs_values(observations, stations)
    sums, station_sets, used = [], [], []
    rain = pl.col("variable") == "precipitation"
    for i in range(0, len(run_list), chunk_runs):
        chunk = forecasts.filter(pl.col("run").is_in(run_list[i : i + chunk_runs])).collect()
        found = run_pairs(chunk, observed, required_)
        if found.height == 0:
            continue
        sums.append(
            found.group_by(RUN_KEYS).agg(
                pl.col("run").n_unique().alias("runs"),
                *metrics.error_sums(),
                *metrics.contingency_counts(THRESHOLD),
            )
        )
        station_sets.append(found.select(*RUN_KEYS, "station_id").unique())
        used.append(
            found.filter(pl.col("stratum") == "all")
            .group_by("model")
            .agg(
                pl.col("run").n_unique().alias("runs"),
                pl.len().alias("pairs"),
                pl.col("run").min().alias("first"),
                pl.col("run").max().alias("last"),
            )
        )
    info = {
        "models": {},
        "first_run": None,
        "last_run": None,
        "stations": 0,
        "short_record": runs_mod.short_records(cover),
    }
    if not sums:
        return pl.DataFrame(schema={c: pl.Null for c in COLUMNS}).clear(), info
    totals = pl.concat(sums).group_by(RUN_KEYS).agg(pl.all().sum())
    counted = (
        pl.concat(station_sets)
        .unique()
        .group_by(RUN_KEYS)
        .agg(pl.col("station_id").n_unique().alias("stations"))
    )
    order = {h: i for i, h in enumerate(["all", *RUN_HOURS])}
    table = (
        metrics.continuous_scores(totals.join(counted, on=RUN_KEYS))
        .with_columns(pl.when(rain).then(pl.col(c)).otherwise(None).alias(c) for c in COUNTS)
        .with_columns(
            pl.lit("cz").alias("region"),
            pl.lit("Česko").alias("region_name"),
            pl.col("stratum").alias("run_hour"),
            pl.col("stratum").replace_strict(order, return_dtype=pl.Int8).alias("_o"),
        )
        .sort("_o", "model", "variable", "lead_h")
        .drop("_o", "stratum")
    )
    per_model = (
        pl.concat(used)
        .group_by("model")
        .agg(
            pl.col("runs").sum(),
            pl.col("pairs").sum(),
            pl.col("first").min(),
            pl.col("last").max(),
        )
        .sort("model")
    )
    reach = {}
    for model, hour, last in horizon_table.rows():
        reach.setdefault(model, {})[hour] = last
    info["models"] = {
        r["model"]: {"runs": r["runs"], "pairs": r["pairs"], "horizon_h": reach.get(r["model"], {})}
        for r in per_model.iter_rows(named=True)
    }
    info["first_run"] = per_model["first"].min()
    info["last_run"] = per_model["last"].max()
    info["stations"] = int(pl.concat(station_sets)["station_id"].n_unique())
    return table, info


def runs_document(
    table: pl.DataFrame,
    info: dict,
    generated: datetime,
    delays: dict[str, float | None] | None = None,
    names: dict[str, str] | None = None,
) -> dict:
    """``leads.json``: every model by lead hour from Open-Meteo's single runs."""
    stamp = "%Y-%m-%dT%H:%MZ"
    rounded = table.select(
        pl.col(c).round(3) if c in ("mae", "bias", "rmse") else pl.col(c) for c in RUN_COLUMNS
    )
    models = {
        model: {
            "name": (names or {}).get(model, model),
            **facts,
            "publication_delay_h": (delays or {}).get(model),
        }
        for model, facts in info["models"].items()
    }
    return {
        "generated": generated.strftime(stamp),
        "source": "Open-Meteo single runs: open-data bucket on AWS and Single Runs API "
        "(free, non-commercial use)",
        "about": (
            "Every model verified run by run: each lead hour H+1…H+120 of the 00, 06, 12 "
            "and 18 UTC runs against the ČHMÚ observation at its valid time (run + lead), "
            "at about 100 stations, at the station elevation. Not the D+N scores."
        ),
        "fair_set": (
            "For each lead hour, variable and run hour only the models that reach that "
            "lead with their own output are compared, on the runs and stations that every "
            "one of them has; the set of models shrinks as short models end. "
            "run_hour 'all': a model must reach the lead in every run hour. Models with "
            f"fewer than {runs_mod.MIN_COVERAGE:.0%} of the period's runs (short_record, "
            "e.g. newly added) are left out until they have them."
        ),
        "short_record": info.get("short_record", {}),
        "first_run": info["first_run"].strftime(stamp) if info["first_run"] else None,
        "last_run": info["last_run"].strftime(stamp) if info["last_run"] else None,
        "stations": info["stations"],
        "models": models,
        "variables": {**UNITS, "precipitation": "mm in the hour ending at the valid time"},
        "region": "cz",
        "regions": {"cz": "Česko"},
        "column_notes": {
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
        "columns": RUN_COLUMNS,
        "rows": rounded.rows(),
    }


# --- ranking by lead band (H+1-6 … H+49-72), from the single runs --------------------

#: Lead bands (first and last lead hour, inclusive).
BANDS = ((1, 6), (7, 12), (13, 24), (25, 48), (49, 72))
BAND_VARIABLES = ("temperature_2m", "wind_speed_10m", "precipitation", "wind_gusts_10m")
#: The "6h" set: every model at the lead hours that are multiples of 6 (instant values
#: only: a 3- or 6-hourly model has no hourly precipitation sum).
SIX_HOURLY_VARIABLES = ("temperature_2m", "wind_speed_10m")
BAND_SETS = ("hourly", "6h")
#: Bias-corrected MAE, as for the D+N scores (``aggregate.bias_corrected``).
BAND_CORRECTED = ("temperature_2m", "wind_speed_10m")
BIAS_TRAINING_DAYS = 30
BIAS_MIN_DAYS = 10
#: Hourly precipitation events (mm in the hour): POD/FAR/ETS.
BAND_THRESHOLDS = (0.1, 1.0)
#: Windows: the last 90 days of runs (up to the last run) and every run.
BAND_WINDOWS = {"90d": 90, "all": None}
#: Levels: Czechia, main WMO vs other stations, kraje. No okres level: ~100 stations for
#: 76 okresy, most okresy have one station or none.
BAND_LEVELS = ("cz", "network", "kraj")
BAND_MIN_STATIONS = 3
#: Results on fewer days of runs are marked preliminary on the page.
PRELIMINARY_DAYS = 30
#: The page opens at this band (instead of D+1) once its 90-day ranking for Czechia
#: rests on at least ``DEFAULT_BAND_DAYS`` days (``band_default``).
DEFAULT_BAND = "h13-24"
DEFAULT_BAND_DAYS = 60
#: Gust output: a model with gusts in fewer than this share of its rows has none.
GUST_SHARE = 0.5

#: ``run_bits``: one bit per run hour (00, 06, 12, 18 UTC), so runs add up over stations.
RUN_BITS = {0: 1, 6: 2, 12: 4, 18: 8}
BAND_KEYS = ["set", "band", "variable", "model"]
BAND_SUMS = [
    "n", "sum_err", "sum_abs_err", "sum_sq_err", "n_bc", "sum_abs_err_bc",
    *(c for t in BAND_THRESHOLDS for c in metrics.counts_columns(t)),
]  # fmt: skip
BAND_COLUMNS = [
    "level", "region", "band", "set", "variable", "model", "rank", "tied", "clear",
    "mae", "bias", "rmse", "mae_bc", "ets_0p1", "ets_1", "pod_1", "far_1",
    "diff", "diff_low", "diff_high", "n", "n_bc", "runs", "stations", "days",
]  # fmt: skip


def band_name(first: int, last: int) -> str:
    """``h13-24`` for H+13 … H+24."""
    return f"h{first}-{last}"


BAND_NAMES = tuple(band_name(a, b) for a, b in BANDS)


def band_of(lead_h: pl.Expr) -> pl.Expr:
    """The band name of a lead hour (null outside the bands)."""
    (a, b), *rest = BANDS
    expr = pl.when(lead_h.is_between(a, b)).then(pl.lit(band_name(a, b)))
    for a, b in rest:
        expr = expr.when(lead_h.is_between(a, b)).then(pl.lit(band_name(a, b)))
    return expr.otherwise(pl.lit(None, pl.String))


def run_summary(forecasts: pl.LazyFrame | pl.DataFrame) -> pl.DataFrame:
    """One row per model and run: ``lead_h`` (its last lead hour with temperature),
    ``temperature_2m`` (1.0, so ``horizons`` reads it like the runs), ``gust_rows`` and
    ``rows``. Small, so coverage and horizons need not hold every row in memory."""
    frame = forecasts.lazy()
    gusts = (
        pl.col("wind_gusts_10m").is_not_null().sum()
        if "wind_gusts_10m" in frame.collect_schema().names()
        else pl.lit(0)
    )
    return (
        frame.group_by("model", "run")
        .agg(
            pl.col("lead_h").filter(pl.col("temperature_2m").is_not_null()).max(),
            gusts.cast(pl.Int64).alias("gust_rows"),
            pl.len().cast(pl.Int64).alias("rows"),
        )
        .with_columns(pl.lit(1.0).alias("temperature_2m"))
        .collect(engine="streaming")
    )


def gust_models(summary_: pl.DataFrame) -> set[str]:
    """Models with gusts in their runs (AIFS, AIGFS and JMA have none), from
    ``run_summary``."""
    share = summary_.group_by("model").agg(
        (pl.col("gust_rows").sum() / pl.col("rows").sum()).alias("share")
    )
    return set(share.filter(pl.col("share") >= GUST_SHARE)["model"])


def band_reach(horizon_table: pl.DataFrame) -> dict[str, int]:
    """The last lead hour each model reaches in every run hour it has (``horizons``)."""
    reach: dict[str, int] = {}
    for model, _, last in horizon_table.select("model", "run_hour", "horizon_h").rows():
        reach[model] = min(int(last), reach.get(model, int(last)))
    return reach


def band_required(
    horizon_table: pl.DataFrame, models: list[Model], gusts: set[str] | None = None
) -> pl.DataFrame:
    """The fair sets of the lead bands: ``set``, ``band``, ``lead_h``, ``variable``,
    ``model`` and ``n_required`` (models in that set at that lead and variable).

    A model enters a band only if it reaches the band's last hour in every run hour
    (``band_reach``). Set "hourly": the models with hourly output over the whole band,
    every lead hour of the band, all ``BAND_VARIABLES`` (gusts: the models that have
    them). Set "6h": every model reaching the band, at its lead hours that are multiples
    of 6 (where 3- and 6-hourly models have their own output), temperature and wind.
    """
    catalogue = {m.id: m for m in models}
    reach = band_reach(horizon_table)
    gusts = set(reach) if gusts is None else gusts
    rows = []
    for a, b in BANDS:
        band = band_name(a, b)
        entered = sorted(m for m, last in reach.items() if last >= b)
        hourly = [
            m
            for m in entered
            if m not in catalogue or all(catalogue[m].step_at(h) == 1 for h in range(a, b + 1))
        ]
        for variable in BAND_VARIABLES:
            for model in hourly:
                if variable == "wind_gusts_10m" and model not in gusts:
                    continue
                rows += [("hourly", band, h, variable, model) for h in range(a, b + 1)]
        six = [h for h in range(a, b + 1) if h % 6 == 0]
        for variable in SIX_HOURLY_VARIABLES:
            for model in entered:
                rows += [
                    ("6h", band, h, variable, model)
                    for h in six
                    if model not in catalogue or catalogue[model].native_hour(h)
                ]
    schema = {
        "set": pl.String, "band": pl.String, "lead_h": pl.Int16, "variable": pl.String,
        "model": pl.String,
    }  # fmt: skip
    table = pl.DataFrame(rows, schema=schema, orient="row")
    return table.with_columns(
        pl.len().over("set", "lead_h", "variable").cast(pl.UInt32).alias("n_required")
    )


def _bias_table(training: pl.DataFrame, days: list) -> pl.DataFrame:
    """Leakage-free bias for the runs of ``days``: per station, model, variable, band and
    valid hour of day, the mean error over the valid dates ``day - 30 … day - 1`` (all
    observed before any run of ``day`` started); null with fewer than
    ``BIAS_MIN_DAYS`` such dates."""
    keys = ["station_id", "model", "variable", "band", "hod"]
    found = []
    for day in days:
        lower = day - timedelta(days=BIAS_TRAINING_DAYS)
        part = (
            training.filter(pl.col("vdate") >= lower, pl.col("vdate") < day)
            .group_by(keys)
            .agg(
                pl.col("sum_e").sum(),
                pl.col("count").sum(),
                pl.col("vdate").n_unique().alias("dates"),
            )
            .filter(pl.col("dates") >= BIAS_MIN_DAYS)
            .select(*keys, pl.lit(day).alias("day"), (pl.col("sum_e") / pl.col("count")).alias("b"))
        )
        found.append(part)
    return pl.concat(found)


def band_sums(
    forecasts: pl.LazyFrame | pl.DataFrame,
    observations: pl.LazyFrame | pl.DataFrame,
    models: list[Model],
    chunk_runs: int = 8,
    log=None,
) -> tuple[pl.DataFrame, dict]:
    """Station-day sums of the band fair sets: one row per ``BAND_KEYS``, ``station_id``
    and ``day`` (the runs' start date) with ``BAND_SUMS`` and ``run_bits`` (bit k set
    when the run at 6·k UTC was scored there). Facts: ``required``, ``reach``,
    ``short_record``, ``first_run``, ``last_run``.

    Runs are read ``chunk_runs`` at a time in time order; the bias of each pair comes
    from the errors of earlier valid dates only (``_bias_table``), kept for the last
    ``BIAS_TRAINING_DAYS`` + 3 days."""
    forecasts = forecasts.lazy().filter(pl.col("lead_h").is_between(1, MAX_LEAD_H))
    names = forecasts.collect_schema().names()
    variables = [v for v in BAND_VARIABLES if v in names]
    summary_ = run_summary(forecasts)
    cover = runs_mod.coverage(summary_)
    covered = cover.filter("covered").select("model")
    forecasts = forecasts.join(covered.lazy(), on="model", how="semi")
    summary_ = summary_.join(covered, on="model", how="semi")
    horizon_table = horizons(summary_)
    required_ = band_required(horizon_table, models, gust_models(summary_))
    info = {
        "required": required_,
        "reach": band_reach(horizon_table),
        "short_record": runs_mod.short_records(cover),
        "first_run": None,
        "last_run": None,
    }
    run_list = sorted(forecasts.select("run").unique().collect()["run"].to_list())
    if not run_list or required_.height == 0:
        return pl.DataFrame(), info
    info["first_run"], info["last_run"] = run_list[0], run_list[-1]
    stations = forecasts.select("station_id").unique().collect()["station_id"].to_list()
    observed = _obs_values(observations, stations, variables)
    group = ["set", "band", "variable", "model", "station_id", "day"]
    train_keys = ["station_id", "model", "variable", "band", "hod", "vdate"]
    # categories instead of strings: the training errors of ~33 days stay small
    enums = {
        "station_id": pl.Enum(sorted(stations)),
        "model": pl.Enum(sorted(covered["model"])),
        "variable": pl.Enum(list(BAND_VARIABLES)),
        "band": pl.Enum(list(BAND_NAMES)),
        "set": pl.Enum(list(BAND_SETS)),
    }
    required_enum = required_.with_columns(
        pl.col(c).cast(enums[c]) for c in ("set", "band", "variable", "model")
    )
    training = pl.DataFrame(
        schema={
            **{c: enums[c] for c in ("station_id", "model", "variable", "band")},
            "hod": pl.Int8,
            "vdate": pl.Date,
            "sum_e": pl.Float64,
            "count": pl.UInt32,
        }
    )
    rain = pl.col("variable") == "precipitation"
    sums = []
    for i in range(0, len(run_list), chunk_runs):
        runs_here = run_list[i : i + chunk_runs]
        chunk = forecasts.filter(pl.col("run").is_in(runs_here)).select(*RUN_INDEX, *variables)
        long = (
            chunk.unpivot(
                index=RUN_INDEX, on=variables, variable_name="variable", value_name="forecast"
            )
            .drop_nulls("forecast")
            .with_columns(pl.col("forecast").cast(pl.Float64), pl.col("lead_h").cast(pl.Int16))
            .join(observed.lazy(), on=["station_id", "valid_time", "variable"])
            .with_columns(
                *(pl.col(c).cast(enums[c]) for c in ("station_id", "model", "variable")),
                band_of(pl.col("lead_h")).cast(enums["band"]).alias("band"),
                pl.col("run").dt.date().alias("day"),
                pl.col("valid_time").dt.date().alias("vdate"),
                pl.col("valid_time").dt.hour().cast(pl.Int8).alias("hod"),
                (pl.col("forecast") - pl.col("observed")).alias("error"),
            )
            .collect()
        )
        if long.height == 0:
            continue
        # every pair of a model trains its own bias (fair set or not)
        first_day = runs_here[0].date()
        training = (
            pl.concat(
                [
                    training.filter(
                        pl.col("vdate") >= first_day - timedelta(days=BIAS_TRAINING_DAYS + 3)
                    ),
                    long.filter(pl.col("variable").is_in(BAND_CORRECTED))
                    .group_by(train_keys)
                    .agg(
                        pl.col("error").sum().alias("sum_e"),
                        pl.len().cast(pl.UInt32).alias("count"),
                    ),
                ],
                how="vertical_relaxed",
            )
            .group_by(train_keys)
            .agg(pl.col("sum_e").sum(), pl.col("count").sum())
        )
        days = sorted(set(long["day"].unique().to_list()))
        bias = _bias_table(training, days)
        fair = (
            long.join(required_enum, on=["lead_h", "variable", "model"])
            .filter(
                pl.len().over("set", "run", "station_id", "lead_h", "variable")
                == pl.col("n_required")
            )
            .join(
                bias,
                on=["station_id", "model", "variable", "band", "hod", "day"],
                how="left",
            )
            .with_columns(
                (
                    pl.col("b").count().over("set", "run", "station_id", "lead_h", "variable")
                    == pl.col("n_required")
                ).alias("all_bias")
            )
        )
        corrected = (pl.col("error") - pl.col("b")).abs()
        counts = [e for t in BAND_THRESHOLDS for e in metrics.contingency_counts(t)]
        sums.append(
            fair.group_by(group).agg(
                *metrics.error_sums(),
                pl.col("all_bias").sum().cast(pl.Int64).alias("n_bc"),
                corrected.filter("all_bias").sum().alias("sum_abs_err_bc"),
                *counts,
                pl.col("run")
                .dt.hour()
                .replace_strict(RUN_BITS, default=0, return_dtype=pl.UInt8)
                .unique()
                .sum()
                .cast(pl.UInt8)
                .alias("run_bits"),
            )
        )
        if log:
            done = f"{i + 1}-{i + len(runs_here)} of {len(run_list)}"
            log(f"bands: runs {done}, {fair.height:,} pairs")
    if not sums:
        return pl.DataFrame(), info
    table = pl.concat(sums).with_columns(pl.col(c).cast(pl.String) for c in group[:5])
    table = table.with_columns(
        pl.when(rain).then(pl.col(c)).otherwise(None).alias(c)
        for t in BAND_THRESHOLDS
        for c in metrics.counts_columns(t)
    )
    return table, info


def _band_regions(sums: pl.DataFrame, level: str, stations: pl.DataFrame) -> pl.DataFrame:
    """``sums`` with ``region`` for a level (kraje with at least ``BAND_MIN_STATIONS``
    stations in a group only)."""
    if level == "cz":
        return sums.with_columns(pl.lit("cz").alias("region"))
    if level == "network":
        return sums.with_columns(
            pl.when(pl.col("station_id").str.starts_with(MAIN_PREFIX))
            .then(pl.lit("main"))
            .otherwise(pl.lit("other"))
            .alias("region")
        )
    kraj = stations.select(pl.col("id").alias("station_id"), pl.col("kraj_code").alias("region"))
    return sums.join(kraj, on="station_id").drop_nulls("region")


def band_scores(
    sums: pl.DataFrame,
    stations: pl.DataFrame,
    resamples: int = 1000,
    seed: int = 0,
) -> pl.DataFrame:
    """Scores and ranking of every level, region, band, set and variable from the
    station-day sums of one window (``BAND_COLUMNS``). Models are ranked by MAE; the 95 %
    interval of each model's MAE minus the best one's comes from resampling whole days
    (``ranking.bootstrap_group``); ``tied``: that interval contains 0."""
    from meteoverdict.ranking import bootstrap_group

    frames = []
    groups = ["region", "set", "band", "variable"]
    for level in BAND_LEVELS:
        here = _band_regions(sums, level, stations)
        size = here.group_by(groups).agg(pl.col("station_id").n_unique().alias("_st"))
        here = here.join(
            size.filter(pl.col("_st") >= (BAND_MIN_STATIONS if level == "kraj" else 1)),
            on=groups,
            how="semi",
        )
        if here.height == 0:
            continue
        keys = [*groups, "model"]
        totals = here.group_by(keys).agg(
            *(metrics.total(c) if c in metrics.SUMS else pl.col(c).sum() for c in BAND_SUMS),
            pl.col("station_id").n_unique().alias("stations"),
            pl.col("day").n_unique().alias("days"),
        )
        runs = (
            here.group_by([*keys, "day"])
            .agg(pl.col("run_bits").bitwise_or())
            .group_by(keys)
            .agg(pl.col("run_bits").bitwise_count_ones().sum().cast(pl.Int64).alias("runs"))
        )
        table = metrics.continuous_scores(totals.join(runs, on=keys))
        for t in BAND_THRESHOLDS:
            table = metrics.categorical_scores(table, t)
        table = table.with_columns(
            pl.when(pl.col("n_bc") > 0)
            .then(pl.col("sum_abs_err_bc") / pl.col("n_bc"))
            .alias("mae_bc"),
            pl.lit(level).alias("level"),
        )
        daily = (
            here.group_by([*keys, "day"])
            .agg(metrics.total("sum_abs_err"), metrics.total("n"))
            .sort("day")
        )
        ranks = []
        for key, part in daily.partition_by(groups, as_dict=True).items():
            sae = part.pivot(on="model", index="day", values="sum_abs_err").sort("day").fill_null(0)
            n = part.pivot(on="model", index="day", values="n").sort("day").fill_null(0)
            ids = [c for c in sae.columns if c != "day"]
            a = sae.select(ids).to_numpy().astype(float)
            m = n.select(ids).to_numpy().astype(float)
            if len(ids) == 1:
                order, diff, bounds = np.array([0]), np.array([0.0]), np.zeros((2, 1))
            else:
                text = "|".join(map(str, (level, *key))).encode()
                rng = np.random.default_rng([seed, zlib.crc32(text)])
                order, diff, bounds = bootstrap_group(a, m, rng, resamples)
            tied = (bounds[0] <= 0) & (bounds[1] >= 0) & (order.argsort() > 0)
            clear = len(ids) > 1 and not tied.any()
            for position, index in enumerate(order):
                ranks.append(
                    (*key, ids[index], position + 1, bool(tied[index]),
                     bool(position == 0 and clear), float(diff[index]),
                     float(bounds[0][index]), float(bounds[1][index]))
                )  # fmt: skip
        rank_table = pl.DataFrame(
            ranks,
            schema={
                "region": pl.String,
                "set": pl.String,
                "band": pl.String,
                "variable": pl.String,
                "model": pl.String,
                "rank": pl.Int16,
                "tied": pl.Boolean,
                "clear": pl.Boolean,
                "diff": pl.Float64,
                "diff_low": pl.Float64,
                "diff_high": pl.Float64,
            },
            orient="row",
        )
        frames.append(table.join(rank_table, on=keys).select(BAND_COLUMNS))
    if not frames:
        return pl.DataFrame(schema=BAND_COLUMNS)
    order = {b: i for i, b in enumerate(BAND_NAMES)}
    return (
        pl.concat(frames)
        .with_columns(
            pl.col("level").replace_strict({k: i for i, k in enumerate(BAND_LEVELS)}).alias("_l"),
            pl.col("band").replace_strict(order).alias("_b"),
        )
        .sort("_l", "region", "set", "_b", "variable", "rank")
        .drop("_l", "_b")
    )


def window_sums(sums: pl.DataFrame, days: int | None) -> pl.DataFrame:
    """The station-day sums of the last ``days`` days up to the last run's day (all for None)."""
    if days is None or sums.height == 0:
        return sums
    last = sums["day"].max()
    return sums.filter(pl.col("day") > last - timedelta(days=days))


def band_rankings(
    forecasts: pl.LazyFrame | pl.DataFrame,
    observations: pl.LazyFrame | pl.DataFrame,
    models: list[Model],
    stations: pl.DataFrame,
    chunk_runs: int = 8,
    resamples: int = 1000,
    log=None,
) -> dict[str, tuple[pl.DataFrame, dict]]:
    """``{window: (band_scores table, facts)}`` for ``BAND_WINDOWS``. The sums of all runs
    serve the 90-day window too unless its own fair sets differ (a model only covered
    in the last 90 days, ``runs.coverage``); then its runs are scored again."""
    forecasts = forecasts.lazy()
    whole, info = band_sums(forecasts, observations, models, chunk_runs, log)
    out = {}
    for window, days in BAND_WINDOWS.items():
        sums, facts = whole, info
        if days is not None and info["last_run"] is not None:
            since = info["last_run"] - timedelta(days=days)
            recent = forecasts.filter(pl.col("run") > since)
            summary_ = run_summary(recent.filter(pl.col("lead_h").is_between(1, MAX_LEAD_H)))
            cover = runs_mod.coverage(summary_)
            kept = summary_.join(cover.filter("covered").select("model"), on="model", how="semi")
            req = band_required(horizons(kept), models, gust_models(kept))
            if not req.sort(req.columns).equals(info["required"].sort(req.columns)):
                sums, facts = band_sums(recent, observations, models, chunk_runs, log)
        sums = window_sums(sums, days)
        table = band_scores(sums, stations, resamples) if sums.height else pl.DataFrame()
        facts = {
            **facts,
            "first_day": sums["day"].min() if sums.height else None,
            "last_day": sums["day"].max() if sums.height else None,
        }
        out[window] = (table, facts)
    return out


def band_default(table: pl.DataFrame) -> str | None:
    """``DEFAULT_BAND`` when its 90-day ranking of temperature for Czechia rests on at
    least ``DEFAULT_BAND_DAYS`` days, else None (the page then opens at D+1)."""
    if table.height == 0:
        return None
    found = table.filter(
        pl.col("level") == "cz",
        pl.col("band") == DEFAULT_BAND,
        pl.col("set") == "hourly",
        pl.col("variable") == "temperature_2m",
    )
    return DEFAULT_BAND if found.height and found["days"].max() >= DEFAULT_BAND_DAYS else None


def band_documents(
    table: pl.DataFrame,
    facts: dict,
    window: str,
    generated: datetime,
    region_names: dict[str, str],
    names: dict[str, str] | None = None,
    default: str | None = None,
) -> dict[str, dict]:
    """``{file name: document}``: ``leads-bands-<window>.json`` (Czechia and the station
    kinds) and ``leads-bands-<window>-kraj.json`` (kraje), ``{"columns", "rows"}``."""
    stamp = "%Y-%m-%dT%H:%MZ"
    required_ = facts["required"]
    members: dict = {}
    for set_, band, variable, model in (
        required_.select("set", "band", "variable", "model").unique().sort(pl.all()).rows()
    ):
        members.setdefault(band, {}).setdefault(set_, {}).setdefault(variable, []).append(model)
    used = sorted(set(required_["model"])) if required_.height else []
    header = {
        "generated": generated.strftime(stamp),
        "source": "Open-Meteo Single Runs (free, non-commercial use) and ČHMÚ observations",
        "about": (
            "Models ranked by lead band, run by run: every lead hour of the 00, 06, 12 and "
            "18 UTC runs against the ČHMÚ observation at its valid time (run + lead), "
            "pooled over the band. Not the D+N scores."
        ),
        "window": window,
        "first_run": facts["first_run"].strftime(stamp) if facts.get("first_run") else None,
        "last_run": facts["last_run"].strftime(stamp) if facts.get("last_run") else None,
        "first_day": facts["first_day"].isoformat() if facts.get("first_day") else None,
        "last_day": facts["last_day"].isoformat() if facts.get("last_day") else None,
        "bands": {band_name(a, b): [a, b] for a, b in BANDS},
        "sets": {
            "hourly": (
                "models with hourly output over the whole band, every lead hour of the "
                "band; temperature, wind, hourly precipitation, gusts (models with gusts)"
            ),
            "6h": (
                "every model reaching the band, at the lead hours that are multiples of 6 "
                "(own output of 3- and 6-hourly models too); temperature and wind"
            ),
        },
        "fair_set": (
            "A model enters a band only if its runs reach the band's last hour in every run "
            "hour it has. Within a set only the (run, station, lead hour, variable) that "
            "every model of the set has are scored, so all models share the same pairs. "
            f"Models with fewer than {runs_mod.MIN_COVERAGE:.0%} of the runs are left out "
            "(short_record)."
        ),
        "ranking": (
            "Rank by MAE. diff, diff_low, diff_high: MAE minus the best model's MAE and its "
            "95 % interval from resampling whole days of runs (1000 times); tied: the "
            "interval contains 0 (not significantly worse than the best); clear: the best "
            "model with no model tied."
        ),
        "bias_corrected": (
            "mae_bc (temperature, wind): each model's own mean error at the station, band "
            f"and valid hour of day over the {BIAS_TRAINING_DAYS} valid dates before the "
            f"run's day (observed before the run started; at least {BIAS_MIN_DAYS}) is "
            "removed; only pairs where every model of the set has such a bias (n_bc)."
        ),
        "preliminary_days": PRELIMINARY_DAYS,
        "default_band": default,
        "short_record": facts.get("short_record", {}),
        "reach_h": {m: facts["reach"].get(m) for m in used},
        "members": members,
        "models": {m: (names or {}).get(m, m) for m in used},
        "variables": {
            **UNITS,
            "precipitation": "mm in the hour ending at the valid time",
            "wind_gusts_10m": "m/s, gust at the valid time (observed: hourly maximum)",
        },
        "column_notes": {
            "level": "cz, network (region main = WMO main stations, other) or kraj",
            "n": "pairs (station x run x lead hour) per model",
            "runs, stations, days": "runs, stations and days of runs behind the result",
            "ets_0p1, ets_1, pod_1, far_1": "precipitation >= 0.1 / 1 mm in the hour",
        },
        "columns": BAND_COLUMNS,
    }
    rounded = (
        table.with_columns(
            pl.col(c).round(3)
            for c in (
                "mae",
                "bias",
                "rmse",
                "mae_bc",
                "ets_0p1",
                "ets_1",
                "pod_1",
                "far_1",
                "diff",
                "diff_low",
                "diff_high",
            )
        )
        if table.height
        else table
    )
    docs = {}
    for name, levels in (
        (f"leads-bands-{window}.json", ("cz", "network")),
        (f"leads-bands-{window}-kraj.json", ("kraj",)),
    ):
        part = rounded.filter(pl.col("level").is_in(levels)) if rounded.height else rounded
        codes = sorted(set(part["region"])) if part.height else []
        docs[name] = {
            **header,
            "regions": {c: region_names.get(c, c) for c in codes},
            "rows": part.select(BAND_COLUMNS).rows() if part.height else [],
        }
    return docs
