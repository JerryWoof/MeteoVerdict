import math

import polars as pl
import pytest

from meteoverdict.regions import (
    add_regions,
    elevation_class,
    find_kraj,
    find_region,
    load_kraje,
    load_regions,
)

NUTS3 = {
    "CZ010": "Hlavní město Praha",
    "CZ020": "Středočeský kraj",
    "CZ031": "Jihočeský kraj",
    "CZ032": "Plzeňský kraj",
    "CZ041": "Karlovarský kraj",
    "CZ042": "Ústecký kraj",
    "CZ051": "Liberecký kraj",
    "CZ052": "Královéhradecký kraj",
    "CZ053": "Pardubický kraj",
    "CZ063": "Kraj Vysočina",
    "CZ064": "Jihomoravský kraj",
    "CZ071": "Olomoucký kraj",
    "CZ072": "Zlínský kraj",
    "CZ080": "Moravskoslezský kraj",
}


def test_bundled_boundaries_have_all_14_kraje():
    assert {k.code: k.name for k in load_kraje()} == NUTS3


@pytest.mark.parametrize(
    ("place", "lon", "lat", "code"),
    [
        # ČHMÚ stations from the recorded meta1 fixture
        ("Cheb", 12.391389, 50.068333, "CZ041"),
        ("Praha, Libuš", 14.446944, 50.007778, "CZ010"),
        ("Karlovy Vary", 12.914167, 50.201667, "CZ041"),
        # Kladno lies in Středočeský kraj, which has Praha as a hole
        ("Kladno", 14.1031, 50.1473, "CZ020"),
        ("Brno", 16.6068, 49.1951, "CZ064"),
        ("Ostrava", 18.2625, 49.8209, "CZ080"),
        ("Jihlava", 15.5911, 49.3961, "CZ063"),
        ("Zlín", 17.6667, 49.2265, "CZ072"),
    ],
)
def test_places_fall_in_the_right_kraj(place, lon, lat, code):
    assert find_kraj(lon, lat).code == code


@pytest.mark.parametrize(("lon", "lat"), [(13.7373, 51.0504), (16.37, 48.21), (19.5, 50.0)])
def test_foreign_points_have_no_kraj(lon, lat):
    # Dresden, Vienna, and a point in Poland well beyond the border
    assert find_kraj(lon, lat) is None


def test_points_just_outside_the_border_get_the_nearest_kraj():
    lon, lat = 12.05, 50.25  # in Germany, a few km west of Aš
    assert all(not k.contains(lon, lat) for k in load_kraje())
    distance = min(k.distance_km(lon, lat) for k in load_kraje())
    assert 0 < distance < 10
    assert find_kraj(lon, lat, tolerance_km=distance - 0.1) is None
    assert find_kraj(lon, lat, tolerance_km=distance + 0.1).code == "CZ041"


@pytest.mark.parametrize(
    ("elevation", "expected"),
    [
        (150.0, "lowland"),
        (399.9, "lowland"),
        (400.0, "upland"),
        (800.0, "upland"),
        (800.1, "mountain"),
        (1602.0, "mountain"),
        (None, None),
        (math.nan, None),
    ],
)
def test_elevation_class(elevation, expected):
    assert elevation_class(elevation) == expected


def test_add_regions_adds_columns_and_drops_foreign_stations():
    stations = pl.DataFrame(
        {
            "id": ["a", "b", "c"],
            "lon": [14.446944, 13.7373, 12.391389],
            "lat": [50.007778, 51.0504, 50.068333],
            "elevation": [302.04, 113.0, None],
        }
    )
    out = add_regions(stations)
    assert out["id"].to_list() == ["a", "c"]
    assert out["okres_code"].to_list() == ["CZ0100", "CZ0411"]
    assert out["okres"].to_list() == ["území Hlavního města Prahy", "Cheb"]
    assert out["kraj_code"].to_list() == ["CZ010", "CZ041"]
    assert out["kraj"].to_list() == ["Hlavní město Praha", "Karlovarský kraj"]
    assert out["elevation_class"].to_list() == ["lowland", None]


def test_bundled_okresy_are_77_and_belong_to_a_kraj():
    okresy = load_regions("okres")
    codes = [o.code for o in okresy]
    assert len(okresy) == 77 == len(set(codes))
    assert {c[:5] for c in codes} == set(NUTS3)


@pytest.mark.parametrize(
    ("place", "lon", "lat", "okres"),
    [
        ("Brno centre", 16.6068, 49.1951, "Brno-město"),  # a hole in Brno-venkov
        ("Kuřim", 16.5316, 49.2985, "Brno-venkov"),
        ("Praha, Libuš", 14.446944, 50.007778, "území Hlavního města Prahy"),
        ("Kladno", 14.1031, 50.1473, "Kladno"),
        ("Cheb", 12.391389, 50.068333, "Cheb"),
        ("Lysá hora", 18.4475, 49.5461, "Frýdek-Místek"),
    ],
)
def test_places_fall_in_the_right_okres(place, lon, lat, okres):
    assert find_region(lon, lat, "okres").name == okres


def test_okres_and_kraj_polygons_agree_away_from_borders():
    # a 0.1° grid over Czechia: the kraj polygon and the okres code must agree
    # except within the ~0.6 km simplification margin along borders
    points = [(12.1 + 0.1 * i, 48.6 + 0.1 * j) for i in range(68) for j in range(25)]
    pairs = [(find_region(x, y, "okres", 0), find_region(x, y, "kraj", 0)) for x, y in points]
    inside = [(o, k) for o, k in pairs if o and k]
    agree = sum(o.code[:5] == k.code for o, k in inside)
    assert len(inside) > 700
    assert agree / len(inside) > 0.99
