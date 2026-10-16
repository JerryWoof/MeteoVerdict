"""TV-style forecast for every okres (roadmap 6.6).

Twice a day, ask the Open-Meteo Forecast API for the next ``DAYS`` days of all models at
the forecast point of every okres (one request, 77 locations), combine them with the
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

Cost: 77 locations x 5 variables x models / 10 weighted calls a run, and only the
models with weights are asked: 11 models about 420, 19 models about 730. A request
stays at or below ``MAX_REQUEST`` calls (Open-Meteo allows 600 a minute), so with more
than 12 models the okresy are split into equal parts, a minute apart.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import polars as pl

from meteoverdict import rain_calibration, sun_cloud_gust
from meteoverdict.combine import combine_values, okres_points
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
#: plain means of the models, not combined with weights; corrected afterwards
#: (``sun_cloud_gust.correct_hourly``)
MEANS = ("cloud_cover", "sunshine_duration")
COMBINED = ("temperature_2m", "precipitation", "wind_speed_10m")
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
#: refused above this (all 19 models with weights: ~732 a run, ~1,465 a day)
MAX_CALLS = 800
#: one request at most (Open-Meteo: 600 a minute); parts are ``PART_PAUSE`` s apart
MAX_REQUEST = 500
PART_PAUSE = 61


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
            if all(c is None for c in columns.values()):
                continue
            frames.append(
                pl.DataFrame(
                    {
                        "okres": codes[result.get("location_id", position)],
                        "time": times,
                        "model": model,
                        **{v: columns[v] for v in VARIABLES},
                    },
                    schema={
                        "okres": pl.String,
                        "time": pl.Datetime("us", "UTC"),
                        "model": pl.String,
                        **{v: pl.Float64 for v in VARIABLES},
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


def combine_hourly(fc: pl.DataFrame, weights: pl.DataFrame, now: datetime) -> pl.DataFrame:
    """One row per okres and hour: the combined temperature, precipitation and wind,
    the plain means of cloud cover and sunshine, and the number of models."""
    fc = with_lead_and_fade(fc, now)
    lead = _lead_weights(weights)
    # some models publish sunshine slightly outside the hour (seen: 3605.6 and -1.0 s)
    fc = fc.with_columns(pl.col("sunshine_duration").clip(0.0, 3600.0))
    out = fc.group_by("okres", "time").agg(
        *[pl.col(v).mean() for v in MEANS], pl.col("model").n_unique().alias("models")
    )
    for variable in COMBINED:
        w = lead.filter(pl.col("variable") == variable).select(
            "okres", "lead_day", "model", "weight", "correction"
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
        )
        .with_columns(pl.col("heavy_rain_probability").round(2))
        .select(COLUMNS)
    )
    doc = {
        "generated": generated.isoformat(timespec="minutes"),
        "time_zone": TIME_ZONE,
        "parts": list(PARTS),
        "days": sorted(rounded["day"].unique().to_list()),
        "okresy": points.select("code", "name", "lat", "lon").rows(named=True),
        "columns": list(COLUMNS),
        "rows": rounded.rows(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path


HOURLY = ("temperature_2m", "precipitation", "wind_speed_10m", "cloud_cover", "sunshine_duration")


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
        },
        "okresy": okresy,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path


def outlook(
    client: httpx.Client,
    weights: pl.DataFrame,
    points: pl.DataFrame,
    now: datetime | None = None,
    sleep: Callable[[float], None] = lambda _: None,
    calibration: rain_calibration.Calibration | None = None,
    corrections: dict | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Fetch, combine and summarise for all ``points`` (code, name, lat, lon) that have
    weights: the parts-of-day table and the combined hourly series (with the plain
    means of cloud and sunshine as ``cloud_cover_raw`` and ``sunshine_duration_raw``);
    with a rain ``calibration``, calibrated probabilities of precipitation;
    ``corrections``: the coefficients of ``sun_cloud_gust`` (default: the bootstrap)."""
    now = now or datetime.now(UTC)
    points = points.filter(pl.col("code").is_in(weights["region"].unique().to_list()))
    models = sorted(weights["model"].unique().to_list())
    payload = fetch(client, points, models, sleep)
    fc = parse(payload, points["code"].to_list(), models)
    hourly = combine_hourly(fc, weights, now)
    hourly = sun_cloud_gust.correct_hourly(
        hourly, points, corrections or sun_cloud_gust.load(), now
    )
    table = summarise(hourly, probability(fc, weights, now, calibration, points))
    return with_sun(table, points), hourly
