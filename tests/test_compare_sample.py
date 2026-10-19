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
