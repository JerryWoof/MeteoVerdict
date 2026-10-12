from datetime import date

import polars as pl

from meteoverdict import aggregate as agg
from meteoverdict import neighbours, ranking

# Real places: Benešov and Vlašim (okres Benešov, CZ0201); Mnichovice (3 km beyond its
# border) and Říčany (9 km) in Praha-východ (CZ0209); Brno (CZ0642), 110 km away.
PLACES = {
    "benesov": (14.69, 49.78, "CZ0201", "Benešov"),
    "vlasim": (14.90, 49.71, "CZ0201", "Benešov"),
    "mnichovice": (14.709, 49.936, "CZ0209", "Praha-východ"),
    "ricany": (14.654, 49.992, "CZ0209", "Praha-východ"),
    "brno": (16.61, 49.19, "CZ0642", "Brno-město"),
}
STATIONS = pl.DataFrame(
    {
        "id": list(PLACES),
        "name": [p.title() for p in PLACES],
        "lon": [v[0] for v in PLACES.values()],
        "lat": [v[1] for v in PLACES.values()],
        "okres_code": [v[2] for v in PLACES.values()],
        "okres": [v[3] for v in PLACES.values()],
        "kraj_code": [v[2][:5] for v in PLACES.values()],
        "kraj": ["Středočeský kraj"] * 4 + ["Jihomoravský kraj"],
        "elevation_class": ["upland"] * 5,
    }
)
DAY = date(2026, 9, 30)


def scores(missing=()):
    """Temperature D+1 scores of models a and b at every station, except ``missing``
    (station, model) pairs."""
    rows = [
        {
            "date": DAY,
            "station_id": s,
            "model": m,
            "lead_day": 1,
            "variable": "temperature_2m",
            "period_h": 0,
            "n": 24,
            "sum_err": 24.0,
            "sum_abs_err": 24.0 * (1 if m == "a" else 2),
            "sum_sq_err": 24.0,
        }
        for s in PLACES
        for m in ("a", "b")
        if (s, m) not in missing
    ]
    return pl.DataFrame(rows)


def test_distance_to_an_okres_is_zero_inside_and_grows_outside():
    d = neighbours.distances(STATIONS).filter(pl.col("region") == "CZ0201")
    km = dict(d.select("station_id", "distance_km").rows())
    assert km["benesov"] == km["vlasim"] == 0
    assert 2 < km["mnichovice"] < 5 < km["ricany"] < 12
    assert km["brno"] > neighbours.MAX_KM
    assert d["region_name"][0] == "Benešov"
    assert neighbours.distances(STATIONS)["region"].n_unique() == 77  # every okres


def pool_frame(rows):
    return pl.DataFrame(
        rows, schema=["region", "region_name", "station_id", "distance_km"], orient="row"
    )


DISTANCE = pool_frame(
    [
        ("A", "Alpha", "a1", 0.0),
        ("A", "Alpha", "b1", 4.0),
        ("A", "Alpha", "b2", 2.0),
        ("A", "Alpha", "far", 50.0),
        ("B", "Beta", "b1", 0.0),
        ("B", "Beta", "b2", 0.0),
        ("B", "Beta", "a1", 1.0),
    ]
)


def available(variable, stations):
    return pl.DataFrame({"variable": variable, "station_id": stations})


def members(pool, region, variable="t"):
    part = pool.filter(pl.col("region") == region, pl.col("variable") == variable)
    return dict(part.select("station_id", "borrowed").rows())


def test_an_okres_borrows_the_nearest_stations_up_to_the_minimum():
    pool = neighbours.pools(DISTANCE, available("t", ["a1", "b1", "b2", "far"]), 3)
    assert members(pool, "A") == {"a1": False, "b2": True, "b1": True}
    assert members(pool, "B") == {"b1": False, "b2": False, "a1": True}
    pool = neighbours.pools(DISTANCE, available("t", ["a1", "b1", "b2", "far"]), 2)
    assert members(pool, "A") == {"a1": False, "b2": True}
    assert members(pool, "B") == {"b1": False, "b2": False}  # enough of its own


def test_only_stations_within_reach_and_with_the_variable_are_borrowed():
    pool = neighbours.pools(DISTANCE, available("t", ["a1", "far"]), 3)
    assert members(pool, "A") == {"a1": False}  # "far" is beyond MAX_KM
    both = pl.concat([available("t", ["a1"]), available("w", ["a1", "b2"])])
    pool = neighbours.pools(DISTANCE, both, 3)
    assert members(pool, "A", "t") == {"a1": False}
    assert members(pool, "A", "w") == {"a1": False, "b2": True}


def test_excluded_stations_are_replaced():
    exclude = pl.DataFrame({"variable": ["t"], "region": ["A"], "station_id": ["b2"]})
    pool = neighbours.pools(DISTANCE, available("t", ["a1", "b1", "b2"]), 2, exclude=exclude)
    assert members(pool, "A") == {"a1": False, "b1": True}
    assert members(pool, "B") == {"b1": False, "b2": False}


def okres_rows(table, region):
    part = table.filter(pl.col("level") == "okres", pl.col("region") == region)
    return part.filter(pl.col("model") == "a").select("stations", "borrowed", "enough_stations")


def test_aggregate_ranks_an_okres_with_borrowed_stations():
    table = agg.aggregate(scores(), STATIONS, windows=("all",))
    assert okres_rows(table, "CZ0201").row(0) == (3, 1, True)  # + Mnichovice
    assert okres_rows(table, "CZ0642").row(0) == (1, 0, False)  # nothing within reach
    # the other levels keep their own stations
    kraj = table.filter(pl.col("level") == "kraj", pl.col("region") == "CZ020")
    assert kraj["stations"].unique().to_list() == [4]
    assert kraj["borrowed"].unique().to_list() == [0]


def test_a_station_the_fair_comparison_drops_is_replaced_by_the_next():
    # model b never reached Mnichovice, so Benešov borrows Říčany instead
    table = agg.aggregate(scores(missing={("mnichovice", "b")}), STATIONS, windows=("all",))
    assert okres_rows(table, "CZ0201").row(0) == (3, 1, True)
    pool = agg.okres_pools(
        scores(missing={("mnichovice", "b")})
        .lazy()
        .join(agg.station_info(STATIONS), on="station_id"),
        neighbours.distances(STATIONS),
    )
    assert members(pool, "CZ0201", "temperature_2m") == {
        "benesov": False,
        "vlasim": False,
        "ricany": True,
    }


def test_ranking_uses_the_same_pools():
    ranks = ranking.rank(scores(), STATIONS, windows=("all",), resamples=10)
    okres = ranks.filter(pl.col("level") == "okres", pl.col("region") == "CZ0201")
    assert okres.select("model", "rank").rows() == [("a", 1), ("b", 2)]
