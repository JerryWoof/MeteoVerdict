"""Weights for combining the models into one forecast per okres (roadmap 6.2).

For every okres, variable and lead day, each model gets a weight from how well it did
there over the last 90 days (the okres scores of ``mvd aggregate``, on the same fair
station-days for all models, with borrowed stations where an okres has few). Only the
models compared there get a weight: a model with scores on fewer than
``aggregate.MIN_COVERAGE`` of the window's days (``short_record``, e.g. one added
recently) gets none until it has them, and does not shorten the others' training:

- **temperature and wind**: the forecast is first corrected by the model's mean error
  (bias) there, so the weight is the inverse of the error variance left after that
  correction, ``1 / (RMSE² - bias²)``;
- **precipitation** (daily totals): no correction (subtracting a mean would give
  negative rain), weight ``1 / RMSE²``.

With few days these numbers are noisy, so both are shrunk towards the plain mean of all
models (weight ``1 / models``, no correction), the correction much less than the weight:
with ``days`` scored days, the weight is ``s * w + (1 - s) / models`` with
``s = days / (days + SHRINK_DAYS)`` and the correction ``c * bias`` with
``c = days / (days + BIAS_SHRINK_DAYS)``. After 30 days half of the weight comes from
the scores, after 90 days three quarters; the correction is 6/7 of the bias after 30
days. A model's mean error is stable enough to be removed almost in full (out of sample
in September 2026, shrinking it like the weights left about half of it in and cost
7-10 % of wind MAE).

The combined forecast is ``sum_m weight_m * (forecast_m - correction_m)`` over the
models available for that hour, with the weights of the missing ones left out and the
rest rescaled (``combine_values``), with at least ``MIN_MODELS`` models; precipitation
and wind are not allowed below 0. Whether this beats the best single model is tested
out of sample by ``meteoverdict.blendtest`` (roadmap 6.4).

**Temperature and wind: regression blend.** Where the station-level pairs of the last
90 days are at hand (``mvd daily``), temperature and wind get a second set of weights
and hour-of-day and elevation corrections from ``meteoverdict.mos``: ``mos_weight``
(constrained ridge regression, sums to 1 over the ``mos_models`` models, may be
negative) and ``correction_00`` … ``correction_18`` (the correction at the okres's
forecast point at 00/06/12/18 UTC, interpolated linearly in between). An hour uses the
regression weights when every one of those models has a value (and is not fading out);
otherwise the inverse-error ``weight`` above with the slot corrections, rescaled over
the models present. Without the pairs (too little history, ``mvd aggregate`` alone) the
rows have no ``mos_weight`` and everything works as described above. ``correction``
then holds the mean of the four slot corrections, so a reader that knows only
``weight`` and ``correction`` still gets a sensible forecast.

Output (``write_forecast``): ``forecast/okresy.json`` with a forecast point per okres
and ``forecast/<okres>.json`` with its weights, both ``{"columns", "rows"}`` like the
score files (``FORECAST_COLUMNS``: ``WEIGHT_COLUMNS`` plus the columns above).
"""

from __future__ import annotations

import json
from importlib.resources import files
from itertools import pairwise
from pathlib import Path

import polars as pl

from meteoverdict import blend, mos
from meteoverdict.regions import Region, load_regions

WINDOW = "90d"
#: shrinkage of the weights towards the plain mean, in scored days (half-way after this)
SHRINK_DAYS = 30
#: shrinkage of the bias correction towards none, in scored days
BIAS_SHRINK_DAYS = 5
#: smallest error variance used, so a model that was perfect on a few days does not get
#: all the weight (units of the variable squared)
MIN_ERROR_VARIANCE = 0.01
#: Open-Meteo hourly variable → (score variable the weights come from, bias-corrected)
VARIABLES = {
    "temperature_2m": ("temperature_2m", True),
    "wind_speed_10m": ("wind_speed_10m", True),
    "precipitation": ("precipitation_daily", False),
}
WEIGHT_COLUMNS = ("variable", "lead_day", "model", "weight", "correction", "mae", "rank", "days")
#: corrections at 00, 06, 12 and 18 UTC (``mos.SLOTS``)
SLOT_CORRECTIONS = tuple(f"correction_{s}" for s in mos.SLOT_NAMES)
#: the published weight files: WEIGHT_COLUMNS plus the regression blend (null without)
FORECAST_COLUMNS = (*WEIGHT_COLUMNS, "mos_weight", "mos_models", *SLOT_CORRECTIONS)
#: elevation of the forecast point of every okres (scripts/build_okres_elevations.py)
ELEVATIONS_FILE = "okres-elevations.csv"
#: the elevation term at the okres's forecast point at half strength: checked against
#: the station nearest each point (held out 24-30 Sep 2026) the full term beat none by
#: 4.4 % wind / 1.5 % temperature MAE, half by 3.3 % / 0.9 %, but the full term made 15
#: okresy more than 5 % worse for wind (half: 4); against the okres's station mean, none
#: is best (docs/methodology.md)
POINT_LAPSE_FACTOR = 0.5
#: the weight table of the forecast (``forecast_weights``) for ``mvd outlook``, in the
#: data folder and in the release data-latest
FORECAST_WEIGHTS_FILE = "forecast-weights.parquet"
#: a combined value needs at least this many models with a value at that hour
MIN_MODELS = 2
#: combined variables that cannot be negative (clipped at 0 after the bias correction)
NON_NEGATIVE = ("precipitation", "wind_speed_10m")


def weights(table: pl.DataFrame, window: str = WINDOW) -> pl.DataFrame:
    """One row per okres, variable (Open-Meteo name), lead day and model.

    ``table`` holds aggregated scores (``meteoverdict.aggregate``); ``rank`` (from
    ``meteoverdict.ranking``) is passed through where present, null otherwise.
    """
    if "rank" not in table.columns:
        table = table.with_columns(pl.lit(None, pl.Int16).alias("rank"))
    if "short_record" not in table.columns:  # tables from before the coverage rule
        table = table.with_columns(pl.lit(False).alias("short_record"))
    by_score = {score: (name, corrected) for name, (score, corrected) in VARIABLES.items()}
    rows = table.filter(
        pl.col("level") == "okres",
        pl.col("window") == window,
        pl.col("variable").is_in(list(by_score)),
        pl.col("model") != blend.ID,
        pl.col("enough_stations"),
        ~pl.col("short_record").fill_null(False),
        pl.col("n") > 0,
        pl.col("rmse").is_not_null(),
    )
    corrected = pl.col("variable").replace_strict(
        {s: c for s, (_, c) in by_score.items()}, return_dtype=pl.Boolean
    )
    group = ["region", "variable", "lead_day"]
    variance = (
        pl.when(corrected)
        .then(pl.col("rmse") ** 2 - pl.col("bias") ** 2)
        .otherwise(pl.col("rmse") ** 2)
    )
    shrink = pl.col("days") / (pl.col("days") + SHRINK_DAYS)
    shrink_bias = pl.col("days") / (pl.col("days") + BIAS_SHRINK_DAYS)
    return (
        rows.with_columns(
            (1 / pl.max_horizontal(variance, pl.lit(MIN_ERROR_VARIANCE))).alias("inverse"),
            shrink.alias("shrink"),
        )
        .with_columns(
            (
                pl.col("shrink") * pl.col("inverse") / pl.col("inverse").sum().over(group)
                + (1 - pl.col("shrink")) / pl.len().over(group)
            ).alias("weight"),
            pl.when(corrected)
            .then(shrink_bias * pl.col("bias"))
            .otherwise(0.0)
            .alias("correction"),
            pl.col("variable").replace_strict({s: n for s, (n, _) in by_score.items()}),
        )
        .select("region", "region_name", *WEIGHT_COLUMNS)
        .sort("region", "variable", "lead_day", "weight", descending=[False, False, False, True])
    )


def with_mos(
    weights: pl.DataFrame, coefficients: pl.DataFrame | None, keys: tuple[str, ...] = ("region",)
) -> pl.DataFrame:
    """``weights`` (rows of ``weights``) with the regression coefficients of
    ``mos.Fit.frame`` (``mos.COEFFICIENT_COLUMNS``, joined on ``keys``, variable, lead
    day and model). A group gets them only when every model of its regression has an
    inverse-error weight there (needed for the fallback); otherwise they stay null."""
    columns = list(mos.COEFFICIENT_COLUMNS)
    if coefficients is None or coefficients.is_empty():
        return weights.with_columns(
            pl.lit(None, pl.Int16 if c in ("mos_models", "mos_days") else pl.Float64).alias(c)
            for c in columns
        )
    group = [*keys, "variable", "lead_day"]
    on = [*group, "model"]
    joined = weights.join(coefficients.select(*on, *columns), on=on, how="left")
    expected = coefficients.group_by(group).agg(pl.col("mos_models").first().alias("_expected"))
    found = joined.filter(pl.col("mos_weight").is_not_null()).group_by(group).len("_found")
    complete = (
        expected.join(found, on=group)
        .filter(pl.col("_found") == pl.col("_expected"))
        .select(*group, pl.lit(True).alias("_complete"))
    )
    return (
        joined.join(complete, on=group, how="left")
        .with_columns(pl.when(pl.col("_complete")).then(pl.col(c)).alias(c) for c in columns)
        .drop("_complete")
    )


def slot_corrections(elevation: pl.Expr, lapse_factor: float = 1.0) -> list[pl.Expr]:
    """``correction_00`` … ``correction_18`` at a place of the okres at ``elevation``
    (m; null: the mean elevation of the okres's stations) from the coefficient columns
    of ``with_mos``; ``correction`` where there are none (precipitation, no regression).
    ``lapse_factor`` scales the elevation term (``POINT_LAPSE_FACTOR`` at the point)."""
    dz = lapse_factor * (
        ((elevation - pl.col("station_elevation")) / mos.ELEVATION_STEP_M)
        .fill_null(0.0)
        .clip(pl.col("dz_min"), pl.col("dz_max"))
    )
    return [
        pl.when(pl.col(bias).is_not_null())
        .then(pl.col(bias) + pl.col(lapse) * dz)
        .otherwise(pl.col("correction"))
        .alias(name)
        for bias, lapse, name in zip(
            mos.BIAS_COLUMNS, mos.LAPSE_COLUMNS, SLOT_CORRECTIONS, strict=True
        )
    ]


def hourly_correction() -> pl.Expr:
    """The correction at the UTC hour of ``time``: the slot corrections interpolated
    linearly (00 → 06 → 12 → 18 → 00), or ``correction`` without them."""
    position = (pl.col("time").dt.hour() + pl.col("time").dt.minute() / 60) / 6
    index = position.floor().cast(pl.Int32) % 4
    fraction = position - position.floor()

    def at(i: pl.Expr) -> pl.Expr:
        out = pl.lit(None, pl.Float64)
        for k, name in enumerate(SLOT_CORRECTIONS):
            out = pl.when(i == k).then(pl.col(name)).otherwise(out)
        return out

    value = at(index) * (1 - fraction) + at((index + 1) % 4) * fraction
    return pl.coalesce(value, pl.col("correction"))


#: columns ``combine_values`` reads from a weight table (the last ones optional)
BLEND_COLUMNS = ("weight", "correction", "mos_weight", "mos_models", *SLOT_CORRECTIONS)


def combine_values(
    frame: pl.LazyFrame | pl.DataFrame, variable: str, by: list[str], weight: str = "weight"
) -> pl.LazyFrame | pl.DataFrame:
    """The combined forecast of ``variable``, one row per group ``by``.

    ``frame`` has one row per group and model with the model's forecast in
    ``variable``, its ``weight`` (column named by ``weight``) and its ``correction``.
    ``sum(weight * (forecast - correction)) / sum(weight)`` over the models with a value,
    so the weights of missing models are left out and the rest rescaled; null with fewer
    than ``MIN_MODELS`` models; not below 0 for ``NON_NEGATIVE`` variables.

    With ``SLOT_CORRECTIONS`` and ``time`` the correction is the one of the hour
    (``hourly_correction``). With ``mos_weight`` and ``mos_models``: where every model
    of the regression has a value (and, with a ``fade`` column, is not fading out),
    ``sum(mos_weight * (forecast - correction))`` over them instead.
    """
    names = frame.collect_schema().names()
    w = pl.col(weight)
    hourly = set(SLOT_CORRECTIONS) <= set(names) and "time" in names
    correction = hourly_correction() if hourly else pl.col("correction")
    value = pl.col(variable) - pl.col("_correction")
    aggregations = [((w * value).sum() / w.sum()).alias(variable), pl.len().alias("_models")]
    regression = "mos_weight" in names and "mos_models" in names
    if regression:
        present = pl.col("mos_weight").is_not_null()
        if "fade" in names:
            present = present & (pl.col("fade") >= 1)
        aggregations += [
            (pl.col("mos_weight") * value).filter(present).sum().alias("_regression"),
            present.sum().alias("_present"),
            pl.col("mos_models").max().alias("_expected"),
        ]
    combined = (
        frame.drop_nulls(variable)
        .with_columns(correction.alias("_correction"))
        .group_by(by)
        .agg(aggregations)
    )
    if regression:
        complete = (pl.col("_expected") > 0) & (pl.col("_present") == pl.col("_expected"))
        combined = combined.with_columns(
            pl.when(complete)
            .then(pl.col("_regression"))
            .otherwise(pl.col(variable))
            .alias(variable)
        ).drop("_regression", "_present", "_expected")
    combined = combined.with_columns(
        pl.when(pl.col("_models") >= MIN_MODELS).then(pl.col(variable)).alias(variable)
    ).drop("_models")
    if variable in NON_NEGATIVE:
        combined = combined.with_columns(pl.col(variable).clip(lower_bound=0))
    return combined


def representative_point(region: Region) -> tuple[float, float]:
    """A point inside the okres: the centroid of its largest polygon, or, where that
    falls outside (a crescent-shaped okres), the inside grid point nearest to it."""
    ring = max((p[0] for p in region.polygons), key=lambda r: abs(_area(r)))
    area = _area(ring)
    lon = sum((x1 + x2) * (x1 * y2 - x2 * y1) for (x1, y1), (x2, y2) in pairwise(ring))
    lat = sum((y1 + y2) * (x1 * y2 - x2 * y1) for (x1, y1), (x2, y2) in pairwise(ring))
    lon, lat = lon / (6 * area), lat / (6 * area)
    if region.contains(lon, lat):
        return lon, lat
    lon_min, lat_min, lon_max, lat_max = region.bbox
    steps = 60
    inside = [
        (lon_min + (lon_max - lon_min) * i / steps, lat_min + (lat_max - lat_min) * j / steps)
        for i in range(steps + 1)
        for j in range(steps + 1)
    ]
    inside = [(x, y) for x, y in inside if region.contains(x, y)]
    return min(inside, key=lambda p: (p[0] - lon) ** 2 + (p[1] - lat) ** 2)


def _area(ring: list[tuple[float, float]]) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in pairwise(ring)) / 2


def _write(path: Path, frame: pl.DataFrame) -> Path:
    rows = frame.select(
        pl.col(c).round(4) if frame.schema[c].is_float() else pl.col(c) for c in frame.columns
    ).rows()
    doc = {"columns": frame.columns, "rows": rows}
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path


def okres_points() -> pl.DataFrame:
    """``code``, ``name``, ``lat``, ``lon`` of the forecast point of every okres."""
    points = []
    for region in load_regions("okres"):
        lon, lat = representative_point(region)
        points.append((region.code, region.name, round(lat, 4), round(lon, 4)))
    return pl.DataFrame(points, schema=["code", "name", "lat", "lon"], orient="row")


def point_elevations() -> pl.DataFrame:
    """``code`` and ``elevation`` (m) of the forecast point of every okres."""
    source = files("meteoverdict").joinpath("data", ELEVATIONS_FILE)
    with source.open("rb") as f:
        return pl.read_csv(f.read()).select("code", pl.col("elevation").cast(pl.Float64))


def forecast_weights(table: pl.DataFrame, coefficients: pl.DataFrame | None = None) -> pl.DataFrame:
    """The weight table of the forecast (``region``, ``region_name`` and
    ``FORECAST_COLUMNS``): ``weights`` of the okres scores and, where ``coefficients``
    (``mos.Fit.frame`` rows) cover a group, the regression weights and the slot
    corrections at the okres's forecast point (``correction`` then is their mean)."""
    w = with_mos(weights(table), coefficients)
    points = point_elevations().select(
        pl.col("code").alias("region"), pl.col("elevation").alias("_point")
    )
    corrected = pl.col("bias_00").is_not_null()
    return (
        w.join(points, on="region", how="left")
        .with_columns(slot_corrections(pl.col("_point"), POINT_LAPSE_FACTOR))
        .with_columns(
            pl.when(corrected)
            .then(pl.mean_horizontal(*SLOT_CORRECTIONS))
            .otherwise(pl.col("correction"))
            .alias("correction")
        )
        .select("region", "region_name", *FORECAST_COLUMNS)
    )


def write_forecast(
    table: pl.DataFrame, out_dir: Path, forecast: pl.DataFrame | None = None
) -> list[Path]:
    """``out_dir/forecast/okresy.json`` and one ``out_dir/forecast/<okres>.json`` each,
    from ``forecast`` (``forecast_weights``; default: without the regression)."""
    folder = out_dir / "forecast"
    folder.mkdir(parents=True, exist_ok=True)
    w = forecast_weights(table) if forecast is None else forecast
    index = okres_points().with_columns(
        pl.col("code").is_in(w["region"].unique().to_list()).alias("weights")
    )
    written = [_write(folder / "okresy.json", index.sort("code"))]
    for (code,), part in sorted(w.partition_by("region", as_dict=True).items()):
        written.append(_write(folder / f"{code}.json", part.select(FORECAST_COLUMNS)))
    return written
