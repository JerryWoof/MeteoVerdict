import math

import polars as pl
import pytest

from meteoverdict.regions import (
    add_regions,
    elevation_class,
    find_kraj,
    load_kraje,
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
    assert out["kraj_code"].to_list() == ["CZ010", "CZ041"]
    assert out["kraj"].to_list() == ["Hlavní město Praha", "Karlovarský kraj"]
    assert out["elevation_class"].to_list() == ["lowland", None]
