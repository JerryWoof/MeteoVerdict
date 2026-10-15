"""Does it matter which stations score the models? (docs/station-check.md)

Two checks on the daily scores (``meteoverdict.scoring``):

* ``compare_subsets``: the MAE ranking of the models, for Czechia and per kraj, when
  only a subset of the stations is used (e.g. only the main WMO stations, or only the
  automatic climate stations), with the same fair station-days and day bootstrap as
  ``meteoverdict.ranking``; ``summarize`` compares each subset with all stations
  (Spearman rank correlation, best model, MAE, intervals).
* ``suspicious_stations``: stations whose errors are much larger than their okres's for
  all models, or whose models all err the same way (a persistent bias, which points to
  the station's siting: a frost hollow, a town, a sheltered wind sensor).

The kind of each station (``stations.network``) comes from ČHMÚ's ``meta2``
(``networks``).
"""

from __future__ import annotations

import math
import zlib

import numpy as np
import polars as pl

from meteoverdict import aggregate, blend, metrics, ranking, station_pages
from meteoverdict.stations import network

VARIABLES = (
    "temperature_2m",
    "temperature_2m_00utc",
    "temperature_2m_06utc",
    "temperature_2m_12utc",
    "temperature_2m_18utc",
    "wind_speed_10m",
    "precipitation_daily",
    "precipitation_24h",
)
LEAD_DAYS = (1, 2, 3, 4, 5)
LEVELS = ("cz", "kraj")
#: subsets of ``subsets_by_network``: name → kinds of station
SUBSETS = {
    "main": ("main",),
    "climate": ("climate",),
    "manual_precipitation": ("precipitation",),
}

#: a station's median-model MAE this many times its okres's median is suspicious
MAE_RATIO = 2.0
#: a bias this much beyond the okres's median bias (with all models agreeing) is too
BIAS_EXCESS = {"temperature": 1.5, "wind_speed_10m": 1.5}
#: lead days for the station check: the shortest, where the station's own share of the
#: error is largest
CHECK_LEAD_DAYS = (1, 2)
CHECK_VARIABLES = (
    "temperature_2m",
    "temperature_2m_06utc",
    "temperature_2m_12utc",
    "wind_speed_10m",
    "precipitation_daily",
    "precipitation_24h",
)

COMPARE_SCHEMA = {
    "subset": pl.String,
    "level": pl.String,
    "region": pl.String,
    "variable": pl.String,
    "lead_day": pl.Int8,
    "stations": pl.Int32,
    "days": pl.Int32,
    "model": pl.String,
    "mae": pl.Float64,
    "rank": pl.Int16,
    "diff_to_best": pl.Float64,
    "diff_ci_low": pl.Float64,
    "diff_ci_high": pl.Float64,
    "tied_with_best": pl.Boolean,
}


def networks(stations: pl.DataFrame, meta2: pl.DataFrame) -> pl.DataFrame:
    """``id`` and ``network`` (``stations.NETWORKS``) of every station."""
    by_wsi = meta2.partition_by("WSI", as_dict=True) if meta2.height else {}
    empty = meta2.clear()
    kinds = [
        network(wsi, station_pages.element_table(by_wsi.get((wsi,), empty), wsi))
        for wsi in stations["id"].to_list()
    ]
    return pl.DataFrame({"id": stations["id"], "network": kinds})


def subsets_by_network(kinds: pl.DataFrame) -> dict[str, list[str]]:
    """Station ids of each subset in ``SUBSETS`` (``kinds`` from ``networks``)."""
    return {
        name: kinds.filter(pl.col("network").is_in(list(wanted)))["id"].to_list()
        for name, wanted in SUBSETS.items()
    }


def compare_subsets(
    scores: pl.LazyFrame | pl.DataFrame,
    stations: pl.DataFrame,
    subsets: dict[str, list[str] | None],
    variables: tuple[str, ...] = VARIABLES,
    lead_days: tuple[int, ...] = LEAD_DAYS,
    levels: tuple[str, ...] = LEVELS,
    resamples: int = ranking.RESAMPLES,
    seed: int = 0,
) -> pl.DataFrame:
    """MAE ranking of the models per subset (None: all stations), level, region,
    variable and lead day, over all days of ``scores``.

    As in ``ranking.rank``: only station-days every model of the region has, whole days
    resampled, a model ``tied_with_best`` when the 95 % interval of its MAE minus the
    best's includes 0; the mean of all models (``blend``) is not ranked. Regions with
    fewer than ``aggregate.MIN_STATIONS`` stations are left out.
    """
    scores = scores.lazy().filter(
        pl.col("variable").is_in(list(variables)), pl.col("lead_day").is_in(list(lead_days))
    )
    info = aggregate.station_info(stations)
    rows = []
    for name, ids in subsets.items():
        part = scores if ids is None else scores.filter(pl.col("station_id").is_in(ids))
        part = part.join(info, on="station_id", how="inner")
        for level in levels:
            fair = aggregate.common_days(
                part.with_columns(*aggregate.region_columns(level)), by="region"
            )
            daily = (
                fair.group_by("region", "variable", "lead_day", "date", "model")
                .agg(metrics.total("sum_abs_err"), metrics.total("n"))
                .collect()
            )
            counts = (
                fair.group_by("region", "variable", "lead_day")
                .agg(pl.col("station_id").n_unique().alias("stations"))
                .collect()
            )
            count = {(r, v, d): s for r, v, d, s in counts.iter_rows()}
            for (region, variable, lead_day), group in daily.partition_by(
                ["region", "variable", "lead_day"], as_dict=True
            ).items():
                n_stations = count.get((region, variable, lead_day), 0)
                if n_stations < aggregate.MIN_STATIONS:
                    continue
                key = f"{name}|{level}|{region}|{variable}|{lead_day}"
                rows += [
                    (name, level, region, variable, lead_day, *r)
                    for r in _rank_group(group, resamples, seed, key, n_stations)
                ]
    table = pl.DataFrame(rows, schema=COMPARE_SCHEMA, orient="row")
    return table.sort("subset", "level", "region", "variable", "lead_day", "rank", nulls_last=True)


def _rank_group(
    group: pl.DataFrame, resamples: int, seed: int, key: str, n_stations: int
) -> list[tuple]:
    abs_err = group.pivot(on="model", index="date", values="sum_abs_err").sort("date")
    n = group.pivot(on="model", index="date", values="n").sort("date")
    models = [c for c in abs_err.columns if c != "date"]
    ranked = np.array([m != blend.ID for m in models])
    a = abs_err.select(models).fill_null(0).to_numpy().astype(float)
    m = n.select(models).fill_null(0).to_numpy().astype(float)
    mae = a.sum(axis=0) / m.sum(axis=0)
    if ranked.sum() < 2:
        order, diff, bounds = (
            np.arange(len(models)),
            np.zeros(len(models)),
            np.zeros((2, len(models))),
        )
    else:
        rng = np.random.default_rng([seed, zlib.crc32(key.encode())])
        order, diff, bounds = ranking.bootstrap_group(a, m, rng, resamples, ranked)
    position = order.argsort()
    tied = (bounds[0] <= 0) & (bounds[1] >= 0) & (position > 0)
    out = []
    for i in order:
        rank = int(position[i]) + 1 if ranked[i] else None
        out.append(
            (
                n_stations, a.shape[0], models[i], float(mae[i]), rank, float(diff[i]),
                float(bounds[0][i]), float(bounds[1][i]), bool(tied[i]),
            )
        )  # fmt: skip
    return out


def spearman(x: list[float], y: list[float]) -> float | None:
    """Spearman rank correlation (average ranks for ties); None for fewer than 3."""
    if len(x) < 3:
        return None
    rx = pl.Series(x).rank("average").to_numpy()
    ry = pl.Series(y).rank("average").to_numpy()
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def summarize(table: pl.DataFrame, base: str = "all") -> pl.DataFrame:
    """Each subset against ``base`` per level, region, variable and lead day: Spearman
    correlation of the ranked models' MAEs, the best model of each, whether the change
    is within the intervals (each best model is tied with the other's best), the MAE
    of the base's best model in both, and the mean MAE difference (subset - base)."""
    ranked = table.filter(pl.col("rank").is_not_null())
    keys = ["level", "region", "variable", "lead_day"]
    base_rows = ranked.filter(pl.col("subset") == base)
    out = []
    for (subset,), part in (
        ranked.filter(pl.col("subset") != base).partition_by("subset", as_dict=True).items()
    ):
        joined = part.join(base_rows, on=[*keys, "model"], suffix="_base")
        for group_key, g in joined.partition_by(keys, as_dict=True).items():
            if g.height < 2:
                continue
            best_sub = g.sort("mae")["model"][0]
            best_base = g.sort("mae_base")["model"][0]
            # within the intervals: each best model is the best or tied with it in the other
            ok_base = (
                g.filter(pl.col("model") == best_sub)
                .select((pl.col("rank_base") == 1) | pl.col("tied_with_best_base"))
                .item()
            )
            ok_sub = (
                g.filter(pl.col("model") == best_base)
                .select((pl.col("rank") == 1) | pl.col("tied_with_best"))
                .item()
            )
            base_best = g.filter(pl.col("model") == best_base).row(0, named=True)
            out.append(
                (
                    subset, *group_key, g.height, int(g["stations"][0]),
                    int(g["stations_base"][0]),
                    spearman(g["mae"].to_list(), g["mae_base"].to_list()),
                    best_base, best_sub, best_base == best_sub, bool(ok_base and ok_sub),
                    base_best["mae_base"], base_best["mae"],
                    float((g["mae"] - g["mae_base"]).mean()),
                )
            )  # fmt: skip
    schema = {
        "subset": pl.String,
        "level": pl.String,
        "region": pl.String,
        "variable": pl.String,
        "lead_day": pl.Int8,
        "models": pl.Int32,
        "stations": pl.Int32,
        "stations_base": pl.Int32,
        "spearman": pl.Float64,
        "best_base": pl.String,
        "best": pl.String,
        "same_best": pl.Boolean,
        "within_ci": pl.Boolean,
        "best_base_mae_base": pl.Float64,
        "best_base_mae": pl.Float64,
        "mean_mae_diff": pl.Float64,
    }
    return pl.DataFrame(out, schema=schema, orient="row").sort(
        "subset", "level", "region", "variable", "lead_day"
    )


def overview(summary: pl.DataFrame) -> pl.DataFrame:
    """Per subset, level and variable over the lead days: median Spearman, how often
    the best model is the same and how often a change is within the intervals."""
    return (
        summary.group_by("subset", "level", "variable")
        .agg(
            pl.len().alias("groups"),
            pl.col("stations").median().alias("stations"),
            pl.col("spearman").median().alias("spearman_median"),
            pl.col("spearman").min().alias("spearman_min"),
            pl.col("same_best").mean().alias("same_best"),
            pl.col("within_ci").mean().alias("within_ci"),
            pl.col("mean_mae_diff").mean().alias("mean_mae_diff"),
        )
        .sort("subset", "level", "variable")
    )


# --- suspicious stations --------------------------------------------------------------------
def station_errors(
    scores: pl.LazyFrame | pl.DataFrame,
    variables: tuple[str, ...] = CHECK_VARIABLES,
    lead_days: tuple[int, ...] = CHECK_LEAD_DAYS,
) -> pl.DataFrame:
    """Per station and variable over all days and ``lead_days``: the median over the
    models of their MAE and bias, and the share of models whose bias has the sign of
    the median (1: all models err the same way). The blend is left out."""
    per_model = (
        scores.lazy()
        .filter(
            pl.col("variable").is_in(list(variables)),
            pl.col("lead_day").is_in(list(lead_days)),
            pl.col("model") != blend.ID,
        )
        .group_by("station_id", "variable", "model")
        .agg(
            metrics.total("sum_abs_err"),
            metrics.total("sum_err"),
            metrics.total("n"),
            pl.col("date").n_unique().alias("days"),
        )
        .filter(pl.col("n") > 0)
        .with_columns(
            (pl.col("sum_abs_err") / pl.col("n")).alias("mae"),
            (pl.col("sum_err") / pl.col("n")).alias("bias"),
        )
        .collect()
    )
    return (
        per_model.group_by("station_id", "variable")
        .agg(
            pl.len().alias("models"),
            pl.col("n").max().alias("n"),
            pl.col("days").max().alias("days"),
            pl.col("mae").median().alias("mae"),
            pl.col("bias").median().alias("bias"),
            pl.col("bias").sign().alias("signs"),
        )
        .with_columns(
            (
                pl.col("signs").list.eval(pl.element() == pl.element().median().sign()).list.mean()
            ).alias("agree")
        )
        .drop("signs")
    )


def _threshold(variable: str) -> float | None:
    if variable.startswith("temperature"):
        return BIAS_EXCESS["temperature"]
    return BIAS_EXCESS.get(variable)


def _hint(variable: str, bias_excess: float, ratio: float) -> str:
    """What a station's error pattern suggests (error = forecast - observed)."""
    if variable.startswith("temperature") and abs(bias_excess) >= BIAS_EXCESS["temperature"]:
        if bias_excess > 0:
            return "colder than the models and its okres: valley, frost hollow or inversion"
        return "warmer than the models and its okres: town, slope or sheltered sensor"
    if variable == "wind_speed_10m" and abs(bias_excess) >= BIAS_EXCESS["wind_speed_10m"]:
        if bias_excess > 0:
            return "weaker wind than forecast: sheltered sensor (trees, buildings, valley)"
        return "stronger wind than forecast: exposed ridge or summit"
    if variable.startswith("precipitation") and ratio >= MAE_RATIO:
        return "precipitation errors far above its okres: gauge, data or local showers"
    return "errors far above its okres for all models"


def daily_errors(
    scores: pl.LazyFrame | pl.DataFrame,
    variables: tuple[str, ...] = CHECK_VARIABLES,
    lead_days: tuple[int, ...] = CHECK_LEAD_DAYS,
) -> pl.DataFrame:
    """Per station, variable and day (``lead_days`` together): the median over the
    models (not the blend) of their MAE and bias that day."""
    return (
        scores.lazy()
        .filter(
            pl.col("variable").is_in(list(variables)),
            pl.col("lead_day").is_in(list(lead_days)),
            pl.col("model") != blend.ID,
        )
        .group_by("station_id", "variable", "date", "model")
        .agg(metrics.total("sum_abs_err"), metrics.total("sum_err"), metrics.total("n"))
        .filter(pl.col("n") > 0)
        .group_by("station_id", "variable", "date")
        .agg(
            (pl.col("sum_abs_err") / pl.col("n")).median().alias("mae"),
            (pl.col("sum_err") / pl.col("n")).median().alias("bias"),
        )
        .collect()
    )


def suspicious_stations(
    errors: pl.DataFrame,
    daily: pl.DataFrame,
    stations: pl.DataFrame,
    kinds: pl.DataFrame | None = None,
    min_models: int = 3,
    min_days: int = 20,
    min_okres: int = aggregate.MIN_STATIONS,
) -> pl.DataFrame:
    """Stations whose errors stand out from their okres's (the kraj's when the okres
    has fewer than ``min_okres`` stations for the variable), **on the same days**: the
    station's median-model MAE is at least ``MAE_RATIO`` times the okres's median, or
    its median bias is ``BIAS_EXCESS`` beyond the okres's with every model agreeing on
    the sign (``errors`` from ``station_errors``, ``daily`` from ``daily_errors``).
    Only stations with at least ``min_models`` models and ``min_days`` days count, also
    for the okres medians. Sorted by ``severity`` (the larger of the MAE ratio over
    ``MAE_RATIO`` and the bias excess over its threshold), one row per station and
    variable. ``mae`` and ``bias`` are the station's daily values averaged over its
    days, ``area_mae`` and ``area_bias`` the okres's daily medians over the same days."""
    info = stations.select(pl.col("id").alias("station_id"), "name", "okres", "kraj", "elevation")
    if kinds is not None:
        info = info.join(kinds.rename({"id": "station_id"}), on="station_id", how="left")
    frame = errors.filter(pl.col("models") >= min_models, pl.col("days") >= min_days).join(
        info, on="station_id"
    )
    days = daily.join(
        frame.select("station_id", "variable", "okres", "kraj"), on=["station_id", "variable"]
    )
    areas = {}
    for area in ("okres", "kraj"):
        per_day = days.group_by(area, "variable", "date").agg(
            pl.col("mae").median().alias(f"{area}_mae"),
            pl.col("bias").median().alias(f"{area}_bias"),
        )
        areas[area] = (
            days.join(per_day, on=[area, "variable", "date"])
            .group_by("station_id", "variable")
            .agg(
                pl.col(f"{area}_mae").mean(),
                pl.col(f"{area}_bias").mean(),
                pl.col("mae").mean().alias("day_mae"),
                pl.col("bias").mean().alias("day_bias"),
            )
        )
    count = frame.group_by("okres", "variable").agg(pl.len().alias("okres_stations"))
    frame = (
        frame.drop("mae", "bias")
        .join(areas["okres"], on=["station_id", "variable"])
        .join(areas["kraj"].drop("day_mae", "day_bias"), on=["station_id", "variable"])
        .join(count, on=["okres", "variable"])
        .rename({"day_mae": "mae", "day_bias": "bias"})
    )
    use_okres = pl.col("okres_stations") >= min_okres
    frame = frame.with_columns(
        pl.when(use_okres).then(pl.lit("okres")).otherwise(pl.lit("kraj")).alias("compared_to"),
        pl.when(use_okres).then("okres_mae").otherwise("kraj_mae").alias("area_mae"),
        pl.when(use_okres).then("okres_bias").otherwise("kraj_bias").alias("area_bias"),
    ).with_columns(
        (pl.col("mae") / pl.col("area_mae")).alias("ratio"),
        (pl.col("bias") - pl.col("area_bias")).alias("bias_excess"),
    )
    rows = []
    for row in frame.iter_rows(named=True):
        threshold = _threshold(row["variable"])
        ratio = row["ratio"] if row["ratio"] is not None and math.isfinite(row["ratio"]) else 0
        bias_part = 0.0
        if threshold and row["agree"] == 1:
            bias_part = abs(row["bias_excess"]) / threshold
        severity = max(ratio / MAE_RATIO, bias_part)
        if severity >= 1:
            rows.append(
                {
                    **row,
                    "severity": severity,
                    "hint": _hint(row["variable"], row["bias_excess"], ratio),
                }
            )
    columns = [
        "station_id", "name", "okres", "kraj", "elevation",
        *(["network"] if kinds is not None else []), "variable", "models", "days", "mae",
        "bias", "agree", "compared_to", "area_mae", "area_bias", "ratio", "bias_excess",
        "severity", "hint",
    ]  # fmt: skip
    if not rows:
        schema = {c: frame.schema.get(c, pl.Float64) for c in columns}
        return pl.DataFrame(schema={**schema, "hint": pl.String})
    return pl.DataFrame(rows).select(columns).sort("severity", descending=True)


def top_stations(flagged: pl.DataFrame, k: int = 10) -> pl.DataFrame:
    """The ``k`` most severe stations, each with its most severe variable and how many
    variables are flagged for it."""
    if flagged.is_empty():
        return flagged
    count = flagged.group_by("station_id").agg(pl.len().alias("flagged"))
    return (
        flagged.sort("severity", descending=True)
        .unique("station_id", keep="first", maintain_order=True)
        .join(count, on="station_id")
        .sort("severity", descending=True)
        .head(k)
    )


# --- Markdown ---------------------------------------------------------------------------
def markdown_table(frame: pl.DataFrame, digits: int = 2) -> str:
    """A plain Markdown table of ``frame``, floats rounded."""

    def cell(v: object) -> str:
        if v is None:
            return "-"
        if isinstance(v, float):
            return f"{v:.{digits}f}"
        if isinstance(v, bool):
            return "yes" if v else "no"
        return str(v)

    lines = ["| " + " | ".join(frame.columns) + " |", "|" + "---|" * frame.width]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in frame.iter_rows()]
    return "\n".join(lines)


def report(summary: pl.DataFrame, flagged: pl.DataFrame, k: int = 10) -> str:
    """The check as Markdown: Czechia per subset, variable and lead day; the kraje in
    brief; the ``k`` most suspicious stations."""
    cz = summary.filter(pl.col("level") == "cz").select(
        "subset", "variable", "lead_day", "stations", "spearman", "best_base", "best",
        "within_ci", pl.col("best_base_mae_base").alias("mae_all"),
        pl.col("best_base_mae").alias("mae_subset"), "mean_mae_diff",
    )  # fmt: skip
    kraje = overview(summary.filter(pl.col("level") == "kraj")).drop("level")
    top = top_stations(flagged, k)
    if not top.is_empty():
        top = top.select(
            "name", "okres", pl.col("elevation").round(0).cast(pl.Int32),
            *(["network"] if "network" in top.columns else []), "variable",
            pl.col("mae").round(2), pl.col("area_mae").round(2), pl.col("ratio").round(1),
            pl.col("bias").round(2), pl.col("bias_excess").round(2), "flagged", "hint",
        )  # fmt: skip
    parts = [
        "## Czechia: each subset against all stations",
        "",
        "`best_base`: best model with all stations, `best`: with the subset; "
        "`within_ci`: each is the best or tied with the best in the other ranking; "
        "`mae_all`/`mae_subset`: MAE of `best_base` with all stations and with the subset; "
        "`mean_mae_diff`: mean over the models of MAE(subset) - MAE(all).",
        "",
        markdown_table(cz),
        "",
        "## Kraje (over kraje with enough stations and lead days 1-5)",
        "",
        markdown_table(kraje),
        "",
        f"## Suspicious stations (top {k} of {flagged['station_id'].n_unique()} flagged)",
        "",
        markdown_table(top) if not top.is_empty() else "None.",
        "",
    ]
    return "\n".join(parts)
