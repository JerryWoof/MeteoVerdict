"""D+N forecasts for the most recent days, built from the single runs (no API calls).

The D+N forecasts of the Previous Runs API come from the backfill in complete 14-day
windows, so the scores, the ranking and the combination weights lag 14-20 days behind.
The single runs (``runs``: every 00, 06, 12 and 18 UTC run of every model at the ~100
stations of ``run-stations.csv``, fetched four times a day) hold the same forecasts:
Open-Meteo's ``<variable>_previous_dayN`` at a valid hour ``T`` is the value of the
newest run that started at least 24·N hours before ``T`` (docs/data-sources.md,
"Open-Meteo Previous Runs API"). ``previous_days`` rebuilds exactly that:

- for lead day N, the rows of each run with ``24·N <= lead_h < 24·(N + 1)``, and of
  those the newest run per model, station and hour (a run that does not reach the hour,
  e.g. the shorter 06 and 18 UTC runs of IFS HRES, has no row there, so the run before
  it is used, as in the Previous Runs archive; where the archive keeps a run for fewer
  hours than the Single Runs API, ``Model.previous_runs_max_lead_h`` says so: UKMO);
- only where the run that Open-Meteo would use first (the newest run of the model's
  ``run_hours`` at least 24·N hours before ``T``) is among the runs we have: if it is
  missing (not fetched yet, or a gap at Open-Meteo) the hour is left out instead of
  silently taking an older run;
- models whose archive also has runs in between (``Model.previous_runs_step_h``:
  ICON-D2, GeoSphere and DMI every 3 hours, KNMI every hour) only at the hours where a
  00/06/12/18 UTC run is the newest (for 3-hourly runs: 00-02, 06-08, … UTC; for KNMI
  the synoptic hours), which leaves out their daily precipitation;
- single runs reach 120 hours, so D+5 has only the hours exactly 120 hours after a run
  (00, 06, 12 and 18 UTC; 00 and 12 UTC for GEM Global): temperature and wind at the
  synoptic hours, which is what is ranked, but no daily precipitation.

Checked live on 2026-10-16 against the Previous Runs API (15 stations, 19 models,
D+1 to D+5): identical values at every hour scored for temperature and wind; the
3- and 6-hourly models differ only at their interpolated hours, so their daily
precipitation can differ slightly (AIFS 0.09 mm in MAE over 11 station-days).

``fill`` adds these rows to the Previous Runs forecasts only for the hours (model, lead
day, hour) the backfill has not delivered yet; once a window arrives its rows replace
them at the next re-scoring. ``mark`` records in the scores where each day's forecasts
came from (``source``), and ``compare`` checks both sources against each other on the
hours where both exist (docs/methodology.md, "Fresh scores from the single runs").
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl

from meteoverdict import blend
from meteoverdict.forecasts import SCHEMA
from meteoverdict.models import VARIABLES, Model
from meteoverdict.scoring import PREVIOUS_RUNS, SINGLE_RUNS

#: How many days back the daily run rebuilds D+N forecasts from the single runs: more
#: than the backfill's lag (complete 14-day windows, fetched a few days after they end)
DAYS = 30
#: Single runs are stored up to this lead hour (``runs.MAX_LEAD_H``)
MAX_LEAD_H = 120


def _expected_run_offsets(models: list[Model]) -> pl.LazyFrame:
    """Per model and hour of ``(T - 24·N)`` truncated to 6 hours: hours back to the
    newest run hour of the model (``run_hours``) at or before it."""
    rows = []
    for m in models:
        for hour in (0, 6, 12, 18):
            back = next(b for b in range(0, 25, 6) if (hour - b) % 24 in m.run_hours)
            rows.append((m.id, hour, back))
    return pl.LazyFrame(
        rows, schema={"model": pl.String, "_base_hour": pl.Int8, "_back": pl.Int64}, orient="row"
    )


def previous_days(
    single_runs: pl.LazyFrame | pl.DataFrame,
    models: list[Model],
    first: datetime,
    last: datetime,
) -> pl.LazyFrame:
    """D+N rows (``forecasts.SCHEMA``) for valid hours ``first`` to ``last`` (UTC) from
    the single runs (``runs.SCHEMA``), as the Previous Runs API defines them."""
    runs = single_runs.lazy().filter(pl.col("model").is_in([m.id for m in models]))
    lead_days = pl.LazyFrame(
        [(m.id, n) for m in models for n in m.lead_days],
        schema={"model": pl.String, "lead_day": pl.Int8},
        orient="row",
    )
    caps = pl.LazyFrame(
        [(m.id, h, n) for m in models for h, n in m.previous_runs_max_lead_h.items()],
        schema={"model": pl.String, "_run_hour": pl.Int8, "_max_lead": pl.Int16},
        orient="row",
    )
    steps = pl.LazyFrame(
        [(m.id, m.previous_runs_step_h) for m in models],
        schema={"model": pl.String, "_step": pl.Int64},
        orient="row",
    )
    present = runs.select("model", pl.col("run").alias("_expected")).unique()
    candidates = (
        runs.filter(
            pl.col("valid_time").is_between(first, last),
            pl.col("lead_h") >= 24,
            pl.col("lead_h") <= MAX_LEAD_H,
        )
        .with_columns(
            (pl.col("lead_h") // 24).cast(pl.Int8).alias("lead_day"),
            pl.col("run").dt.hour().cast(pl.Int8).alias("_run_hour"),
        )
        .join(lead_days, on=["model", "lead_day"], how="inner")
        # runs that the Previous Runs archive keeps for fewer hours (UKMO 06/18 UTC)
        .join(caps, on=["model", "_run_hour"], how="left")
        .filter(pl.col("_max_lead").is_null() | (pl.col("lead_h") <= pl.col("_max_lead")))
    )
    newest = candidates.filter(
        pl.col("run") == pl.col("run").max().over("model", "station_id", "valid_time", "lead_day")
    )
    target = pl.col("valid_time") - pl.duration(hours=24 * pl.col("lead_day"))
    return (
        newest.with_columns(target.alias("_target"), target.dt.truncate("6h").alias("_base"))
        .with_columns(pl.col("_base").dt.hour().cast(pl.Int8).alias("_base_hour"))
        .join(_expected_run_offsets(models), on=["model", "_base_hour"], how="inner")
        .with_columns((pl.col("_base") - pl.duration(hours=pl.col("_back"))).alias("_expected"))
        .join(present, on=["model", "_expected"], how="semi")
        # models with runs in between in the archive: only where no such run is newer
        .join(steps, on="model", how="inner")
        .filter((pl.col("_target") - pl.col("_base")).dt.total_hours() < pl.col("_step"))
        .select(
            "station_id",
            pl.col("valid_time").alias("time"),
            "model",
            "lead_day",
            *VARIABLES,
        )
        .cast(SCHEMA)
    )


def fill(
    forecasts: pl.LazyFrame | pl.DataFrame, derived: pl.LazyFrame | pl.DataFrame
) -> tuple[pl.LazyFrame, pl.DataFrame]:
    """``(forecasts with the derived rows added, the derived rows added)``: derived rows
    only for the model, lead day and hour that the Previous Runs forecasts lack."""
    fc = forecasts.lazy()
    have = fc.select("model", "lead_day", "time").unique()
    added = derived.lazy().join(have, on=["model", "lead_day", "time"], how="anti").collect()
    return pl.concat([fc.select(list(SCHEMA)), added.lazy()], how="vertical_relaxed"), added


def mark(scores: pl.DataFrame, added: pl.LazyFrame | pl.DataFrame) -> pl.DataFrame:
    """Scores with ``source``: ``single_runs`` where at least one hour behind the score
    was rebuilt from the single runs (for the model, or for any member of the blend),
    else ``previous_runs``. The day an hour counts for depends on the variable, as in
    ``scoring``: precipitation periods by the hour they end in (an hour ending at 24:00
    belongs to that day), the 06-06 UTC total by the day it starts, the rest by the
    UTC date."""
    hours = added.lazy().select("time", "model", "lead_day").unique()
    hours = pl.concat([hours, hours.with_columns(pl.lit(blend.ID).alias("model"))]).unique()
    shifts = {"_d0": 0, "_d1": 1, "_d7": 7}
    days = (
        hours.with_columns(
            (pl.col("time") - pl.duration(hours=h)).dt.date().alias(name)
            for name, h in shifts.items()
        )
        .unpivot(index=["model", "lead_day"], on=list(shifts), variable_name="_shift")
        .rename({"value": "date"})
        .unique()
        .collect()
    )
    period = (
        pl.when(pl.col("variable") == "precipitation_24h")
        .then(pl.lit("_d7"))
        .when(pl.col("variable").str.starts_with("precipitation"))
        .then(pl.lit("_d1"))
        .otherwise(pl.lit("_d0"))
    )
    return (
        scores.with_columns(period.alias("_shift"))
        .join(
            days.with_columns(pl.lit(True).alias("_rebuilt")),
            on=["date", "model", "lead_day", "_shift"],
            how="left",
        )
        .drop("_shift")
        .with_columns(
            pl.when(pl.col("_rebuilt"))
            .then(pl.lit(SINGLE_RUNS))
            .otherwise(pl.lit(PREVIOUS_RUNS))
            .alias("source")
        )
        .drop("_rebuilt")
    )


def compare(
    forecasts: pl.LazyFrame | pl.DataFrame,
    derived: pl.LazyFrame | pl.DataFrame,
    observations: pl.LazyFrame | pl.DataFrame | None = None,
    models: list[Model] | None = None,
) -> pl.DataFrame:
    """Both sources on the hours where both exist, per model, lead day and variable:
    ``n``, ``mean_abs_diff`` and ``max_abs_diff`` between them and, with
    ``observations``, ``n_obs``, ``mae_previous``, ``mae_single`` and their difference
    ``mae_diff`` (single minus previous) on the same hours. With ``models``,
    temperature and wind only at each model's native hours, the ones scored
    (``align.pairs``); the hours in between are interpolated by Open-Meteo, in the
    Previous Runs archive across runs, so they can differ."""
    on = ["station_id", "time", "model", "lead_day"]

    def long(frame, name):
        return frame.lazy().unpivot(
            index=on, on=list(VARIABLES), variable_name="variable", value_name=name
        )

    both = (
        long(forecasts, "previous")
        .join(long(derived, "single"), on=[*on, "variable"], how="inner")
        .drop_nulls(["previous", "single"])
    )
    if models is not None:
        steps = pl.LazyFrame(
            [(m.id, n, m.native_step(n)) for m in models for n in m.lead_days],
            schema={"model": pl.String, "lead_day": pl.Int8, "_step": pl.Int8},
            orient="row",
        )
        both = both.join(steps, on=["model", "lead_day"], how="inner").filter(
            (pl.col("variable") == "precipitation")
            | (pl.col("time").dt.hour() % pl.col("_step") == 0)
        )
    diff = (pl.col("single") - pl.col("previous")).abs()
    stats = [
        pl.len().alias("n"),
        diff.mean().alias("mean_abs_diff"),
        diff.max().alias("max_abs_diff"),
    ]
    if observations is not None:
        obs = observations.lazy().select("station_id", "time", "variable", "value")
        both = both.join(obs, on=["station_id", "time", "variable"], how="left")
        seen = pl.col("value").is_not_null()
        stats += [
            seen.sum().alias("n_obs"),
            (pl.col("previous") - pl.col("value")).abs().filter(seen).mean().alias("mae_previous"),
            (pl.col("single") - pl.col("value")).abs().filter(seen).mean().alias("mae_single"),
        ]
    table = (
        both.group_by("model", "lead_day", "variable")
        .agg(stats)
        .sort("model", "lead_day", "variable")
    )
    if observations is not None:
        table = table.with_columns(
            (pl.col("mae_single") - pl.col("mae_previous")).alias("mae_diff")
        )
    return table.collect()


def summary(table: pl.DataFrame) -> str:
    """One line for the log: hours compared, mean and largest difference."""
    if table.height == 0:
        return "no hour has both Previous Runs and single-runs forecasts yet"
    n = int(table["n"].sum())
    mean = float((table["mean_abs_diff"] * table["n"]).sum() / n)
    worst = table.sort("max_abs_diff", descending=True).row(0, named=True)
    line = (
        f"single runs vs Previous Runs on {n:,} overlapping values: mean |difference| "
        f"{mean:.3f}, largest {worst['max_abs_diff']:.2f} ({worst['model']} D+"
        f"{worst['lead_day']} {worst['variable']})"
    )
    if "mae_diff" in table.columns and table["n_obs"].sum() > 0:
        line += f", MAE difference at most {table['mae_diff'].abs().max():.3f}"
    return line


def sources(scores: pl.LazyFrame | pl.DataFrame) -> dict[str, dict[str, str]]:
    """For meta.json: the first and last day scored from each source (``source``;
    rows without it, from before 2026-10-16, are Previous Runs)."""
    frame = scores.lazy()
    if "source" not in frame.collect_schema().names():
        frame = frame.with_columns(pl.lit(None, pl.String).alias("source"))
    spans = (
        frame.with_columns(pl.col("source").fill_null(PREVIOUS_RUNS))
        .group_by("source")
        .agg(pl.col("date").min().alias("from"), pl.col("date").max().alias("to"))
        .sort("source")
        .collect()
    )
    return {s: {"from": str(a), "to": str(b)} for s, a, b in spans.rows()}


def window(day: date) -> tuple[datetime, datetime]:
    """Valid hours rebuilt by the daily run for ``day``: the last ``DAYS`` days up to
    the 00:00 hour after ``day`` (that day's precipitation total ends there)."""
    first = datetime.combine(day - timedelta(days=DAYS - 1), datetime.min.time(), UTC)
    return first, datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC)
