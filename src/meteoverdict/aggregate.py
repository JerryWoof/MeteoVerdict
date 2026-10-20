"""Aggregate daily scores per region and time window (roadmap 2.4).

Levels: ``station``, ``okres``, ``kraj``, ``elevation`` (lowland/upland/mountain),
``network`` (``main``: the main WMO stations, open sites with the wind sensor at 10 m;
``other``: all other stations, mostly automatic climate stations, often more sheltered),
``high_sites`` (the high sites below, together) and ``cz`` (all stations). Windows, all
ending at ``as_of`` (the last scored day): ``90d`` (the last 90 days), ``season`` (the
meteorological season so far: DJF, MAM, JJA, SON) and ``all``; and per season over all
years (roadmap 5.1): ``djf``, ``mam``, ``jja`` and ``son``, every day of that season up
to ``as_of`` (their ``from``/``to``: the first and last scored day inside the season's
months).

Fair comparison: for each window, variable, lead day and region, only the station-days
that **every** compared model present in that region has scores for are used. So a
model with gaps (UKMO) does not get easier or harder days than the others, and all
models in a region are compared on the same stations: where a model
cannot reach some stations (ICON-D2 at six stations in the far east), those stations
are left out of that region's comparison for every model, and still compared among the
other models at the station level.
Compared are the models with scores on at least ``MIN_COVERAGE`` (80 %) of the days the
window has scores for that variable and lead day (``coverage``). A model with a shorter
record (one added recently, whose backfill has only reached its newest weeks) would
otherwise cut every model's station-days down to its few days: in October 2026 eight
added models with 10 days cut the 90-day comparison of the others from 40 days to 10.
Such a model gets its own rows with ``short_record`` true, aggregated on its own
station-days among the fair ones of the compared models (so its ``days`` and ``n`` are
smaller); it is not ranked and gets no combination weight until it reaches the
coverage. Where no model reaches it (all records equally patchy), all are compared.
High sites: a station more than ``HIGH_SITE_ABOVE_M`` (300 m) above the median
elevation of its okres's stations (``high_site``: Milešovka 620 m above Litoměřice's,
Lysá hora, Praděd, Sněžka, Klínovec, 47 of 782 stations in October 2026) is left out of
its own okres, and of every okres that would borrow it where it is also that much above
that okres's median (``high_pairs``: Protivanov, 675 m, is high for Prostějov but not
for Blansko, whose stations lie at 300-540 m; since 2026-10-20): 300 m is about 2 °C of
temperature, more than the models differ by, and a summit's wind is another climate
(August-October 2026, D+1: Milešovka had 35 % of Litoměřice's pairs, but 40 % of its
temperature error and 70 % of its wind error). It keeps its own ``station`` rows, is
ranked with the other high sites in ``high_sites`` and stays in the kraj, elevation,
network and Czechia levels, which describe the whole area including its mountains.
Wind-atypical stations (``WIND_ATYPICAL``, ``data/wind-atypical.csv``): the 10 % of the
other stations whose hourly wind deviates most from their neighbours' (sheltered or
exposed) are left out of the okres wind rankings only, as the high sites are from all.
A region needs at least ``MIN_STATIONS`` stations; otherwise ``enough_stations`` is
false and it must not be ranked. An okres with too few stations of its own borrows the
nearest ones of its neighbours (``meteoverdict.neighbours``, roadmap 6.1); ``borrowed``
counts them.

Bias-corrected MAE (``mae_bc``, temperature and wind, all levels but ``station``): how
good a model is once its usual bias is removed, which is what our combined forecast
does (``meteoverdict.mos``). For each pair (station, synoptic hour 00/06/12/18 UTC,
day ``d``, model, lead day N) the bias is the model's mean error at that station and
hour over the ``BIAS_TRAINING_DAYS`` days ending on ``d - N - 1``: only days whose
observations were known when the D+N forecast for ``d`` was made, never ``d`` itself.
Pairs with fewer than ``BIAS_MIN_DAYS`` such days get none, and a station-hour-day
counts only where every compared model has one, so all models are again compared on
the same pairs (from the per-hour score rows ``<variable>_HHutc``, ``scoring``).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from meteoverdict import metrics, neighbours, scoring
from meteoverdict.stations import MAIN_PREFIX

LEVELS = ("station", "okres", "kraj", "elevation", "network", "high_sites", "cz")
#: meteorological seasons and their months
SEASONS = {"djf": (12, 1, 2), "mam": (3, 4, 5), "jja": (6, 7, 8), "son": (9, 10, 11)}
WINDOWS = ("90d", "season", "all", *SEASONS)
MIN_STATIONS = 3
#: a station this far above the median elevation of its okres's stations is a high site:
#: not in any okres's pool, ranked on its own and in the level ``high_sites``
HIGH_SITE_ABOVE_M = 300.0
HIGH_SITES = ("high_sites", "Stanice vysoko nad okresem")
#: wind stations whose wind is not like their neighbours' (the mean absolute deviation of
#: log((v + 0.3) / neighbours' IDW mean) over hourly observations is in the top 10 % of the
#: stations that are not high sites, ``WIND_ATYPICAL_MAD`` or more: sheltered in a valley or
#: town, or exposed on a ridge); in no okres's wind ranking. Versioned list, ``data/``
WIND_ATYPICAL_MAD = 0.73
WIND_ATYPICAL_FILE = Path(__file__).parent / "data" / "wind-atypical.csv"


def load_wind_atypical(path: Path = WIND_ATYPICAL_FILE) -> frozenset[str]:
    return frozenset(pl.read_csv(path)["station_id"].to_list())


WIND_ATYPICAL = load_wind_atypical()
#: a model is compared in a window when it has scores on at least this share of the days
#: the window has scores for (per variable and lead day)
MIN_COVERAGE = 0.8
COVERAGE_KEYS = ["variable", "lead_day", "model"]
_REGION = {
    "station": ("station_id", "station_name"),
    "okres": ("okres_code", "okres"),
    "kraj": ("kraj_code", "kraj"),
    "elevation": ("elevation_class", "elevation_class"),
    "network": ("network", "network"),
}
#: Bias-corrected MAE (``bias_corrected``): of these score variables, from their per-hour
#: rows; the bias of the ``BIAS_TRAINING_DAYS`` days before the forecast was made, with
#: at least ``BIAS_MIN_DAYS`` of them; at every level but ``station`` (file size)
CORRECTED_VARIABLES = scoring.SLOT_VARIABLES
BIAS_TRAINING_DAYS = 30
BIAS_MIN_DAYS = 10
CORRECTED_LEVELS = ("okres", "kraj", "elevation", "network", "cz")
#: per-hour score rows used only for the bias-corrected MAE, not aggregated on their own
#: (the temperature ones are, as before they were used for it)
SLOT_ONLY = tuple(scoring.slot_variable("wind_speed_10m", h) for h in scoring.SYNOPTIC_HOURS)


def season_start(day: date) -> date:
    """First day of the meteorological season containing ``day``."""
    if day.month == 12:
        return date(day.year, 12, 1)
    if day.month <= 2:
        return date(day.year - 1, 12, 1)
    return date(day.year, (day.month // 3) * 3, 1)


def window_start(window: str, as_of: date, first_day: date) -> date:
    """First day of a window: ``90d`` (or any ``<N>d``, the last N days), ``season``
    or ``all``."""
    if window.endswith("d") and window[:-1].isdigit() and int(window[:-1]) > 0:
        return as_of - timedelta(days=int(window[:-1]) - 1)
    if window == "season":
        return season_start(as_of)
    if window == "all":
        return first_day
    raise ValueError(f"unknown window {window!r}")


def window_days(window: str, as_of: date, first_day: date) -> tuple[date, pl.Expr]:
    """First day of a window and the filter on ``date`` that selects its days.

    A season over all years (``djf`` …) has gaps, so its first day here is ``first_day``;
    ``aggregate`` reports the first and last scored day inside its months instead.
    """
    if window in SEASONS:
        months = pl.col("date").dt.month().is_in(SEASONS[window])
        return first_day, pl.col("date").is_between(first_day, as_of) & months
    start = window_start(window, as_of, first_day)
    return start, pl.col("date").is_between(start, as_of)


def common_days(scores: pl.LazyFrame, by: str = "station_id") -> pl.LazyFrame:
    """Keep the station-days every model present in the group ``by`` has scores for.

    Per variable, lead day and group (a station, or ``region`` after
    ``region_columns``), the models compared are those with any score in that group in
    the period; a station-day is kept only if all of them have a score there.
    """
    group = ["variable", "lead_day", by]
    keys = list(dict.fromkeys([*group, "station_id", "date"]))
    models = scores.group_by(group).agg(pl.col("model").n_unique().alias("models"))
    present = (
        scores.group_by(keys)
        .agg(pl.col("model").n_unique().alias("present"))
        .join(models, on=group)
        .filter(pl.col("present") == pl.col("models"))
        .select(keys)
    )
    return scores.join(present, on=keys, how="semi")


def coverage(scores: pl.LazyFrame | pl.DataFrame) -> pl.DataFrame:
    """``variable``, ``lead_day``, ``model``, ``model_days`` (days with a score of that
    model), ``all_days`` (days with any score), ``coverage`` (their ratio) and
    ``covered``: at least ``MIN_COVERAGE``, or no model of the variable and lead day
    reaches it (then all are compared, as without the rule)."""
    group = ["variable", "lead_day"]
    frame = scores.lazy()
    every = frame.group_by(group).agg(pl.col("date").n_unique().alias("all_days"))
    return (
        frame.group_by(COVERAGE_KEYS)
        .agg(pl.col("date").n_unique().alias("model_days"))
        .join(every, on=group)
        .with_columns((pl.col("model_days") / pl.col("all_days")).alias("coverage"))
        .with_columns((pl.col("coverage") >= MIN_COVERAGE).alias("covered"))
        .with_columns(pl.col("covered") | ~pl.col("covered").any().over(group))
        .sort(COVERAGE_KEYS)
        .collect()
    )


def covered_only(
    scores: pl.LazyFrame | pl.DataFrame, cover: pl.DataFrame | None = None
) -> pl.LazyFrame:
    """The rows of the models that are compared (``coverage``; computed from ``scores``
    unless given)."""
    cover = coverage(scores) if cover is None else cover
    keep = cover.filter("covered").select(COVERAGE_KEYS)
    return scores.lazy().join(keep.lazy(), on=COVERAGE_KEYS, how="semi")


def short_records(cover: pl.DataFrame) -> pl.DataFrame:
    """The models left out of the comparison (``coverage`` rows not ``covered``)."""
    return cover.filter(~pl.col("covered"))


def network_class(station_id: pl.Expr) -> pl.Expr:
    """``main`` for a main (synoptic) station with a WMO number (``stations.network``:
    WIGOS ``0-20000-0-<WMO>``), ``other`` for every other station."""
    return (
        pl.when(station_id.str.starts_with(MAIN_PREFIX))
        .then(pl.lit("main"))
        .otherwise(pl.lit("other"))
    )


def with_high_sites(stations: pl.DataFrame) -> pl.DataFrame:
    """``stations`` with ``high_site``: more than ``HIGH_SITE_ABOVE_M`` above the median
    elevation of the stations of its okres (all stations of the table there); false
    without an elevation."""
    if not {"elevation", "okres_code"} <= set(stations.columns):
        return stations.with_columns(pl.lit(False).alias("high_site"))
    elevation = pl.col("elevation").cast(pl.Float64)
    median = elevation.median().over("okres_code")
    return stations.with_columns(
        ((elevation - median) > HIGH_SITE_ABOVE_M).fill_null(False).alias("high_site"),
        median.alias("okres_median_m"),
    )


def high_pairs(in_window: pl.LazyFrame, distance: pl.DataFrame) -> pl.DataFrame | None:
    """``variable``, ``region``, ``station_id``: the stations more than
    ``HIGH_SITE_ABOVE_M`` above the median elevation of an okres whose pool they could
    join (its own, or one within reach that would borrow them), so they are left out of
    that okres only. None without the elevations (``station_info``)."""
    names = in_window.collect_schema().names()
    if not {"elevation", "okres_median_m"} <= set(names):
        return None
    rows = in_window.select("variable", "station_id", "elevation", "okres_code", "okres_median_m")
    rows = rows.unique().collect()
    medians = rows.select(pl.col("okres_code").alias("region"), "okres_median_m").unique("region")
    return (
        rows.select("variable", "station_id", "elevation")
        .unique()
        .join(distance.select("station_id", "region").unique(), on="station_id")
        .join(medians, on="region")
        .filter((pl.col("elevation") - pl.col("okres_median_m")) > HIGH_SITE_ABOVE_M)
        .select("variable", "region", "station_id")
        .cast(pl.String)
    )


def station_info(stations: pl.DataFrame) -> pl.LazyFrame:
    info = with_high_sites(stations)
    # the elevations ``high_pairs`` needs, where the table has them
    heights = [pl.col("elevation").cast(pl.Float64), "okres_median_m"]
    return info.select(
        pl.col("id").alias("station_id"),
        pl.col("name").alias("station_name"),
        "okres_code",
        "okres",
        "kraj_code",
        "kraj",
        "elevation_class",
        network_class(pl.col("id")).alias("network"),
        "high_site",
        pl.col("id").is_in(sorted(WIND_ATYPICAL)).alias("wind_atypical"),
        *(heights if "okres_median_m" in info.columns else []),
    ).lazy()


def region_columns(level: str) -> list[pl.Expr]:
    """``region`` and ``region_name`` for a level (needs the station_info columns)."""
    code, name = _REGION.get(level, (None, None))
    if code:
        return [pl.col(code).alias("region"), pl.col(name).alias("region_name")]
    if level == "high_sites":
        return [pl.lit(HIGH_SITES[0]).alias("region"), pl.lit(HIGH_SITES[1]).alias("region_name")]
    return [pl.lit("cz").alias("region"), pl.lit("Česko").alias("region_name")]


def okres_distances(stations: pl.DataFrame) -> pl.DataFrame | None:
    """Station-to-okres distances for borrowing, or None without station coordinates."""
    if not {"lon", "lat"} <= set(stations.columns):
        return None
    return neighbours.distances(stations)


#: rounds of replacing stations the fair comparison drops (each round is one more scan)
POOL_ROUNDS = 3


def okres_pools(
    in_window: pl.LazyFrame, distance: pl.DataFrame, exclude: pl.DataFrame | None = None
) -> pl.DataFrame:
    """``neighbours.pools`` for the stations with scores in ``in_window``.

    A station counts only if it survives the fair comparison (``common_days``) of the
    compared models (``covered_only``) at the first lead day, where all are present: a
    station that some of the okres's models never reach (fewer models fetched for a rain
    gauge, ICON-D2 in the far east) would otherwise fill a place in the pool and then be
    dropped. Such stations are excluded from that okres and replaced by the next nearest
    ones. ``exclude`` (``variable``, ``region``, ``station_id``) leaves stations out of
    single okresy from the start (``high_pairs``).
    """
    available = in_window.select("variable", "station_id").unique().collect()
    keys = ["variable", "region", "station_id"]
    excluded = pl.DataFrame(schema={k: pl.String for k in keys})
    if exclude is not None:
        excluded = pl.concat([excluded, exclude.select(keys).cast(pl.String)])
    pool = neighbours.pools(distance, available, MIN_STATIONS, exclude=excluded)
    # the models compared (``covered_only``): a model with a short record must not drop
    # the stations it lacks from every okres
    first = covered_only(in_window.filter(pl.col("lead_day") == pl.col("lead_day").min()))
    for _ in range(POOL_ROUNDS):
        joined = first.drop("okres_code", "okres").join(
            pool.lazy(), on=["variable", "station_id"], how="inner"
        )
        kept = common_days(joined, by="region").select(keys).unique().collect()
        short = (
            pool.select("variable", "region")
            .unique()
            .join(kept.group_by("variable", "region").len(), on=["variable", "region"], how="left")
            .filter(pl.col("len").fill_null(0) < MIN_STATIONS)
        )
        dropped = (
            pool.select(keys)
            .join(kept, on=keys, how="anti")
            .join(short, on=["variable", "region"], how="semi")
        )
        if dropped.is_empty():
            break
        excluded = pl.concat([excluded, dropped])
        pool = neighbours.pools(distance, available, MIN_STATIONS, exclude=excluded)
    return pool


def with_regions(
    in_window: pl.LazyFrame,
    level: str,
    distance: pl.DataFrame | None,
    high_sites_in_okres: bool = False,
) -> pl.LazyFrame:
    """Rows of ``in_window`` with ``region``, ``region_name`` and ``borrowed``.

    At the okres level with ``distance`` (from ``okres_distances``), a station's rows
    appear once for every okres whose pool it is in (``neighbours.pools``). The high
    sites are in no okres they stand that high above (``high_pairs``; ``high_site``,
    their own okres, without borrowing or elevations), unless ``high_sites_in_okres``
    (the training of our forecast's regression, ``mos.pools``, which keeps them); the level
    ``high_sites`` has only them. The wind-atypical stations (``wind_atypical``) are in no
    okres's wind pool, on the same terms (and they are in the pools of other variables).
    """
    if (
        level == "okres"
        and not high_sites_in_okres
        and "wind_atypical" in in_window.collect_schema().names()
    ):
        wind = pl.col("variable").str.starts_with("wind_speed_10m")
        in_window = in_window.filter(~(wind & pl.col("wind_atypical")))
    pairs = None
    if level == "okres" and not high_sites_in_okres and distance is not None:
        pairs = high_pairs(in_window, distance)
    if "high_site" in in_window.collect_schema().names():
        if level == "okres" and not high_sites_in_okres and pairs is None:
            in_window = in_window.filter(~pl.col("high_site"))
        elif level == "high_sites":
            in_window = in_window.filter(pl.col("high_site"))
    elif level == "high_sites":
        in_window = in_window.filter(pl.lit(False))
    if level == "okres" and distance is not None:
        pool = okres_pools(in_window, distance, pairs)
        return in_window.drop("okres_code", "okres").join(
            pool.lazy(), on=["variable", "station_id"], how="inner"
        )
    return in_window.with_columns(*region_columns(level), pl.lit(False).alias("borrowed"))


def date_span(scores: pl.LazyFrame) -> tuple[date, date]:
    span = scores.select(pl.col("date").min().alias("first"), pl.col("date").max().alias("last"))
    first_day, last_day = span.collect().row(0)
    if first_day is None:
        raise ValueError("no scores to aggregate")
    return first_day, last_day


def _sum_columns(columns: list[str]) -> list[pl.Expr]:
    counts = [c for t in metrics.THRESHOLDS for c in metrics.counts_columns(t)]
    return [metrics.total(c) for c in (*metrics.SUMS, *counts) if c in columns]


def _metrics(frame: pl.LazyFrame) -> pl.LazyFrame:
    frame = metrics.continuous_scores(frame)
    columns = set(frame.collect_schema().names())
    if {"n_bc", "sum_abs_err_bc"} <= columns:
        n = pl.col("n_bc").cast(pl.Float64)
        frame = frame.with_columns(
            pl.when(n > 0).then(pl.col("sum_abs_err_bc") / n).alias("mae_bc")
        )
    for threshold in metrics.THRESHOLDS:
        if set(metrics.counts_columns(threshold)) <= columns:  # no daily rows, no counts
            frame = metrics.categorical_scores(frame, threshold)
    return frame


def _summary(frame: pl.LazyFrame, columns: list[str]) -> pl.LazyFrame:
    return frame.group_by("region", "region_name", "variable", "lead_day", "model").agg(
        *_sum_columns(columns),
        pl.col("station_id").n_unique().alias("stations"),
        pl.col("station_id").filter("borrowed").n_unique().alias("borrowed"),
        pl.col("date").n_unique().alias("days"),
    )


def slot_errors(scores: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """The error of every pair at a synoptic hour: ``station_id``, ``date``, ``model``,
    ``lead_day``, ``variable`` (of ``CORRECTED_VARIABLES``), ``slot`` (UTC hour) and
    ``error`` (forecast - observed), from the per-hour score rows (one pair each)."""
    names = {
        scoring.slot_variable(v, h): (v, h)
        for v in CORRECTED_VARIABLES
        for h in scoring.SYNOPTIC_HOURS
    }
    variable = pl.col("variable")
    return (
        scores.lazy()
        .filter(variable.is_in(list(names)), pl.col("n") > 0)
        .select(
            "station_id",
            "date",
            "model",
            "lead_day",
            variable.replace_strict({k: v for k, (v, _) in names.items()}).alias("variable"),
            variable.replace_strict(
                {k: h for k, (_, h) in names.items()}, return_dtype=pl.Int8
            ).alias("slot"),
            (pl.col("sum_err").cast(pl.Float64) / pl.col("n").cast(pl.Float64)).alias("error"),
        )
    )


def bias_corrected(
    scores: pl.LazyFrame | pl.DataFrame,
    training_days: int = BIAS_TRAINING_DAYS,
    min_days: int = BIAS_MIN_DAYS,
) -> pl.DataFrame:
    """``slot_errors`` with ``bias`` and ``abs_err_bc`` = |error - bias|: the bias is the
    mean error of the same station, hour, model and lead day N over the
    ``training_days`` days ending on ``date - N - 1`` (the last day whose observations
    were all known when the D+N forecast was made), null with fewer than ``min_days``.
    """
    group = ["station_id", "model", "lead_day", "variable", "slot"]
    errors = slot_errors(scores).collect()
    cumulative = (
        errors.sort([*group, "date"])
        .with_columns(
            pl.col("error").cum_sum().over(group).alias("_sum"),
            pl.int_range(1, pl.len() + 1, dtype=pl.Int64).over(group).alias("_count"),
        )
        .select(*group, "date", "_sum", "_count")
        .sort("date")
    )
    lead = pl.duration(days=pl.col("lead_day").cast(pl.Int64) + 1)
    frame = errors.with_columns((pl.col("date") - lead).cast(pl.Date).alias("_upper"))
    frame = frame.with_columns((pl.col("_upper") - timedelta(days=training_days)).alias("_lower"))

    def upto(frame: pl.DataFrame, on: str, suffix: str) -> pl.DataFrame:
        right = cumulative.rename({"date": on, "_sum": f"_sum{suffix}", "_count": f"_n{suffix}"})
        return frame.sort(on).join_asof(
            right, on=on, by=group, strategy="backward", check_sortedness=False
        )

    frame = upto(upto(frame, "_upper", "_u"), "_lower", "_l")
    days = pl.col("_n_u").fill_null(0) - pl.col("_n_l").fill_null(0)
    total = pl.col("_sum_u").fill_null(0.0) - pl.col("_sum_l").fill_null(0.0)
    bias = pl.when(days >= min_days).then(total / days)
    return (
        frame.with_columns(bias.alias("bias"))
        .with_columns((pl.col("error") - pl.col("bias")).abs().alias("abs_err_bc"))
        .select(*group, "date", "error", "bias", "abs_err_bc")
        .sort([*group, "date"])
    )


def _corrected_sums(fair: pl.LazyFrame, corrected: pl.LazyFrame) -> pl.LazyFrame:
    """``n_bc`` and ``sum_abs_err_bc`` per region, variable, lead day and model: the
    bias-corrected errors of the fair station-days, at the hours every model of the
    station-day has a bias for."""
    keys = ["variable", "lead_day", "station_id", "date"]
    group = ["region", *keys]
    base = fair.filter(pl.col("variable").is_in(CORRECTED_VARIABLES)).select(*group, "model")
    joined = base.join(
        corrected.filter(pl.col("abs_err_bc").is_not_null()).select(
            *keys, "model", "slot", "abs_err_bc"
        ),
        on=[*keys, "model"],
        how="inner",
    )
    need = base.group_by(group).agg(pl.col("model").n_unique().alias("_models"))
    full = (
        joined.group_by([*group, "slot"])
        .agg(pl.col("model").n_unique().alias("_have"))
        .join(need, on=group)
        .filter(pl.col("_have") == pl.col("_models"))
        .select(*group, "slot")
    )
    return (
        joined.join(full, on=[*group, "slot"], how="semi")
        .group_by("region", "variable", "lead_day", "model")
        .agg(pl.len().alias("n_bc"), pl.col("abs_err_bc").sum().alias("sum_abs_err_bc"))
    )


def aggregate(
    scores: pl.LazyFrame | pl.DataFrame,
    stations: pl.DataFrame,
    as_of: date | None = None,
    windows: tuple[str, ...] = WINDOWS,
    levels: tuple[str, ...] = LEVELS,
    corrected: bool = True,
) -> pl.DataFrame:
    """One row per level, region, window, variable, lead day and model.

    ``corrected``: also the bias-corrected MAE (``bias_corrected``, ``mae_bc``).

    ``coverage``: the model's share of the window's scored days; ``short_record``: below
    ``MIN_COVERAGE``, so not compared (its rows cover only its own station-days among the
    fair ones of the compared models)."""
    scores = scores.lazy()
    first_day, last_day = date_span(scores)
    as_of = as_of or last_day
    info = station_info(stations)
    distance = okres_distances(stations)
    columns = scores.collect_schema().names()
    corrected = bias_corrected(scores.filter(pl.col("date") <= as_of)).lazy() if corrected else None
    if corrected is not None and not corrected.select(pl.len()).collect().item():
        corrected = None
    scores = scores.filter(~pl.col("variable").is_in(SLOT_ONLY))
    frames = []
    for window in windows:
        start, days = window_days(window, as_of, first_day)
        in_window = scores.filter(days).join(info, on="station_id", how="inner")
        cover = coverage(in_window)
        short = short_records(cover).select(COVERAGE_KEYS)
        # the window may start before the first scored day
        span = (max(start, first_day), as_of)
        if window in SEASONS:  # e.g. jja in October: its last scored day is 31 Aug
            dates = pl.col("date")
            span = in_window.select(dates.min().alias("from"), dates.max().alias("to"))
            span = span.collect().row(0)
        stamp = [
            pl.lit(window).alias("window"),
            pl.lit(span[0], pl.Date).alias("from"),
            pl.lit(span[1], pl.Date).alias("to"),
        ]
        share = cover.lazy().select(*COVERAGE_KEYS, "coverage")
        for level in levels:
            regions = with_regions(in_window, level, distance)
            fair = common_days(covered_only(regions, cover), by="region")
            summary = _summary(fair, columns)
            if corrected is not None and level in CORRECTED_LEVELS:
                sums = _corrected_sums(fair, corrected)
                summary = summary.join(
                    sums, on=["region", "variable", "lead_day", "model"], how="left"
                )
            parts = [summary.with_columns(pl.lit(False).alias("short_record"))]
            if short.height:  # each on its own station-days among the fair ones
                keys = ["variable", "lead_day", "region", "station_id", "date"]
                own = regions.join(short.lazy(), on=COVERAGE_KEYS, how="semi").join(
                    fair.select(keys).unique(), on=keys, how="semi"
                )
                parts.append(
                    _summary(own, columns).with_columns(pl.lit(True).alias("short_record"))
                )
            frames += [
                part.join(share, on=COVERAGE_KEYS, how="left").with_columns(
                    pl.lit(level).alias("level"), *stamp
                )
                for part in parts
            ]
    out = _metrics(pl.concat(frames, how="diagonal_relaxed")).with_columns(
        ((pl.col("level") == "station") | (pl.col("stations") >= MIN_STATIONS)).alias(
            "enough_stations"
        )
    )
    first = ["level", "region", "region_name", "window", "from", "to", "variable", "lead_day"]
    return out.collect().select(pl.col(first), pl.exclude(first)).sort([*first, "model"])


#: Columns published in the JSON files (the additive sums stay in Parquet).
JSON_COLUMNS = (
    "region",
    "region_name",
    "lead_day",
    "model",
    "stations",
    "borrowed",
    "days",
    "n",
    "mae",
    "bias",
    "rmse",
    "pod_0p1",
    "far_0p1",
    "ets_0p1",
    "pod_5",
    "far_5",
    "ets_5",
    "pod_20",
    "far_20",
    "ets_20",
    "pod_30",
    "far_30",
    "ets_30",
    "enough_stations",
    "rank",
    "diff_ci_low",
    "diff_ci_high",
    "tied_with_best",
    "clear_winner",
    # added later: the share of the window's scored days a model has, and whether that
    # is below MIN_COVERAGE (not compared, not ranked: a newly added model)
    "coverage",
    "short_record",
    # added in October 2026: event skill at 1 and 10 mm a day, and the MAE once each
    # model's usual bias at the station and hour is removed (``bias_corrected``)
    "pod_1",
    "far_1",
    "ets_1",
    "pod_10",
    "far_10",
    "ets_10",
    "mae_bc",
    # added with the block bootstrap (October 2026): the probability of being the best
    # model, the Diebold-Mariano p-value against the best one and the small-sample flag
    "p_best",
    "dm_p",
    "small_sample",
)


#: Left out of the station-level JSON (its largest files; ``aggregates.parquet`` keeps
#: them): the event scores at 1 and 10 mm, which the pages show for regions only
STATION_LEFT_OUT = ("pod_1", "far_1", "ets_1", "pod_10", "far_10", "ets_10")


def write_json(table: pl.DataFrame, out_dir: Path, meta: dict) -> list[Path]:
    """Write ``out_dir/meta.json`` and ``out_dir/<window>/<level>/<variable>.json``.

    Each data file is ``{"columns": [...], "rows": [[...], ...]}`` with floats rounded to
    3 decimals, small enough for a static web page. Columns that are empty in a file
    (e.g. event scores for temperature) are left out, and so is the native-period
    precipitation, whose periods differ between models (``aggregates.parquet`` keeps it),
    and ``STATION_LEFT_OUT`` at the station level.
    """
    written = []
    out_dir.mkdir(parents=True, exist_ok=True)
    table = table.filter(pl.col("variable") != "precipitation")
    groups = table.partition_by(["window", "level", "variable"], as_dict=True)
    for (window, level, variable), part in sorted(groups.items()):
        columns = [
            c
            for c in JSON_COLUMNS
            if c in part.columns
            and (c == "region" or part[c].null_count() < part.height)
            and not (level == "station" and c in STATION_LEFT_OUT)
        ]
        rows = part.select(
            pl.col(c).round(3) if part.schema[c].is_float() else pl.col(c) for c in columns
        ).rows()
        path = out_dir / window / level / f"{variable}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"columns": columns, "rows": rows}, ensure_ascii=False, separators=(",", ":")
            ),
            encoding="utf-8",
        )
        written.append(path)
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), "utf-8")
    return [meta_path, *written]


def excluded(table: pl.DataFrame) -> dict[str, dict[str, dict]]:
    """The models left out of each window's comparison for too short a record:
    ``{window: {model: {"coverage": highest share of the scored days, "days": most days,
    "variables": [score variables where it is left out at some lead day]}}}`` (Czechia
    rows, without the native-period precipitation, which is not published)."""
    if "short_record" not in table.columns:
        return {}
    rows = (
        table.filter(
            pl.col("short_record"), pl.col("level") == "cz", pl.col("variable") != "precipitation"
        )
        .group_by("window", "model")
        .agg(
            pl.col("coverage").max(),
            pl.col("days").max(),
            pl.col("variable").unique().sort().alias("variables"),
        )
        .sort("window", "model")
    )
    out: dict[str, dict[str, dict]] = {}
    for r in rows.iter_rows(named=True):
        out.setdefault(r["window"], {})[r["model"]] = {
            "coverage": round(r["coverage"], 3),
            "days": r["days"],
            "variables": r["variables"],
        }
    return out


def metadata(table: pl.DataFrame, models: dict[str, str], generated: datetime) -> dict:
    from meteoverdict import ranking  # ranking imports this module

    windows = table.select("window", "from", "to").unique().sort("window").rows(named=True)
    return {
        "generated": generated.isoformat(timespec="seconds"),
        "as_of": str(table["to"].max()),
        "windows": {w["window"]: {"from": str(w["from"]), "to": str(w["to"])} for w in windows},
        "levels": list(LEVELS),
        "variables": sorted(table["variable"].unique().to_list()),
        "models": models,
        "min_stations": MIN_STATIONS,
        "borrow_max_km": neighbours.MAX_KM,
        "precipitation_thresholds_mm": list(metrics.PRECIPITATION_THRESHOLDS),
        "heat_thresholds_c": list(metrics.HEAT_THRESHOLDS),
        "fair_comparison": (
            "per window, variable and lead day only station-days all compared models cover; "
            f"compared are the models with scores on at least {MIN_COVERAGE:.0%} of the "
            "window's scored days, the others (short_record, e.g. newly added models) are "
            "shown on their own station-days and not ranked"
        ),
        "min_coverage": MIN_COVERAGE,
        "networks": {
            "main": "main (synoptic) stations with a WMO number: open sites, wind at 10 m",
            "other": "all other stations, mostly automatic climate stations",
        },
        "bias_corrected": (
            "mae_bc: MAE after removing each model's own bias at the station and synoptic "
            f"hour, estimated on the {BIAS_TRAINING_DAYS} days before the forecast was made "
            f"(at least {BIAS_MIN_DAYS}); only pairs where every compared model has one"
        ),
        "short_record": excluded(table),
        "ranking": (
            "by MAE; 95 % moving-block bootstrap interval of the MAE difference to the best "
            f"model (blocks of {ranking.BLOCK_DAYS} consecutive days); tied_with_best unless "
            "that interval excludes 0 and the Diebold-Mariano test (Newey-West variance, "
            f"{ranking.DM_LAGS} lags) gives dm_p < {ranking.DM_ALPHA}; clear_winner when "
            "nobody is tied; p_best: share of the resamples in which the model has the "
            f"lowest MAE, the map names a winner only from {ranking.P_BEST_MIN}; "
            f"small_sample: fewer than {ranking.SMALL_SAMPLE_DAYS} days; the blend (mean of "
            "all models) is not ranked, its difference and interval are relative to the "
            "best single model"
        ),
        "p_best_min": ranking.P_BEST_MIN,
        "small_sample_days": ranking.SMALL_SAMPLE_DAYS,
        "block_days": ranking.BLOCK_DAYS,
        "high_sites": (
            f"stations more than {HIGH_SITE_ABOVE_M:.0f} m above the median elevation of "
            "their okres's stations: in no okres's ranking, ranked on their own (station "
            "level) and together (level high_sites); still in kraj, elevation, network, cz"
        ),
        "high_site_above_m": HIGH_SITE_ABOVE_M,
        "wind_atypical": (
            f"{len(WIND_ATYPICAL)} stations whose wind differs most from their neighbours' "
            f"(mean absolute log deviation {WIND_ATYPICAL_MAD} or more): left out of the "
            "okres wind rankings, in all other levels"
        ),
        "licence": "CC BY-SA 4.0, https://creativecommons.org/licenses/by-sa/4.0/",
        "attribution": (
            "Observations: ČHMÚ (opendata.chmi.cz, CC BY 4.0). Forecasts: Open-Meteo.com "
            "(CC BY 4.0) from DWD, ECMWF, NOAA, Météo-France, GeoSphere Austria, KNMI, DMI, "
            "ČHMÚ, Environment and Climate Change Canada, the Japan Meteorological Agency, "
            "the China Meteorological Administration and the UK Met Office (CC BY-SA 4.0). "
            "Boundaries: ČÚZK (CC BY 4.0)."
        ),
    }


#: Station columns for the web map's dots (``stations.json``); ``high_site`` (added in
#: October 2026) marks the stations left out of the okresy
STATION_COLUMNS = (
    "id", "name", "lat", "lon", "elevation", "okres_code", "kraj_code", "active", "high_site",
)  # fmt: skip


def write_stations(stations: pl.DataFrame, out_dir: Path) -> Path:
    """``out_dir/stations.json``: position and region of every station, same layout."""
    stations = with_high_sites(stations)
    columns = [c for c in STATION_COLUMNS if c in stations.columns]
    rows = stations.select(
        pl.col(c).round(5) if stations.schema[c].is_float() else pl.col(c) for c in columns
    ).rows()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "stations.json"
    doc = {"columns": columns, "rows": rows}
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path


#: Daily error series per station for the web map's charts (roadmap 4.4)
SERIES_DAYS = 90
SERIES_LEAD_DAYS = (1, 2)


def write_series(
    scores: pl.LazyFrame | pl.DataFrame,
    out_dir: Path,
    as_of: date,
    variables: tuple[str, ...],
) -> list[Path]:
    """``out_dir/series/<station>.json``: each model's daily MAE over the last 90 days.

    ``{"from": …, "to": …, "series": {variable: {lead day: {model: [MAE or null]}}}}``,
    one value per day, rounded to 2 decimals; D+1 and D+2 only, to keep the files small.
    """
    first = as_of - timedelta(days=SERIES_DAYS - 1)
    daily = (
        scores.lazy()
        .filter(
            pl.col("date").is_between(first, as_of),
            pl.col("lead_day").is_in(SERIES_LEAD_DAYS),
            pl.col("variable").is_in(variables),
        )
        .group_by("station_id", "variable", "lead_day", "model", "date")
        .agg((metrics.total("sum_abs_err") / metrics.total("n")).alias("mae"))
        .collect()
    )
    days = [first + timedelta(days=i) for i in range(SERIES_DAYS)]
    folder = out_dir / "series"
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for (station,), part in daily.partition_by("station_id", as_dict=True).items():
        series: dict = {}
        groups = part.partition_by(["variable", "lead_day", "model"], as_dict=True)
        for (variable, lead_day, model), rows in sorted(groups.items()):
            values = dict(zip(rows["date"], rows["mae"], strict=True))
            series.setdefault(variable, {}).setdefault(str(lead_day), {})[model] = [
                None if values.get(d) is None else round(values[d], 2) for d in days
            ]
        doc = {"from": str(first), "to": str(as_of), "series": series}
        path = folder / f"{station}.json"
        path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        written.append(path)
    return written
