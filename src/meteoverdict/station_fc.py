"""Every model's forecast at the station point, by day, next to what the station measured
(``mvd station-fc``): the data of the measured page's model selector (measured.html).

The measured page used to compare the measurements with one okres-level forecast, which is
several degrees off at a mountain station. The single runs (``runs``) hold every model's
forecast at the ~300 run stations, at the station's own elevation: from them, for each
station, model and lead day, the day's values the measured page shows: ``tmax`` and
``tmin`` (°C), ``r`` (precipitation, mm), ``wind`` (mean 10 m wind, m/s) and ``gust``
(highest gust, m/s), for the Prague calendar day.

**Lead day D+N** is the 00 UTC run of day D-N (so D+1 is yesterday's morning run), N = 1
or 2. A model-day counts only when the run's steps cover the day (a first step in the
first six hours and a last one in the last six, at least four steps): a model with 3- or
6-hourly steps still gets an extreme from fewer points, which is a little too mild; that
is a property of the model's output and told on the page. ``blend`` is
MeteoVerdict's weighted mean at the station: the models that have the day (at least
``MIN_MEMBERS``) weighted by the weights of the station's okres (``forecast-weights``,
the same weights as the forecast, per lead day; no bias correction), a plain mean for a
value or station the weights do not cover (and without weights at all).

The measurements are taken the same way from the hourly observations (``obs``), so the
differences compare like with like: a day needs at least ``MIN_OBS_HOURS`` hourly values.

Output (``write``), one file per station with at least one forecast day, in the layout of
``series/<station>.json`` (``aggregate.write_series``) with values instead of errors:
``{"from", "to", "obs": {value: [per day]}, "series": {value: {lead day: {model:
[per day]}}}}`` over the last ``DAYS`` days (null = no value; shorter than ``series/``,
the site is near its size budget), plus ``index.json`` (the models' names and the
stations). Published as ``station-fc.zip``.

The model-error map (measured.html colours the station dots by what the chosen model got
wrong) needs one day of all stations at once, which the per-station files cannot give
without ~300 requests. So ``write`` also makes ``err-<day>.json`` per day: ``{"day",
"scale": 10, "stations": [ids, the order of the lists], "e": {value: {lead day: {model:
[per station]}}}}`` with the model's value minus the measured one in tenths (integers;
null = the model or the station has no value that day), for ``ERROR_VALUES``: about
140 kB a day, ~5 MB for the ``DAYS`` days.
"""

from __future__ import annotations

import json
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from meteoverdict import blend

DAYS = 35
LEADS = (1, 2)
RUN_HOUR = 0
TIME_ZONE = "Europe/Prague"
MIN_MEMBERS = blend.MIN_MEMBERS
MIN_STEPS = 4
MIN_OBS_HOURS = 20
#: value → (source variable, aggregation)
VALUES = {
    "tmax": ("temperature_2m", "max"),
    "tmin": ("temperature_2m", "min"),
    "r": ("precipitation", "sum"),
    "wind": ("wind_speed_10m", "mean"),
    "gust": ("wind_gusts_10m", "max"),
}
#: the values of the per-day error files (the dots of the map; gusts are not mapped)
ERROR_VALUES = ("tmax", "tmin", "r", "wind")
ERROR_SCALE = 10
UNITS = {"tmax": "°C", "tmin": "°C", "r": "mm", "wind": "m/s", "gust": "m/s"}
#: Open-Meteo's precipitation (and the observations') is the total of the preceding
#: interval: a value at 00:00 belongs to the day before
SUM_VARIABLES = ("precipitation",)


def _aggregate(name: str, variable: str, how: str) -> pl.Expr:
    column = pl.col(variable)
    return getattr(column, how)().alias(name)


def _day_of(time: str, variable: str) -> pl.Expr:
    local = pl.col(time).dt.convert_time_zone(TIME_ZONE)
    if variable in SUM_VARIABLES:
        local = local - pl.duration(seconds=1)
    return local.dt.date()


def daily_forecasts(
    runs: pl.LazyFrame | pl.DataFrame,
    first: date,
    last: date,
    weights: pl.DataFrame | None = None,
    station_okres: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Per station, model, lead day and day: ``tmax``, ``tmin``, ``r``, ``wind``, ``gust``
    (null where the model lacks the variable or the day is not covered), for the days
    ``first`` to ``last`` from the 00 UTC runs. ``blend`` rows are added: the weighted
    mean (``weights``: the forecast's weight table, ``station_okres``: ``station_id`` and
    ``okres_code``) or, without them, the plain mean."""
    since = datetime.combine(first - timedelta(days=max(LEADS)), datetime.min.time())
    until = datetime.combine(last + timedelta(days=1), datetime.min.time())
    base = (
        runs.lazy()
        .filter(
            pl.col("run").dt.hour() == RUN_HOUR,
            pl.col("run").dt.replace_time_zone(None).is_between(since, until),
            pl.col("lead_h") <= (max(LEADS) + 1) * 24 + 2,
        )
        .with_columns(pl.col("run").dt.date().alias("run_day"))
    )
    parts = []
    for variable in sorted({v for v, _ in VALUES.values()}):
        wanted = {n: how for n, (v, how) in VALUES.items() if v == variable}
        hours = pl.col("valid_time").dt.convert_time_zone(TIME_ZONE).dt.hour()
        part = (
            base.filter(pl.col(variable).is_not_null())
            .with_columns(_day_of("valid_time", variable).alias("date"), hours.alias("hour"))
            .with_columns((pl.col("date") - pl.col("run_day")).dt.total_days().alias("lead_day"))
            .filter(pl.col("lead_day").is_in(LEADS), pl.col("date").is_between(first, last))
            .group_by("station_id", "model", "lead_day", "date")
            .agg(
                pl.len().alias("steps"),
                pl.col("hour").min().alias("h0"),
                pl.col("hour").max().alias("h1"),
                *[_aggregate(n, variable, how) for n, how in wanted.items()],
            )
            # the steps cover the day (a precipitation total at 00:00 sits at hour 23)
            .filter(pl.col("steps") >= MIN_STEPS, pl.col("h0") <= 5, pl.col("h1") >= 18)
            .drop("steps", "h0", "h1")
        )
        parts.append(part)
    keys = ["station_id", "model", "lead_day", "date"]
    frame = parts[0]
    for part in parts[1:]:
        frame = frame.join(part, on=keys, how="full", coalesce=True)
    daily = frame.collect()
    return pl.concat([daily, _blend(daily, weights, station_okres)], how="diagonal_relaxed").sort(
        keys
    )


def _blend(
    daily: pl.DataFrame,
    weights: pl.DataFrame | None = None,
    station_okres: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """The blend per station, lead day and day, where at least MIN_MEMBERS models have the
    value: the mean weighted by the station's okres weights of the value's variable and
    lead day, the plain mean where a station or value has no weights."""
    values = list(VALUES)
    members = daily.filter(pl.col("model") != blend.ID)
    plain = [
        pl.when(pl.col(v).count() >= MIN_MEMBERS).then(pl.col(v).mean()).alias(v) for v in values
    ]
    keys = ["station_id", "lead_day", "date"]
    means = members.group_by(keys).agg(plain)
    if weights is not None and station_okres is not None and weights.height:
        by_okres = members.join(
            station_okres.select("station_id", pl.col("okres_code").alias("region")),
            on="station_id",
            how="left",
        )
        for value, (variable, _) in VALUES.items():
            table = weights.filter(pl.col("variable") == variable).select(
                "region", "lead_day", "model", "weight"
            )
            if table.is_empty():
                continue
            weighted = (
                by_okres.filter(pl.col(value).is_not_null())
                .join(table, on=["region", "lead_day", "model"], how="left")
                .group_by(keys)
                .agg(
                    pl.col(value).count().alias("_n"),
                    pl.col("weight").is_not_null().sum().alias("_covered"),
                    (pl.col(value) * pl.col("weight")).sum().alias("_num"),
                    pl.col("weight").sum().alias("_den"),
                )
                # only when every member has a weight: a partial set would skew the mean
                .filter((pl.col("_n") >= MIN_MEMBERS) & (pl.col("_covered") == pl.col("_n")))
                .filter(pl.col("_den") > 0)
                .select(*keys, (pl.col("_num") / pl.col("_den")).alias("_w"))
            )
            means = (
                means.join(weighted, on=keys, how="left")
                .with_columns(pl.coalesce("_w", value).alias(value))
                .drop("_w")
            )
    return means.with_columns(pl.lit(blend.ID).alias("model")).filter(
        pl.any_horizontal(pl.col(v).is_not_null() for v in values)
    )


def daily_observations(obs: pl.LazyFrame | pl.DataFrame, first: date, last: date) -> pl.DataFrame:
    """Per station and Prague day: the same five values from the hourly observations,
    for days with at least MIN_OBS_HOURS hourly values of the variable."""
    parts = []
    for variable in sorted({v for v, _ in VALUES.values()}):
        wanted = {n: how for n, (v, how) in VALUES.items() if v == variable}
        part = (
            obs.lazy()
            .filter(pl.col("variable") == variable, pl.col("value").is_not_null())
            .with_columns(_day_of("time", variable).alias("date"))
            .filter(pl.col("date").is_between(first, last))
            .group_by("station_id", "date")
            .agg(pl.len().alias("n"), *[_aggregate(n, "value", how) for n, how in wanted.items()])
            .filter(pl.col("n") >= MIN_OBS_HOURS)
            .drop("n")
        )
        parts.append(part)
    frame = parts[0]
    for part in parts[1:]:
        frame = frame.join(part, on=["station_id", "date"], how="full", coalesce=True)
    return frame.collect().sort("station_id", "date")


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 1)


def documents(
    forecasts: pl.DataFrame, observed: pl.DataFrame, first: date, last: date
) -> dict[str, dict]:
    """One document per station that has a forecast day (see the module doc)."""
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    docs: dict[str, dict] = {}
    obs_by_station = {k[0]: v for k, v in observed.partition_by("station_id", as_dict=True).items()}
    for (station,), rows in forecasts.partition_by("station_id", as_dict=True).items():
        series: dict[str, dict[str, dict[str, list]]] = {}
        for value in VALUES:
            if value not in rows.columns:
                continue
            for (lead, model), part in rows.partition_by("lead_day", "model", as_dict=True).items():
                got = dict(zip(part["date"], part[value], strict=True))
                column = [_round(got.get(d)) for d in days]
                if any(v is not None for v in column):
                    series.setdefault(value, {}).setdefault(str(lead), {})[model] = column
        if not series:
            continue
        measured = obs_by_station.get(station)
        obs = {}
        if measured is not None:
            for value in VALUES:
                if value in measured.columns:
                    got = dict(zip(measured["date"], measured[value], strict=True))
                    obs[value] = [_round(got.get(d)) for d in days]
        docs[station] = {"from": str(first), "to": str(last), "obs": obs, "series": series}
    return docs


def error_documents(docs: dict[str, dict]) -> dict[str, dict]:
    """``err-<day>`` documents (see the module doc) from the station documents: per day, the
    model's value minus the measured one (tenths) for every station in ``docs``, in the
    order of ``sorted(docs)``, which is the order of ``index.json``'s stations."""
    stations = sorted(docs)
    if not stations:
        return {}
    first = date.fromisoformat(docs[stations[0]]["from"])
    n = (date.fromisoformat(docs[stations[0]]["to"]) - first).days + 1
    out: dict[str, dict] = {}
    for i in range(n):
        errors: dict[str, dict[str, dict[str, list]]] = {}
        for k, station in enumerate(stations):
            doc = docs[station]
            for value in ERROR_VALUES:
                observed = doc["obs"].get(value)
                if not observed or observed[i] is None:
                    continue
                for lead, models in doc["series"].get(value, {}).items():
                    for model, column in models.items():
                        if column[i] is None:
                            continue
                        row = (
                            errors.setdefault(value, {})
                            .setdefault(lead, {})
                            .setdefault(model, [None] * len(stations))
                        )
                        row[k] = round((column[i] - observed[i]) * ERROR_SCALE)
        if errors:
            day = str(first + timedelta(days=i))
            out[day] = {"day": day, "scale": ERROR_SCALE, "stations": stations, "e": errors}
    return out


def write(
    docs: dict[str, dict],
    out_dir: Path,
    names: dict[str, str],
    generated: datetime,
) -> list[Path]:
    """``out_dir/<station>.json``, ``err-<day>.json`` and ``out_dir/index.json``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for station, doc in docs.items():
        path = out_dir / f"{station}.json"
        path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        written.append(path)
    models = sorted(
        {
            m
            for d in docs.values()
            for v in d["series"].values()
            for lead in v.values()
            for m in lead
        }
    )
    index = {
        "generated": generated.strftime("%Y-%m-%dT%H:%MZ"),
        "from": next(iter(docs.values()))["from"] if docs else None,
        "to": next(iter(docs.values()))["to"] if docs else None,
        "leads": list(LEADS),
        "units": UNITS,
        "models": {m: names.get(m, m) for m in models},
        "stations": sorted(docs),
    }
    path = out_dir / "index.json"
    path.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for day, doc in error_documents(docs).items():
        err = out_dir / f"err-{day}.json"
        err.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        written.append(err)
    return [*written, path]


def write_zip(paths: list[Path], path: Path) -> Path:
    """The files in one zip (one release asset instead of ~300)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for p in paths:
            archive.write(p, p.name)
    return path
