"""Regression blend of temperature and wind ("MOS"), from station-level errors.

For temperature and wind ``meteoverdict.combine`` replaces the plain inverse-error
weights with a small model output statistics step, fitted every day on the forecast and
observation pairs of the last ``WINDOW_DAYS`` days at 00, 06, 12 and 18 UTC (the hours
every model has natively), separately for every variable and lead day N:

1. **Training rows**: station x slot (00/06/12/18 UTC) x day, for the days up to the
   last scored one, only the models with a value in at least ``MIN_COVERAGE`` of the
   rows and only the rows where all of those have one. An okres uses the stations of
   its pool (its own and, with fewer than three, borrowed ones, as in the ranking).
   ``D`` = the number of days with rows.
2. **Hour-of-day bias** per okres g, slot h and model m, shrunk towards the okres's
   all-hours bias with ``SLOT_SHRINK_DAYS``: ``B = (D b_ghm + k b_gm) / (D + k)``
   (errors are forecast minus observed).
3. **Elevation term**: ``dz`` = (station elevation - mean elevation of the okres's
   stations) / 100 m; the residual error left after step 2 regressed on ``dz``
   through the origin, nationally per slot and model: ``beta_hm``. The correction at
   a place of the okres is ``C = B_ghm + beta_hm dz``.
4. **Weights**: ridge regression of the observations on the corrected forecasts
   ``f - C`` with the weights summing to 1, first nationally (prior ``1 / M``,
   ridge ``NATIONAL_RIDGE * n``), then per okres on its rows with the national weights
   as the prior (ridge ``OKRES_RIDGE * n_g``). Weights may be negative.
5. **Forecast**: ``sum_m w_gm (f_m - D / (D + 5) C_ghm)``, wind not below 0. Between
   the four slots the correction is interpolated linearly in UTC hour. At the okres's
   forecast point the elevation term counts half (``combine.POINT_LAPSE_FACTOR``).
6. **Guard (wind)**: an okres whose regression, fitted without the last
   ``GUARD_DAYS`` days of the window, did worse on them than the method before keeps
   the method before (``worse_than_before``): okresy whose stations span very
   different heights (Chomutov with Klínovec) lost up to a third without it.

Out of sample (rolling origin, 11-30 Sep 2026, research report in the PR) this cut the
MAE of the okres combination by about 7 % for temperature and 11 % for wind against the
inverse-error weights with an all-hours bias. The fit is a few small linear systems.

When it cannot be used, ``combine`` falls back: with too few days (``MIN_DAYS``), no
rows in an okres or a guarded okres to the inverse-error weights of the okres scores
with an all-hours bias (the method before); at an hour where one of the regression's
models has no value (or fades out) to those inverse-error weights with the slot and
elevation corrections above (renormalised over the models present).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from meteoverdict import aggregate, observations, partitions

VARIABLES = ("temperature_2m", "wind_speed_10m")
SLOTS = (0, 6, 12, 18)
WINDOW_DAYS = 90
#: shrinkage of the hour-of-day bias towards the all-hours bias, in days
SLOT_SHRINK_DAYS = 10
#: shrinkage of the whole correction towards none (as ``combine.BIAS_SHRINK_DAYS``)
BIAS_SHRINK_DAYS = 5
#: ridge penalty per training row towards equal weights (national fit) ...
NATIONAL_RIDGE = 0.1
#: ... and towards the national weights (okres fit)
OKRES_RIDGE = 1.0
#: a model takes part when it has a value in this share of the training rows
MIN_COVERAGE = 0.8
#: fewer training days: no regression, the inverse-error weights of the okres scores
MIN_DAYS = 14
#: per okres, the regression falls back to the method before it where it did worse on
#: the last GUARD_DAYS days of its window (fitted without them); for wind, where a few
#: okresy with stations at very different heights (Chomutov with Klínovec) lost
GUARD_VARIABLES = ("wind_speed_10m",)
GUARD_DAYS = 7
NON_NEGATIVE = ("wind_speed_10m",)
#: elevation differences are counted in steps of this many metres
ELEVATION_STEP_M = 100.0
#: columns of the coefficient table (``Fit.frame``), besides region/variable/lead_day/model
SLOT_NAMES = tuple(f"{h:02d}" for h in SLOTS)
BIAS_COLUMNS = tuple(f"bias_{s}" for s in SLOT_NAMES)
LAPSE_COLUMNS = tuple(f"lapse_{s}" for s in SLOT_NAMES)
COEFFICIENT_COLUMNS = (
    "mos_weight",
    "mos_models",
    "mos_days",
    *BIAS_COLUMNS,
    *LAPSE_COLUMNS,
    "station_elevation",
    "dz_min",
    "dz_max",
)


def pairs(
    observations: pl.LazyFrame | pl.DataFrame,
    fc: pl.LazyFrame | pl.DataFrame,
    first: date,
    last: date,
) -> pl.DataFrame:
    """Forecast-observation pairs of temperature and wind at 00/06/12/18 UTC on the
    days ``first`` … ``last``: ``variable``, ``station_id``, ``date``, ``slot`` (0-3),
    ``lead_day``, ``model``, ``forecast``, ``observed``. Every model is native at these
    hours (``align.pairs`` keeps the same ones)."""
    hour = pl.col("time").dt.hour()
    span = pl.col("time").dt.date().is_between(first, last)
    keys = ["station_id", "time", "model", "lead_day"]
    forecast = (
        fc.lazy()
        .filter(span, hour.is_in(SLOTS), pl.col("model") != "blend")
        .select(*keys, *VARIABLES)
        .unpivot(index=keys, on=list(VARIABLES), variable_name="variable", value_name="forecast")
        .drop_nulls("forecast")
    )
    observed = (
        observations.lazy()
        .filter(pl.col("variable").is_in(VARIABLES), span, hour.is_in(SLOTS))
        .select("station_id", "time", "variable", pl.col("value").alias("observed"))
        .drop_nulls("observed")
        .unique(["station_id", "time", "variable"], keep="last")
    )
    return (
        forecast.join(observed, on=["station_id", "time", "variable"])
        .select(
            "variable",
            "station_id",
            pl.col("time").dt.date().alias("date"),
            (hour // 6).cast(pl.Int8).alias("slot"),
            pl.col("lead_day").cast(pl.Int8),
            "model",
            pl.col("forecast").cast(pl.Float32),
            pl.col("observed").cast(pl.Float32),
        )
        .collect()
    )


def pools(scores: pl.LazyFrame | pl.DataFrame, stations: pl.DataFrame) -> pl.DataFrame:
    """The stations of every okres per variable (``variable``, ``region``,
    ``region_name``, ``station_id``): its own and borrowed ones, as in the ranking, but
    with the high sites (``aggregate.with_high_sites``), on which the regression was
    tested and which the elevation term helps most."""
    in_period = scores.lazy().join(aggregate.station_info(stations), on="station_id")
    distance = aggregate.okres_distances(stations)
    return (
        aggregate.with_regions(in_period, "okres", distance, high_sites_in_okres=True)
        .select("variable", "region", "region_name", "station_id")
        .unique()
        .collect()
    )


def own_okres(stations: pl.DataFrame) -> pl.DataFrame:
    """Pools of only the stations' own okres (for both variables)."""
    own = stations.select(
        pl.col("okres_code").alias("region"),
        pl.col("okres").alias("region_name"),
        pl.col("id").alias("station_id"),
    )
    return pl.concat([own.with_columns(pl.lit(v).alias("variable")) for v in VARIABLES])


@dataclass
class Table:
    """Pairs of one variable and lead day, one row per okres x station x day x slot."""

    variable: str
    lead_day: int
    models: list[str]
    forecast: np.ndarray  # rows x models, nan where a model has no value
    observed: np.ndarray
    day: np.ndarray  # days since 1970-01-01
    slot: np.ndarray  # 0-3
    okres: np.ndarray  # index into okresy
    okresy: list[str]
    dz: np.ndarray  # (station elevation - okres mean) / ELEVATION_STEP_M
    elevation: np.ndarray  # mean station elevation of each okres
    station: list[str]

    @property
    def size(self) -> int:
        return len(self.observed)


def tables(
    pair_rows: pl.DataFrame, okres_pools: pl.DataFrame, stations: pl.DataFrame
) -> dict[tuple[str, int], Table]:
    """``Table`` per variable and lead day from ``pairs`` rows and okres pools."""
    # a station without an elevation counts as at the okres mean (no elevation term)
    height = pl.col("elevation") if "elevation" in stations.columns else pl.lit(None)
    elevation = stations.select(
        pl.col("id").alias("station_id"), height.cast(pl.Float64).alias("elevation")
    )
    out = {}
    for (variable, lead), part in sorted(
        pair_rows.partition_by(["variable", "lead_day"], as_dict=True).items()
    ):
        pool = (
            okres_pools.filter(pl.col("variable") == variable)
            .select("region", "station_id")
            .join(elevation, on="station_id")
        )
        if pool.is_empty():
            continue
        # the okres mean over its stations (each once), then dz of every member
        pool = (
            pool.with_columns(
                pl.col("elevation").mean().over("region").fill_null(0.0).alias("okres_elevation")
            )
            .with_columns(pl.col("elevation").fill_null(pl.col("okres_elevation")))
            .with_columns(
                ((pl.col("elevation") - pl.col("okres_elevation")) / ELEVATION_STEP_M).alias("dz")
            )
        )
        models = sorted(part["model"].unique().to_list())
        keys = ["station_id", "date", "slot"]
        wide = (
            part.pivot(on="model", index=[*keys, "observed"], values="forecast")
            .join(pool, on="station_id")
            .sort("region", "station_id", "date", "slot")
        )
        if wide.is_empty():
            continue
        okresy = sorted(wide["region"].unique().to_list())
        index = {code: i for i, code in enumerate(okresy)}
        means = dict(pool.select("region", "okres_elevation").unique().iter_rows())
        out[(variable, int(lead))] = Table(
            variable=variable,
            lead_day=int(lead),
            models=models,
            forecast=wide.select(models).to_numpy().astype(np.float64),
            observed=wide["observed"].to_numpy().astype(np.float64),
            day=wide["date"].cast(pl.Int32).to_numpy(),
            slot=wide["slot"].to_numpy().astype(np.int64),
            okres=np.array([index[c] for c in wide["region"].to_list()], dtype=np.int64),
            okresy=okresy,
            dz=wide["dz"].to_numpy().astype(np.float64),
            elevation=np.array([means[c] for c in okresy], dtype=np.float64),
            station=wide["station_id"].to_list(),
        )
    return out


def _group_mean(index: np.ndarray, groups: int, values: np.ndarray) -> np.ndarray:
    """Mean of ``values`` (rows x M) per group; nan for empty groups."""
    count = np.bincount(index, minlength=groups).astype(float)
    columns = range(values.shape[1])
    total = np.stack(
        [np.bincount(index, weights=values[:, m], minlength=groups) for m in columns], axis=1
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        return total / count[:, None]


def solve(x: np.ndarray, y: np.ndarray, prior: np.ndarray, ridge: float) -> np.ndarray:
    """``argmin |y - x w|² + ridge |w - prior|²`` subject to ``sum(w) = 1`` (the KKT
    system of the equality-constrained ridge regression)."""
    m = x.shape[1]
    kkt = np.zeros((m + 1, m + 1))
    kkt[:m, :m] = x.T @ x + ridge * np.eye(m)
    kkt[:m, m] = 1.0
    kkt[m, :m] = 1.0
    rhs = np.r_[x.T @ y + ridge * prior, 1.0]
    return np.linalg.solve(kkt, rhs)[:m]


@dataclass
class Fit:
    """The regression of one variable and lead day, fitted on days up to ``end``."""

    variable: str
    lead_day: int
    models: list[str]
    days: int
    okresy: list[str]
    fitted: np.ndarray  # okresy with training rows (bool)
    bias: np.ndarray  # okresy x 4 x models, B_ghm (not shrunk)
    lapse: np.ndarray  # okresy x 4 x models, beta per ELEVATION_STEP_M
    weights: np.ndarray  # okresy x models
    national: np.ndarray  # models
    elevation: np.ndarray  # okresy
    dz_range: np.ndarray  # okresy x 2, the training range of dz

    @property
    def shrink(self) -> float:
        return self.days / (self.days + BIAS_SHRINK_DAYS)

    def correction(self, okres: np.ndarray, slot: np.ndarray, dz: np.ndarray) -> np.ndarray:
        """``D / (D + 5) (B_ghm + beta_hm dz)`` for rows (rows x models)."""
        lo, hi = self.dz_range[okres, 0], self.dz_range[okres, 1]
        dz = np.clip(dz, lo, hi)
        return self.shrink * (self.bias[okres, slot] + self.lapse[okres, slot] * dz[:, None])

    def predict(
        self, forecast: np.ndarray, okres: np.ndarray, slot: np.ndarray, dz: np.ndarray
    ) -> np.ndarray:
        """Combined forecast for rows with a value of every model (``forecast`` columns
        in the order of ``models``)."""
        value = (self.weights[okres] * (forecast - self.correction(okres, slot, dz))).sum(1)
        return np.clip(value, 0, None) if self.variable == "wind_speed_10m" else value

    def frame(self) -> pl.DataFrame:
        """One row per fitted okres and model: ``region``, ``variable``, ``lead_day``,
        ``model`` and ``COEFFICIENT_COLUMNS`` (bias and lapse already shrunk by
        ``D / (D + 5)``; the correction at elevation z and slot h is
        ``bias_h + lapse_h * clip((z - station_elevation) / 100, dz_min, dz_max)``)."""
        rows = []
        s = self.shrink
        for g, code in enumerate(self.okresy):
            if not self.fitted[g]:
                continue
            for m, model in enumerate(self.models):
                rows.append(
                    (
                        code, self.variable, self.lead_day, model,
                        float(self.weights[g, m]), len(self.models), self.days,
                        *(float(s * self.bias[g, h, m]) for h in range(4)),
                        *(float(s * self.lapse[g, h, m]) for h in range(4)),
                        float(self.elevation[g]),
                        float(self.dz_range[g, 0]), float(self.dz_range[g, 1]),
                    )
                )  # fmt: skip
        schema = {
            "region": pl.String,
            "variable": pl.String,
            "lead_day": pl.Int8,
            "model": pl.String,
            **{c: pl.Float64 for c in COEFFICIENT_COLUMNS},
        }
        schema["mos_models"] = pl.Int16
        schema["mos_days"] = pl.Int16
        return pl.DataFrame(rows, schema=schema, orient="row")


def fit(
    table: Table,
    end: int,
    window: int = WINDOW_DAYS,
    models: list[str] | None = None,
    allowed: set[str] | None = None,
    min_days: int = MIN_DAYS,
    guard: bool = True,
) -> Fit | None:
    """The regression on the rows of the ``window`` days ending on day ``end`` (days
    since 1970-01-01). ``models``: use exactly these (else those with
    ``MIN_COVERAGE``, among ``allowed`` if given). None with fewer than ``min_days``
    days or two models."""
    in_window = (table.day <= end) & (table.day > end - window)
    if not in_window.any():
        return None
    f = table.forecast[in_window]
    if models is None:
        coverage = (~np.isnan(f)).mean(0)
        cols = [
            i
            for i, m in enumerate(table.models)
            if coverage[i] >= MIN_COVERAGE and (allowed is None or m in allowed)
        ]
    else:
        index = {m: i for i, m in enumerate(table.models)}
        if any(m not in index for m in models):
            return None
        cols = [index[m] for m in models]
    if len(cols) < 2:
        return None
    rows = np.where(in_window)[0]
    rows = rows[~np.isnan(table.forecast[np.ix_(rows, cols)]).any(1)]
    days = len(np.unique(table.day[rows]))
    if days < min_days:
        return None
    x = table.forecast[np.ix_(rows, cols)]
    y = table.observed[rows]
    g, h, dz = table.okres[rows], table.slot[rows], table.dz[rows]
    n_okresy, n_models = len(table.okresy), len(cols)
    error = x - y[:, None]
    # 1. hour-of-day bias shrunk towards the all-hours bias of the okres
    b_g = _group_mean(g, n_okresy, error)
    b_gh = _group_mean(g * 4 + h, n_okresy * 4, error).reshape(n_okresy, 4, n_models)
    b_gh = np.where(np.isnan(b_gh), b_g[:, None, :], b_gh)
    k = SLOT_SHRINK_DAYS
    bias = (days * b_gh + k * b_g[:, None, :]) / (days + k)
    # 2. national elevation term per slot and model
    residual = error - bias[g, h]
    lapse_cz = np.zeros((4, n_models))
    for slot in range(4):
        at = h == slot
        z = dz[at]
        lapse_cz[slot] = (z[:, None] * residual[at]).sum(0) / ((z**2).sum() + 1e-9)
    # one for all okresy: fitted per okres it would mostly learn its few stations, which
    # does not carry over to the okres's forecast point
    lapse = np.repeat(lapse_cz[None], n_okresy, 0)
    corrected = x - (bias[g, h] + lapse[g, h] * dz[:, None])
    # 3. constrained ridge regression: national, then per okres towards it
    national = solve(corrected, y, np.full(n_models, 1 / n_models), NATIONAL_RIDGE * len(y))
    weights = np.tile(national, (n_okresy, 1))
    fitted = np.zeros(n_okresy, bool)
    dz_range = np.zeros((n_okresy, 2))
    for okres in np.unique(g):
        at = g == okres
        weights[okres] = solve(corrected[at], y[at], national, OKRES_RIDGE * at.sum())
        fitted[okres] = True
        dz_range[okres] = dz[at].min(), dz[at].max()
    result = Fit(
        variable=table.variable,
        lead_day=table.lead_day,
        models=[table.models[i] for i in cols],
        days=days,
        okresy=table.okresy,
        fitted=fitted,
        bias=np.nan_to_num(bias),
        lapse=lapse,
        weights=weights,
        national=national,
        elevation=table.elevation,
        dz_range=dz_range,
    )
    if guard and table.variable in GUARD_VARIABLES:
        result.fitted &= ~worse_than_before(table, end, result.models, window, min_days)
    return result


def inverse_error(
    x: np.ndarray, y: np.ndarray, okres: np.ndarray, okresy: int, days: int
) -> tuple[np.ndarray, np.ndarray]:
    """The method before the regression, from pairs: per okres inverse error-variance
    weights shrunk towards equal with 30 days and the all-hours bias shrunk with 5 days
    (as ``combine.weights`` from the okres scores). ``(weights, corrections)``, okresy x
    models."""
    error = x - y[:, None]
    bias = np.nan_to_num(_group_mean(okres, okresy, error))
    square = np.nan_to_num(_group_mean(okres, okresy, error**2))
    inverse = 1 / np.maximum(square - bias**2, 0.01)
    s = days / (days + 30)
    weights = s * inverse / inverse.sum(1, keepdims=True) + (1 - s) / x.shape[1]
    return weights, days / (days + BIAS_SHRINK_DAYS) * bias


def worse_than_before(
    table: Table, end: int, models: list[str], window: int, min_days: int
) -> np.ndarray:
    """Okresy (bool per ``table.okresy``) where the regression did worse than the method
    before it on the last ``GUARD_DAYS`` days of the window, both fitted on the days
    before them (out of sample). False everywhere when that inner fit is not possible."""
    worse = np.zeros(len(table.okresy), bool)
    inner_end = end - GUARD_DAYS
    inner = fit(table, inner_end, window, models=models, min_days=min_days, guard=False)
    if inner is None:
        return worse
    cols = [table.models.index(m) for m in models]

    def complete(first: int, last: int) -> np.ndarray:
        rows = np.where((table.day > first) & (table.day <= last))[0]
        return rows[~np.isnan(table.forecast[np.ix_(rows, cols)]).any(1)]

    train, check = complete(inner_end - window, inner_end), complete(inner_end, end)
    if len(check) == 0:
        return worse
    n = len(table.okresy)
    weights, corrections = inverse_error(
        table.forecast[np.ix_(train, cols)], table.observed[train], table.okres[train], n,
        len(np.unique(table.day[train])),
    )  # fmt: skip
    x, y, g = table.forecast[np.ix_(check, cols)], table.observed[check], table.okres[check]
    before = (weights[g] * (x - corrections[g])).sum(1) / weights[g].sum(1)
    now = inner.predict(x, g, table.slot[check], table.dz[check])
    if table.variable in NON_NEGATIVE:
        before = np.clip(before, 0, None)
    error_now = np.bincount(g, weights=np.abs(now - y), minlength=n)
    error_before = np.bincount(g, weights=np.abs(before - y), minlength=n)
    return error_now > error_before


def day_number(day: date) -> int:
    return (day - date(1970, 1, 1)).days


def coefficients(
    pair_rows: pl.DataFrame,
    okres_pools: pl.DataFrame,
    stations: pl.DataFrame,
    as_of_days: list[date],
    window: int = WINDOW_DAYS,
    allowed: pl.DataFrame | None = None,
    min_days: int = MIN_DAYS,
) -> pl.DataFrame:
    """``Fit.frame`` rows for every ``as_of`` day (column ``as_of``), each fitted on the
    ``window`` days ending on it. ``allowed``: ``variable``, ``lead_day``, ``model`` that
    may take part (e.g. those with weights from the okres scores)."""
    frames = []
    for (variable, lead), table in tables(pair_rows, okres_pools, stations).items():
        ok = None
        if allowed is not None:
            ok = set(
                allowed.filter(pl.col("variable") == variable, pl.col("lead_day") == lead)[
                    "model"
                ].to_list()
            )
        for as_of in as_of_days:
            result = fit(table, day_number(as_of), window, allowed=ok, min_days=min_days)
            if result is not None:
                frames.append(result.frame().with_columns(pl.lit(as_of).alias("as_of")))
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames)


def training_span(as_of: date, window: int = WINDOW_DAYS) -> tuple[date, date]:
    """The days whose pairs a fit on ``as_of`` uses."""
    return as_of - timedelta(days=window - 1), as_of


def recent(
    data_dir: Path,
    scores: pl.LazyFrame | pl.DataFrame,
    stations: pl.DataFrame,
    as_of: date,
    allowed: pl.DataFrame | None = None,
    fc: pl.LazyFrame | None = None,
) -> pl.DataFrame | None:
    """The coefficients of the live forecast: fitted on the ``WINDOW_DAYS`` days up to
    ``as_of`` from the observations and forecasts in ``data_dir`` (``obs/``, ``fc/``),
    with the okres pools of the ``scores`` of those days. ``fc``: the forecasts to use
    instead of ``fc/`` (e.g. with the days rebuilt from the single runs). None without
    data."""
    first, last = training_span(as_of)
    obs = observations.scan(data_dir, first, last)
    if fc is None:
        fc = partitions.scan_months(data_dir / "fc", first, last)
    if obs is None or fc is None:
        return None
    rows = pairs(obs, fc, first, last)
    if rows.is_empty():
        return None
    in_window = scores.lazy().filter(
        pl.col("date").is_between(first, last), pl.col("variable").is_in(VARIABLES)
    )
    out = coefficients(rows, pools(in_window, stations), stations, [as_of], allowed=allowed)
    return None if out.is_empty() else out.drop("as_of")
