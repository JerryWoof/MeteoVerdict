from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import polars as pl
import pytest

from meteoverdict import bucket, combine, models, outlook, outlook_bucket

RUN = datetime(2026, 10, 20, 0, tzinfo=UTC)
PRAGUE = (50.07, 14.47)


def test_okres_cells_cover_every_point_and_bucket_model():
    cells = outlook_bucket.load_cells()
    codes = set(combine.okres_points()["code"])
    assert set(cells["station_id"]) == codes
    assert set(cells["bucket_model"]) == set(bucket.bucket_models())
    assert cells.group_by("bucket_model").len()["len"].to_list() == [len(codes)] * len(
        set(cells["bucket_model"])
    )
    # the nearest cell: within half the coarsest grid's diagonal (GEM 15 km, JMA ~0.5°)
    assert cells["grid_distance_km"].max() < 40


def test_point_table_has_the_api_elevation():
    table = outlook_bucket.point_table(combine.okres_points())
    assert table.columns == ["id", "lat", "lon", "elevation"]
    assert table["elevation"].null_count() == 0 and table.height == 77


def test_backwards_sum_spreads_a_step_total_over_its_hours():
    leads = np.array([1.0, 2.0, 3.0, 6.0])
    hours = np.arange(1, 7)
    out = outlook_bucket.backwards_sum(leads, np.array([0.5, 0.0, 1.0, 3.0]), hours)
    assert out.tolist() == [0.5, 0.0, 1.0, 1.0, 1.0, 1.0]
    # a 6-hourly model: its first total covers the run's first six hours
    out = outlook_bucket.backwards_sum(np.array([6.0, 12.0]), np.array([6.0, 12.0]), hours)
    assert out.tolist() == [1.0] * 6


def test_hermite_and_linear_keep_the_native_values_and_fill_between():
    leads = np.array([3.0, 6.0, 9.0, 12.0])
    values = np.array([10.0, 13.0, 16.0, 19.0])
    hours = np.arange(1, 14)
    out = outlook_bucket.hermite(leads, values, hours)
    assert np.isnan(out[:2]).all() and np.isnan(out[12])  # outside the run's leads
    assert out[2::3].tolist() == [10.0, 13.0, 16.0, 19.0]
    assert out[6] == pytest.approx(14.0)  # a straight line stays straight inside
    out = outlook_bucket.linear(leads, np.array([0.0, 30.0, 30.0, 90.0]), hours)
    assert out[3] == pytest.approx(10.0) and out[10] == pytest.approx(70.0)
    # a wind speed never goes below 0
    out = outlook_bucket.hermite(leads, np.array([5.0, 0.0, 0.0, 5.0]), hours, low=0.0)
    assert np.nanmin(out) == 0.0


def test_solar_interpolation_keeps_hourly_radiation():
    leads = np.arange(1.0, 25.0)
    noon = np.array([max(0.0, 600 * np.sin((h - 6) / 12 * np.pi)) for h in leads])
    out = outlook_bucket.solar_backwards(leads, noon, leads, RUN, *PRAGUE)
    assert out.tolist() == noon.tolist()


def test_solar_interpolation_of_three_hourly_means():
    leads = np.arange(3.0, 25.0, 3)
    clear = np.array(
        [
            outlook_bucket.solar_factor(RUN.timestamp() + 3600 * h, 3 * 3600, *PRAGUE) * 900
            for h in leads
        ]
    )
    hours = np.arange(1, 25)
    out = outlook_bucket.solar_backwards(leads, clear, hours, RUN, *PRAGUE)
    # a constant clearness index: each hour at that index of its own solar factor
    expect = [
        outlook_bucket.solar_factor(RUN.timestamp() + 3600 * h, 3600, *PRAGUE) * 900 for h in hours
    ]
    assert np.nansum(np.abs(out - expect)) < 1.0
    # the 3 h means are kept (to the interpolation's error)
    assert out[6:9].mean() == pytest.approx(clear[2], rel=0.02)


def test_sunshine_from_direct_radiation():
    noon = RUN.replace(hour=12).timestamp()
    assert outlook_bucket.sunshine(0.0, noon, *PRAGUE) == 0.0
    assert outlook_bucket.sunshine(500.0, noon, *PRAGUE) == pytest.approx(3600)
    assert outlook_bucket.sunshine(500.0, RUN.replace(hour=1).timestamp(), *PRAGUE) == 0.0
    # DNI between 60 and 180 W/m²: part of the hour
    weak = outlook_bucket.sunshine(40.0, noon, *PRAGUE)
    assert 0 < weak < 3600
    assert outlook_bucket.diffuse(100.0, RUN.replace(hour=1).timestamp(), *PRAGUE) == 100.0
    assert 0 < outlook_bucket.diffuse(600.0, noon, *PRAGUE) < 600.0


def _rows(run, leads, temperature, station="CZ0100", **extra):
    n = len(leads)
    data = {
        "run": [run] * n,
        "model": "m",
        "station_id": station,
        "lead_h": leads,
        "valid_time": [run + timedelta(hours=h) for h in leads],
        "temperature_2m": temperature,
        "precipitation": extra.get("precipitation", [0.0] * n),
        "wind_speed_10m": [3.0] * n,
        "cloud_cover": extra.get("cloud_cover", [50.0] * n),
        "shortwave_radiation": [0.0] * n,
        "sunshine_duration": extra.get("sunshine_duration", [None] * n),
    }
    return pl.DataFrame(data, schema_overrides={"lead_h": pl.Int16})


def test_hourly_and_stitch_take_each_hour_from_the_newest_run():
    cells = pl.DataFrame(
        {"bucket_model": ["b"], "station_id": ["CZ0100"], "grid_lat": [50.0], "grid_lon": [14.5]}
    )
    source = bucket.Source("b")
    old = outlook_bucket.hourly(
        _rows(RUN - timedelta(hours=6), [3, 6, 9, 12], [1.0, 1.0, 1.0, 1.0]), cells, source, "m"
    )
    new = outlook_bucket.hourly(_rows(RUN, [1, 2, 3], [5.0, 5.0, 5.0]), cells, source, "m")
    series = outlook_bucket.stitch([new, old])
    by_time = dict(series.select("time", "temperature_2m").rows())
    assert by_time[RUN - timedelta(hours=3)] == 1.0  # before the new run: the old one
    assert by_time[RUN] == 1.0  # the new run starts at lead 1
    assert by_time[RUN + timedelta(hours=2)] == 5.0
    assert by_time[RUN + timedelta(hours=6)] == 1.0  # after the new run's end
    assert series["sunshine_duration"].drop_nulls().max() == 0.0  # the night: no sun


def test_candidate_runs_three_hourly_where_the_bucket_has_them():
    catalogue = {m.id: m for m in models.enabled_models()}
    now = datetime(2026, 10, 20, 10, 50, tzinfo=UTC)
    d2 = outlook_bucket.candidate_runs(catalogue["dwd_icon_d2"], now)
    assert d2[:3] == [now.replace(hour=h, minute=0) for h in (9, 6, 3)]
    # ICON-EU's runs in between reach 30 h: complete at that
    assert bucket.SOURCES["dwd_icon_eu"].horizon(9) == 30
    assert bucket.SOURCES["dwd_icon_eu"].horizon(6) == 120
    ifs = outlook_bucket.candidate_runs(catalogue["ecmwf_ifs"], now)
    assert ifs[:2] == [now.replace(hour=6, minute=0), now.replace(hour=0, minute=0)]
    assert ifs[-1] >= now - timedelta(hours=outlook_bucket.LOOKBACK_H + 1)


def test_gather_asks_the_api_only_for_models_the_bucket_lacks(monkeypatch):
    points = combine.okres_points().filter(pl.col("code") == "CZ0100")
    times = [RUN + timedelta(hours=h) for h in range(3)]
    have = pl.DataFrame(
        {
            "okres": "CZ0100",
            "time": times,
            "model": "dwd_icon",
            **{v: [1.0, 2.0, 3.0] for v in outlook.VARIABLES},
        },
        schema=outlook_bucket.EMPTY_SCHEMA,
    )

    def from_bucket(store, chosen, pts, now, days, log):
        reads = [
            outlook_bucket.ModelRead(m.id, have if m.id == "dwd_icon" else None) for m in chosen
        ]
        return have, reads

    monkeypatch.setattr(outlook_bucket, "from_bucket", from_bucket)
    asked = []

    def handler(request):
        asked.append(request.url.params["models"])
        hourly = {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times]}
        hourly |= {v: [0.5, 0.5, 0.5] for v in outlook.VARIABLES}
        return httpx.Response(200, json={"elevation": 200.0, "hourly": hourly})

    sources = {}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fc, answer = outlook.gather(
            client, object(), points, ["dwd_icon", "jma_gsm"], RUN, lambda _: None, sources
        )
    assert asked == ["jma_gsm"]
    assert sources == {"bucket": ["dwd_icon"], "api": ["jma_gsm"], "left_out": []}
    assert sorted(fc["model"].unique()) == ["dwd_icon", "jma_gsm"]
    assert answer[0]["elevation"] == 217.0  # the point's, as the API answers it


def test_the_api_fallback_stays_within_its_budget():
    # 77 okresy: five models at most, ~193 calls; four runs a day <= 800
    assert outlook.cost(77, 5) <= outlook.MAX_FALLBACK_CALLS < outlook.cost(77, 6)
