import numpy as np

from meteoverdict import compare_sample


def _data(days=40, seed=0):
    rng = np.random.default_rng(seed)
    n = np.full((days, 4), 20.0)
    # series: good model, worse model, mean, ai (best)
    base = np.array([1.0, 1.4, 1.2, 0.8])
    a = n * (base + rng.normal(0, 0.05, (days, 4)))
    return a, n


def test_entry_ranks_and_flags():
    a, n = _data()
    ids = ["m1", "m2", "blend", "meteoverdict_ai"]
    kinds = {"blend": "mean", "meteoverdict_ai": "ai"}
    e = compare_sample.entry(list(range(40)), ids, a, n, kinds, "k", stations=10, resamples=200)
    assert e["series"][0]["id"] == "meteoverdict_ai"
    assert e["series"][0]["kind"] == "ai" and e["days"] == 40 and not e["small_sample"]
    assert e["clear_winner"] and not e["series"][0]["tied"] and e["series"][-1]["tied"] is False
    assert len(e["series"][0]["daily"]) == 40 and e["hours"] == 800


def test_entry_small_sample_and_missing_series():
    a, n = _data(days=12)
    a[3, 1] = np.nan
    n[3, 1] = np.nan
    e = compare_sample.entry(list(range(12)), ["a", "b", "c", "d"], a, n, {}, "k", resamples=100)
    assert e["small_sample"] and {s["id"] for s in e["series"]} == {"a", "c", "d"}


def test_identical_series_no_clear_winner():
    n = np.full((40, 2), 20.0)
    rng = np.random.default_rng(1)
    a = n * (1 + rng.normal(0, 0.1, (40, 2)))
    e = compare_sample.entry(list(range(40)), ["a", "b"], a, n, {}, "k", resamples=200)
    assert not e["clear_winner"]


def test_versus_outlook():
    a, n = _data()
    ids = ["m1", "combined", "blend", "meteoverdict_ai"]
    e = compare_sample.entry(list(range(40)), ids, a, n, {}, "k", resamples=200)
    ai = next(s for s in e["series"] if s["id"] == "meteoverdict_ai")
    assert (
        ai["vs_outlook"]["diff"] < 0
        and ai["vs_outlook"]["high"] < 0
        and ai["vs_outlook"]["p"] < 0.05
    )
    assert next(s for s in e["series"] if s["id"] == "combined")["vs_outlook"] is None


def test_same_okresy_keeps_the_candidate_in_the_sum():
    import polars as pl

    rows = []
    for region in ("A", "B", "C"):
        for date in (1, 2):
            for model in ("m1", "combined", "ai") if region != "C" else ("m1", "combined"):
                rows.append((region, "temperature_2m", 1, date, model, 10.0, 10, 2))
    days = pl.DataFrame(
        rows,
        schema=["region", "variable", "lead_day", "date", "model", "sum_abs_err", "n", "stations"],
        orient="row",
    )
    wide = compare_sample.same_okresy(days, {"ai"})
    assert set(wide["region"]) == {"A", "B"} and wide["model"].n_unique() == 3
    other = days.with_columns(pl.lit("precipitation_daily").alias("variable")).filter(
        pl.col("model") != "ai"
    )
    assert (
        compare_sample.same_okresy(pl.concat([days, other]), {"ai"})
        .filter(pl.col("variable") == "precipitation_daily")["region"]
        .n_unique()
        == 3
    )
    assert compare_sample.same_okresy(days, set()).height == days.height


def test_has_ai_needs_enough_stations():
    def doc(stations):
        return {
            "entries": {
                "t/1": {"stations": stations, "series": [{"kind": "ai"}, {"kind": "model"}]}
            }
        }

    assert compare_sample.has_ai(doc(5)) and not compare_sample.has_ai(doc(2))
    assert not compare_sample.has_ai(
        {"entries": {"t/1": {"stations": 9, "series": [{"kind": "model"}]}}}
    )
