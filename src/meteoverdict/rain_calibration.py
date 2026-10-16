"""Calibrated probability of precipitation for the outlook (``meteoverdict.outlook``).

The raw probability, the share of models with at least ``WET_MM`` in a 6-hour part of
day, rates rain too likely at every level. Every night the daily pipeline refits a
pooled logistic regression on the last ``WINDOW_DAYS`` days of verified 6-hour cases
(okres, part of day, lead day) and publishes its coefficients as ``rain-calibration.json``;
the outlook loads them and gives

    rain_probability = BLEND * p_logistic + (1 - BLEND) * share

for every part of day. Predictors of ``p_logistic``:

* ``wshare``: the share of wet models, each model weighted by 1 / its Brier score for
  rain or no rain (per lead day; normalised to a mean of 1, shrunk towards equal weights
  by days / (days + ``SHRINK_DAYS``));
* ``share1``: the share of models with at least 1 mm;
* the square roots of the mean and of the largest model total;
* the neighbourhood (okresy whose forecast points are at most ``NEIGHBOUR_KM`` apart,
  the okres itself included): the share of wet values over all models and okresy, and
  the square root of the mean over the models of each one's largest total there;
* indicators for morning, afternoon and evening and for lead days 2 to 5.

The 50/50 blend with the raw share hedges against a change of regime between training
and use (a wetter month after a dry one pulls the fitted part too dry). Out of sample
(Aug-Sep 2026, test Sep 13-30, refitted every 6 days) it improved the Brier score of the
okres probability by about 10 % against the raw share, and showers drawn at a blended
probability of at least ``SHOWER_PROBABILITY`` (0.40, rather than 0.30 on the raw share)
raised the ETS of "any precipitation symbol" by 0.075 (docs/methodology.md).

A second, extended logistic regression (Wilks 2009: the thresholds 0.2, 1 and 5 mm
stacked, sqrt(threshold) as one more predictor; also the share of models with 5 mm and
the square root of the 90th percentile of the models) gives ``heavy_rain_probability``,
P(>= ``HEAVY_MM`` mm in the part of day). ``heavy_rain`` flags parts at or above the
probability that had the best ETS on the training cases.

Training cases come from the release data: the station forecasts of the backfill
(``fc/``, D+1..D+5) and the hourly station observations (``obs/``). A model's value for
an okres is the mean of its 6-hour totals at the okres's stations; the observation is
the mean of the stations with all 6 hours. The outlook uses one forecast point per okres,
so its values are a little less smooth than the training ones.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

FILE = "rain-calibration.json"
VERSION = 1
TIME_ZONE = "Europe/Prague"
PARTS = ("night", "morning", "afternoon", "evening")
LEAD_DAYS = (1, 2, 3, 4, 5)
#: a model is "wet" for a part of day with at least this total (mm), as in the outlook
WET_MM = 0.2
#: thresholds of the extended logistic regression; the heavy-rain flag is for the last
THRESHOLDS = (0.2, 1.0, 5.0)
HEAVY_MM = 5.0
#: training: the last WINDOW_DAYS days with verified cases, at least MIN_DAYS of them
WINDOW_DAYS = 90
MIN_DAYS = 30
#: a calibration older than this (its last training day) is not used
MAX_AGE_DAYS = 14
#: the model weights move from equal to 1/Brier as days / (days + SHRINK_DAYS)
SHRINK_DAYS = 30
#: a model's Brier score at a lead day needs at least this many cases
MIN_MODEL_CASES = 200
#: a case needs at least this many models (fewer: the raw share is used)
MIN_MODELS = 3
NEIGHBOUR_KM = 40.0
#: share of the fitted probability in the published one
BLEND = 0.5
#: the "showers" symbol with a calibrated probability (0.3 on the raw share)
SHOWER_PROBABILITY = 0.40
#: older cases weigh less with a half-life in days (None: all the same)
HALF_LIFE_DAYS: float | None = None
#: L2 penalty as scikit-learn's LogisticRegression(C=1): 0.5 * |b|^2 / C, no intercept
C = 1.0
#: heavy rain needs at least this many training cases with HEAVY_MM to be fitted
MIN_HEAVY_CASES = 20

FEATURES = (
    "wshare",
    "share1",
    "sqrt_mean",
    "sqrt_max",
    "nb_share",
    "sqrt_nb_maxmean",
    *(f"part_{p}" for p in PARTS[1:]),
    *(f"lead_{d}" for d in LEAD_DAYS[1:]),
)
HEAVY_FEATURES = (*FEATURES, "share5", "sqrt_q90", "sqrt_threshold")


# --- logistic regression (Newton / IRLS with an L2 penalty) ------------------------------


def fit_logistic(
    x: np.ndarray,
    y: np.ndarray,
    sample_weight: np.ndarray | None = None,
    c: float = C,
    max_iter: int = 100,
    tol: float = 1e-10,
) -> tuple[float, np.ndarray]:
    """``(intercept, coefficients)`` minimising sum(w * log loss) + 0.5 * |b|^2 / c,
    the intercept not penalised: the optimum of scikit-learn's ``LogisticRegression(C=c)``.
    Newton steps with step halving; converges in a few iterations."""
    n, k = x.shape
    xa = np.column_stack([np.ones(n), x])
    s = np.ones(n) if sample_weight is None else np.asarray(sample_weight, float)
    y = np.asarray(y, float)
    penalty = np.r_[0.0, np.full(k, 1.0 / c)]
    beta = np.zeros(k + 1)

    def loss(b: np.ndarray) -> float:
        eta = xa @ b
        return float(np.sum(s * (np.logaddexp(0.0, eta) - y * eta)) + 0.5 * penalty @ b**2)

    current = loss(beta)
    for _ in range(max_iter):
        p = _expit(xa @ beta)
        gradient = xa.T @ (s * (p - y)) + penalty * beta
        hessian = (xa * (s * p * (1 - p))[:, None]).T @ xa + np.diag(penalty)
        step = np.linalg.solve(hessian + 1e-10 * np.eye(k + 1), gradient)
        t = 1.0
        while True:
            candidate = beta - t * step
            value = loss(candidate)
            if value <= current or t < 1e-6:
                break
            t /= 2
        beta, previous, current = candidate, current, value
        if np.max(np.abs(t * step)) < tol or previous - current < tol * max(1.0, abs(current)):
            break
    return float(beta[0]), beta[1:]


def _expit(eta: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * eta))


def predict(intercept: float, coefficients: np.ndarray, x: np.ndarray) -> np.ndarray:
    return _expit(intercept + x @ np.asarray(coefficients, float))


# --- cases -------------------------------------------------------------------------------


def neighbours(points: pl.DataFrame, km: float = NEIGHBOUR_KM) -> pl.DataFrame:
    """``okres``, ``nbr``: pairs of okresy whose points (``code``, ``lat``, ``lon``) are
    at most ``km`` apart, every okres paired with itself too."""
    points = points.sort("code")
    lat = np.radians(points["lat"].to_numpy())
    lon = np.radians(points["lon"].to_numpy())
    dx = (lon[:, None] - lon[None, :]) * np.cos((lat[:, None] + lat[None, :]) / 2)
    dy = lat[:, None] - lat[None, :]
    near = 6371.0 * np.sqrt(dx**2 + dy**2) <= km
    codes = points["code"].to_list()
    i, j = np.nonzero(near)
    return pl.DataFrame(
        {"okres": [codes[a] for a in i], "nbr": [codes[b] for b in j]},
        schema={"okres": pl.String, "nbr": pl.String},
    )


def _local(frame: pl.LazyFrame) -> pl.LazyFrame:
    """Local ``day`` and ``part`` of the hour ending at ``time`` (as the outlook's sums)."""
    local = (pl.col("time") - pl.duration(hours=1)).dt.convert_time_zone(TIME_ZONE)
    hour = local.dt.hour()
    part = pl.lit(None, pl.String)
    for n, name in enumerate(PARTS):
        part = pl.when(hour.is_between(6 * n, 6 * n + 5)).then(pl.lit(name)).otherwise(part)
    return frame.with_columns(local.dt.date().alias("day"), part.alias("part"))


def _span(first: date, last: date) -> pl.Expr:
    start = datetime.combine(first - timedelta(days=1), datetime.min.time(), UTC)
    end = datetime.combine(last + timedelta(days=2), datetime.min.time(), UTC)
    return pl.col("time").is_between(start, end, closed="left")


def _okres_of(stations: pl.DataFrame) -> pl.LazyFrame:
    return stations.select(
        pl.col("id").alias("station_id"), pl.col("okres_code").alias("okres")
    ).lazy()


def six_hour_forecasts(
    fc: pl.LazyFrame | pl.DataFrame, stations: pl.DataFrame, first: date, last: date
) -> pl.DataFrame:
    """``okres``, ``issue``, ``day``, ``part``, ``lead``, ``model``, ``fc``: each model's
    total over a whole part of day (all 6 hours from one issue day), averaged over the
    stations of the okres. ``issue`` is the UTC day ``lead_day`` days before the hour."""
    frame = (
        fc.lazy()
        .select("station_id", "time", "model", "lead_day", "precipitation")
        .filter(_span(first, last), pl.col("precipitation").is_not_null())
        .with_columns(
            (pl.col("time").dt.date() - pl.duration(days=pl.col("lead_day").cast(pl.Int64))).alias(
                "issue"
            )
        )
    )
    return (
        _local(frame)
        .filter(pl.col("day").is_between(first, last))
        .group_by("station_id", "issue", "model", "day", "part")
        .agg(
            pl.col("precipitation").sum().alias("fc"),
            pl.len().alias("hours"),
            pl.col("lead_day").min().cast(pl.Int8).alias("lead"),
        )
        .filter(pl.col("hours") == 6)
        .join(_okres_of(stations), on="station_id")
        .group_by("okres", "issue", "day", "part", "lead", "model")
        .agg(pl.col("fc").mean().cast(pl.Float64))
        .collect()
    )


def six_hour_observations(
    obs: pl.LazyFrame | pl.DataFrame, stations: pl.DataFrame, first: date, last: date
) -> pl.DataFrame:
    """``okres``, ``day``, ``part``, ``obs``: the mean over the okres's stations with all 6
    hourly precipitation values of the part of day."""
    frame = (
        obs.lazy()
        .filter(
            pl.col("variable") == "precipitation",
            pl.col("value").is_not_null(),
            _span(first, last),
        )
        .select("station_id", "time", "value")
    )
    return (
        _local(frame)
        .filter(pl.col("day").is_between(first, last))
        .group_by("station_id", "day", "part")
        .agg(pl.col("value").sum().alias("obs"), pl.len().alias("hours"))
        .filter(pl.col("hours") == 6)
        .join(_okres_of(stations), on="station_id")
        .group_by("okres", "day", "part")
        .agg(pl.col("obs").mean().cast(pl.Float64), pl.len().alias("stations"))
        .collect()
    )


def features(
    totals: pl.DataFrame,
    nbrs: pl.DataFrame,
    weights: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """One row per okres and case (the columns of ``totals`` other than ``okres``,
    ``model`` and ``fc``; ``lead`` and ``part`` among them) with the predictors.

    ``totals``: one row per okres, case and model with the model's total ``fc``;
    ``weights``: ``lead``, ``model``, ``weight`` (models without one weigh 1)."""
    keys = [c for c in totals.columns if c not in ("okres", "model", "fc")]
    fc = pl.col("fc")
    wet = fc >= WET_MM
    if weights is None or weights.is_empty():
        weights = pl.DataFrame(
            schema={"lead": totals.schema["lead"], "model": pl.String, "weight": pl.Float64}
        )
    weighted = totals.join(
        weights.with_columns(pl.col("lead").cast(totals.schema["lead"])),
        on=["lead", "model"],
        how="left",
    ).with_columns(pl.col("weight").fill_null(1.0))
    own = weighted.group_by("okres", *keys).agg(
        pl.len().alias("n_models"),
        wet.mean().alias("share"),
        (fc >= 1.0).mean().alias("share1"),
        (fc >= HEAVY_MM).mean().alias("share5"),
        fc.mean().alias("mean"),
        fc.max().alias("max"),
        fc.quantile(0.9, "linear").alias("q90"),
        ((wet.cast(pl.Float64) * pl.col("weight")).sum() / pl.col("weight").sum()).alias("wshare"),
    )
    around = (
        nbrs.join(totals.rename({"okres": "nbr"}), on="nbr")
        .group_by("okres", *keys, "model")
        .agg(fc.max().alias("nbmax"), wet.mean().alias("nbwet"))
        .group_by("okres", *keys)
        .agg(
            pl.col("nbmax").mean().alias("nb_maxmean"),
            pl.col("nbwet").mean().alias("nb_share"),
        )
    )
    return own.join(around, on=["okres", *keys], how="left")


def model_weights(cases: pl.DataFrame, totals: pl.DataFrame) -> pl.DataFrame:
    """``lead``, ``model``, ``weight``: 1 / the Brier score of each model's rain or no
    rain at each lead day over ``cases`` (with ``obs``), normalised to a mean of 1 over
    the models of the lead day and shrunk towards 1 by days / (days + SHRINK_DAYS)."""
    keys = [c for c in totals.columns if c not in ("okres", "model", "fc")]
    days = cases["day"].n_unique()
    shrink = days / (days + SHRINK_DAYS)
    scored = (
        totals.join(cases.select("okres", *keys, "obs"), on=["okres", *keys])
        .group_by("lead", "model")
        .agg(
            (((pl.col("fc") >= WET_MM).cast(pl.Float64) - (pl.col("obs") >= WET_MM)) ** 2)
            .mean()
            .alias("brier"),
            pl.len().alias("n"),
        )
        .filter(pl.col("n") > MIN_MODEL_CASES, pl.col("brier") > 0)
        .with_columns((1 / pl.col("brier")).alias("inverse"))
    )
    return (
        scored.with_columns(
            (
                shrink * pl.col("inverse") / pl.col("inverse").mean().over("lead") + (1 - shrink)
            ).alias("weight")
        )
        .select("lead", "model", "weight")
        .sort("lead", "model")
    )


def design(frame: pl.DataFrame, heavy_threshold: float | None = None) -> np.ndarray:
    """The predictors of ``FEATURES`` (with ``heavy_threshold``: of ``HEAVY_FEATURES``)."""
    sqrt = lambda c: pl.col(c).clip(lower_bound=0).sqrt()  # noqa: E731
    columns = [
        pl.col("wshare"),
        pl.col("share1"),
        sqrt("mean"),
        sqrt("max"),
        pl.col("nb_share"),
        sqrt("nb_maxmean"),
        *[(pl.col("part") == p).cast(pl.Float64) for p in PARTS[1:]],
        *[(pl.col("lead") == d).cast(pl.Float64) for d in LEAD_DAYS[1:]],
    ]
    if heavy_threshold is not None:
        columns += [pl.col("share5"), sqrt("q90"), pl.lit(math.sqrt(heavy_threshold))]
    names = [f"x{n}" for n in range(len(columns))]
    return (
        frame.select([c.cast(pl.Float64).alias(n) for c, n in zip(columns, names, strict=True)])
        .fill_null(0.0)
        .to_numpy()
    )


# --- the calibration ---------------------------------------------------------------------


@dataclass
class Calibration:
    intercept: float
    coefficients: list[float]
    heavy_intercept: float | None
    heavy_coefficients: list[float] | None
    #: heavy_rain when heavy_rain_probability is at least this (None: never)
    heavy_flag_at: float | None
    #: lead day → model → weight
    weights: dict[int, dict[str, float]]
    first: date
    last: date
    days: int
    cases: int
    generated: datetime | None = None
    info: dict = field(default_factory=dict)

    def weight_frame(self) -> pl.DataFrame:
        rows = [(lead, m, w) for lead, ws in self.weights.items() for m, w in ws.items()]
        return pl.DataFrame(
            rows, schema={"lead": pl.Int8, "model": pl.String, "weight": pl.Float64}, orient="row"
        )

    def to_dict(self) -> dict:
        return {
            "version": VERSION,
            "generated": self.generated.isoformat(timespec="minutes") if self.generated else None,
            "from": self.first.isoformat(),
            "to": self.last.isoformat(),
            "days": self.days,
            "cases": self.cases,
            "wet_mm": WET_MM,
            "blend": BLEND,
            "min_models": MIN_MODELS,
            "neighbour_km": NEIGHBOUR_KM,
            "showers_at": SHOWER_PROBABILITY,
            "features": list(FEATURES),
            "intercept": self.intercept,
            "coefficients": list(self.coefficients),
            "heavy": {
                "mm": HEAVY_MM,
                "thresholds": list(THRESHOLDS),
                "features": list(HEAVY_FEATURES),
                "intercept": self.heavy_intercept,
                "coefficients": self.heavy_coefficients,
                "flag_at": self.heavy_flag_at,
            },
            "model_weights": {
                str(lead): dict(sorted(ws.items())) for lead, ws in sorted(self.weights.items())
            },
            **self.info,
        }

    @classmethod
    def from_dict(cls, doc: dict) -> Calibration:
        if doc.get("version") != VERSION or doc.get("features") != list(FEATURES):
            raise ValueError("rain calibration of another version")
        heavy = doc.get("heavy") or {}
        if heavy.get("coefficients") is not None and heavy.get("features") != list(HEAVY_FEATURES):
            raise ValueError("heavy-rain calibration of another version")
        generated = doc.get("generated")
        return cls(
            intercept=float(doc["intercept"]),
            coefficients=[float(v) for v in doc["coefficients"]],
            heavy_intercept=heavy.get("intercept"),
            heavy_coefficients=heavy.get("coefficients"),
            heavy_flag_at=heavy.get("flag_at"),
            weights={
                int(lead): {m: float(w) for m, w in ws.items()}
                for lead, ws in doc.get("model_weights", {}).items()
            },
            first=date.fromisoformat(doc["from"]),
            last=date.fromisoformat(doc["to"]),
            days=int(doc["days"]),
            cases=int(doc["cases"]),
            generated=datetime.fromisoformat(generated) if generated else None,
            info={k: doc[k] for k in ("brier", "brier_share", "base_rate") if k in doc},
        )


def ets(forecast: np.ndarray, observed: np.ndarray) -> float:
    """Equitable threat score of yes/no forecasts (nan without events or forecasts)."""
    hits = np.sum(forecast & observed)
    false = np.sum(forecast & ~observed)
    misses = np.sum(~forecast & observed)
    random = (hits + false) * (hits + misses) / max(len(forecast), 1)
    denominator = hits + false + misses - random
    return float((hits - random) / denominator) if denominator > 0 else float("nan")


def fit(
    totals: pl.DataFrame,
    observed: pl.DataFrame,
    nbrs: pl.DataFrame,
    half_life: float | None = HALF_LIFE_DAYS,
    min_days: int = MIN_DAYS,
    generated: datetime | None = None,
) -> Calibration | None:
    """Fit on all cases of ``totals`` (``six_hour_forecasts``) that have an observation
    (``six_hour_observations``) and at least ``MIN_MODELS`` models; None with fewer than
    ``min_days`` days of cases."""
    feats = features(totals, nbrs)
    cases = feats.join(observed.select("okres", "day", "part", "obs"), on=["okres", "day", "part"])
    cases = cases.filter(pl.col("n_models") >= MIN_MODELS)
    if cases.is_empty() or cases["day"].n_unique() < min_days:
        return None
    weights = model_weights(cases, totals)
    keys = [c for c in totals.columns if c not in ("okres", "model", "fc")]
    cases = (
        features(totals, nbrs, weights)
        .join(cases.select("okres", *keys, "obs"), on=["okres", *keys])
        .sort("okres", *keys)
    )
    first, last = cases["day"].min(), cases["day"].max()
    sample_weight = None
    if half_life:
        age = (pl.lit(last) - pl.col("day")).dt.total_days()
        sample_weight = cases.select(0.5 ** (age / half_life)).to_series().to_numpy()
    obs = cases["obs"].to_numpy()
    x = design(cases)
    wet = (obs >= WET_MM).astype(float)
    intercept, coefficients = fit_logistic(x, wet, sample_weight)
    p = BLEND * predict(intercept, coefficients, x) + (1 - BLEND) * cases["share"].to_numpy()
    info = {
        "base_rate": round(float(wet.mean()), 4),
        "brier": round(float(np.mean((p - wet) ** 2)), 5),
        "brier_share": round(float(np.mean((cases["share"].to_numpy() - wet) ** 2)), 5),
    }
    heavy_intercept = heavy_coefficients = flag_at = None
    if np.sum(obs >= HEAVY_MM) >= MIN_HEAVY_CASES:
        stacked = np.vstack([design(cases, q) for q in THRESHOLDS])
        labels = np.concatenate([(obs >= q).astype(float) for q in THRESHOLDS])
        weights_stacked = None if sample_weight is None else np.tile(sample_weight, len(THRESHOLDS))
        heavy_intercept, heavy = fit_logistic(stacked, labels, weights_stacked)
        heavy_coefficients = [float(v) for v in heavy]
        p5 = predict(heavy_intercept, heavy, design(cases, HEAVY_MM))
        flag_at, best = flag_threshold(p5, obs >= HEAVY_MM)
        info["heavy_ets"] = round(best, 4)
    return Calibration(
        intercept=intercept,
        coefficients=[float(v) for v in coefficients],
        heavy_intercept=heavy_intercept,
        heavy_coefficients=heavy_coefficients,
        heavy_flag_at=flag_at,
        weights={
            int(lead): {m: float(w) for m, w in zip(part["model"], part["weight"], strict=True)}
            for (lead,), part in weights.partition_by("lead", as_dict=True).items()
        },
        first=first,
        last=last,
        days=cases["day"].n_unique(),
        cases=cases.height,
        generated=generated,
        info=info,
    )


def flag_threshold(p: np.ndarray, event: np.ndarray) -> tuple[float | None, float]:
    """The probability (0.02 to 0.60 by 0.01) at which a yes/no flag has the best ETS."""
    best, at = -np.inf, None
    for t in np.round(np.arange(0.02, 0.605, 0.01), 2):
        score = ets(p >= t, event)
        if not np.isnan(score) and score > best:
            best, at = score, float(t)
    return at, float(best) if at is not None else float("nan")


def apply(
    totals: pl.DataFrame,
    calibration: Calibration | None,
    nbrs: pl.DataFrame | None,
) -> pl.DataFrame:
    """Per okres and case of ``totals`` (``okres``, ``model``, ``fc``, ``lead``,
    ``part`` and other keys): ``model_share`` (the raw share of wet models),
    ``rain_probability`` (calibrated and blended; the raw share without a calibration or
    with fewer than ``MIN_MODELS`` models), ``calibrated``, ``heavy_rain_probability``
    and ``heavy_rain`` (null without a heavy-rain calibration)."""
    keys = [c for c in totals.columns if c not in ("okres", "model", "fc")]
    if calibration is None or nbrs is None:
        return (
            totals.group_by("okres", *keys)
            .agg((pl.col("fc") >= WET_MM).mean().alias("model_share"))
            .with_columns(
                pl.col("model_share").alias("rain_probability"),
                pl.lit(False).alias("calibrated"),
                pl.lit(None, pl.Float64).alias("heavy_rain_probability"),
                pl.lit(None, pl.Boolean).alias("heavy_rain"),
            )
        )
    feats = features(totals, nbrs, calibration.weight_frame())
    x = design(feats)
    ok = (feats["n_models"] >= MIN_MODELS).to_numpy()
    share = feats["share"].to_numpy()
    fitted = predict(calibration.intercept, np.array(calibration.coefficients), x)
    p = np.where(ok, BLEND * fitted + (1 - BLEND) * share, share)
    heavy = np.full(len(share), np.nan)
    flag = np.full(len(share), None, dtype=object)
    if calibration.heavy_coefficients is not None:
        heavy = predict(
            calibration.heavy_intercept,
            np.array(calibration.heavy_coefficients),
            design(feats, HEAVY_MM),
        )
        heavy = np.where(ok, heavy, np.nan)
        at = calibration.heavy_flag_at
        flag = np.array(
            [None if np.isnan(h) else (at is not None and bool(h >= at)) for h in heavy],
            dtype=object,
        )
    return feats.select("okres", *keys).with_columns(
        pl.Series("model_share", share, pl.Float64),
        pl.Series("rain_probability", p, pl.Float64),
        pl.Series("calibrated", ok, pl.Boolean),
        pl.Series("heavy_rain_probability", heavy, pl.Float64, nan_to_null=True),
        pl.Series("heavy_rain", flag.tolist(), pl.Boolean),
    )


# --- files and the pipeline --------------------------------------------------------------


def write(calibration: Calibration, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calibration.to_dict(), indent=1), "utf-8")
    return path


def load(path: Path, today: date | None = None, log=lambda _: None) -> Calibration | None:
    """The calibration in ``path``, or None when it is missing, of another version or
    older than ``MAX_AGE_DAYS`` (the outlook then keeps the raw share)."""
    if not path.exists():
        log(f"no {path.name}: rain probability is the raw share of models")
        return None
    try:
        calibration = Calibration.from_dict(json.loads(path.read_text("utf-8")))
    except (ValueError, KeyError, TypeError) as exc:
        log(f"{path.name} not used ({exc}): rain probability is the raw share of models")
        return None
    today = today or datetime.now(UTC).date()
    if (today - calibration.last).days > MAX_AGE_DAYS:
        log(f"{path.name} ends {calibration.last}, too old: raw share of models")
        return None
    return calibration


def refit(
    fc: pl.LazyFrame | pl.DataFrame,
    obs: pl.LazyFrame | pl.DataFrame,
    stations: pl.DataFrame,
    points: pl.DataFrame,
    day: date,
    window: int = WINDOW_DAYS,
    generated: datetime | None = None,
) -> Calibration | None:
    """The nightly refit: cases of the ``window`` days up to ``day``."""
    first = day - timedelta(days=window - 1)
    totals = six_hour_forecasts(fc, stations, first, day)
    observed = six_hour_observations(obs, stations, first, day)
    if totals.is_empty() or observed.is_empty():
        return None
    return fit(totals, observed, neighbours(points), generated=generated)
