"""How good is the obec forecast where there is no station? Leave one station out.

The forecast for every obec (``meteoverdict.obce_forecast``) reads each model at the
obec's own place and height and combines the models with the weights and corrections of
the obec's okres, the corrections' elevation term taken at the obec's height. Nobody can
check it at an obec, but every ČHMÚ station is a place too. So for each station ``s``
(the target) the same forecast is rebuilt at ``s`` as if ``s`` did not exist, and scored
against what ``s`` measured:

1. **Held out.** ``s`` (``loso``), or ``s`` and every station within ``BUFFER_KM``
   of it (``buffer``, the stricter variant: no close neighbour helps either), is
   removed from everything it feeds: the scores the weights and bias corrections come
   from, the okres pools (its okres borrows another station instead where it gets
   too few), the regression blend's pairs (hour-of-day bias, the national elevation
   term and the ridge weights, ``mos``) and the nearest-station baseline below.
2. **Trained as live, out of sample** (``meteoverdict.hindcast``): the D+N forecast for
   day ``d`` uses the scores up to ``d - N - 1`` (``hindcast.as_of``), the 90-day window,
   ``combine.weights`` and ``mos`` as the daily run does.
3. **Series**, all from the stored D+N forecasts (``fc-YYYY-MM.parquet``, the newest
   days rebuilt from the single runs as in ``mvd daily``), scored like the blend test
   (temperature and wind at 00/06/12/18 UTC, precipitation as UTC-day totals):

   - ``obec``: the models at ``s`` combined with the weights of ``s``'s okres, the slot
     corrections' elevation term at ``s``'s own height (``combine.POINT_LAPSE_FACTOR``),
     exactly as ``obce_forecast`` does for an obec;
   - ``obec_point``: the same with the slot corrections at the okres's point (what
     ``obce_forecast`` did until 20 October 2026);
   - ``okres``: the okres's forecast without the downscaling: the same weights applied
     at the okres's other stations (its pool) and averaged over them, as
     ``hindcast`` rebuilds the okres forecast (the okres point itself has no stored D+N);
   - ``nearest``: the models at ``s`` weighted and bias-corrected (``combine.weights``,
     no regression) by their scores at the nearest remaining station alone;
   - ``median``: the plain median of the models at ``s``, uncorrected.

4. **Compared** on the station-days every series has, per variable, lead day and
   stratum (all, ``elevation_class``, height of ``s`` relative to the okres's point),
   with a 95 % interval of ``obec`` minus each other series from a moving-block
   bootstrap of whole days (``BLOCK_DAYS``-day circular blocks, so that the day-to-day
   correlation of the weather is kept; ``block_bootstrap``, our own helper).

Targets that do not share an okres neighbourhood are held out together (``batches``),
which leaves the local training exact and only removes a few more stations from the
national regression terms (stricter, never leaking).
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from meteoverdict import blend, blendtest, combine, forecasts, hindcast, mos, neighbours

OBEC = "obec"
OBEC_POINT = "obec_point"
OKRES = "okres"
NEAREST = "nearest"
MEDIAN = "median"
SERIES = (OBEC, OBEC_POINT, OKRES, NEAREST, MEDIAN)
#: ``obec`` minus each of these, with an interval
COMPARED = (OKRES, NEAREST, MEDIAN, OBEC_POINT)
LEADS = (1, 2, 3, 4, 5)
VARIANTS = ("loso", "buffer")
#: the stricter variant also holds out every station this close to the target
BUFFER_KM = 20.0
#: moving-block bootstrap: block length in days and resamples
BLOCK_DAYS = 4
RESAMPLES = 2000
#: height of the target relative to its okres's forecast point (m): classes
HEIGHT_CLASSES = ((150.0, "within 150 m"), (400.0, "150-400 m"), (float("inf"), "over 400 m"))
UNITS = blendtest.UNITS
#: published in the release data-latest, next to blend-test.json
ASSET = "obce-loso.json"


# --- who is held out together ----------------------------------------------------------
def distances_km(stations: pl.DataFrame) -> np.ndarray:
    """Distance (km) between every two stations, in the order of ``stations`` (the local
    projection of ``neighbours.border_distances_km``)."""
    lat = stations["lat"].to_numpy().astype(float)
    lon = stations["lon"].to_numpy().astype(float)
    kx = 111.32 * np.cos(np.radians((lat[:, None] + lat[None, :]) / 2))
    return np.hypot((lon[:, None] - lon[None, :]) * kx, (lat[:, None] - lat[None, :]) * 110.57)


def removal_sets(
    stations: pl.DataFrame, targets: list[str], buffer_km: float | None
) -> dict[str, set[str]]:
    """The stations held out with each target: itself, and with ``buffer_km`` also every
    station within that distance."""
    ids = stations["id"].to_list()
    index = {s: i for i, s in enumerate(ids)}
    if buffer_km is None:
        return {t: {t} for t in targets}
    km = distances_km(stations)
    return {t: {ids[j] for j in np.where(km[index[t]] <= buffer_km)[0]} | {t} for t in targets}


def zones(stations: pl.DataFrame, max_km: float = neighbours.MAX_KM) -> dict[str, set[str]]:
    """Per okres the stations its pool can contain: its own and those within ``max_km``
    of its border (``neighbours.pools`` borrows no further)."""
    near = neighbours.distances(stations).filter(pl.col("distance_km") <= max_km)
    return {
        code: set(part["station_id"].to_list())
        for (code,), part in near.partition_by("region", as_dict=True).items()
    }


def batches(
    targets: list[str],
    okres_of: dict[str, str],
    removed: dict[str, set[str]],
    zone: dict[str, set[str]],
) -> list[list[str]]:
    """Group the targets so that none of a group's held-out stations can enter the okres
    pool of another target of the group (greedy, in the order given): each target's
    own okres is then trained exactly as with only its own stations held out."""
    groups: list[list[str]] = []
    held: list[set[str]] = []  # held-out stations of each group
    reach: list[set[str]] = []  # stations the group's okres pools can contain
    for t in targets:
        mine = zone.get(okres_of[t], set())
        for k in range(len(groups)):
            if not (removed[t] & reach[k]) and not (held[k] & mine):
                groups[k].append(t)
                held[k] |= removed[t]
                reach[k] |= mine
                break
        else:
            groups.append([t])
            held.append(set(removed[t]))
            reach.append(set(mine))
    return groups


# --- training ----------------------------------------------------------------------------
def needed_as_of(days: list[date], leads: tuple[int, ...] = LEADS) -> list[date]:
    """Every training day the test ``days`` need (``hindcast.as_of``)."""
    return sorted({hindcast.as_of(d, n) for d in days for n in leads})


def okres_weights(
    scores: pl.DataFrame,
    pairs: pl.DataFrame | None,
    stations: pl.DataFrame,
    as_of_days: list[date],
    okresy: list[str],
    reach: set[str],
    window: str = combine.WINDOW,
    min_days: int = blendtest.MIN_TRAINING_DAYS,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """``(weights, pools)`` of the ``okresy`` as the live forecast trains them, from
    ``scores``, ``pairs`` and ``stations`` with the held-out stations already removed.

    The score-based weights read only the stations in ``reach`` (all an okres's pool
    can contain, ``zones``), the regression all pairs (its elevation term and ridge
    prior are national). ``weights`` carry ``date`` = the day they are used for (as
    ``hindcast.rebuild``: ``as_of`` + lead + 1) and the coefficient columns of
    ``combine.with_mos``."""
    length = int(window.removesuffix("d"))
    period = scores.filter(pl.col("date") > min(as_of_days) - timedelta(days=length))
    pools = blendtest.pools(period, stations)
    local = scores.filter(pl.col("station_id").is_in(list(reach)))
    w, _ = blendtest.training(local, stations, as_of_days, window, min_days)
    if w.is_empty():
        return w, pools
    w = w.filter(pl.col("region").is_in(okresy)).drop(mos.COEFFICIENT_COLUMNS, strict=False)
    coefficients = None
    if pairs is not None and not pairs.is_empty():
        allowed = w.select("variable", "lead_day", "model").unique()
        coefficients = mos.coefficients(
            pairs, pools, stations, as_of_days, length, allowed=allowed, min_days=min_days
        )
        if not coefficients.is_empty():
            coefficients = coefficients.filter(pl.col("region").is_in(okresy))
    w = combine.with_mos(w, coefficients, keys=("as_of", "region"))
    return w.with_columns((pl.col("date") + timedelta(days=1)).alias("date")), pools


def nearest_stations(
    stations: pl.DataFrame,
    available: pl.DataFrame,
    targets: list[str],
    removed: dict[str, set[str]],
) -> pl.DataFrame:
    """``target``, ``variable`` (score variable), ``station_id``: per target and variable
    the nearest station with scores for it (``available``: ``variable``,
    ``station_id``) that is not held out with the target."""
    ids = stations["id"].to_list()
    index = {s: i for i, s in enumerate(ids)}
    km = distances_km(stations)
    rows = []
    for (variable,), part in available.partition_by("variable", as_dict=True).items():
        have = [index[s] for s in part["station_id"].unique().to_list() if s in index]
        for t in targets:
            options = [j for j in have if ids[j] not in removed[t]]
            if options:
                best = min(options, key=lambda j: (km[index[t], j], ids[j]))
                rows.append((t, variable, ids[best]))
    return pl.DataFrame(rows, schema=["target", "variable", "station_id"], orient="row")


def nearest_weights(
    scores: pl.DataFrame,
    nearest: pl.DataFrame,
    as_of_days: list[date],
    window: str = combine.WINDOW,
    min_days: int = blendtest.MIN_TRAINING_DAYS,
) -> pl.DataFrame:
    """``combine.weights`` of every target (``region`` = the target) from the scores of
    its nearest station alone, per ``as_of`` (``date`` as ``okres_weights``): the
    models with scores on ``aggregate.MIN_COVERAGE`` of its days, on the days all of
    them have."""
    length = int(window.removesuffix("d"))
    group = ["target", "variable", "lead_day"]
    frames = []
    for as_of in as_of_days:
        part = (
            scores.lazy()
            .filter(pl.col("date").is_between(as_of - timedelta(days=length - 1), as_of))
            .filter(pl.col("n") > 0, pl.col("model") != blend.ID)
            .join(nearest.lazy(), on=["variable", "station_id"])
        )
        days = pl.col("date").n_unique()
        covered = (
            part.with_columns(days.over(group).alias("_all"))
            .group_by(*group, "model")
            .agg(days.alias("_days"), pl.col("_all").first())
            .filter(pl.col("_days") >= blendtest.MIN_MODEL_COVERAGE * pl.col("_all"))
            .select(*group, "model")
        )
        part = part.join(covered, on=[*group, "model"], how="semi")
        need = part.group_by(group).agg(pl.col("model").n_unique().alias("_models"))
        full = (
            part.group_by(*group, "date")
            .agg(pl.col("model").n_unique().alias("_have"))
            .join(need, on=group)
            .filter(pl.col("_have") == pl.col("_models"))
            .select(*group, "date")
        )
        n = pl.col("n").cast(pl.Float64).sum()
        table = (
            part.join(full, on=[*group, "date"], how="semi")
            .group_by(*group, "model")
            .agg(
                n.alias("n"),
                (pl.col("sum_abs_err").cast(pl.Float64).sum() / n).alias("mae"),
                (pl.col("sum_err").cast(pl.Float64).sum() / n).alias("bias"),
                (pl.col("sum_sq_err").cast(pl.Float64).sum() / n).sqrt().alias("rmse"),
                pl.col("date").n_unique().alias("days"),
            )
            .collect()
        )
        if table.is_empty():
            continue
        table = table.select(
            pl.lit("okres").alias("level"),
            pl.lit(window).alias("window"),
            pl.col("target").alias("region"),
            pl.col("target").alias("region_name"),
            "variable",
            "lead_day",
            "model",
            "n",
            "mae",
            "bias",
            "rmse",
            "days",
            pl.lit(True).alias("enough_stations"),
        )
        w = combine.weights(table, window)
        enough = (
            w.group_by("region", "variable", "lead_day")
            .agg(pl.col("days").max())
            .filter(pl.col("days") >= min_days)
            .drop("days")
        )
        w = w.join(enough, on=["region", "variable", "lead_day"], how="semi")
        frames.append(w.with_columns(pl.lit(as_of).alias("as_of")))
    if not frames:
        return pl.DataFrame()
    w = pl.concat(frames)
    target_day = pl.col("as_of") + pl.duration(days=pl.col("lead_day").cast(pl.Int64) + 1)
    return w.with_columns(target_day.cast(pl.Date).alias("date"))


# --- the series ----------------------------------------------------------------------------
#: the weight columns ``combined`` needs (the others would only fill the memory)
WEIGHT_COLUMNS = tuple(
    dict.fromkeys(
        ("date", "region", "lead_day", "model", *combine.BLEND_COLUMNS, *mos.COEFFICIENT_COLUMNS)
    )
)


def _date_of(variable: str) -> pl.Expr:
    """The day an hour is scored on: precipitation by the hour ending at ``time``."""
    start = pl.col("time") - timedelta(hours=1) if variable == "precipitation" else pl.col("time")
    return start.dt.date().alias("date")


def combined(
    fc: pl.LazyFrame | pl.DataFrame,
    members: pl.DataFrame,
    weights: pl.DataFrame,
    elevation: pl.Expr | None = None,
) -> pl.DataFrame:
    """The combined forecast (``combine.combine_values``) at the stations of ``members``
    (``variable`` = score variable, ``region``, ``station_id``) with the weights of their
    ``region`` of the day: ``region``, ``station_id``, ``time``, ``lead_day`` and the
    three variables. With the regression's coefficients the slot corrections are taken
    at ``elevation`` (an expression over the weight columns, ``_elevation``, the
    station's height, and ``_point``, the okres's point; default: the point) with the
    point's elevation factor."""
    keys = ["region", "station_id", "time", "lead_day"]
    raw = fc.lazy().filter(pl.col("model") != blend.ID)
    regression = "bias_00" in weights.columns
    out = None
    for name, score in blendtest.SCORE_VARIABLES.items():
        mine = members.filter(pl.col("variable") == score).select(
            "region", "station_id", *[c for c in ("_elevation", "_point") if c in members.columns]
        )
        w = weights.filter(pl.col("variable") == name).select(
            *[c for c in WEIGHT_COLUMNS if c in weights.columns]
        )
        rows = (
            raw.select("station_id", "time", "lead_day", "model", name)
            .with_columns(_date_of(name))
            .join(mine.lazy(), on="station_id")
            .join(w.lazy(), on=["date", "region", "lead_day", "model"])
        )
        if regression:
            at = elevation if elevation is not None else pl.col("_point")
            rows = rows.with_columns(combine.slot_corrections(at, combine.POINT_LAPSE_FACTOR))
        part = combine.combine_values(rows, name, keys)
        out = part if out is None else out.join(part, on=keys, how="full", coalesce=True)
    return out.collect()


def median(fc: pl.LazyFrame | pl.DataFrame, targets: list[str]) -> pl.DataFrame:
    """The median of the models at each target, hour and lead day (null with fewer than
    ``combine.MIN_MODELS`` models)."""
    names = list(blendtest.SCORE_VARIABLES)
    return (
        fc.lazy()
        .filter(pl.col("station_id").is_in(targets), pl.col("model") != blend.ID)
        .group_by("station_id", "time", "lead_day")
        .agg(
            pl.when(pl.col(v).count() >= combine.MIN_MODELS).then(pl.col(v).median()).alias(v)
            for v in names
        )
        .collect()
    )


def as_forecasts(frame: pl.DataFrame, series: str) -> pl.DataFrame:
    """Rows of one series at the targets in the forecast table's layout."""
    return (
        frame.select(
            "station_id",
            "time",
            pl.lit(series).alias("model"),
            "lead_day",
            *[
                pl.col(v) if v in frame.columns else pl.lit(None).alias(v)
                for v in blendtest.SCORE_VARIABLES
            ],
        )
        .cast(forecasts.SCHEMA)
        .filter(~pl.all_horizontal(pl.col(v).is_null() for v in blendtest.SCORE_VARIABLES))
    )


def batch_series(
    fc: pl.LazyFrame,
    batch: list[str],
    stations: pl.DataFrame,
    weights: pl.DataFrame,
    pools: pl.DataFrame,
    points: dict[str, float],
) -> list[pl.DataFrame]:
    """``obec``, ``obec_point`` and ``okres`` at the targets of one batch."""
    info = stations.filter(pl.col("id").is_in(batch)).select(
        pl.col("id").alias("station_id"),
        pl.col("okres_code").alias("region"),
        pl.col("elevation").cast(pl.Float64).alias("_elevation"),
    )
    info = info.with_columns(
        pl.col("region")
        .replace_strict(points, default=None, return_dtype=pl.Float64)
        .alias("_point")
    )
    variables = list(blendtest.SCORE_VARIABLES.values())
    at_targets = info.join(pl.DataFrame({"variable": variables}), how="cross")
    at_fc = fc.filter(pl.col("station_id").is_in(batch))
    obec = combined(at_fc, at_targets, weights, elevation=pl.col("_elevation"))
    obec_point = combined(at_fc, at_targets, weights)
    # the okres's forecast: its pool (the targets are not in it) and its point's height
    okresy = info["region"].unique().to_list()
    members = pools.filter(pl.col("region").is_in(okresy)).select(
        "variable", "region", "station_id"
    )
    members = members.with_columns(
        pl.col("region")
        .replace_strict(points, default=None, return_dtype=pl.Float64)
        .alias("_point")
    )
    names = list(blendtest.SCORE_VARIABLES)
    parts = []
    for (_,), mine in members.partition_by("region", as_dict=True).items():
        # one okres at a time: all pools at once take several GB
        at_pool = fc.filter(pl.col("station_id").is_in(mine["station_id"].unique().to_list()))
        parts.append(
            combined(at_pool, mine, weights)
            .group_by("region", "time", "lead_day")
            .agg(pl.col(v).mean() for v in names)
        )
    okres = pl.concat(parts).join(info.select("region", "station_id"), on="region")
    return [
        as_forecasts(obec, OBEC),
        as_forecasts(obec_point, OBEC_POINT),
        as_forecasts(okres, OKRES),
    ]


# --- the whole run ---------------------------------------------------------------------------
def run(
    scores: pl.DataFrame,
    fc: pl.LazyFrame | pl.DataFrame,
    observations: pl.LazyFrame | pl.DataFrame,
    stations: pl.DataFrame,
    first: date,
    last: date,
    variant: str = "loso",
    buffer_km: float = BUFFER_KM,
    window: str = combine.WINDOW,
    min_training_days: int = blendtest.MIN_TRAINING_DAYS,
    regression: bool = True,
    targets: list[str] | None = None,
    log: Callable[[str], None] = lambda _: None,
    checkpoint: Path | None = None,
) -> pl.DataFrame:
    """Daily scores (``sum_abs_err``, ``sum_err``, ``n`` per ``date``, ``station_id``,
    ``variable``, ``lead_day`` and ``model`` = series) of every target, on the
    station-days all ``SERIES`` have. ``variant``: ``loso`` (the target held out) or
    ``buffer`` (also every station within ``buffer_km``). ``checkpoint``: a folder that
    keeps each batch's scores, so that a run that stopped carries on where it was."""
    variables = list(blendtest.SCORE_VARIABLES.values())
    scores = scores.filter(pl.col("variable").is_in(variables))
    stations = stations.filter(pl.col("lat").is_not_null(), pl.col("lon").is_not_null())
    tested = scores.filter(pl.col("date").is_between(first, last))
    if targets is None:
        targets = sorted(set(tested["station_id"]) & set(stations["id"]))
    targets = [t for t in targets if t in set(stations["id"])]
    if not targets:
        return pl.DataFrame()
    days = [first + timedelta(days=k) for k in range((last - first).days + 1)]
    as_of_days = [a for a in needed_as_of(days) if a <= scores["date"].max()]
    length = int(window.removesuffix("d"))
    okres_of = dict(stations.select("id", "okres_code").iter_rows())
    removed = removal_sets(stations, targets, buffer_km if variant == "buffer" else None)
    zone = zones(stations)
    groups = batches(targets, okres_of, removed, zone)
    log(f"{variant}: {len(targets)} targets in {len(groups)} batches")
    fc = fc.lazy()
    pairs = None
    if regression:
        pairs = mos.pairs(observations, fc, as_of_days[0] - timedelta(days=length - 1), last)
    points = dict(combine.point_elevations().iter_rows())
    start = datetime(first.year, first.month, first.day, tzinfo=UTC)
    end = datetime(last.year, last.month, last.day, tzinfo=UTC) + timedelta(days=1)
    # read once: every batch reads its targets and pools from it
    test_fc = (
        fc.filter(pl.col("time").is_between(start, end), pl.col("lead_day").is_in(LEADS))
        .collect()
        .lazy()
    )
    # the nearest-station baseline: trained for every target at once
    available = tested.select("variable", "station_id").unique()
    nearest = nearest_stations(stations, available, targets, removed)
    near_w = nearest_weights(scores, nearest, as_of_days, window, min_training_days)
    obs = observations.lazy()
    frames = []
    for k, batch in enumerate(groups, 1):
        saved = checkpoint / f"{variant}-{k:03d}.parquet" if checkpoint is not None else None
        if saved is not None and saved.exists():
            frames.append(pl.read_parquet(saved))
            continue
        held = set().union(*(removed[t] for t in batch))
        reach = set().union(*(zone.get(okres_of[t], set()) for t in batch))
        kept = scores.filter(~pl.col("station_id").is_in(list(held)))
        own = stations.filter(~pl.col("id").is_in(list(held)))
        kept_pairs = (
            pairs.filter(~pl.col("station_id").is_in(list(held))) if pairs is not None else None
        )
        okresy = sorted({okres_of[t] for t in batch})
        w, pools = okres_weights(
            kept, kept_pairs, own, as_of_days, okresy, reach - held, window, min_training_days
        )
        series = []
        if not w.is_empty():
            series += batch_series(test_fc, batch, stations, w, pools, points)
        at = test_fc.filter(pl.col("station_id").is_in(batch))
        mine = nearest.filter(pl.col("target").is_in(batch))
        if not near_w.is_empty() and mine.height:
            members = mine.select(
                "variable", pl.col("target").alias("region"), pl.col("target").alias("station_id")
            )
            series.append(as_forecasts(combined(at, members, near_w), NEAREST))
        series.append(as_forecasts(median(at, batch), MEDIAN))
        candidates = pl.concat(series)
        scored = fair(
            blendtest.score_candidates(
                obs.filter(pl.col("station_id").is_in(batch)), candidates, first, last
            )
        )
        if saved is not None:
            saved.parent.mkdir(parents=True, exist_ok=True)
            scored.write_parquet(saved)
        frames.append(scored)
        log(
            f"{variant}: batch {k}/{len(groups)}, {len(batch)} targets, {len(held)} held out, "
            f"{scored['station_id'].n_unique()} scored"
        )
    return pl.concat(frames) if frames else pl.DataFrame()


def fair(scored: pl.DataFrame) -> pl.DataFrame:
    """The station-days (per variable and lead day) every series has a score on."""
    keys = ["date", "station_id", "variable", "lead_day"]
    rows = scored.filter(pl.col("n") > 0).select(*keys, "model", "sum_abs_err", "sum_err", "n")
    complete = (
        rows.group_by(keys)
        .agg(pl.col("model").n_unique().alias("_series"))
        .filter(pl.col("_series") == len(SERIES))
        .drop("_series")
    )
    return rows.join(complete, on=keys, how="semi").sort(*keys, "model")


# --- results -----------------------------------------------------------------------------------
def block_bootstrap(days: int, block: int, resamples: int, rng: np.random.Generator) -> np.ndarray:
    """Day indices of ``resamples`` circular moving-block bootstrap samples, each of
    ``days`` days made of blocks of ``block`` consecutive days (wrapping round), shape
    (resamples, days). Our own helper: ``ranking.bootstrap_group`` resamples single
    days, which treats days as independent."""
    block = max(1, min(block, days))
    count = -(-days // block)
    starts = rng.integers(0, days, size=(resamples, count))
    index = (starts[:, :, None] + np.arange(block)[None, None, :]) % days
    return index.reshape(resamples, count * block)[:, :days]


def height_class(dz: pl.Expr) -> pl.Expr:
    """``HEIGHT_CLASSES`` label of |height above the okres's point|."""
    out = pl.lit(None, pl.String)
    for limit, label in reversed(HEIGHT_CLASSES):
        out = pl.when(dz.abs() < limit).then(pl.lit(label)).otherwise(out)
    return out


def strata(stations: pl.DataFrame) -> pl.DataFrame:
    """``station_id``, ``elevation_class`` and ``height`` (``height_class``) of every
    station."""
    points = combine.point_elevations().rename({"code": "okres_code", "elevation": "_point"})
    return (
        stations.select("id", "okres_code", "elevation_class", pl.col("elevation").cast(pl.Float64))
        .join(points, on="okres_code", how="left")
        .select(
            pl.col("id").alias("station_id"),
            "elevation_class",
            height_class(pl.col("elevation") - pl.col("_point")).alias("height"),
        )
    )


GROUP_COLUMNS = [
    "variant", "variable", "lead_day", "stratum", "value", "days", "stations", "n",
    *(f"mae_{s}" for s in SERIES), *(f"bias_{s}" for s in SERIES),
    *(f"{k}_{c}" for c in COMPARED for k in ("diff", "low", "high")),
]  # fmt: skip


def compare(
    days: pl.DataFrame, rng: np.random.Generator, block: int, resamples: int
) -> dict | None:
    """MAE and bias of every series of one group and ``obec`` minus each of
    ``COMPARED`` with its 95 % moving-block interval; ``days``: ``date``, ``model``,
    ``sum_abs_err``, ``sum_err``, ``n`` (summed over the group's stations)."""
    daily = days.group_by("date", "model").agg(
        pl.col("sum_abs_err").sum(), pl.col("sum_err").sum(), pl.col("n").sum()
    )
    wide = {
        c: daily.pivot(on="model", index="date", values=c).sort("date")
        for c in ("sum_abs_err", "sum_err", "n")
    }
    if any(s not in wide["n"].columns for s in SERIES):
        return None
    a = wide["sum_abs_err"].select(SERIES).fill_null(0).to_numpy().astype(float)
    e = wide["sum_err"].select(SERIES).fill_null(0).to_numpy().astype(float)
    m = wide["n"].select(SERIES).fill_null(0).to_numpy().astype(float)
    if m.sum() == 0:
        return None
    mae = a.sum(0) / m.sum(0)
    bias = e.sum(0) / m.sum(0)
    out = {"days": a.shape[0], "mae": mae, "bias": bias, "diff": {}}
    ours = SERIES.index(OBEC)
    if a.shape[0] >= 2:
        index = block_bootstrap(a.shape[0], block, resamples, rng)
        sample = a[index].sum(1) / m[index].sum(1)  # (resamples, series)
    for c in COMPARED:
        j = SERIES.index(c)
        diff = mae[ours] - mae[j]
        if a.shape[0] >= 2:
            low, high = np.percentile(sample[:, ours] - sample[:, j], [2.5, 97.5])
        else:
            low = high = np.nan
        out["diff"][c] = (diff, low, high)
    return out


def _round(value) -> float | None:
    return None if value is None or np.isnan(value) else round(float(value), 3)


def results(
    scored: dict[str, pl.DataFrame],
    stations: pl.DataFrame,
    block: int = BLOCK_DAYS,
    resamples: int = RESAMPLES,
    seed: int = 0,
) -> list[list]:
    """``GROUP_COLUMNS`` rows per variant, variable, lead day (and ``all`` = 1-5 pooled)
    and stratum (``all``; ``elevation_class``; ``height`` above the okres's point)."""
    info = strata(stations)
    rows = []
    for variant, frame in scored.items():
        if frame.is_empty():
            continue
        frame = frame.join(info, on="station_id", how="left").with_columns(
            pl.col("lead_day").cast(pl.String)
        )
        pooled = frame.with_columns(pl.lit("all").alias("lead_day"))
        for (variable, lead), part in sorted(
            pl.concat([frame, pooled]).partition_by(["variable", "lead_day"], as_dict=True).items()
        ):
            groups = [("all", "all", part)]
            for stratum in ("elevation_class", "height"):
                for (value,), sub in sorted(
                    part.drop_nulls(stratum).partition_by(stratum, as_dict=True).items()
                ):
                    groups.append((stratum, value, sub))
            for stratum, value, sub in groups:
                key = f"obce-loso|{variant}|{variable}|{lead}|{stratum}|{value}"
                rng = np.random.default_rng([seed, zlib.crc32(key.encode())])
                got = compare(sub, rng, block, resamples)
                if got is None:
                    continue
                row = [
                    variant, variable, lead, stratum, value, got["days"],
                    sub["station_id"].n_unique(),
                    int(sub.filter(pl.col("model") == OBEC)["n"].sum()),
                    *(_round(v) for v in got["mae"]), *(_round(v) for v in got["bias"]),
                ]  # fmt: skip
                for c in COMPARED:
                    row += [_round(v) for v in got["diff"][c]]
                rows.append(row)
    return rows


STATION_COLUMNS = ["variant", "station_id", "variable", "days", *(f"mae_{s}" for s in SERIES)]


def station_rows(scored: dict[str, pl.DataFrame]) -> list[list]:
    """Per variant, station and variable the MAE of every series over all lead days."""
    rows = []
    for variant, frame in scored.items():
        if frame.is_empty():
            continue
        table = (
            frame.group_by("station_id", "variable", "model")
            .agg(
                (pl.col("sum_abs_err").sum() / pl.col("n").sum()).alias("mae"),
                pl.col("date").n_unique().alias("days"),
            )
            .pivot(on="model", index=["station_id", "variable"], values="mae")
            .join(
                frame.group_by("station_id", "variable").agg(
                    pl.col("date").n_unique().alias("days")
                ),
                on=["station_id", "variable"],
            )
            .sort("station_id", "variable")
        )
        for r in table.iter_rows(named=True):
            rows.append(
                [variant, r["station_id"], r["variable"], r["days"]]
                + [_round(r.get(s)) for s in SERIES]
            )
    return rows


METHOD = (
    "Leave one station out: for every ČHMÚ station the obec forecast (the models at the "
    "place combined with the weights and corrections of its okres, the corrections' "
    "elevation term at the place's own height, as mvd obce-forecast) is rebuilt at the "
    "station with the station removed from the scores, okres pools, regression pairs and "
    "nearest-station baseline it would feed (variant buffer: also every station within "
    "{buffer:.0f} km), trained out of sample (the D+N for day d on the {window} window of "
    "scores up to d - N - 1, at least {min_days} scored days) and scored against the "
    "station: temperature and wind at 00/06/12/18 UTC, precipitation as UTC-day totals, "
    "on the station-days all series have. Series: obec (as the site), obec_point (the "
    "corrections at the okres's forecast point, as the site until 20 Oct 2026), okres "
    "(the same weights at the okres's other stations, averaged: the okres forecast "
    "without downscaling), nearest (the models at the place weighted and bias-corrected "
    "at the nearest remaining station only), median (the plain median of the models). "
    "diff = MAE of obec minus the series (negative: obec better), 95 % interval from "
    "{resamples} circular moving-block bootstrap resamples of {block}-day blocks."
)


def document(
    scored: dict[str, pl.DataFrame],
    groups: list[list],
    stations: pl.DataFrame,
    generated: datetime,
    buffer_km: float = BUFFER_KM,
    window: str = combine.WINDOW,
    min_training_days: int = blendtest.MIN_TRAINING_DAYS,
    block: int = BLOCK_DAYS,
    resamples: int = RESAMPLES,
) -> dict:
    """The published JSON: method, period, counts, the group table and per station."""
    dates = sorted({d for f in scored.values() if f.height for d in f["date"].unique()})
    names = dict(stations.select("id", "name").iter_rows())
    targets = sorted({s for f in scored.values() if f.height for s in f["station_id"].unique()})
    return {
        "generated": generated.isoformat(timespec="seconds"),
        "method": METHOD.format(
            buffer=buffer_km,
            window=window,
            min_days=min_training_days,
            resamples=resamples,
            block=block,
        ),
        "from": str(dates[0]) if dates else None,
        "to": str(dates[-1]) if dates else None,
        "test_days": len(dates),
        "stations": {
            v: {
                variable: f.filter(pl.col("variable") == variable)["station_id"].n_unique()
                for variable in sorted(f["variable"].unique())
            }
            for v, f in scored.items()
            if f.height
        },
        "buffer_km": buffer_km,
        "block_days": block,
        "series": list(SERIES),
        "units": UNITS,
        "height_classes": [label for _, label in HEIGHT_CLASSES],
        "names": {s: names.get(s, s) for s in targets},
        "groups": {"columns": GROUP_COLUMNS, "rows": groups},
        "by_station": {"columns": STATION_COLUMNS, "rows": station_rows(scored)},
    }


def write(doc: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path


def _nan(value: float | None) -> float:
    return float("nan") if value is None else value


def summary(groups: list[list]) -> list[str]:
    """All stations, one line per variant, variable and lead day."""
    at = {c: i for i, c in enumerate(GROUP_COLUMNS)}
    lines = []
    for row in groups:
        if row[at["stratum"]] != "all":
            continue
        text = (
            f"{row[at['variant']]:<6} {row[at['variable']]:<20} D+{row[at['lead_day']]:<3} "
            f"{row[at['days']]:>3} days {row[at['stations']]:>3} st  "
            f"obec {_nan(row[at['mae_obec']]):.3f}"
        )
        for c in COMPARED:
            diff, low, high = (_nan(row[at[f"{k}_{c}"]]) for k in ("diff", "low", "high"))
            text += f"  {c} {_nan(row[at[f'mae_{c}']]):.3f} ({diff:+.3f} [{low:+.3f}, {high:+.3f}])"
        lines.append(text)
    return lines
