"""Night minimum, air frost and ground frost for every okres (docs/methodology.md#frost).

The models forecast night minima that are too warm, most of all on clear, calm nights,
and almost never forecast frost (docs/data-sources.md, the farmers' event skill). The
**night** is 18-06 UTC, labelled by the date it ends (ČHMÚ ``TMInoc``, the night minimum
at 2 m, and ``TPM``, the ground minimum at 5 cm above the ground, both reported at 06 UTC).

Correction, out of sample in September and October 2026 (research of 16 October 2026):

1. **per model and lead day**: ``fmin - b[model, lead]``, the model's mean night-minimum
   error over the last ``WINDOW_NIGHTS`` nights at all stations; then the plain mean of
   the models;
2. **per station**: ``- b_station``, the station's mean error left after 1. over the same
   nights, shrunk ``n / (n + SHRINK_NIGHTS)`` and applied in full (half was worse);
   optionally split by forecast night wind below / from ``CALM_WIND``;
3. **clear and calm nights**: ``- (a + b * cloud + c * min(wind, WIND_CAP))`` with the
   night means of the forecast cloud fraction (0-1) and wind (m/s). Defaults from the
   research sample (``CLEAR_CALM``); refitted on ``CLEAR_CALM_DAYS`` days of archived
   outlook nights (``outlook-nights-YYYY-MM.parquet``) once there are
   ``CLEAR_CALM_MIN_NIGHTS`` nights.

The station corrections come from the archived D+N forecasts at the stations
(``fc-YYYY-MM``) and ČHMÚ's daily ``TMInoc`` (``mvd frost-fit``, ``frost.json``). The
outlook applies them to the forecast at the okres point: the okres minimum takes the
mean station correction of the okres, the **coldest site** each station's own (moved
from the point's to the station's elevation with ``LAPSE``, as Open-Meteo does).

From the corrected minimum: frost probability ``P = Φ(-min / sigma)`` (sigma: the error
left in training), an **air-frost** threshold flag at ``AIR_FROST_AT`` °C or below, and the
**ground minimum** ``min + GROUND[0] + GROUND[1] * cloud + GROUND[2] * wind`` with a
ground-frost threshold flag at 0 °C or below.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from meteoverdict import partitions

#: a night is 18-05 UTC (hourly values at 18, 19, …, 05), labelled by the date it ends
NIGHT_FIRST_HOUR = 18
NIGHT_LAST_HOUR = 5
#: a forecast night needs this many hourly temperatures
MIN_NIGHT_HOURS = 10
#: leads fitted; longer leads use the bias of the longest
MAX_LEAD = 3
#: training window and shrinkage of the station bias (nights)
WINDOW_NIGHTS = 60
SHRINK_NIGHTS = 10
#: forecast night-mean wind (m/s) below which a night counts as calm (station bias split)
CALM_WIND = 2.0
#: clear-calm term: a + b * cloud_fraction + c * min(wind, WIND_CAP), subtracted
WIND_CAP = 5.0
CLEAR_CALM = {
    "intercept": 1.33,
    "cloud": -1.12,
    "wind": -0.36,
    "source": (
        "research 2026-10-16: Open-Meteo Previous Runs sample (ECMWF IFS, ICON-EU, "
        "ICON-D2, ALADIN 1 km; D+1/D+2) at 16 ČHMÚ stations, nights 1-13 April and "
        "1-14 October 2026, fitted on the error left after the per-model correction; "
        "bootstrap 95 % ranges 1.02-1.68, -1.98 to -0.45, -0.53 to -0.18"
    ),
    "nights": None,
}
#: refit of the clear-calm term on archived outlook nights
CLEAR_CALM_DAYS = 45
CLEAR_CALM_MIN_NIGHTS = 30
#: ground minimum (5 cm) = air minimum + GROUND[0] + GROUND[1] * cloud + GROUND[2] * wind
#: (April and October 2026 fits averaged; ČHMÚ TPM against TMInoc)
GROUND = (-5.0, 1.5, 0.35)
#: spread of the corrected minimum when it cannot be fitted (°C)
SIGMA = 1.6
#: threshold flags: air frost when the corrected minimum is at most this (best CSI), ground
#: frost when the ground minimum is at most this
AIR_FROST_AT = 1.0
GROUND_FROST_AT = 0.0
#: °C per metre, Open-Meteo's elevation correction (standard atmosphere)
LAPSE = 0.0065
#: stations more than this many metres above the okres point are left out of the okres
#: correction and the coldest site
MAX_SITE_ABOVE_POINT = 300.0

#: the new optional fields of outlook.json on the "night" and "day" rows of the date the
#: night ends
OUTLOOK_SCHEMA = {
    "night_min": pl.Float64,
    "coldest_site": pl.String,
    "coldest_min": pl.Float64,
    "frost_probability": pl.Float64,
    "frost": pl.Boolean,
    "ground_min": pl.Float64,
    "ground_frost": pl.Boolean,
}
OUTLOOK_COLUMNS = tuple(OUTLOOK_SCHEMA)
#: archived outlook nights (one row per run, okres, model and night)
ARCHIVE_COLUMNS = (
    "run",
    "okres",
    "model",
    "night",
    "lead_day",
    "fmin",
    "wind",
    "cloud",
    "hours",
    "elevation",
)


#: local folder of the archive (``<data>/outlook-nights/YYYY-MM.parquet``)
ARCHIVE_FOLDER = "outlook-nights"


def archive_name(month: str) -> str:
    """The asset of the release ``data-YYYY-MM`` with the outlook nights of runs in it."""
    return f"outlook-nights-{month}.parquet"


def write_archive(nights: pl.DataFrame, folder: Path) -> list[Path]:
    """Merge ``point_nights`` rows into ``folder/YYYY-MM.parquet`` by the month of the run
    (a repeated run replaces its rows)."""
    return partitions.write_monthly(
        nights.select(ARCHIVE_COLUMNS), folder, ["run", "okres", "model", "night"], "run"
    )


# --- nights ------------------------------------------------------------------------------
def night_minima(frame: pl.DataFrame | pl.LazyFrame, keys: list[str]) -> pl.DataFrame:
    """Per ``keys`` and night: ``fmin`` (lowest ``temperature_2m``), the night means
    ``wind`` (``wind_speed_10m``) and ``cloud`` (``cloud_cover`` / 100) where the
    columns exist, and ``hours``; nights with fewer than ``MIN_NIGHT_HOURS`` are left out."""
    frame = frame.lazy()
    names = frame.collect_schema().names()
    hour = pl.col("time").dt.hour()
    stats = [
        pl.col("temperature_2m").min().alias("fmin"),
        pl.col("temperature_2m").count().alias("hours"),
    ]
    if "wind_speed_10m" in names:
        stats.append(pl.col("wind_speed_10m").mean().alias("wind"))
    if "cloud_cover" in names:
        stats.append((pl.col("cloud_cover").mean() / 100).alias("cloud"))
    return (
        frame.filter((hour >= NIGHT_FIRST_HOUR) | (hour <= NIGHT_LAST_HOUR))
        .with_columns(
            (pl.col("time") + pl.duration(hours=24 - NIGHT_FIRST_HOUR)).dt.date().alias("night")
        )
        .group_by(*keys, "night")
        .agg(stats)
        .filter(pl.col("hours") >= MIN_NIGHT_HOURS)
        .collect()
    )


def observed_nights(daily: pl.DataFrame | pl.LazyFrame) -> pl.DataFrame:
    """ČHMÚ daily data (the ``chmi-daily-YYYY-MM`` archive) → ``station_id``, ``night``,
    ``tmin`` (TMInoc, 2 m) and ``ground`` (TPM, 5 cm), both 18-06 UTC."""
    rows = (
        daily.lazy()
        .filter(pl.col("element").is_in(["TMInoc", "TPM"]), pl.col("vtype") == "06:00")
        .drop_nulls("value")
        .group_by(pl.col("station").alias("station_id"), pl.col("time").dt.date().alias("night"))
        .agg(
            pl.col("value")
            .filter(pl.col("element") == "TMInoc")
            .first()
            .cast(pl.Float64)
            .alias("tmin"),
            pl.col("value")
            .filter(pl.col("element") == "TPM")
            .first()
            .cast(pl.Float64)
            .alias("ground"),
        )
    )
    return rows.drop_nulls("tmin").collect()


# --- fitting -----------------------------------------------------------------------------
class Calibration:
    """What ``fit`` learnt: ``model_bias`` (model, lead_day, bias, n), ``stations``
    (station_id, name, okres, elevation, bias, bias_calm, bias_windy, nights), ``sigma``,
    the clear-calm coefficients and the training nights."""

    def __init__(
        self,
        model_bias: pl.DataFrame,
        stations: pl.DataFrame,
        sigma: float = SIGMA,
        clear_calm: dict | None = None,
        first: date | None = None,
        last: date | None = None,
        split_wind: bool = False,
    ) -> None:
        self.model_bias = model_bias
        self.stations = stations
        self.sigma = sigma
        self.clear_calm = dict(clear_calm or CLEAR_CALM)
        self.first, self.last = first, last
        self.split_wind = split_wind

    def to_json(self, generated: datetime | None = None) -> dict:
        def table(frame: pl.DataFrame) -> dict:
            rounded = frame.select(
                pl.col(c).round(3) if frame.schema[c].is_float() else pl.col(c)
                for c in frame.columns
            )
            return {"columns": frame.columns, "rows": rounded.rows()}

        return {
            "generated": (generated or datetime.now(UTC)).isoformat(timespec="minutes"),
            "from": self.first.isoformat() if self.first else None,
            "to": self.last.isoformat() if self.last else None,
            "window_nights": WINDOW_NIGHTS,
            "shrink_nights": SHRINK_NIGHTS,
            "split_wind": self.split_wind,
            "calm_wind": CALM_WIND,
            "sigma": round(self.sigma, 3),
            "clear_calm": self.clear_calm,
            "ground": list(GROUND),
            "air_frost_at": AIR_FROST_AT,
            "model_bias": table(self.model_bias),
            "stations": table(self.stations),
        }

    @classmethod
    def from_json(cls, doc: dict) -> Calibration:
        def frame(part: dict) -> pl.DataFrame:
            return pl.DataFrame(part["rows"], schema=part["columns"], orient="row")

        model_bias = frame(doc["model_bias"]).with_columns(pl.col("lead_day").cast(pl.Int8))
        return cls(
            model_bias,
            frame(doc["stations"]),
            doc.get("sigma", SIGMA),
            doc.get("clear_calm"),
            date.fromisoformat(doc["from"]) if doc.get("from") else None,
            date.fromisoformat(doc["to"]) if doc.get("to") else None,
            doc.get("split_wind", False),
        )

    def write(self, path: Path, generated: datetime | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(generated), ensure_ascii=False), "utf-8")
        return path

    @classmethod
    def read(cls, path: Path) -> Calibration:
        return cls.from_json(json.loads(path.read_text("utf-8")))


def _shrunk(mean: pl.Expr, n: pl.Expr) -> pl.Expr:
    return mean * n / (n + SHRINK_NIGHTS)


def fit(
    pairs: pl.DataFrame,
    stations: pl.DataFrame | None = None,
    split_wind: bool = False,
    window_nights: int = WINDOW_NIGHTS,
) -> Calibration:
    """Corrections from ``pairs``: one row per station, model, lead day and night with
    the forecast ``fmin``, ``wind`` and the observed ``tmin`` (``forecast_pairs``).
    Only the last ``window_nights`` nights and leads up to ``MAX_LEAD`` count.
    ``stations`` (id, name, okres_code, elevation) names the stations."""
    pairs = pairs.filter(pl.col("lead_day") <= MAX_LEAD).drop_nulls(["fmin", "tmin"])
    last = pairs["night"].max()
    first = last - timedelta(days=window_nights - 1)
    pairs = pairs.filter(pl.col("night") >= first).with_columns(
        (pl.col("fmin") - pl.col("tmin")).alias("e")
    )
    first = pairs["night"].min()
    model_bias = (
        pairs.group_by("model", "lead_day")
        .agg(pl.col("e").mean().alias("bias"), pl.len().alias("n"))
        .sort("model", "lead_day")
    )
    pairs = pairs.join(model_bias.drop("n"), on=["model", "lead_day"]).with_columns(
        (pl.col("e") - pl.col("bias")).alias("r")
    )
    # one residual per station and night (all models and leads), then over nights
    per_night = pairs.group_by("station_id", "night").agg(
        pl.col("r").mean(), (pl.col("wind").mean() < CALM_WIND).alias("calm")
    )
    biases = per_night.group_by("station_id").agg(
        _shrunk(pl.col("r").mean(), pl.len()).alias("bias"),
        _shrunk(pl.col("r").filter(pl.col("calm")).mean(), pl.col("calm").sum()).alias("bias_calm"),
        _shrunk(pl.col("r").filter(~pl.col("calm")).mean(), (~pl.col("calm")).sum()).alias(
            "bias_windy"
        ),
        pl.len().alias("nights"),
    )
    biases = biases.with_columns(
        pl.col("bias_calm").fill_null(pl.col("bias")),
        pl.col("bias_windy").fill_null(pl.col("bias")),
    )
    if stations is not None:
        info = stations.select(
            pl.col("id").alias("station_id"),
            "name",
            pl.col("okres_code").alias("okres"),
            pl.col("elevation").cast(pl.Float64),
        )
        biases = info.join(biases, on="station_id", how="inner")
    else:
        biases = biases.with_columns(
            pl.lit(None, pl.String).alias("name"),
            pl.lit(None, pl.String).alias("okres"),
            pl.lit(None, pl.Float64).alias("elevation"),
        )
    biases = biases.select(
        "station_id", "name", "okres", "elevation", "bias", "bias_calm", "bias_windy", "nights"
    ).sort("station_id")
    cal = Calibration(model_bias, biases, first=first, last=last, split_wind=split_wind)
    # spread: the error of the corrected mean of the models per station and night
    corrected = station_ensemble(pairs.drop("bias", "r", "e"), cal, clear_calm=False)
    joined = corrected.join(
        pairs.group_by("station_id", "night").agg(pl.col("tmin").first()),
        on=["station_id", "night"],
    )
    if joined.height > 1:
        cal.sigma = float((joined["min"] - joined["tmin"]).std())
    return cal


def forecast_pairs(fc: pl.DataFrame | pl.LazyFrame, obs: pl.DataFrame) -> pl.DataFrame:
    """D+N forecasts at the stations (``fc-YYYY-MM``: station_id, time, model, lead_day,
    temperature_2m, wind_speed_10m) → night minima with the observed ``tmin``/``ground``."""
    nights = night_minima(fc, ["station_id", "model", "lead_day"])
    return nights.join(obs, on=["station_id", "night"], how="inner")


# --- applying ----------------------------------------------------------------------------
def clear_calm(cloud: pl.Expr, wind: pl.Expr, coefficients: dict) -> pl.Expr:
    """The clear-calm term (°C, subtracted from the minimum); 0 without cloud or wind."""
    term = (
        coefficients["intercept"]
        + coefficients["cloud"] * cloud
        + coefficients["wind"] * pl.min_horizontal(wind, pl.lit(WIND_CAP))
    )
    return term.fill_null(0.0)


def _model_corrected(nights: pl.DataFrame, cal: Calibration) -> pl.DataFrame:
    """``fmin - b[model, lead]`` (leads beyond the fitted ones use the longest); models
    without a fitted bias are left out."""
    longest = cal.model_bias.group_by("model").agg(pl.col("lead_day").max().alias("_longest"))
    return (
        nights.join(longest, on="model", how="inner")
        .with_columns(pl.min_horizontal("lead_day", "_longest").cast(pl.Int8).alias("_lead"))
        .join(
            cal.model_bias.select("model", pl.col("lead_day").alias("_lead"), "bias"),
            on=["model", "_lead"],
        )
        .with_columns((pl.col("fmin") - pl.col("bias")).alias("corrected"))
        .drop("_longest", "_lead", "bias")
    )


def _station_bias(cal: Calibration, calm: pl.Expr) -> pl.Expr:
    if cal.split_wind:
        return pl.when(calm).then(pl.col("bias_calm")).otherwise(pl.col("bias_windy"))
    return pl.col("bias")


def station_ensemble(
    nights: pl.DataFrame, cal: Calibration, clear_calm: bool = True
) -> pl.DataFrame:
    """Forecasts at the stations (station_id, model, lead_day, night, fmin, wind[,
    cloud]) → per station, night and lead day the corrected minimum ``min`` (mean of the
    models), ``model_only`` (without the station and clear-calm terms) and ``raw``."""
    corrected = _model_corrected(nights, cal)
    has_cloud = "cloud" in corrected.columns
    ens = corrected.group_by("station_id", "night", "lead_day").agg(
        pl.col("fmin").mean().alias("raw"),
        pl.col("corrected").mean().alias("model_only"),
        pl.col("wind").mean(),
        *([pl.col("cloud").mean()] if has_cloud else []),
    )
    ens = ens.join(
        cal.stations.select("station_id", "bias", "bias_calm", "bias_windy"),
        on="station_id",
        how="left",
    ).with_columns(_station_bias(cal, pl.col("wind") < CALM_WIND).fill_null(0.0).alias("_bias"))
    term = clear_calm_expr(cal) if clear_calm and has_cloud else pl.lit(0.0)
    return ens.with_columns((pl.col("model_only") - pl.col("_bias") - term).alias("min")).drop(
        "bias", "bias_calm", "bias_windy", "_bias"
    )


def clear_calm_expr(cal: Calibration) -> pl.Expr:
    return clear_calm(pl.col("cloud"), pl.col("wind"), cal.clear_calm)


def probability(minimum: float | None, sigma: float) -> float | None:
    """P(minimum <= 0 °C) for a Gaussian error ``sigma`` around ``minimum``."""
    if minimum is None or sigma <= 0:
        return None
    return 0.5 * (1 + math.erf((0 - minimum) / (sigma * math.sqrt(2))))


def ground_offset(cloud: pl.Expr, wind: pl.Expr) -> pl.Expr:
    """5 cm ground minimum minus 2 m air minimum (°C), from forecast cloud and wind."""
    return GROUND[0] + GROUND[1] * cloud.fill_null(0.5) + GROUND[2] * wind.fill_null(2.0)


# --- the outlook -------------------------------------------------------------------------
def point_nights(
    fc: pl.DataFrame, payload: list | dict, codes: list[str], now: datetime
) -> pl.DataFrame:
    """The outlook's models at the okres points (``outlook.parse``) → one row per okres,
    model and night ending 1+ days after ``now`` (UTC date): ``ARCHIVE_COLUMNS``. The
    point's ``elevation`` is the one Open-Meteo answered with."""
    results = payload if isinstance(payload, list) else [payload]
    heights = {codes[r.get("location_id", i)]: r.get("elevation") for i, r in enumerate(results)}
    nights = night_minima(fc, ["okres", "model"])
    today = now.astimezone(UTC).date()
    return (
        nights.with_columns(
            pl.lit(now.astimezone(UTC)).dt.cast_time_unit("us").alias("run"),
            (pl.col("night") - pl.lit(today)).dt.total_days().cast(pl.Int8).alias("lead_day"),
            pl.col("okres")
            .replace_strict(heights, default=None, return_dtype=pl.Float64)
            .alias("elevation"),
        )
        .filter(pl.col("lead_day") >= 1)
        .with_columns(pl.col("hours").cast(pl.Int16))
        .select(ARCHIVE_COLUMNS)
        .sort("okres", "night", "model")
    )


def okres_nights(nights: pl.DataFrame, cal: Calibration) -> pl.DataFrame:
    """Per okres and night (``point_nights``): the corrected okres minimum, the coldest
    site, frost probability and the ground minimum with their threshold flags."""
    corrected = _model_corrected(nights, cal)
    okres = corrected.group_by("okres", "night").agg(
        pl.col("corrected").mean().alias("model_only"),
        pl.col("wind").mean(),
        pl.col("cloud").mean(),
        pl.col("elevation").first(),
    )
    okres = okres.with_columns(clear_calm_expr(cal).alias("_term"))
    calm = pl.col("wind") < CALM_WIND
    sites = (
        okres.join(cal.stations.drop("nights"), on="okres", how="inner")
        # summits (Milešovka above Litoměřice) are cold by height and warm in
        # inversions: they say nothing about frost in the okres's fields
        .filter(
            (pl.col("elevation_right") - pl.col("elevation")).fill_null(0.0) <= MAX_SITE_ABOVE_POINT
        )
        .with_columns(_station_bias(cal, calm).alias("_bias"))
        .with_columns(
            (
                pl.col("model_only")
                + LAPSE * (pl.col("elevation") - pl.col("elevation_right")).fill_null(0.0)
                - pl.col("_bias")
                - pl.col("_term")
            ).alias("site_min")
        )
    )
    per_okres = sites.group_by("okres", "night").agg(
        pl.col("_bias").mean().alias("_okres_bias"),
        pl.col("name").sort_by("site_min").first().alias("coldest_site"),
        pl.col("site_min").min().alias("coldest_min"),
    )
    out = okres.join(per_okres, on=["okres", "night"], how="left").with_columns(
        (pl.col("model_only") - pl.col("_okres_bias").fill_null(0.0) - pl.col("_term")).alias(
            "night_min"
        )
    )
    out = out.with_columns(
        (pl.col("night_min") + ground_offset(pl.col("cloud"), pl.col("wind"))).alias("ground_min")
    )
    probabilities = [probability(m, cal.sigma) for m in out["night_min"].to_list()]
    return out.with_columns(
        pl.Series("frost_probability", probabilities, pl.Float64),
        (pl.col("night_min") <= AIR_FROST_AT).alias("frost"),
        (pl.col("ground_min") <= GROUND_FROST_AT).alias("ground_frost"),
    ).select("okres", "night", *OUTLOOK_COLUMNS)


def add_to_outlook(
    table: pl.DataFrame, nights: pl.DataFrame, cal: Calibration | None
) -> pl.DataFrame:
    """Add ``OUTLOOK_COLUMNS`` to the "night" and "day" rows of the outlook table (by
    the date the night ends); null elsewhere and without a calibration."""
    schema = OUTLOOK_SCHEMA
    if cal is None or nights.is_empty():
        values = pl.DataFrame(schema={"okres": pl.String, "day": pl.Date, **schema})
    else:
        values = okres_nights(nights, cal).rename({"night": "day"}).cast(schema)
    joined = table.join(values, on=["okres", "day"], how="left", maintain_order="left")
    keep = pl.col("part").is_in(["night", "day"])
    return joined.with_columns(
        pl.when(keep).then(pl.col(c)).otherwise(None).alias(c) for c in OUTLOOK_COLUMNS
    )


# --- refitting the clear-calm term from the archived outlook nights ------------------------
def refit_clear_calm(
    archive: pl.DataFrame, obs: pl.DataFrame, cal: Calibration, last: date | None = None
) -> dict:
    """The clear-calm coefficients fitted on the archived outlook nights of the last
    ``CLEAR_CALM_DAYS`` days: the error left at the okres stations after the model and
    station corrections, against ``[1, cloud, min(wind, WIND_CAP)]``. The defaults
    (``cal.clear_calm``) stay with fewer than ``CLEAR_CALM_MIN_NIGHTS`` nights."""
    last = last or obs["night"].max()
    first = last - timedelta(days=CLEAR_CALM_DAYS - 1)
    nights = archive.filter(
        pl.col("night").is_between(first, last), pl.col("lead_day") <= MAX_LEAD
    ).drop_nulls(["fmin", "cloud", "wind"])
    if nights.is_empty():
        return cal.clear_calm
    okres = (
        _model_corrected(nights, cal)
        .group_by("run", "okres", "night")
        .agg(
            pl.col("corrected").mean().alias("model_only"),
            pl.col("wind").mean(),
            pl.col("cloud").mean(),
            pl.col("elevation").first(),
        )
    )
    calm = pl.col("wind") < CALM_WIND
    rows = (
        okres.join(cal.stations, on="okres", how="inner")
        .join(obs.select("station_id", "night", "tmin"), on=["station_id", "night"])
        .with_columns(
            (
                pl.col("model_only")
                + LAPSE * (pl.col("elevation") - pl.col("elevation_right")).fill_null(0.0)
                - _station_bias(cal, calm)
                - pl.col("tmin")
            ).alias("r")
        )
    )
    if rows["night"].n_unique() < CLEAR_CALM_MIN_NIGHTS:
        return cal.clear_calm
    x = np.column_stack(
        [
            np.ones(rows.height),
            rows["cloud"].to_numpy(),
            np.minimum(rows["wind"].to_numpy(), WIND_CAP),
        ]
    )
    a, b, c = np.linalg.lstsq(x, rows["r"].to_numpy(), rcond=None)[0]
    return {
        "intercept": round(float(a), 3),
        "cloud": round(float(b), 3),
        "wind": round(float(c), 3),
        "source": f"refit on archived outlook nights {first} to {last}",
        "nights": int(rows["night"].n_unique()),
    }
