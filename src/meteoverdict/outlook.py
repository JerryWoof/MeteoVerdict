"""TV-style forecast for every okres (roadmap 6.6).

Four times a day (after the 00, 06, 12 and 18 UTC model runs), read the next ``DAYS``
days of all models at the forecast point of every okres from Open-Meteo's open-data
bucket (``meteoverdict.outlook_bucket``, no API calls; until 2026-10-20 one Forecast API
request for the 77 locations, which now only asks for a model the bucket lacks),
combine them with the
okres weights of ``meteoverdict.combine`` (the same rules as the forecast page: bias
correction, weights per lead day, the next 24 h with D+1, models fading out over their
last ``TAPER_HOURS`` hours) and summarise each day by part of day in Prague time:
night 0-6, morning 6-12, afternoon 12-18, evening 18-24.

Per part of day and per whole day: minimum and maximum of the combined temperature,
combined precipitation total, **probability of precipitation** (the share of models
whose own total for that period is at least ``WET_MM``, every model counting the same;
averaging rain smooths it, see docs/forecast-research.md; for parts of day blended 50/50
with a calibrated probability when ``rain-calibration.json`` is there, see
``meteoverdict.rain_calibration``; with it also a heavy-rain flag), the highest combined hourly
wind, mean cloud cover, hours of sunshine and a weather symbol. Cloud cover and
sunshine are the plain mean of the models corrected against ČHMÚ observations
(``meteoverdict.sun_cloud_gust``: sunshine as a share of the day length, refitted
nightly; the hourly sunshine is scaled to the corrected day). Every day also gets
its sunrise and sunset at the okres point (``meteoverdict.sun``, computed, no request).
Wind gusts (``gust``, the largest per part of day, corrected, and ``gust_over_threshold``) come
from the newest stored single run at the okres's lowland stations
(``meteoverdict.gusts``, no request); null beyond the run and without one.

Cost of the API fallback: 77 locations x 5 variables x models / 10 weighted calls a
run, only for the models the bucket lacks (all 19: about 730). A request stays at or
below ``MAX_REQUEST`` calls (Open-Meteo allows 600 a minute), so with more than 12
models the okresy are split into equal parts, a minute apart.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import polars as pl

from meteoverdict import (
    blend_interval,
    bucket,
    combine,
    frost,
    gusts,
    outlook_bucket,
    rain_calibration,
    sun_cloud_gust,
)
from meteoverdict import models as catalogue
from meteoverdict import runs as runs_mod
from meteoverdict.combine import BLEND_COLUMNS, combine_values, okres_points, point_elevations
from meteoverdict.forecasts import _reason, call_weight
from meteoverdict.sun import sun_times

URL = "https://api.open-meteo.com/v1/forecast"
VARIABLES = (
    "temperature_2m",
    "precipitation",
    "wind_speed_10m",
    "cloud_cover",
    "sunshine_duration",
)
#: further variables of each model's own hourly forecast (the per-model files only, never
#: combined; since 2026-10-22): from the bucket only, null from the API fallback, whose
#: call weight would grow with every variable (``outlook_bucket.EXTRA_VARIABLES``)
EXTRA_VARIABLES = tuple(outlook_bucket.EXTRA_VARIABLES)
#: plain means of the models, not combined with weights; corrected afterwards
#: (``sun_cloud_gust.correct_hourly``)
MEANS = ("cloud_cover", "sunshine_duration")
COMBINED = ("temperature_2m", "precipitation", "wind_speed_10m")
#: further variables combined with weights (scored against the stations, ``extras``): only
#: where the weight table has rows for them (a table from before has none: null series)
COMBINED_EXTRA = tuple(combine.EXTRA_VARIABLES)
#: variables of the models' own forecasts for which no weights exist (no or too few
#: stations measure them, or not the same quantity): the plain mean of the models, labelled
#: ``reference`` in the files, not a weighted forecast
REFERENCE = (
    "shortwave_radiation",
    "cloud_cover_low",
    "snowfall",
    "snow_depth",
    "snow_depth_water_equivalent",
    "surface_temperature",
    "visibility",
)
DAYS = 6
MAX_LEAD_DAY = 5
TAPER_HOURS = 3
TIME_ZONE = "Europe/Prague"
#: part of day → first and last local hour + 1
PARTS = {"night": (0, 6), "morning": (6, 12), "afternoon": (12, 18), "evening": (18, 24)}
#: a part of day (6 h) or day (24 h) needs at least this many hours of combined
#: temperature; the forecast starts at 00 UTC, 02:00 in Prague in summer time, so today's
#: night and the day as a whole are a few hours short
MIN_PART_HOURS = 4
MIN_DAY_HOURS = 18
#: a model "forecasts precipitation" for a period with at least this total (mm)
WET_MM = 0.2
#: symbols: precipitation when likely, otherwise by cloud cover
RAIN_PROBABILITY = 0.5
#: the "rain" symbol (and sleet, snow) also needs at least this combined total (mm);
#: 0.3 rather than WET_MM: in September 2026 it drew rain less often where none fell
#: (frequency bias 1.26 → 1.19) and scored better (ETS 0.420 → 0.430)
RAIN_MM = 0.3
SHOWER_PROBABILITY = 0.3
#: on the corrected cloud cover, which is less spread than the plain mean: 30/65 gave
#: the observed shares of clear, partly cloudy and cloudy days (25/70 % in ČHMÚ's
#: octas) and the best Heidke skill out of sample (docs/methodology.md)
CLEAR_BELOW = 30.0
PARTLY_BELOW = 65.0
SNOW_AT_OR_BELOW = 0.5
SLEET_AT_OR_BELOW = 2.0
#: refused above this (all 19 models with weights: ~732 a run, ~2,930 a day in four runs)
MAX_CALLS = 800
#: one request at most (Open-Meteo: 600 a minute); parts are ``PART_PAUSE`` s apart
MAX_REQUEST = 500
PART_PAUSE = 61
#: a run's API calls for the models the bucket lacks (since 2026-10-20; 77 okresy:
#: ~38.5 a model, so 5 models); models beyond it are left out of that run
MAX_FALLBACK_CALLS = 200


def request_params(points: pl.DataFrame, models: list[str]) -> dict:
    return {
        "latitude": ",".join(str(v) for v in points["lat"]),
        "longitude": ",".join(str(v) for v in points["lon"]),
        "hourly": ",".join(VARIABLES),
        "wind_speed_unit": "ms",
        "timezone": "GMT",
        "forecast_days": DAYS,
        "models": ",".join(models),
    }


def cost(points: int, models: int) -> float:
    return call_weight(points, len(VARIABLES) * models, DAYS)


def parts(n_points: int, n_models: int) -> list[int]:
    """Points per request: equal parts of at most ``MAX_REQUEST`` calls."""
    if n_points <= 0:
        return []
    per_point = cost(1, n_models)
    size = max(1, int(MAX_REQUEST // per_point))
    count = -(-n_points // size)
    base, extra = divmod(n_points, count)
    return [base + 1] * extra + [base] * (count - extra)


def fetch(
    client: httpx.Client,
    points: pl.DataFrame,
    models: list[str],
    sleep: Callable[[float], None],
) -> list | dict:
    """All points, in as few requests as ``MAX_REQUEST`` allows (one answer list, as if
    asked at once). Retried after a pause: the per-minute limit (429), server and
    network errors, and an answer that is not JSON."""
    weight = cost(points.height, len(models))
    if weight > MAX_CALLS:
        raise ValueError(f"{weight:.0f} weighted calls is more than MAX_CALLS = {MAX_CALLS}")
    sizes = parts(points.height, len(models))
    if len(sizes) == 1:
        return _fetch_part(client, points, models, sleep)
    merged, offset = [], 0
    for n, size in enumerate(sizes):
        if n:
            sleep(PART_PAUSE)  # stay under Open-Meteo's 600 calls a minute
        payload = _fetch_part(client, points.slice(offset, size), models, sleep)
        for position, item in enumerate(payload if isinstance(payload, list) else [payload]):
            merged.append({**item, "location_id": offset + item.get("location_id", position)})
        offset += size
    return merged


def _fetch_part(
    client: httpx.Client,
    points: pl.DataFrame,
    models: list[str],
    sleep: Callable[[float], None],
) -> list | dict:
    problem = ""
    for wait in (30, 60, 120, None):
        try:
            response = client.get(URL, params=request_params(points, models))
        except httpx.TransportError as exc:
            problem = f"{type(exc).__name__}: {exc}"
        else:
            status = response.status_code
            daily_limit = status == 429 and "daily" in response.text.lower()
            if daily_limit or (400 <= status < 500 and status != 429):
                # not worth retrying: the daily limit, a bad request
                raise RuntimeError(f"Open-Meteo forecast: HTTP {status}: {_reason(response)}")
            if status < 400:
                try:
                    return response.json()
                except ValueError:
                    problem = f"HTTP {response.status_code} with a non-JSON answer"
            else:
                problem = f"HTTP {status}: {_reason(response)}"
        if wait is None:
            break
        sleep(wait)
    raise RuntimeError(f"Open-Meteo forecast unavailable after 4 attempts ({problem})")


def parse(payload: list | dict, codes: list[str], models: list[str]) -> pl.DataFrame:
    """The API answer → one row per okres, hour and model with the variables."""
    results = payload if isinstance(payload, list) else [payload]
    if len(results) != len(codes):
        raise ValueError(f"asked for {len(codes)} locations, got {len(results)}")
    frames = []
    for position, result in enumerate(results):
        hourly = result["hourly"]
        times = pl.Series(hourly["time"]).str.to_datetime("%Y-%m-%dT%H:%M", time_zone="UTC")
        for model in models:
            columns = {v: hourly.get(f"{v}_{model}") for v in VARIABLES}
            if len(models) == 1 and all(c is None for c in columns.values()):
                # one model asked (the bucket's fallback): the API leaves out the suffix
                columns = {v: hourly.get(v) for v in VARIABLES}
            if all(c is None for c in columns.values()):
                continue
            frames.append(
                pl.DataFrame(
                    {
                        "okres": codes[result.get("location_id", position)],
                        "time": times,
                        "model": model,
                        **{v: columns[v] for v in VARIABLES},
                        **{v: None for v in EXTRA_VARIABLES},  # not asked of the API
                    },
                    schema={
                        "okres": pl.String,
                        "time": pl.Datetime("us", "UTC"),
                        "model": pl.String,
                        **{v: pl.Float64 for v in (*VARIABLES, *EXTRA_VARIABLES)},
                    },
                    strict=False,
                )
            )
    out = pl.concat(frames)
    return out.filter(~pl.all_horizontal(pl.col(v).is_null() for v in VARIABLES))


def _lead_weights(weights: pl.DataFrame) -> pl.DataFrame:
    """Weights for every lead day 1..MAX_LEAD_DAY, taking the nearest shorter lead day
    that has weights where one is missing (as the forecast page does)."""
    have = weights.select("region", "variable", "lead_day").unique()
    wanted = (
        have.select("region", "variable")
        .unique()
        .join(
            pl.DataFrame({"lead": list(range(1, MAX_LEAD_DAY + 1))}, schema={"lead": pl.Int8}),
            how="cross",
        )
    )
    source = (
        wanted.join(have, on=["region", "variable"])
        .filter(pl.col("lead_day") <= pl.col("lead"))
        .group_by("region", "variable", "lead")
        .agg(pl.col("lead_day").max())
    )
    return (
        source.join(weights, on=["region", "variable", "lead_day"])
        .drop("lead_day")
        .rename({"lead": "lead_day", "region": "okres"})
    )


def with_lead_and_fade(fc: pl.DataFrame, now: datetime) -> pl.DataFrame:
    """Add ``lead_day`` (whole days ahead of ``now``, 1 to MAX_LEAD_DAY) and ``fade``
    (1, then 3/4, 1/2, 1/4 in the last hours of a model that ends before the others)."""
    hours = (pl.col("time") - pl.lit(now)).dt.total_hours()
    last = (
        pl.col("time").filter(pl.col("temperature_2m").is_not_null()).max().over("okres", "model")
    )
    return fc.with_columns(
        pl.min_horizontal(pl.lit(MAX_LEAD_DAY), pl.max_horizontal(pl.lit(1), hours // 24))
        .cast(pl.Int8)
        .alias("lead_day"),
        # 1, then ¾, ½, ¼ in a model's last hours, unless it reaches the end of all
        pl.when(last == pl.col("time").max().over("okres"))
        .then(1.0)
        .otherwise(
            pl.min_horizontal(
                pl.lit(1.0),
                ((last - pl.col("time")).dt.total_hours() + 1) / (TAPER_HOURS + 1),
            )
        )
        .alias("fade"),
    )


def _weighted_extras(fc: pl.DataFrame, lead: pl.DataFrame) -> list[str]:
    """The ``COMBINED_EXTRA`` variables that ``fc`` has values for and ``lead`` weights."""
    weighted = set(lead["variable"].unique().to_list())
    return [v for v in COMBINED_EXTRA if v in weighted and v in fc.columns]


def combine_hourly(fc: pl.DataFrame, weights: pl.DataFrame, now: datetime) -> pl.DataFrame:
    """One row per okres and hour: the combined temperature, precipitation and wind,
    the plain means of cloud cover and sunshine, and the number of models."""
    fc = with_lead_and_fade(fc, now)
    lead = _lead_weights(weights)
    # some models publish sunshine slightly outside the hour (seen: 3605.6 and -1.0 s)
    fc = fc.with_columns(pl.col("sunshine_duration").clip(0.0, 3600.0))
    out = fc.group_by("okres", "time").agg(
        *[pl.col(v).mean() for v in MEANS],
        *[pl.col(v).mean().alias(f"{v}_reference") for v in REFERENCE if v in fc.columns],
        pl.col("model").n_unique().alias("models"),
    )
    for variable in (*COMBINED, *_weighted_extras(fc, lead)):
        # with the regression blend's weights and slot corrections where there are some
        blend_columns = [c for c in BLEND_COLUMNS if c in lead.columns]
        w = lead.filter(pl.col("variable") == variable).select(
            "okres", "lead_day", "model", *blend_columns
        )
        part = combine_values(
            fc.select("okres", "time", "model", "lead_day", "fade", variable)
            .join(w, on=["okres", "lead_day", "model"])
            .with_columns((pl.col("weight") * pl.col("fade")).alias("w")),
            variable,
            ["okres", "time"],
            weight="w",
        )
        out = out.join(part, on=["okres", "time"], how="left")
    if "dew_point_2m" in out.columns:  # the dew point never above the air temperature
        out = out.with_columns(
            pl.min_horizontal("dew_point_2m", "temperature_2m").alias("dew_point_2m")
        )
    return out.sort("okres", "time")


def _local(frame: pl.DataFrame, hour_ending: bool = False) -> pl.DataFrame:
    """Add the local ``day`` and ``part`` of each row; ``hour_ending``: by the hour that
    ends at ``time`` (sums such as precipitation and sunshine), else by ``time`` itself."""
    time = pl.col("time") - pl.duration(hours=1) if hour_ending else pl.col("time")
    local = time.dt.convert_time_zone(TIME_ZONE)
    part = pl.lit(None, pl.String)
    for name, (first, end) in PARTS.items():
        part = (
            pl.when(local.dt.hour().is_between(first, end - 1)).then(pl.lit(name)).otherwise(part)
        )
    return frame.with_columns(local.dt.date().alias("day"), part.alias("part"))


def probability(
    fc: pl.DataFrame,
    weights: pl.DataFrame,
    now: datetime,
    calibration: rain_calibration.Calibration | None = None,
    points: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Per okres, day and part (and ``part`` = "day" for whole days): the share of
    models whose own precipitation total is at least ``WET_MM``. Only models with
    precipitation weights for the okres that cover as many hours of the period as the
    longest one count, each the same: the weights come from the error of the amounts and
    favour a model (AIFS) that is the worst at rain or no rain (September 2026: Brier
    score 0.071 weighted against 0.070 with equal weights).

    With a ``calibration`` (``meteoverdict.rain_calibration``; neighbours from
    ``points``) the parts of day get the blended calibrated probability, the raw share
    kept as ``model_share``, and ``heavy_rain_probability`` and ``heavy_rain`` (a day:
    the highest of its parts, and whether any part is flagged)."""
    nbrs = None
    if calibration is not None:
        nbrs = rain_calibration.neighbours(points if points is not None else okres_points())
    lead = _lead_weights(weights).filter(pl.col("variable") == "precipitation")
    rows = _local(with_lead_and_fade(fc, now).drop_nulls("precipitation"), hour_ending=True)
    frames = []
    for period in ("part", "day"):
        keys = ["okres", "day"] if period == "day" else ["okres", "day", "part"]
        totals = (
            rows.group_by(*keys, "model")
            .agg(
                pl.col("precipitation").sum(),
                pl.len().alias("hours"),
                pl.col("lead_day").min(),
            )
            # a model ending inside the period would undercount its rain
            .filter(pl.col("hours") == pl.col("hours").max().over(keys))
            .join(lead, on=["okres", "lead_day", "model"])
            .select(
                *keys,
                pl.col("lead_day").alias("lead"),
                "model",
                pl.col("precipitation").alias("fc"),
            )
        )
        if period == "day":
            totals = rain_calibration.apply(totals, None, None).with_columns(
                pl.lit("day").alias("part")
            )
        else:
            totals = rain_calibration.apply(totals, calibration, nbrs)
        frames.append(totals)
    parts, days = frames
    heavy = parts.group_by("okres", "day").agg(
        pl.col("heavy_rain_probability").max(),
        pl.when(pl.col("heavy_rain").is_not_null().any()).then(pl.col("heavy_rain").any()),
    )
    days = days.drop("heavy_rain_probability", "heavy_rain").join(
        heavy, on=["okres", "day"], how="left"
    )
    columns = ["okres", "day", "part", "rain_probability", "model_share", "calibrated"]
    columns += ["heavy_rain_probability", "heavy_rain"]
    return pl.concat([parts.select(columns), days.select(columns)])


def symbol(
    cloud: float | None,
    precipitation: float | None,
    chance: float | None,
    temperature: float | None,
    share: float | None = None,
    showers_at: float = SHOWER_PROBABILITY,
) -> str | None:
    """Weather symbol: precipitation when likely, else sky by cloud cover. Rain (sleet,
    snow) by ``share``, the raw share of wet models, when given (else ``chance``);
    showers when ``chance`` is at least ``showers_at``."""
    if cloud is None and chance is None:
        return None
    wet_share = chance if share is None else share
    wet = (wet_share or 0) >= RAIN_PROBABILITY and (precipitation or 0) >= RAIN_MM
    if wet:
        if temperature is not None and temperature <= SNOW_AT_OR_BELOW:
            return "snow"
        if temperature is not None and temperature <= SLEET_AT_OR_BELOW:
            return "sleet"
        return "rain"
    if (chance or 0) >= showers_at:
        return "showers"
    if cloud is None:
        return None
    if cloud < CLEAR_BELOW:
        return "clear"
    return "partly" if cloud < PARTLY_BELOW else "cloudy"


#: the last day (D+5) is kept only for the parts of day in which every model with at least this
#: temperature weight at D+5 in the okres has a value (a bare "not zero" would let a 1 % model
#: hide a part); ``day`` needs all four. The AI's files follow the same rule (``mvai d5gate``).
LAST_DAY_MIN_WEIGHT = 0.04


def gate_last_day(
    table: pl.DataFrame,
    fc: pl.DataFrame,
    weights: pl.DataFrame,
    now: datetime,
    min_weight: float = LAST_DAY_MIN_WEIGHT,
) -> pl.DataFrame:
    """``table`` (``summarise``) without the rows of the last day (``now``'s local day +
    ``MAX_LEAD_DAY``) for the parts in which a relied-on model has no temperature, and without
    that day's ``day`` row of an okres with such a part."""
    last = now.astimezone(ZoneInfo(TIME_ZONE)).date() + timedelta(days=MAX_LEAD_DAY)
    relied = weights.filter(
        (pl.col("variable") == "temperature_2m")
        & (pl.col("lead_day") == MAX_LEAD_DAY)
        & (pl.col("weight") >= min_weight)
    ).select(pl.col("region").alias("okres"), "model")
    have = (
        _local(fc.filter(pl.col("temperature_2m").is_not_null()))
        .filter(pl.col("day") == last)
        .select("okres", "part", "model")
        .unique()
    )
    need = relied.join(pl.DataFrame({"part": list(PARTS)}), how="cross")
    missing = (
        need.join(have, on=["okres", "part", "model"], how="anti").select("okres", "part").unique()
    )
    drop = pl.concat(
        [missing, missing.select("okres").unique().with_columns(pl.lit("day").alias("part"))]
    ).with_columns(pl.lit(last).alias("day"))
    return table.join(drop, on=["okres", "day", "part"], how="anti")


def summarise(hourly: pl.DataFrame, chances: pl.DataFrame) -> pl.DataFrame:
    """Rows per okres, day and part of day, plus ``part`` = "day" for whole days (its
    symbol from the daytime hours 6-18). Periods with fewer than ``MIN_PART_HOURS`` or
    ``MIN_DAY_HOURS`` hours of combined temperature (the ends of the forecast) are left
    out."""
    rows = _local(hourly)
    # Open-Meteo: precipitation and seconds of sunshine in the hour ending at the time, so
    # they belong to the period of the hour before
    sums = _local(hourly, hour_ending=True)
    stats = [
        pl.col("temperature_2m").min().alias("tmin"),
        pl.col("temperature_2m").max().alias("tmax"),
        pl.col("temperature_2m").mean().alias("tmean"),
        pl.col("wind_speed_10m").max().alias("wind"),
        pl.col("temperature_2m").count().alias("hours"),
    ]
    sum_stats = [
        pl.col("precipitation").sum().alias("precipitation"),
        pl.col("precipitation").sort_by("time").last().is_not_null().alias("last_rain"),
        # null without any sunshine value
        pl.when(pl.col("sunshine_duration").count() > 0)
        .then(pl.col("sunshine_duration").sum() / 3600)
        .alias("sunshine"),
    ]
    part_keys = ["okres", "day", "part"]
    parts = (
        rows.group_by(part_keys)
        .agg(*stats, pl.col("cloud_cover").mean().alias("cloud"))
        .filter(pl.col("hours") >= MIN_PART_HOURS)
        .join(sums.group_by(part_keys).agg(sum_stats), on=part_keys, how="left")
    )
    daytime = pl.col("part").is_in(["morning", "afternoon"])
    days = (
        rows.group_by("okres", "day")
        .agg(
            *stats,
            pl.col("cloud_cover").filter(daytime).mean().alias("cloud"),
        )
        .filter(pl.col("hours") >= MIN_DAY_HOURS)
        .join(sums.group_by("okres", "day").agg(sum_stats), on=["okres", "day"], how="left")
        .with_columns(pl.lit("day").alias("part"))
    )
    table = pl.concat([parts, days], how="diagonal_relaxed")
    table = table.join(chances, on=["okres", "day", "part"], how="left")
    for name, dtype in (("model_share", pl.Float64), ("calibrated", pl.Boolean)):
        if name not in table.columns:
            table = table.with_columns(pl.lit(None, dtype).alias(name))
    showers = rain_calibration.SHOWER_PROBABILITY
    symbols = [
        symbol(c, p, r, t, s, showers if k else SHOWER_PROBABILITY)
        for c, p, r, t, s, k in table.select(
            "cloud", "precipitation", "rain_probability", "tmean", "model_share", "calibrated"
        ).iter_rows()
    ]
    order = {name: i for i, name in enumerate([*PARTS, "day"])}
    return (
        table.with_columns(pl.Series("symbol", symbols, pl.String))
        .drop("hours", "tmean", "model_share", "calibrated")
        .with_columns(pl.col("part").replace_strict(order, return_dtype=pl.Int8).alias("order"))
        .sort("okres", "day", "order")
        .drop("order")
    )


COLUMNS = (
    "okres",
    "day",
    "part",
    "tmin",
    "tmax",
    "precipitation",
    "rain_probability",
    "wind",
    "cloud",
    "sunshine",
    "symbol",
    "sunrise",
    "sunset",
    # optional, with a rain calibration only (null otherwise): P(>= 5 mm) and its flag
    "heavy_rain_probability",
    "heavy_rain",
)
#: after the frost fields: the corrected largest gust of the period (m/s, from the
#: single runs, ``meteoverdict.gusts``) and whether it reaches ``gusts.GUST_THRESHOLD``
#: (a MeteoVerdict threshold, not an official warning); null beyond the newest run's end
#: and without a run. ``gust_warning`` is the deprecated alias of ``gust_over_threshold``
#: (same value), kept for one API version
GUST_COLUMNS = ("gust", "gust_over_threshold", "gust_warning")


def with_sun(table: pl.DataFrame, points: pl.DataFrame) -> pl.DataFrame:
    """Add ``sunrise`` and ``sunset`` (Prague time, "HH:MM") at the okres point to every
    row of a day; null when the sun does not rise or set (not in Czechia)."""
    local = ZoneInfo(TIME_ZONE)
    where = {code: (lat, lon) for code, lat, lon in points.select("code", "lat", "lon").iter_rows()}
    rows = []
    for code, day in table.select("okres", "day").unique().iter_rows():
        rise, set_ = sun_times(*where[code], day) if code in where else (None, None)
        rows.append(
            (
                code,
                day,
                *(t.astimezone(local).strftime("%H:%M") if t else None for t in (rise, set_)),
            )
        )
    sun = pl.DataFrame(
        rows,
        schema={"okres": pl.String, "day": pl.Date, "sunrise": pl.String, "sunset": pl.String},
        orient="row",
    )
    return table.join(sun, on=["okres", "day"], how="left")


def write(table: pl.DataFrame, points: pl.DataFrame, path: Path, generated: datetime) -> Path:
    """``outlook.json``: ``{"generated", "time_zone", "parts", "days", "okresy",
    "columns", "rows"}``, numbers rounded to one decimal (probability to two)."""
    columns = [
        *COLUMNS,
        *(c for c in frost.OUTLOOK_COLUMNS if c in table.columns),
        *GUST_COLUMNS,
    ]
    rounded = (
        table.select(
            pl.col("okres"),
            pl.col("day").cast(pl.String),
            pl.col("part"),
            *[pl.col(c).round(1) for c in ("tmin", "tmax", "precipitation", "wind", "sunshine")],
            pl.col("rain_probability").round(2),
            pl.col("cloud").round(0).cast(pl.Int16, strict=False),
            pl.col("symbol"),
            pl.col("sunrise"),
            pl.col("sunset"),
            *[
                (pl.col(c) if c in table.columns else pl.lit(None, t)).alias(c)
                for c, t in (("heavy_rain_probability", pl.Float64), ("heavy_rain", pl.Boolean))
            ],
            *_frost_columns(table),
            (pl.col("gust") if "gust" in table.columns else pl.lit(None, pl.Float64))
            .round(1)
            .alias("gust"),
            *(
                (
                    pl.col("gust_over_threshold")
                    if "gust_over_threshold" in table.columns
                    else pl.lit(None, pl.Boolean)
                ).alias(c)
                for c in ("gust_over_threshold", "gust_warning")
            ),
        )
        .with_columns(pl.col("heavy_rain_probability").round(2))
        .select(columns)
    )
    doc = {
        "generated": generated.isoformat(timespec="minutes"),
        "time_zone": TIME_ZONE,
        "parts": list(PARTS),
        "days": sorted(rounded["day"].unique().to_list()),
        "okresy": points.select("code", "name", "lat", "lon").rows(named=True),
        "columns": columns,
        "rows": rounded.rows(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path


def _frost_columns(table: pl.DataFrame) -> list[pl.Expr]:
    """The frost fields (``meteoverdict.frost``; ``outlook`` always adds them, null without
    a frost calibration) that the table has, rounded like the others."""
    digits = {"night_min": 1, "coldest_min": 1, "ground_min": 1, "frost_probability": 2}
    return [
        pl.col(c).round(digits[c]) if c in digits else pl.col(c)
        for c in frost.OUTLOOK_COLUMNS
        if c in table.columns
    ]


HOURLY = ("temperature_2m", "precipitation", "wind_speed_10m", "cloud_cover", "sunshine_duration")
#: the 80 % range of the combined temperature (``meteoverdict.blend_interval``), written
#: only when it is there
RANGE = ("temperature_2m_lo", "temperature_2m_hi")


def write_hourly(hourly: pl.DataFrame, path: Path, generated: datetime) -> Path:
    """``outlook-hourly.json``: the combined hourly series of every okres, for the open
    data files (roadmap 6.11): ``{"generated", "time": [ISO UTC], "variables",
    "okresy": {code: {variable: [value or null, ...]}}}``, one decimal."""
    times = hourly["time"].unique().sort()
    grid = pl.DataFrame({"time": times})
    okresy = {}
    for (code,), part in sorted(hourly.partition_by("okres", as_dict=True).items()):
        full = grid.join(part, on="time", how="left").sort("time")
        okresy[code] = {v: full[v].round(1).to_list() for v in HOURLY}
        for v in RANGE:
            if v in full.columns and full[v].null_count() < full.height:
                okresy[code][v] = full[v].round(1).to_list()
    doc = {
        "generated": generated.isoformat(timespec="minutes"),
        "time": [t.strftime("%Y-%m-%dT%H:%MZ") for t in times.to_list()],
        "variables": {
            "temperature_2m": "°C",
            "precipitation": "mm in the hour ending at the time",
            "wind_speed_10m": "m/s, hourly mean",
            "cloud_cover": "%, mean of the models corrected against ČHMÚ observations",
            "sunshine_duration": (
                "s of sunshine in the hour ending at the time, mean of the models scaled "
                "so that each day adds up to the corrected daily sunshine"
            ),
            **(
                {
                    "temperature_2m_lo": "°C, lower end of the 80 % range of temperature_2m",
                    "temperature_2m_hi": "°C, upper end of the 80 % range of temperature_2m",
                }
                if any(RANGE[0] in o for o in okresy.values())
                else {}
            ),
        },
        "okresy": okresy,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path


# --- every model's own hourly forecast (the detailed forecast page, the model picker) ---
#: published under site/data (the web app: data/scores/forecast/models/<okres>.json)
MODELS_FOLDER = Path("forecast") / "models"
#: the folder zipped into the release data-latest (the Pages workflow unzips it)
MODELS_ZIP = "outlook-models.zip"
#: decimals per variable in the per-model files: Open-Meteo's own resolution (0.1 °C,
#: whole % and seconds; wind to 0.1 m/s, which Open-Meteo gives with 2 decimals only as
#: a conversion from km/h; precipitation to 0.01 mm so that no model's drizzle is lost)
MODEL_DIGITS = {
    "temperature_2m": 1,
    "precipitation": 2,
    "wind_speed_10m": 1,
    "cloud_cover": 0,
    "sunshine_duration": 0,
    "temperature_2m_lo": 1,
    "temperature_2m_hi": 1,
    # further variables (``EXTRA_VARIABLES``): the resolution of the bucket's files
    "relative_humidity_2m": 0,
    "dew_point_2m": 1,
    "pressure_msl": 1,
    "wind_direction_10m": 0,
    "wind_gusts_10m": 1,
    "shortwave_radiation": 0,
    "cloud_cover_low": 0,
    "snowfall": 2,
    "snow_depth": 2,
    "snow_depth_water_equivalent": 1,
    "surface_temperature": 1,
    "cape": 0,
    "visibility": 0,
}
MODEL_UNITS = {
    "temperature_2m": "°C",
    "precipitation": "mm in the hour ending at the time",
    "wind_speed_10m": "m/s, hourly mean",
    "cloud_cover": "%",
    "sunshine_duration": "s of sunshine in the hour ending at the time",
    "relative_humidity_2m": "%",
    "dew_point_2m": "°C",
    "pressure_msl": "hPa, reduced to mean sea level",
    "wind_direction_10m": "° the wind comes from (0 north, 90 east)",
    "wind_gusts_10m": "m/s, highest gust in the hour ending at the time",
    "shortwave_radiation": "W/m², mean of the hour ending at the time",
    "cloud_cover_low": "%",
    "snowfall": "cm of fresh snow in the hour ending at the time",
    "snow_depth": "m",
    "snow_depth_water_equivalent": "mm of water in the snow cover",
    "surface_temperature": "°C",
    "cape": "J/kg",
    "visibility": "m",
}


MODELS_LICENCE = "CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)"
MODELS_ATTRIBUTION = (
    "Model forecasts: Open-Meteo.com (CC BY 4.0) from the models of the weather services "
    "(DWD, ECMWF, NOAA, Météo-France, GeoSphere Austria, ČHMÚ, KNMI, DMI and others; UK "
    "Met Office CC BY-SA 4.0), as Open-Meteo gave them, rounded; combined series: "
    "MeteoVerdict (CC BY-SA 4.0), https://github.com/JerryWoof/MeteoVerdict"
)


def _values(series: pl.Series, digits: int, trim: bool = False) -> list:
    """Rounded values (whole numbers as ints), NaN as null; ``trim``: without the
    trailing nulls (a model that ends before the others)."""
    series = series.cast(pl.Float64).fill_nan(None).round(digits)
    if digits == 0:
        series = series.cast(pl.Int64)
    values = series.to_list()
    if trim:
        while values and values[-1] is None:
            values.pop()
    return values


def models_doc(fc: pl.DataFrame, hourly: pl.DataFrame, code: str, generated: datetime) -> dict:
    """One okres: ``{"generated", "okres", "time": [ISO UTC], "variables", "combined":
    {variable: [...]}, "models": {model: {variable: [...]}}, "licence",
    "attribution"}``. ``models``: each model's raw hourly forecast as Open-Meteo gave it
    (no correction; a series ends at the model's last hour, a variable the model lacks is
    left out; ``EXTRA_VARIABLES`` besides the five of ``VARIABLES``, null where a model's
    hour has no value, never 0); ``combined``: our combined series of
    ``outlook-hourly.json``, on the same hours."""
    own = fc.filter(pl.col("okres") == code)
    ours = hourly.filter(pl.col("okres") == code)
    times = pl.concat([own["time"], ours["time"]]).unique().sort()
    grid = pl.DataFrame({"time": times})
    combined_rows = grid.join(ours, on="time", how="left").sort("time")
    combined = {
        v: _values(combined_rows[v], MODEL_DIGITS[v])
        for v in (*HOURLY, *RANGE, *COMBINED_EXTRA)
        if v in combined_rows.columns
        and (v in HOURLY or combined_rows[v].null_count() < combined_rows.height)
    }
    reference = {
        v: _values(combined_rows[f"{v}_reference"], MODEL_DIGITS[v])
        for v in REFERENCE
        if f"{v}_reference" in combined_rows.columns
        and combined_rows[f"{v}_reference"].null_count() < combined_rows.height
    }
    models = {}
    for (model,), part in sorted(own.partition_by("model", as_dict=True).items()):
        rows = grid.join(part, on="time", how="left").sort("time")
        series = {}
        for v in (*VARIABLES, *EXTRA_VARIABLES):
            if v not in rows.columns:
                continue
            values = _values(rows[v], MODEL_DIGITS[v], trim=True)
            if v in EXTRA_VARIABLES and all(x is None for x in values):
                continue  # the model lacks it: left out, never 0
            if values:
                series[v] = values
        if series:
            models[model] = series
    return {
        "generated": generated.isoformat(timespec="minutes"),
        "okres": code,
        "time": [t.strftime("%Y-%m-%dT%H:%MZ") for t in times.to_list()],
        "variables": MODEL_UNITS,
        "combined": combined,
        # plain means of the models, no weights behind them (``REFERENCE``)
        **({"reference": reference} if reference else {}),
        "models": models,
        "licence": MODELS_LICENCE,
        "attribution": MODELS_ATTRIBUTION,
    }


def write_models(
    fc: pl.DataFrame, hourly: pl.DataFrame, folder: Path, generated: datetime
) -> list[Path]:
    """``folder/<okres>.json`` (``models_doc``) for every okres of ``fc``; files of okresy
    no longer in it are removed, so the folder holds one run only."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    codes = sorted(fc["okres"].unique().to_list())
    for code in codes:
        path = folder / f"{code}.json"
        doc = models_doc(fc, hourly, code, generated)
        path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
        written.append(path)
    for old in folder.glob("*.json"):
        if old.stem not in codes:
            old.unlink()
    return written


# --- every model's own parts of day for all okresy (the model switch of the map) -------
#: published under site/data (the web app: data/scores/forecast/models-parts/<model>.json
#: and index.json)
MODEL_PARTS_FOLDER = Path("forecast") / "models-parts"
#: the folder zipped into the release data-latest (the Pages workflow unzips it)
MODEL_PARTS_ZIP = "outlook-models-parts.zip"
MODEL_PARTS_INDEX = "index.json"
#: the parts of one day in the files: the four parts, then the whole day
PERIODS = (*PARTS, "day")
MODEL_PART_COLUMNS = ("tmin", "tmax", "precipitation", "wind", "cloud", "sunshine", "symbol")
MODEL_PART_DIGITS = {"tmin": 1, "tmax": 1, "precipitation": 2, "wind": 1, "cloud": 0, "sunshine": 1}
MODEL_PARTS_NOTES = (
    "One model's raw forecast (Open-Meteo, no correction) summarised by the outlook's "
    "rules: Prague time, night 0-6, morning 6-12, afternoon 12-18, evening 18-24, day "
    "0-24; precipitation and sunshine belong to the hour before their time; tmin/tmax, "
    "precipitation total (mm), highest hourly wind (m/s), mean cloud cover (%, a whole "
    "day: of 6-18), hours of sunshine. A period the model does not cover in full (beyond "
    "its horizon) is null; a part whose every hour the model has, with only the "
    "precipitation of its last hour missing (the model's last hour), counts with the "
    "precipitation it has, a whole day not. Symbol: rain (sleet, snow at a mean of "
    "<= 2 / <= 0.5 °C) when "
    "the model's own total is at least 0.3 mm, else the sky from its cloud cover (clear < "
    "30 %, partly cloudy < 65 %, else cloudy); never showers. No probability of "
    "precipitation from one model (rain_probability null). Values per okres: one list per "
    "column, days x parts (index = day * 5 + part); symbol as its position in symbols."
)


def model_symbol(
    cloud: float | None, precipitation: float | None, temperature: float | None
) -> str | None:
    """One model's symbol (as web/src/models.js modelSymbol): rain, sleet or snow from
    its own total of at least ``RAIN_MM``, else the sky from its cloud cover; never
    showers, which come from a probability one model does not have."""
    if (precipitation or 0) >= RAIN_MM:
        if temperature is not None and temperature <= SNOW_AT_OR_BELOW:
            return "snow"
        if temperature is not None and temperature <= SLEET_AT_OR_BELOW:
            return "sleet"
        return "rain"
    if cloud is None:
        return None
    if cloud < CLEAR_BELOW:
        return "clear"
    return "partly" if cloud < PARTLY_BELOW else "cloudy"


def model_periods(fc: pl.DataFrame) -> pl.DataFrame:
    """Every model's own parts of day and whole days per okres (``parse``'s rows): one
    row per okres, model, day and part (``part`` = "day" for whole days) with
    ``MODEL_PART_COLUMNS``, by the outlook's rules (``summarise``) on the model's raw
    values. Only periods the model covers in full: every hour of the period that the
    forecast has (at least ``MIN_PART_HOURS`` / ``MIN_DAY_HOURS``) with a temperature and,
    for a model with precipitation, every hour of its sums; so nothing beyond the model's
    horizon or where it ends inside a period (its rain would be undercounted). One
    exception (as web/src/models.js modelPeriods): a part of the day whose every hour the
    model has, with only the precipitation of its very last hour missing (ICON-D2 ending
    at 23:00 has no rain for 23-24), counts, its precipitation the hours it has; a whole
    day stays null then, so a day's total is never short."""
    keys = ["okres", "model", "day", "part"]
    grid = fc.select("okres", "time").unique()
    full = grid.join(fc.select("model").unique(), how="cross").join(
        fc, on=["okres", "time", "model"], how="left"
    )
    rainy = fc.group_by("okres", "model").agg(
        pl.col("precipitation").is_not_null().any().alias("rainy")
    )
    inst = _local(full)
    sums = _local(full, hour_ending=True)
    stats = [
        pl.len().alias("hours"),
        pl.col("temperature_2m").count().alias("t_hours"),
        pl.col("temperature_2m").min().alias("tmin"),
        pl.col("temperature_2m").max().alias("tmax"),
        pl.col("temperature_2m").mean().alias("tmean"),
        pl.col("wind_speed_10m").max().alias("wind"),
    ]
    sum_stats = [
        pl.len().alias("sum_hours"),
        pl.col("precipitation").count().alias("p_hours"),
        pl.col("precipitation").sum().alias("precipitation"),
        pl.col("precipitation").sort_by("time").last().is_not_null().alias("last_rain"),
        pl.when(pl.col("sunshine_duration").count() > 0)
        .then(pl.col("sunshine_duration").sum() / 3600)
        .alias("sunshine"),
    ]
    daytime = pl.col("part").is_in(["morning", "afternoon"])
    parts = inst.group_by(keys).agg(*stats, pl.col("cloud_cover").mean().alias("cloud"))
    parts = parts.join(sums.group_by(keys).agg(sum_stats), on=keys, how="left")
    day_keys = ["okres", "model", "day"]
    days = (
        inst.group_by(day_keys)
        .agg(*stats, pl.col("cloud_cover").filter(daytime).mean().alias("cloud"))
        .join(sums.group_by(day_keys).agg(sum_stats), on=day_keys, how="left")
        .with_columns(pl.lit("day").alias("part"))
    )
    table = (
        pl.concat([parts, days], how="diagonal_relaxed")
        .join(rainy, on=["okres", "model"], how="left")
        .with_columns(pl.col("sum_hours", "p_hours").fill_null(0))
    )
    least = pl.when(pl.col("part") == "day").then(MIN_DAY_HOURS).otherwise(MIN_PART_HOURS)
    # a part only its last hour of rain short (the model's last hour) still counts
    last_hour_short = (
        (pl.col("part") != "day")
        & (pl.col("p_hours") == pl.col("sum_hours") - 1)
        & ~pl.col("last_rain").fill_null(False)
    )
    table = table.filter(
        (pl.col("t_hours") >= least)
        & (pl.col("t_hours") == pl.col("hours"))
        & (~pl.col("rainy") | (pl.col("p_hours") == pl.col("sum_hours")) | last_hour_short)
    ).with_columns(pl.when(pl.col("rainy")).then(pl.col("precipitation")).alias("precipitation"))
    symbols = [
        model_symbol(c, p, t)
        for c, p, t in table.select("cloud", "precipitation", "tmean").iter_rows()
    ]
    return table.with_columns(pl.Series("symbol", symbols, pl.String)).select(
        *keys, *MODEL_PART_COLUMNS
    )


#: symbols in the files as their position in this list (small files)
MODEL_SYMBOLS = ("clear", "partly", "cloudy", "rain", "sleet", "snow")


def _part_value(value, column: str):
    """Rounded (whole numbers as ints, to keep the files small), NaN as null; the
    symbol as its position in ``MODEL_SYMBOLS``."""
    if value is None:
        return None
    if column == "symbol":
        return MODEL_SYMBOLS.index(value)
    if isinstance(value, float) and value != value:  # NaN
        return None
    value = round(value, MODEL_PART_DIGITS[column])
    return int(value) if value == int(value) else value


def mean_ranks(weights: pl.DataFrame) -> dict[str, float]:
    """Each model's mean rank over all okresy, variables and lead days of the forecast
    weights (1 = best): the order of the map's model switch."""
    if "rank" not in weights.columns or weights.is_empty():
        return {}
    ranks = weights.drop_nulls("rank").group_by("model").agg(pl.col("rank").mean())
    return {m: round(r, 2) for m, r in ranks.iter_rows()}


def model_parts_doc(
    periods: pl.DataFrame,
    fc: pl.DataFrame,
    model: str,
    codes: list[str],
    days: list[date],
    generated: datetime,
) -> dict:
    """One model for all okresy: ``{"generated", "model", "last_hour", "time_zone",
    "days", "parts", "columns", "symbols", "rain_probability": null, "okresy": {code:
    {column: [value per day and part]}}, "notes", "licence", "attribution"}``. The index
    of a value is ``day * len(parts) + part``; ``symbol`` is a position in ``symbols``;
    null where the model has no full period (beyond ``last_hour``, its last hour with a
    temperature at any okres)."""
    own = periods.filter(pl.col("model") == model)
    at = {
        (o, d, p): row
        for o, d, p, *row in own.select("okres", "day", "part", *MODEL_PART_COLUMNS).iter_rows()
    }
    hours = fc.filter(pl.col("model") == model).drop_nulls("temperature_2m")["time"]
    last = hours.max() if hours.len() else None
    okresy = {}
    for code in codes:
        columns: dict[str, list] = {c: [] for c in MODEL_PART_COLUMNS}
        for day in days:
            for part in PERIODS:
                row = at.get((code, day, part))
                for i, column in enumerate(MODEL_PART_COLUMNS):
                    columns[column].append(_part_value(row[i], column) if row else None)
        okresy[code] = columns
    return {
        "generated": generated.isoformat(timespec="minutes"),
        "model": model,
        "last_hour": last.strftime("%Y-%m-%dT%H:%MZ") if last is not None else None,
        "time_zone": TIME_ZONE,
        "days": [d.isoformat() for d in days],
        "parts": list(PERIODS),
        "columns": list(MODEL_PART_COLUMNS),
        "symbols": list(MODEL_SYMBOLS),
        "rain_probability": None,
        "okresy": okresy,
        "notes": MODEL_PARTS_NOTES,
        "licence": MODELS_LICENCE,
        "attribution": MODELS_ATTRIBUTION,
    }


def write_model_parts(
    fc: pl.DataFrame,
    weights: pl.DataFrame,
    days: list[date],
    folder: Path,
    generated: datetime,
) -> list[Path]:
    """``folder/<model>.json`` (``model_parts_doc``) for every model of ``fc``, all okresy
    in each, and ``folder/index.json``: ``{"generated", "days", "models": [{"model",
    "mean_rank", "last_hour"}]}``, the models by their mean rank over Czechia
    (``mean_ranks``; unranked ones last, by name). Files of models no longer in ``fc`` are
    removed, so the folder holds one run only."""
    folder.mkdir(parents=True, exist_ok=True)
    periods = model_periods(fc)
    codes = sorted(fc["okres"].unique().to_list())
    ranks = mean_ranks(weights)
    models = sorted(
        fc["model"].unique().to_list(),
        key=lambda m: (ranks.get(m) is None, ranks.get(m) or 0.0, m),
    )
    written, entries = [], []
    for model in models:
        doc = model_parts_doc(periods, fc, model, codes, days, generated)
        path = folder / f"{model}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
        written.append(path)
        entries.append(
            {"model": model, "mean_rank": ranks.get(model), "last_hour": doc["last_hour"]}
        )
    for old in folder.glob("*.json"):
        if old.name != MODEL_PARTS_INDEX and old.stem not in models:
            old.unlink()
    index = {
        "generated": generated.isoformat(timespec="minutes"),
        "days": [d.isoformat() for d in days],
        "order": "mean rank over all okresy, variables and lead days of the forecast weights",
        "models": entries,
    }
    path = folder / MODEL_PARTS_INDEX
    path.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return [*written, path]


# --- our own archive of every model's hourly forecast at the okres points --------------
MODEL_ARCHIVE_SCHEMA = {
    "issued": pl.Datetime("us", "UTC"),
    "okres": pl.String,
    "model": pl.String,
    "time": pl.Datetime("us", "UTC"),
    **{v: pl.Float32 for v in VARIABLES},
}


MODEL_ARCHIVE_NOTES = (
    "Every model's hourly forecast at the 77 okres points as the outlook (mvd outlook) "
    "had it: from Open-Meteo's open-data bucket since 2026-10-20 (read and interpolated "
    "to hours as the Forecast API does; a model missing there from the API), before "
    "from the Open-Meteo Forecast API: one file per UTC day of the run "
    "(outlook-models-YYYY-MM-DD.parquet: issued, okres, model, time, temperature_2m, "
    "precipitation, wind_speed_10m, cloud_cover, sunshine_duration; issued = the run's "
    "time, UTC; up to four runs a day), one release per month. Forecasts: "
    "Open-Meteo.com, CC BY 4.0, from the weather services listed in docs/licensing.md "
    "(UK Met Office CC BY-SA 4.0). Published under CC BY-SA 4.0."
)


def model_archive_asset(issued: datetime) -> tuple[str, str]:
    """Release and asset of the model archive for a run: one file per UTC day (a few
    MB, so a run moves little), one release per month (at most 31 assets)."""
    day = issued.astimezone(UTC)
    return f"outlook-models-{day:%Y-%m}", f"outlook-models-{day:%Y-%m-%d}.parquet"


def model_archive_rows(fc: pl.DataFrame, issued: datetime) -> pl.DataFrame:
    """One outlook run's answer (``parse``) as archive rows."""
    return (
        fc.select(
            pl.lit(issued.astimezone(UTC).replace(second=0, microsecond=0))
            .dt.cast_time_unit("us")
            .alias("issued"),
            "okres",
            "model",
            "time",
            *VARIABLES,
        )
        .with_columns(pl.col(v).fill_nan(None) for v in VARIABLES)
        .cast(MODEL_ARCHIVE_SCHEMA)
    )


def append_model_archive(path: Path, rows: pl.DataFrame) -> Path:
    """Merge one or more runs into the day's file: a run (``issued``) already in it is
    replaced, so a repeated run never duplicates rows."""
    rows = rows.cast(MODEL_ARCHIVE_SCHEMA)
    if path.exists():
        old = pl.read_parquet(path).cast(MODEL_ARCHIVE_SCHEMA)
        rows = pl.concat(
            [old.filter(~pl.col("issued").is_in(rows["issued"].unique().implode())), rows]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    # the runs of one hour side by side: they differ little, so the file stays small
    rows.unique(["issued", "okres", "model", "time"], keep="last").sort(
        "okres", "model", "time", "issued"
    ).write_parquet(path, compression="zstd", compression_level=10)
    return path


# --- our own archive of what the forecast map showed (forecast vs. measured) -----------
#: the release of the plain-means archive (``sun_cloud_gust.ARCHIVE_TAG``)
PARTS_ARCHIVE_TAG = sun_cloud_gust.ARCHIVE_TAG
#: what each run's parts of day said, as the forecast map showed them
PARTS_ARCHIVE_COLUMNS = (
    "tmin",
    "tmax",
    "precipitation",
    "rain_probability",
    "wind",
    "gust",
    "cloud",
    "sunshine",
    "symbol",
)
PARTS_ARCHIVE_SCHEMA = {
    "issued": pl.Datetime("us", "UTC"),
    "okres": pl.String,
    "day": pl.Date,
    "part": pl.String,
    **{c: pl.Float32 for c in PARTS_ARCHIVE_COLUMNS if c != "symbol"},
    "symbol": pl.String,
}


def parts_archive_asset(issued: datetime) -> tuple[str, str]:
    """Release and asset of the parts archive: one file per UTC month of the run."""
    return PARTS_ARCHIVE_TAG, f"outlook-parts-{issued.astimezone(UTC):%Y-%m}.parquet"


def parts_archive_rows(table: pl.DataFrame, issued: datetime) -> pl.DataFrame:
    """One run's parts-of-day table (``outlook``'s, as written to outlook.json) as
    archive rows; columns it lacks are null."""
    stamp = issued.astimezone(UTC).replace(second=0, microsecond=0)
    return table.select(
        pl.lit(stamp).dt.cast_time_unit("us").alias("issued"),
        "okres",
        "day",
        "part",
        *[
            (pl.col(c) if c in table.columns else pl.lit(None)).alias(c)
            for c in PARTS_ARCHIVE_COLUMNS
        ],
    ).cast(PARTS_ARCHIVE_SCHEMA)


def append_parts_archive(path: Path, rows: pl.DataFrame) -> Path:
    """Merge runs into the month file; a run (``issued``) already in it is replaced."""
    rows = rows.cast(PARTS_ARCHIVE_SCHEMA)
    if path.exists():
        old = pl.read_parquet(path).cast(PARTS_ARCHIVE_SCHEMA)
        rows = pl.concat(
            [old.filter(~pl.col("issued").is_in(rows["issued"].unique().implode())), rows]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.sort("issued", "okres", "day", "part").write_parquet(
        path, compression="zstd", compression_level=10
    )
    return path


def outlook(
    client: httpx.Client,
    weights: pl.DataFrame,
    points: pl.DataFrame,
    now: datetime | None = None,
    sleep: Callable[[float], None] = lambda _: None,
    calibration: rain_calibration.Calibration | None = None,
    corrections: dict | None = None,
    frost_calibration: frost.Calibration | None = None,
    nights: list[pl.DataFrame] | None = None,
    single_runs: pl.LazyFrame | pl.DataFrame | None = None,
    forecasts: list[pl.DataFrame] | None = None,
    interval: dict | None = None,
    store: bucket.Bucket | None = None,
    sources: dict[str, list[str]] | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Fetch, combine and summarise for all ``points`` (code, name, lat, lon) that have
    weights: the parts-of-day table and the combined hourly series (with the plain
    means of cloud and sunshine as ``cloud_cover_raw`` and ``sunshine_duration_raw``);
    with a rain ``calibration``, calibrated probabilities of precipitation;
    ``corrections``: the coefficients of ``sun_cloud_gust`` (default: the bootstrap).
    The frost fields (``meteoverdict.frost``) come from ``frost_calibration``; the
    models' nights at the okres points are appended to ``nights`` for the archive. The
    gusts come from the newest of ``single_runs`` (``runs``; none: null). Every model's
    own hourly forecast (``parse``, as Open-Meteo gave it) is appended to ``forecasts``
    (the per-model files and the archive; no extra calls). ``interval`` (``blend_interval``
    file): adds ``temperature_2m_lo`` and ``temperature_2m_hi`` to the hourly series.
    With ``store`` the models come from the bucket and only those it lacks from the API
    (``gather``; ``sources``: which came from where)."""
    now = now or datetime.now(UTC)
    points = points.filter(pl.col("code").is_in(weights["region"].unique().to_list()))
    models = sorted(weights["model"].unique().to_list())
    fc, payload = gather(client, store, points, models, now, sleep, sources, log)
    if forecasts is not None:
        forecasts.append(fc)
    hourly = combine_hourly(fc, weights, now)
    hourly = sun_cloud_gust.correct_hourly(
        hourly, points, corrections or sun_cloud_gust.load(), now
    )
    hourly = blend_interval.add_interval(hourly, interval, now)
    table = summarise(hourly, probability(fc, weights, now, calibration, points))
    table = gate_last_day(table, fc, weights, now)
    night_rows = frost.point_nights(fc, payload, points["code"].to_list(), now)
    if nights is not None:
        nights.append(night_rows)
    table = frost.add_to_outlook(table, night_rows, frost_calibration)
    table = add_gusts(table, single_runs, points, corrections or sun_cloud_gust.load(), now)
    return with_sun(table, points), hourly


def gather(
    client: httpx.Client,
    store: bucket.Bucket | None,
    points: pl.DataFrame,
    models: list[str],
    now: datetime,
    sleep: Callable[[float], None],
    sources: dict[str, list[str]] | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> tuple[pl.DataFrame, list | dict]:
    """Every model's hourly forecast at ``points`` (``parse``'s rows) and an answer
    with each point's ``elevation`` (for ``frost.point_nights``): from the bucket
    (``outlook_bucket.from_bucket``) where it has a complete run, the rest from the API
    in one ``fetch``; without ``store`` all from the API."""
    sources = sources if sources is not None else {}
    if store is None:
        payload = fetch(client, points, models, sleep)
        sources["api"] = list(models)
        return parse(payload, points["code"].to_list(), models), payload
    known = {m.id: m for m in catalogue.enabled_models()}
    fc, reads = outlook_bucket.from_bucket(
        store, [known[m] for m in models if m in known], points, now, days=DAYS, log=log
    )
    read = {r.model for r in reads if r.fc is not None}
    sources["bucket"] = sorted(read)
    lacking = [m for m in models if m not in read]
    sources["api"] = [
        m for i, m in enumerate(lacking) if cost(points.height, i + 1) <= MAX_FALLBACK_CALLS
    ]
    sources["left_out"] = lacking[len(sources["api"]) :]
    if sources["left_out"]:
        log(
            f"outlook: over the fallback's {MAX_FALLBACK_CALLS} calls, left out: "
            + ", ".join(sources["left_out"])
        )
    if sources["api"]:
        payload = fetch(client, points, sources["api"], sleep)
        api = parse(payload, points["code"].to_list(), sources["api"])
        fc = pl.concat([fc, api.select(fc.columns).cast(fc.schema)])
    heights = dict(outlook_bucket.point_table(points).select("id", "elevation").rows())
    answer = [{"location_id": i, "elevation": heights.get(c)} for i, c in enumerate(points["code"])]
    return fc.sort("okres", "model", "time"), answer


def add_gusts(
    table: pl.DataFrame,
    single_runs: pl.LazyFrame | pl.DataFrame | None,
    points: pl.DataFrame,
    corrections: dict,
    now: datetime,
) -> pl.DataFrame:
    """Add ``GUST_COLUMNS`` to every row the newest single run covers (null elsewhere;
    everywhere when the runs cannot be read: the gusts must not fail the outlook)."""
    mapping = gusts.okres_stations(runs_mod.load_stations(), points, point_elevations())
    try:
        values = gusts.okres_gusts(single_runs, mapping, corrections, now)
    except (pl.exceptions.PolarsError, OSError, KeyError, ValueError) as exc:
        print(f"outlook: no gusts, the single runs could not be read: {exc}", file=sys.stderr)
        values = gusts.okres_gusts(None, mapping, corrections, now)
    joined = table.join(values, on=["okres", "day", "part"], how="left", maintain_order="left")
    if "wind" not in joined.columns:
        return joined
    # the gusts come from the okres's stations, the wind from its point: a gust below
    # the mean wind would read as nonsense, so it is at least the wind
    return joined.with_columns(
        pl.when(pl.col("gust").is_not_null() & pl.col("wind").is_not_null())
        .then(pl.max_horizontal("gust", "wind"))
        .otherwise(pl.col("gust"))
        .alias("gust")
    ).with_columns(
        pl.when(pl.col("gust").is_not_null())
        .then(pl.col("gust") >= gusts.GUST_THRESHOLD)
        .otherwise(pl.col("gust_over_threshold"))
        .alias("gust_over_threshold")
    )
