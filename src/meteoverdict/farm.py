"""Event skill for farmers: frost, wind gusts and 3-hour rain, run by run (``farm.json``).

The same single runs as ``leads`` (Open-Meteo Single Runs API, ~100 stations, the 00,
06, 12 and 18 UTC runs, leads 1-120), verified as yes/no events instead of errors:

**Frost** (unit: station x night). A night is 18:00 to 09:00 Prague local time (16
hourly values; 15 or 17 on the nights the clocks change), dated by its evening. Event:
the night's lowest hourly 2 m temperature is at or below 0 °C (and -2 °C). Observed: the
minimum of the hourly ČHMÚ ``T`` values at the full hours, all hours of the night
required. Forecast: the minimum of the model's values at its own output hours in the
night (3- and 6-hourly models see fewer hours, as their users do), all of them
required. A night belongs to the lead bin of its last hour (09:00 local): "the night
ending H+x after the run started". The whole night must lie after the run's start.

**Gusts** (unit: station x 3-hour block, 00-03, 03-06, … UTC, ending at the block's
end). Event: the largest gust in the block is at least 10 m/s (15, 20). Observed: the
largest of the three hourly maxima of ČHMÚ ``Fmax`` (each the maximum of six 10-minute
gusts, ``observations``), all three required. Forecast: the largest of the model's
hourly ``wind_gusts_10m`` (Open-Meteo: maximum of the preceding hour) at its own output
hours in the block: all three hours for hourly output, the block's end for 3-hourly
output (what that value covers is Open-Meteo's processing, unverified); models with
6-hourly output there are not scored. 3-hour blocks rather than single hours: a gust a
few minutes early or late should not count as a miss and a false alarm.

**3-hour rain** (unit: station x 3-hour block as above). Event: at least 0.5 mm (2, 5)
in the block. Observed: the sum of the three hourly ČHMÚ sums, all required. Forecast:
the sum of the model's three hourly values (for 3-hourly output Open-Meteo spreads the
period's total over its hours, so the sum is the model's own 3-hour total, as in
``align``); models with 6-hourly output there are not scored.

Runs start at 00/06/12/18 UTC, so blocks end at leads 3, 6, 9, … and never straddle a
run's start; a block belongs to the bin of its end lead.

**Fair set** (as in ``leads``): per event and lead bin, the models compared are those
whose usual coverage of the variable (median first and last lead with a value per run
hour, the narrowest over the run hours) spans the whole bin and, for the blocks, whose
output step in the bin is at most 3 hours. Only units (run, station, night or block)
that every one of them has, and that have the observation, are counted; so within a
bin every model is scored on the same events. Models without a variable at all (AIFS
has no gusts) are left out of that event, and models with fewer than
``runs.MIN_COVERAGE`` of the period's runs (``runs.coverage``: added recently, their
single runs fetched only since) are left out altogether until they have them, so that
they do not cut every model's runs to their few days.

Counts per event, threshold, bin and model: hits, misses, false alarms and correct
negatives; POD, FAR, CSI, ETS and frequency bias from them. Fewer than
``SMALL_SAMPLE`` observed events is flagged. Runs are processed ``chunk_runs`` at a
time (the counts are additive). See docs/methodology.md#event-skill-for-farmers.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from meteoverdict import runs as runs_mod
from meteoverdict.models import Model

PRAGUE = ZoneInfo("Europe/Prague")
#: Lead bins (first and last lead hour, inclusive).
BINS = ((1, 6), (7, 12), (13, 24), (25, 48), (49, 72), (73, 120))
#: Night in local time: from this hour in the evening to this hour next morning (both
#: full hours included).
NIGHT_FROM_H, NIGHT_TO_H = 18, 9
BLOCK_H = 3
#: Fewer observed events than this in a bin: flagged as a small sample.
SMALL_SAMPLE = 20

#: event -> variable, unit, comparison ("le": value <= threshold), thresholds
EVENTS = {
    "frost": {
        "variable": "temperature_2m",
        "unit": "night",
        "op": "le",
        "thresholds": (0.0, -2.0),
        "definition": "lowest hourly 2 m temperature of the night (18:00-09:00 Prague "
        "time) at or below the threshold, °C",
    },
    "gust": {
        "variable": "wind_gusts_10m",
        "unit": "3h",
        "op": "ge",
        "thresholds": (10.0, 15.0, 20.0),
        "definition": "strongest gust in a 3-hour block (00-03, 03-06, … UTC) at or "
        "above the threshold, m/s",
    },
    "rain3h": {
        "variable": "precipitation",
        "unit": "3h",
        "op": "ge",
        "thresholds": (0.5, 2.0, 5.0),
        "definition": "precipitation in a 3-hour block (00-03, 03-06, … UTC) at or "
        "above the threshold, mm",
    },
}

COUNT_COLUMNS = ["hits", "misses", "false_alarms", "correct_negatives"]
COLUMNS = [
    "event", "threshold", "bin", "model", "units", "runs", "stations", "events",
    *COUNT_COLUMNS, "pod", "far", "csi", "ets", "bias",
]  # fmt: skip
UNIT_KEYS = ["run", "station_id", "unit_end"]


def bin_label(first: int, last: int) -> str:
    return f"{first}-{last}"


def bin_expr(lead: pl.Expr) -> pl.Expr:
    """The bin label of a lead hour (null outside every bin)."""
    expr = pl.lit(None, pl.String)
    for first, last in reversed(BINS):
        expr = (
            pl.when(lead.is_between(first, last))
            .then(pl.lit(bin_label(first, last)))
            .otherwise(expr)
        )
    return expr


# --- nights ----------------------------------------------------------------------------


def nights(first: date, last: date) -> pl.DataFrame:
    """``night`` (the evening's date), ``start`` and ``end`` (UTC) and ``hours`` (full
    hours from 18:00 to 09:00 local, inclusive) for every night from ``first`` to
    ``last``."""
    rows, day = [], first
    while day <= last:
        start = datetime(day.year, day.month, day.day, NIGHT_FROM_H, tzinfo=PRAGUE)
        nxt = day + timedelta(days=1)
        end = datetime(nxt.year, nxt.month, nxt.day, NIGHT_TO_H, tzinfo=PRAGUE)
        start_utc, end_utc = start.astimezone(UTC), end.astimezone(UTC)
        hours = int((end_utc - start_utc).total_seconds() // 3600) + 1
        rows.append((day, start_utc, end_utc, hours))
        day = nxt
    return pl.DataFrame(
        rows,
        schema={
            "night": pl.Date,
            "start": pl.Datetime("us", "UTC"),
            "end": pl.Datetime("us", "UTC"),
            "hours": pl.UInt32,
        },
        orient="row",
    )


def night_of(time: pl.Expr) -> pl.Expr:
    """The night (its evening's local date) of a UTC full hour, null for day hours."""
    local = time.dt.convert_time_zone("Europe/Prague")
    hour = local.dt.hour()
    return (
        pl.when(hour >= NIGHT_FROM_H)
        .then(local.dt.date())
        .when(hour <= NIGHT_TO_H)
        .then(local.dt.date() - pl.duration(days=1))
        .otherwise(None)
        .cast(pl.Date)
    )


def block_end(time: pl.Expr) -> pl.Expr:
    """End of the 3-hour UTC block (00-03, 03-06, …) an hour ending at ``time`` is in."""
    return (time - pl.duration(hours=1)).dt.truncate(f"{BLOCK_H}h") + pl.duration(hours=BLOCK_H)


# --- observed units ------------------------------------------------------------------


def observed_units(observations: pl.LazyFrame | pl.DataFrame, event: str) -> pl.DataFrame:
    """``station_id``, ``unit_end`` (UTC end of the night or block), ``observed``."""
    spec = EVENTS[event]
    obs = (
        observations.lazy()
        .filter(pl.col("variable") == spec["variable"], pl.col("time").dt.minute() == 0)
        .select("station_id", "time", pl.col("value").cast(pl.Float64))
        .drop_nulls("value")
        .unique(["station_id", "time"], keep="first")
    )
    if spec["unit"] == "night":
        found = obs.with_columns(night_of(pl.col("time")).alias("night")).drop_nulls("night")
        span = found.select(pl.col("night").min().alias("a"), pl.col("night").max().alias("b"))
        bounds = span.collect()
        if bounds.height == 0 or bounds["a"][0] is None:
            return pl.DataFrame(
                schema={
                    "station_id": pl.String,
                    "unit_end": pl.Datetime("us", "UTC"),
                    "observed": pl.Float64,
                }
            )
        table = nights(bounds["a"][0], bounds["b"][0])
        return (
            found.group_by("station_id", "night")
            .agg(pl.col("value").min().alias("observed"), pl.len().alias("n"))
            .join(table.lazy(), on="night")
            .filter(pl.col("n") == pl.col("hours"))
            .select("station_id", pl.col("end").alias("unit_end"), "observed")
            .collect()
        )
    how = pl.col("value").sum() if spec["variable"] == "precipitation" else pl.col("value").max()
    return (
        obs.with_columns(block_end(pl.col("time")).alias("unit_end"))
        .group_by("station_id", "unit_end")
        .agg(how.alias("observed"), pl.len().alias("n"))
        .filter(pl.col("n") == BLOCK_H)
        .select("station_id", "unit_end", "observed")
        .collect()
    )


# --- forecast units ------------------------------------------------------------------


def _steps(models: list[Model]) -> pl.DataFrame:
    """``model``, ``lead_h``, ``step``, ``native`` and ``native_before`` (native hours
    up to and including the lead) for leads 1-120."""
    rows = []
    for m in models:
        count = 0
        for lead in range(1, runs_mod.MAX_LEAD_H + 1):
            native = m.native_hour(lead)
            count += native
            rows.append((m.id, lead, m.step_at(lead), native, count))
    return pl.DataFrame(
        rows,
        schema={
            "model": pl.String,
            "lead_h": pl.Int16,
            "step": pl.Int8,
            "native": pl.Boolean,
            "native_before": pl.Int32,
        },
        orient="row",
    )


def forecast_units(forecasts: pl.DataFrame, models: list[Model], event: str) -> pl.DataFrame:
    """``run``, ``model``, ``station_id``, ``unit_end``, ``end_lead``, ``forecast``: one row
    per complete unit of a model's run (see the module docstring for "complete")."""
    spec = EVENTS[event]
    variable = spec["variable"]
    steps = _steps(models)
    rows = (
        forecasts.lazy()
        .select(
            "run",
            "model",
            "station_id",
            "lead_h",
            "valid_time",
            pl.col(variable).cast(pl.Float64).alias("v"),
        )
        .with_columns(pl.col("lead_h").cast(pl.Int16))
        .join(steps.lazy(), on=["model", "lead_h"])
    )
    out = ["run", "model", "station_id", "unit_end", "end_lead", "forecast"]
    if spec["unit"] == "night":
        found = rows.filter(pl.col("native")).with_columns(
            night_of(pl.col("valid_time")).alias("night")
        )
        found = found.drop_nulls("night").collect()
        if found.height == 0:
            return pl.DataFrame(schema={c: t for c, t in _UNIT_SCHEMA.items() if c in out})
        table = nights(found["night"].min(), found["night"].max())
        hours = lambda t: ((pl.col(t) - pl.col("run")).dt.total_hours()).cast(pl.Int16)  # noqa: E731
        units = (
            found.group_by("run", "model", "station_id", "night")
            .agg(pl.col("v").min().alias("forecast"), pl.col("v").count().alias("n"))
            .join(table, on="night")
            .with_columns(hours("start").alias("start_lead"), hours("end").alias("end_lead"))
            .filter(pl.col("start_lead") >= 1, pl.col("end_lead") <= runs_mod.MAX_LEAD_H)
        )
        # every native hour of the night must have a value
        cum = steps.select("model", "lead_h", "native_before")
        units = (
            units.join(
                cum.rename({"lead_h": "end_lead", "native_before": "c_end"}),
                on=["model", "end_lead"],
            )
            .join(
                cum.rename({"lead_h": "start_lead", "native_before": "c_start"}),
                on=["model", "start_lead"],
            )
            .join(
                steps.select("model", pl.col("lead_h").alias("start_lead"), "native"),
                on=["model", "start_lead"],
            )
            .filter(
                pl.col("n") == pl.col("c_end") - pl.col("c_start") + pl.col("native").cast(pl.Int32)
            )
        )
        return units.select(
            pl.col("end").alias("unit_end"), *[c for c in out if c != "unit_end"]
        ).select(out)
    blocks = rows.with_columns(
        (pl.col("lead_h") + (BLOCK_H - 1) - (pl.col("lead_h") - 1) % BLOCK_H).alias("end_lead")
    )
    if variable == "precipitation":
        value, needed = pl.col("v").sum(), pl.lit(BLOCK_H)
        use = blocks
    else:  # gusts: the model's own output hours only
        value = pl.col("v").max()
        needed = pl.lit(BLOCK_H) // pl.col("step_max")
        use = blocks.filter(pl.col("native"))
    return (
        use.group_by("run", "model", "station_id", "end_lead")
        .agg(
            value.alias("forecast"),
            pl.col("v").count().alias("n"),
            pl.col("step").max().alias("step_max"),
        )
        .filter(pl.col("step_max") <= BLOCK_H, pl.col("n") == needed.cast(pl.UInt32))
        .with_columns(
            pl.col("end_lead").cast(pl.Int16),
            (pl.col("run") + pl.duration(hours=pl.col("end_lead"))).alias("unit_end"),
        )
        .select(out)
        .collect()
    )


_UNIT_SCHEMA = {
    "run": pl.Datetime("us", "UTC"),
    "model": pl.String,
    "station_id": pl.String,
    "unit_end": pl.Datetime("us", "UTC"),
    "end_lead": pl.Int16,
    "forecast": pl.Float64,
}


# --- the fair set --------------------------------------------------------------------


def coverage(forecasts: pl.LazyFrame | pl.DataFrame) -> pl.DataFrame:
    """``model``, ``variable``, ``first_h``, ``last_h``: the leads a model usually has a
    value for (median per run hour of the first and last lead with a value; over the run
    hours the latest first and the earliest last)."""
    frame = forecasts.lazy()
    names = frame.collect_schema().names()
    variables = sorted({e["variable"] for e in EVENTS.values()} & set(names))
    parts = []
    for variable in variables:
        parts.append(
            frame.filter(pl.col(variable).is_not_null())
            .group_by("model", "run")
            .agg(pl.col("lead_h").min().alias("first"), pl.col("lead_h").max().alias("last"))
            .with_columns(pl.col("run").dt.hour().alias("run_hour"))
            .group_by("model", "run_hour")
            .agg(
                pl.col("first").median().ceil().alias("first"),
                pl.col("last").median().floor().alias("last"),
            )
            .group_by("model")
            .agg(
                pl.col("first").max().cast(pl.Int16).alias("first_h"),
                pl.col("last").min().cast(pl.Int16).alias("last_h"),
                pl.col("run_hour").n_unique().alias("run_hours"),
            )
            .with_columns(pl.lit(variable).alias("variable"))
        )
    if not parts:
        return pl.DataFrame(
            schema={
                "model": pl.String,
                "first_h": pl.Int16,
                "last_h": pl.Int16,
                "run_hours": pl.UInt32,
                "variable": pl.String,
            }
        )
    return pl.concat(parts).collect().sort("variable", "model")


def required(cover: pl.DataFrame, models: list[Model]) -> pl.DataFrame:
    """``event``, ``bin``, ``model`` and ``n_required``: the models compared per event and
    bin. A run hour in which other models have the variable but this one does not counts
    as not covered (gusts exist only in runs fetched since they were added)."""
    catalogue = {m.id: m for m in models}
    rows = []
    for event, spec in EVENTS.items():
        mine = cover.filter(pl.col("variable") == spec["variable"])
        if mine.height == 0:
            continue
        here = mine.filter(pl.col("run_hours") == mine["run_hours"].max())
        for model, first_h, last_h in here.select("model", "first_h", "last_h").rows():
            m = catalogue.get(model)
            if m is None:
                continue
            for first, last in BINS:
                if spec["unit"] == "night":
                    ok = last_h >= last
                else:
                    steps = {m.step_at(h) for h in range(first, last + 1)}
                    ok = first_h <= first and last_h >= last and max(steps) <= BLOCK_H
                if ok:
                    rows.append((event, bin_label(first, last), model))
    table = pl.DataFrame(
        rows, schema={"event": pl.String, "bin": pl.String, "model": pl.String}, orient="row"
    )
    return table.with_columns(pl.len().over("event", "bin").cast(pl.UInt32).alias("n_required"))


# --- counting ------------------------------------------------------------------------


def _event(value: pl.Expr, op: str, threshold: float) -> pl.Expr:
    return value <= threshold if op == "le" else value >= threshold


def fair_pairs(
    forecasts: pl.DataFrame,
    observed: dict[str, pl.DataFrame],
    required_: pl.DataFrame,
    models: list[Model],
) -> pl.DataFrame:
    """Forecast-observation pairs of every event on the fair set: ``event``, ``bin``,
    ``model``, ``run``, ``station_id``, ``unit_end``, ``forecast``, ``observed``."""
    found = []
    for event in EVENTS:
        units = forecast_units(forecasts, models, event)
        if units.height == 0:
            continue
        joined = (
            units.with_columns(
                bin_expr(pl.col("end_lead")).alias("bin"), pl.lit(event).alias("event")
            )
            .drop_nulls("bin")
            .join(observed[event], on=["station_id", "unit_end"])
            .join(required_, on=["event", "bin", "model"])
            .filter(pl.len().over("bin", *UNIT_KEYS) == pl.col("n_required"))
            .select("event", "bin", "model", *UNIT_KEYS, "forecast", "observed")
        )
        found.append(joined)
    if not found:
        return pl.DataFrame(
            schema={
                "event": pl.String,
                "bin": pl.String,
                "model": pl.String,
                **{k: _UNIT_SCHEMA[k] for k in UNIT_KEYS},
                "forecast": pl.Float64,
                "observed": pl.Float64,
            }
        )
    return pl.concat(found)


def count(pairs: pl.DataFrame) -> pl.DataFrame:
    """Counts per ``event``, ``threshold``, ``bin``, ``model`` (additive)."""
    parts = []
    for event, spec in EVENTS.items():
        mine = pairs.filter(pl.col("event") == event)
        if mine.height == 0:
            continue
        for threshold in spec["thresholds"]:
            f = _event(pl.col("forecast"), spec["op"], threshold)
            o = _event(pl.col("observed"), spec["op"], threshold)
            parts.append(
                mine.group_by("event", "bin", "model")
                .agg(
                    pl.len().alias("units"),
                    (f & o).sum().cast(pl.Int64).alias("hits"),
                    (~f & o).sum().cast(pl.Int64).alias("misses"),
                    (f & ~o).sum().cast(pl.Int64).alias("false_alarms"),
                    (~f & ~o).sum().cast(pl.Int64).alias("correct_negatives"),
                )
                .with_columns(pl.lit(threshold).alias("threshold"))
            )
    if not parts:
        return pl.DataFrame()
    return pl.concat(parts)


def _ratio(numerator: pl.Expr, denominator: pl.Expr) -> pl.Expr:
    return pl.when(denominator > 0).then(numerator / denominator).otherwise(None)


def scores(counts: pl.DataFrame) -> pl.DataFrame:
    """POD, FAR, CSI, ETS and frequency bias from the counts."""
    a, c, b, d = (pl.col(k).cast(pl.Float64) for k in COUNT_COLUMNS)
    random_hits = _ratio((a + b) * (a + c), a + b + c + d)
    return counts.with_columns(
        (pl.col("hits") + pl.col("misses")).alias("events"),
        _ratio(a, a + c).alias("pod"),
        _ratio(b, a + b).alias("far"),
        _ratio(a, a + b + c).alias("csi"),
        _ratio(a - random_hits, a + b + c - random_hits).alias("ets"),
        _ratio(a + b, a + c).alias("bias"),
    )


def farm_scores(
    forecasts: pl.LazyFrame | pl.DataFrame,
    observations: pl.LazyFrame | pl.DataFrame,
    models: list[Model],
    chunk_runs: int = 24,
) -> tuple[pl.DataFrame, dict]:
    """Event scores per event, threshold, bin and model on the fair set (``COLUMNS``),
    and facts about the sample (``models``, ``first_run``, ``last_run``, ``stations``,
    ``runs``, ``required``, ``short_record``: the models left out for too few runs,
    ``runs.coverage``)."""
    forecasts = forecasts.lazy()
    names = forecasts.collect_schema().names()
    if "wind_gusts_10m" not in names:  # month files from before the gusts
        forecasts = forecasts.with_columns(pl.lit(None, pl.Float32).alias("wind_gusts_10m"))
    run_cover = runs_mod.coverage(forecasts)
    forecasts = forecasts.join(
        run_cover.filter("covered").select("model").lazy(), on="model", how="semi"
    )
    cover = coverage(forecasts)
    required_ = required(cover, models)
    stations = forecasts.select("station_id").unique().collect()["station_id"].to_list()
    obs = observations.lazy().filter(pl.col("station_id").is_in(stations))
    observed = {event: observed_units(obs, event) for event in EVENTS}
    run_list = sorted(forecasts.select("run").unique().collect()["run"].to_list())
    sums, keys, used = [], ["event", "threshold", "bin", "model"], []
    unit_sets = []
    for i in range(0, len(run_list), chunk_runs):
        chunk = forecasts.filter(pl.col("run").is_in(run_list[i : i + chunk_runs])).collect()
        pairs = fair_pairs(chunk, observed, required_, models)
        if pairs.height == 0:
            continue
        sums.append(count(pairs))
        unit_sets.append(pairs.select("event", "bin", "model", "run", "station_id").unique())
        used.append(pairs.select("model", "run", "station_id"))
    info = {
        "models": {},
        "first_run": None,
        "last_run": None,
        "stations": 0,
        "runs": 0,
        "required": required_,
        "coverage": cover,
        "short_record": runs_mod.short_records(run_cover),
    }
    if not sums:
        return pl.DataFrame(schema={c: pl.Null for c in COLUMNS}).clear(), info
    totals = pl.concat(sums).group_by(keys).agg(pl.all().sum())
    spread = (
        pl.concat(unit_sets)
        .unique()
        .group_by("event", "bin", "model")
        .agg(
            pl.col("run").n_unique().alias("runs"),
            pl.col("station_id").n_unique().alias("stations"),
        )
    )
    order = pl.DataFrame(
        [
            (event, threshold, n * 10 + k)
            for n, (event, spec) in enumerate(EVENTS.items())
            for k, threshold in enumerate(spec["thresholds"])
        ],
        schema={"event": pl.String, "threshold": pl.Float64, "_o": pl.Int32},
        orient="row",
    )
    bins = {bin_label(*b): i for i, b in enumerate(BINS)}
    table = (
        scores(totals.join(spread, on=["event", "bin", "model"]))
        .join(order, on=["event", "threshold"])
        .with_columns(pl.col("bin").replace_strict(bins, return_dtype=pl.Int8).alias("_b"))
        .sort("_o", "_b", "model")
        .select(COLUMNS)
    )
    every = pl.concat(used)
    per_model = every.group_by("model").agg(pl.col("run").n_unique().alias("runs")).sort("model")
    info["models"] = dict(per_model.rows())
    info["first_run"] = every["run"].min()
    info["last_run"] = every["run"].max()
    info["stations"] = every["station_id"].n_unique()
    info["runs"] = every["run"].n_unique()
    return table, info


# --- the document --------------------------------------------------------------------


def document(
    table: pl.DataFrame, info: dict, generated: datetime, names: dict[str, str] | None = None
) -> dict:
    """``farm.json``: header and ``{"columns", "rows"}``."""
    stamp = "%Y-%m-%dT%H:%MZ"
    rounded = table.select(
        pl.col(c).round(3) if c in ("pod", "far", "csi", "ets", "bias") else pl.col(c)
        for c in COLUMNS
    )
    cover = info.get("coverage")
    reach = {}
    if cover is not None and cover.height:
        for model, variable, first_h, last_h in cover.select(
            "model", "variable", "first_h", "last_h"
        ).rows():
            reach.setdefault(model, {})[variable] = [first_h, last_h]
    return {
        "generated": generated.strftime(stamp),
        "source": "Open-Meteo Single Runs API (free, non-commercial use); ČHMÚ observations",
        "about": (
            "Yes/no events for farmers verified run by run: frost nights, strong gusts and "
            "3-hour rain, per model and lead time bin, against ČHMÚ observations at about "
            "100 stations. Not the D+N scores."
        ),
        "fair_set": (
            "Per event and lead bin only the models whose runs cover the whole bin (and, for "
            "the 3-hour blocks, have at most 3-hourly output there) are compared, on the "
            "runs, stations and nights or blocks that every one of them has. Models with "
            f"fewer than {runs_mod.MIN_COVERAGE:.0%} of the period's runs (short_record, "
            "e.g. newly added) are left out until they have them."
        ),
        "short_record": info.get("short_record", {}),
        "first_run": info["first_run"].strftime(stamp) if info["first_run"] else None,
        "last_run": info["last_run"].strftime(stamp) if info["last_run"] else None,
        "runs": info["runs"],
        "stations": info["stations"],
        "bins": [bin_label(*b) for b in BINS],
        "small_sample": SMALL_SAMPLE,
        "events": {
            event: {
                "variable": spec["variable"],
                "unit": spec["unit"],
                "op": "<=" if spec["op"] == "le" else ">=",
                "thresholds": list(spec["thresholds"]),
                "definition": spec["definition"],
            }
            for event, spec in EVENTS.items()
        },
        "models": {
            model: {
                "name": (names or {}).get(model, model),
                "runs": runs,
                "leads": reach.get(model, {}),
            }
            for model, runs in info["models"].items()
        },
        "column_notes": {
            "event": "frost (night), gust (3-hour block), rain3h (3-hour block)",
            "threshold": "°C (frost: value <= threshold), m/s or mm (value >= threshold)",
            "bin": "lead hours after the run's start, by the end of the night or block",
            "units": "nights or blocks scored (station x run), the same for every model of a bin",
            "events": "observed events (hits + misses)",
            "hits, misses, false_alarms, correct_negatives": "the 2x2 counts",
            "pod": "hits / events: share of the observed events that were forecast",
            "far": "false alarms / forecast events: share of the warnings that were wrong",
            "csi": "hits / (hits + misses + false alarms)",
            "ets": "CSI corrected for hits by chance (1 perfect, 0 no skill)",
            "bias": "forecast events / observed events (1 unbiased, > 1 too many warnings)",
        },
        "columns": COLUMNS,
        "rows": rounded.rows(),
    }


def summary(table: pl.DataFrame) -> list[str]:
    """Lines like ``frost <= 0: 13-24 h: 41 events in 2,300 nights; best ETS dwd_icon_d2 0.52``."""
    lines = []
    if table.height == 0:
        return lines
    for (event, threshold, bin_), part in table.group_by(
        "event", "threshold", "bin", maintain_order=True
    ):
        op = "<=" if EVENTS[event]["op"] == "le" else ">="
        ranked = part.drop_nulls("ets").sort("ets", descending=True)
        best = (
            f"best ETS {ranked['model'][0]} {ranked['ets'][0]:.2f}" if ranked.height else "no ETS"
        )
        lines.append(
            f"{event} {op} {threshold:g}: H+{bin_}: {part['events'][0]} events in "
            f"{part['units'][0]:,} units, {part.height} models; {best}"
        )
    return lines


def write(doc: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path
