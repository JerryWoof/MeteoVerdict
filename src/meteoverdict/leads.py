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

Lead 0 (the analysis) is not scored. Sums are kept additive (``metrics``), so MAE, bias
and RMSE come from the sums of each group.
See docs/methodology.md#run-based-verification-by-lead-hour.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from meteoverdict import metrics, partitions
from meteoverdict import runs as runs_mod
from meteoverdict.models import Model

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


def _obs_values(observations: pl.LazyFrame | pl.DataFrame, stations: list[str]) -> pl.DataFrame:
    return (
        observations.lazy()
        .filter(pl.col("variable").is_in(VARIABLES), pl.col("station_id").is_in(stations))
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
    ``first_run``, ``last_run``, ``stations``. Runs are processed ``chunk_runs`` at a
    time (the sums are additive), so months of runs fit in memory."""
    forecasts = forecasts.lazy()
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
    info = {"models": {}, "first_run": None, "last_run": None, "stations": 0}
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
        "source": "Open-Meteo Single Runs API (free, non-commercial use)",
        "about": (
            "Every model verified run by run: each lead hour H+1…H+120 of the 00, 06, 12 "
            "and 18 UTC runs against the ČHMÚ observation at its valid time (run + lead), "
            "at about 100 stations, at the station elevation. Not the D+N scores."
        ),
        "fair_set": (
            "For each lead hour, variable and run hour only the models that reach that "
            "lead with their own output are compared, on the runs and stations that every "
            "one of them has; the set of models shrinks as short models end. "
            "run_hour 'all': a model must reach the lead in every run hour."
        ),
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
