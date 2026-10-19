"""The Compare page's "same sample" comparison: models, the mean of all models, our
combined forecast (the Outlook blend) and experimental candidates (MeteoVerdict AI),
all scored on the same station-days, ranked with the honest-scoring rules of
``meteoverdict.ranking`` (block bootstrap, Diebold-Mariano, ``p_best``).

``blendtest.series`` already puts the candidates through ``aggregate.common_days`` with
the models, the mean and the combination, region by region and day by day, so every
series of one region, variable and lead day has the same stations and hours; only
series that cover every day of the group are compared. This module turns those day
totals into one small JSON file per region (Czechia, kraj or okres): per variable and
lead day the ranking and the daily MAE of every series (the error over time).

Entry (``entry``): ``days``, ``dates`` (first, last), ``stations``, ``hours`` (scored
values of one series), ``small_sample``, ``clear_winner`` and ``series``: one object
per series, best first: ``id``, ``kind`` (``model``, ``mean``, ``outlook``, ``ai``),
``mae``, ``diff`` (MAE minus the best's) with ``low`` and ``high`` (95 % interval),
``p_best``, ``tied`` (not shown to be worse than the best), ``vs_outlook`` (minus our
combination: ``diff``, ``low``, ``high``, Diebold-Mariano ``p``) and ``daily`` (MAE per date,
null where the series has no value).
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path

import numpy as np
import polars as pl

from meteoverdict import blend, ranking

OUTLOOK = "combined"
#: the series of ``blendtest.series`` that are choices, not forecasts
CHOICES = ("best_oos", "best_cz_oos", "best_hindsight")
KINDS = {blend.ID: "mean", OUTLOOK: "outlook"}
#: files per sample: ``<dir>/<region>.json`` and ``<dir>/index.json``
INDEX = "index.json"


def _round(value: float | None, digits: int = 3) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def entry(
    dates: list,
    ids: list[str],
    abs_err: np.ndarray,
    n: np.ndarray,
    kinds: dict[str, str],
    key: str,
    stations: int | None = None,
    resamples: int = ranking.RESAMPLES,
    seed: int = 0,
) -> dict | None:
    """One group's ranking. ``abs_err`` and ``n`` are days x series (NaN: no value that
    day); only the series with a value every day are ranked, the rest are left out."""
    full = ~(np.isnan(abs_err).any(axis=0) | np.isnan(n).any(axis=0)) & (n.sum(axis=0) > 0)
    if abs_err.shape[0] == 0 or not full.any():
        return None
    columns = np.flatnonzero(full)
    a, m = abs_err[:, columns], n[:, columns]
    names = [ids[i] for i in columns]
    if len(names) > 1:
        rng = np.random.default_rng([seed, zlib.crc32(key.encode())])
        order, diff, bounds, p_best = ranking.bootstrap_best(a, m, rng, resamples)
        tied, _, _ = ranking.ties(a, m, order, bounds)
    else:
        order, diff = np.array([0]), np.array([0.0])
        bounds, p_best, tied = np.zeros((2, 1)), np.ones(1), np.array([False])
    mae = a.sum(axis=0) / m.sum(axis=0)
    versus = _versus(a, m, names, key, resamples, seed)
    daily = np.where(m > 0, a / np.where(m > 0, m, 1), np.nan)
    series = [
        {
            "id": names[i], "kind": kinds.get(names[i], "model"), "mae": _round(mae[i]),
            "diff": _round(diff[i]), "low": _round(bounds[0][i]), "high": _round(bounds[1][i]),
            "p_best": _round(p_best[i]), "tied": bool(tied[i]), "vs_outlook": versus.get(names[i]),
            "daily": [_round(v, 2) for v in daily[:, i]],
        }
        for i in order
    ]  # fmt: skip
    clear = len(names) > 1 and not tied.any()
    return {
        "days": int(a.shape[0]),
        "dates": [str(dates[0]), str(dates[-1])],
        "date_list": [str(d) for d in dates],
        "stations": stations,
        "hours": int(m[:, order[0]].sum()),
        "small_sample": bool(a.shape[0] < ranking.SMALL_SAMPLE_DAYS),
        "clear_winner": bool(clear and p_best[order[0]] >= ranking.P_BEST_MIN),
        "series": series,
    }


def _versus(
    a: np.ndarray, m: np.ndarray, names: list[str], key: str, resamples: int, seed: int
) -> dict[str, dict]:
    """Every series minus our combination (the Outlook blend): the MAE difference with
    its block-bootstrap interval and the Diebold-Mariano p-value (negative: better than
    the Outlook blend). Empty without the combination or with fewer than 3 days."""
    if OUTLOOK not in names or a.shape[0] < 3:
        return {}
    ref = names.index(OUTLOOK)
    rng = np.random.default_rng([seed, zlib.crc32((key + "|vs").encode())])
    boot = ranking.resampled_mae(a, m, rng, resamples)
    diffs = boot - boot[:, [ref]]
    tail = (1 - ranking.CONFIDENCE) / 2
    low, high = np.quantile(diffs, [tail, 1 - tail], axis=0)
    mae = a.sum(axis=0) / m.sum(axis=0)
    _, p = ranking.diebold_mariano(a, m, ref)
    return {
        name: {
            "diff": _round(mae[i] - mae[ref]),
            "low": _round(low[i]),
            "high": _round(high[i]),
            "p": _round(p[i], 4),
        }
        for i, name in enumerate(names)
        if i != ref
    }


def from_days(
    group: pl.DataFrame, candidates: set[str], key: str, resamples: int, seed: int
) -> dict | None:
    """``entry`` of one region, variable and lead day of ``blendtest.series``."""
    group = group.filter(~pl.col("model").is_in(CHOICES))
    abs_err = group.pivot(on="model", index="date", values="sum_abs_err").sort("date")
    n = group.pivot(on="model", index="date", values="n").sort("date")
    ids = [c for c in abs_err.columns if c != "date"]
    kinds = {**KINDS, **dict.fromkeys(candidates, "ai")}
    stations = group.group_by("date").agg(pl.col("stations").max())["stations"].max()
    return entry(
        abs_err["date"].to_list(), ids,
        abs_err.select(ids).to_numpy().astype(float), n.select(ids).to_numpy().astype(float),
        kinds, key, stations, resamples, seed,
    )  # fmt: skip


def same_okresy(days: pl.DataFrame, candidates: set[str]) -> pl.DataFrame:
    """The day totals for summing okresy (a kraj, Czechia). A candidate such as the AI
    has forecasts only at some stations, so a few okresy may lack it; ``czechia`` would
    then drop it from the whole sum. Instead, for a variable and lead day with candidates,
    only the okres-days where every candidate has a value stay, for all series, so the
    sum still compares everything on the same okres-days (and stations)."""
    if not candidates:
        return days
    have = (
        days.filter(pl.col("model").is_in(list(candidates)))
        .group_by("region", "variable", "lead_day", "date")
        .agg(pl.col("model").n_unique().alias("_have"))
        .filter(pl.col("_have") == len(candidates))
        .drop("_have")
    )
    keys = ["variable", "lead_day"]
    covered = have.select(keys).unique()
    return pl.concat(
        [
            days.join(covered, on=keys, how="anti"),
            days.join(covered, on=keys, how="semi").join(
                have, on=["region", *keys, "date"], how="semi"
            ),
        ]
    )


def documents(
    days: pl.DataFrame,
    czechia,
    region_names: dict[str, str],
    kraj_of: dict[str, tuple[str, str]],
    candidates: set[str],
    resamples: int = ranking.RESAMPLES,
    seed: int = 0,
    min_days: int = 5,
) -> dict[str, dict]:
    """Region → ``{"name", "level", "entries": {"<variable>/<lead>": entry}}`` for
    Czechia (``cz``), every kraj and every okres. ``czechia`` is ``blendtest.czechia``
    (sums the okresy a series is compared in on every day); a kraj sums its okresy."""
    days = days.filter(~pl.col("model").is_in(CHOICES))
    wide = same_okresy(days, candidates)
    frames: dict[str, tuple[str, str, pl.DataFrame]] = {"cz": ("cz", "Česko", czechia(wide))}
    for okres in sorted(days["region"].unique()):
        frames[okres] = ("okres", region_names.get(okres, okres), days.filter(region=okres))
    krajs: dict[str, tuple[str, list[str]]] = {}
    for okres, (code, name) in kraj_of.items():
        krajs.setdefault(code, (name, []))[1].append(okres)
    for code, (name, okresy) in krajs.items():
        part = wide.filter(pl.col("region").is_in(okresy))
        if not part.is_empty():
            frames[code] = ("kraj", name, czechia(part).with_columns(pl.lit(code).alias("region")))
    docs = {}
    for region, (level, name, frame) in frames.items():
        entries = {}
        for (variable, lead), part in sorted(
            frame.partition_by(["variable", "lead_day"], as_dict=True).items()
        ):
            k = f"compare|{region}|{variable}|{lead}"
            got = from_days(part, candidates, k, resamples, seed)
            if got and got["days"] >= min_days:
                entries[f"{variable}/{lead}"] = got
        if entries:
            docs[region] = {"region": region, "level": level, "name": name, "entries": entries}
    return docs


#: a region is offered for the AI comparison only with this many stations in its sample
#: (an okres usually has one or two AI stations: too few to say anything)
MIN_AI_STATIONS = 3


def has_ai(doc: dict) -> bool:
    """Does the region have the AI (a candidate) with enough stations in its temperature
    or wind comparison?"""
    return any(
        any(s["kind"] == "ai" for s in e["series"]) and (e.get("stations") or 0) >= MIN_AI_STATIONS
        for e in doc["entries"].values()
    )


def write(docs: dict[str, dict], out_dir: Path, info: dict) -> Path:
    """``<out_dir>/<region>.json`` per region and ``index.json`` (``info`` plus the
    regions: code → [level, name, has_ai])."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for region, doc in docs.items():
        (out_dir / f"{region}.json").write_text(
            json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8"
        )
    index = {
        **info,
        "regions": {r: [d["level"], d["name"], has_ai(d)] for r, d in docs.items()},
    }
    (out_dir / INDEX).write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), "utf-8"
    )
    return out_dir / INDEX
