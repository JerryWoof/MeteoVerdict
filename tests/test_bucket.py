"""The bucket reader on a small fake bucket: .om files written with omfiles, served by
an httpx mock with range requests (no network)."""

import math
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import polars as pl
import pytest

from meteoverdict import bucket, partitions, runs
from meteoverdict.models import load_models

MODELS = {m.id: m for m in load_models()}
AIFS = MODELS["ecmwf_aifs025_single"]  # 6-hourly, u/v, no gusts
ICON_EU = MODELS["dwd_icon_eu"]  # hourly to 78 h, then 3-hourly
ALADIN = MODELS["chmi_aladin_cz_1km"]  # hourly to 72 h, wind speed itself
RUN = datetime(2026, 10, 15, 0, tzinfo=UTC)
LATER = RUN + timedelta(hours=30)  # old enough to be final
STATIONS = pl.DataFrame(
    {"id": ["a", "b"], "lat": [50.0, 49.0], "lon": [14.0, 17.0], "elevation": [300.0, 250.0]}
)
NY, NX = 3, 4
#: station -> (y, x, grid elevation); "b" sits on a cell without a surface height
CELLS = {"a": (1, 1, 400.0), "b": (2, 3, None)}


def cells(models=("ecmwf_aifs025_single", "dwd_icon_eu", "chmi_aladin_cz_1km"), ny=NY):
    rows = [
        (m, sid, y, x, ny, NX, 50.0, 14.0, height, 1.0)
        for m in models
        for sid, (y, x, height) in CELLS.items()
    ]
    return pl.DataFrame(rows, schema=bucket.CELL_SCHEMA, orient="row")


def leads(model, horizon=120):
    """The run's valid times (lead hours), lead 0 included, as in meta.json."""
    return [0, *bucket.native_leads(model, horizon)]


def om_file(tmp_path, values: np.ndarray) -> bytes:
    from omfiles import OmFileWriter

    path = tmp_path / f"f{len(list(tmp_path.glob('*.om')))}.om"
    writer = OmFileWriter(str(path))
    variable = writer.write_array(
        values.astype(np.float32), chunks=[1, 2, values.shape[-1]], scale_factor=100
    )
    writer.close(variable)
    return path.read_bytes()


def field(steps: int, base: float, step: float = 0.01) -> np.ndarray:
    """(y, x, t) = base + y + x / 10 + step * t."""
    y, x, t = np.meshgrid(np.arange(NY), np.arange(NX), np.arange(steps), indexing="ij")
    return base + y + x / 10 + step * t


class FakeBucket:
    """``files``: path -> bytes; ``meta``: (bucket model, run) -> lead hours. Serves
    meta.json, HEAD and range GET like S3 (403 for a missing key)."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.fail: dict[str, int] = {}  # path -> how many times to drop the connection
        self.requests = []

    def add_meta(self, bucket_model, run, lead_hours, variables=None):
        times = [f"{run + timedelta(hours=h):%Y-%m-%dT%H:%MZ}" for h in lead_hours]
        doc = {"crs_wkt": "x", "valid_times": times, "reference_time": f"{run:%Y-%m-%dT%H:%MZ}"}
        if variables is not None:  # as Open-Meteo writes it: the text of a Python list
            doc["variables"] = str(sorted(variables))
        import json

        self.files[f"{bucket.run_path(bucket_model, run)}/meta.json"] = json.dumps(doc).encode()

    def add(self, bucket_model, run, name, data: bytes):
        self.files[f"{bucket.run_path(bucket_model, run)}/{name}.om"] = data

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.lstrip("/")
        self.requests.append((request.method, path))
        if self.fail.get(path):
            self.fail[path] -= 1
            raise httpx.RemoteProtocolError("Server disconnected", request=request)
        body = self.files.get(path)
        if body is None:
            return httpx.Response(403)
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(body))})
        span = request.headers.get("range")
        if span:
            start, _, end = span.removeprefix("bytes=").partition("-")
            stop = len(body) if end == "" else int(end) + 1
            return httpx.Response(206, content=body[int(start) : stop])
        return httpx.Response(200, content=body)


def complete(fake, tmp_path, model, run=RUN, **overrides):
    """Every file of ``model``'s run in ``fake``; ``overrides``: file name -> array or
    None (left out)."""
    source = bucket.SOURCES[model.id]
    hours = leads(model, source.horizon(run.hour))
    fake.add_meta(source.bucket, run, hours)
    n = len(hours)
    arrays = {
        "temperature_2m": field(n, 10.0),
        # totals over the preceding step: the files leave out the first step, except
        # ALADIN's, which keep it (empty)
        "precipitation": field(n if model is ALADIN else n - 1, 0.1),
        "wind_speed_10m": np.full((NY, NX, n), 5.0),
        "wind_u_component_10m": np.full((NY, NX, n), 3.0),
        "wind_v_component_10m": np.full((NY, NX, n), 4.0),
        "wind_gusts_10m": field(n if model is ALADIN else n - 1, 6.0),
    }
    arrays |= overrides
    for parts in source.files().values():
        for bucket_model, name in parts:
            if arrays[name] is not None:
                fake.add(bucket_model, run, name, om_file(tmp_path, arrays[name]))
    return hours


def reader(fake, tries=3):
    client = httpx.Client(transport=httpx.MockTransport(fake))
    return bucket.Bucket(client, base="https://bucket.test", tries=tries, sleep=lambda _: None)


def read(fake, model, run=RUN, cells_=None):
    with ThreadPoolExecutor(4) as pool:
        return bucket.read_run(
            reader(fake), model, run, STATIONS, cells() if cells_ is None else cells_, pool
        )


# --- reading a model-run -----------------------------------------------------------------


def test_a_six_hourly_model_at_its_native_steps(tmp_path):
    fake = FakeBucket()
    hours = complete(fake, tmp_path, AIFS)
    fetched = read(fake, AIFS)
    assert fetched.reason == ""
    rows = fetched.rows
    assert rows.schema == pl.Schema(runs.SCHEMA)
    assert set(rows["source"]) == {"bucket"}
    a = rows.filter(pl.col("station_id") == "a").sort("lead_h")
    assert a["lead_h"].to_list() == hours[1:] == list(range(6, 121, 6))  # nothing interpolated
    assert (a["valid_time"] - a["run"]).dt.total_hours().to_list() == a["lead_h"].to_list()
    # 10 + y + x/10 + 0.01 t at (1, 1), corrected from 400 m to 300 m: + 0.65
    assert a["temperature_2m"][0] == pytest.approx(11.1 + 0.01 + 0.65, abs=0.01)
    b = rows.filter(pl.col("station_id") == "b").sort("lead_h")
    assert b["temperature_2m"][0] == pytest.approx(12.3 + 0.01, abs=0.01)  # no height: raw
    assert a["wind_speed_10m"].to_list() == pytest.approx([5.0] * a.height)  # u 3, v 4
    assert a["wind_gusts_10m"].null_count() == a.height  # AIFS has none
    # the precipitation file starts at the second time (6 h): its first value is 6 h's
    assert a["precipitation"][0] == pytest.approx(0.1 + 1.1, abs=0.01)


def test_files_of_totals_start_at_the_second_time(tmp_path):
    fake = FakeBucket()
    complete(fake, tmp_path, ICON_EU)
    rows = read(fake, ICON_EU).rows.filter(pl.col("station_id") == "a").sort("lead_h")
    leads_ = rows["lead_h"].to_list()
    assert leads_[:3] == [1, 2, 3] and 79 not in leads_ and leads_[78:80] == [81, 84]
    one = rows.row(0, named=True)
    assert one["precipitation"] == pytest.approx(1.2, abs=0.01)  # file index 0 → lead 1
    assert one["wind_gusts_10m"] == pytest.approx(7.1, abs=0.01)  # likewise the gusts
    assert one["temperature_2m"] == pytest.approx(11.1 + 0.01 + 0.65, abs=0.01)  # index 1
    late = rows.filter(pl.col("lead_h") == 81).row(0, named=True)  # time index 80
    assert late["precipitation"] == pytest.approx(1.2 + 0.79, abs=0.01)


def test_files_that_keep_the_first_step(tmp_path):
    fake = FakeBucket()
    complete(fake, tmp_path, ALADIN)
    rows = read(fake, ALADIN).rows.filter(pl.col("station_id") == "a").sort("lead_h")
    assert rows["lead_h"].to_list() == list(range(1, 73))
    assert rows["precipitation"][0] == pytest.approx(1.21, abs=0.01)  # index 1 → lead 1
    assert rows["wind_speed_10m"][0] == pytest.approx(5.0)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("no meta", "no meta.json"),
        ("staged", "72 of 92 lead hours written"),  # ECMWF-style: first only to 72 h
        ("no file", "wind_v_component_10m.om missing"),
        ("short file", "temperature_2m.om: 60 time steps"),
        ("hot", "implausible temperature_2m"),
        ("no gusts", "wind_gusts_10m at 0 of 2 stations"),
        ("grid", "grid (3, 4) not in the cells file"),
    ],
)
def test_incomplete_model_runs_are_not_taken(tmp_path, change, reason):
    fake = FakeBucket()
    n = len(leads(ICON_EU))
    overrides = {
        "no file": {"wind_v_component_10m": None},
        "short file": {"temperature_2m": field(60, 10.0)},
        "hot": {"temperature_2m": field(n, 99.0)},
        "no gusts": {"wind_gusts_10m": np.full((NY, NX, n - 1), np.nan)},
    }.get(change, {})
    complete(fake, tmp_path, ICON_EU, **overrides)
    if change == "no meta":
        del fake.files[f"{bucket.run_path('dwd_icon_eu', RUN)}/meta.json"]
    if change == "staged":
        fake.add_meta("dwd_icon_eu", RUN, range(73))
    fetched = read(fake, ICON_EU, cells_=cells(ny=5) if change == "grid" else None)
    assert fetched.rows is None
    assert reason in fetched.reason


def test_a_model_not_in_the_bucket():
    other = MODELS["gem_regional"]
    assert read(FakeBucket(), other).reason == "not in the bucket"


# --- the further variables ----------------------------------------------------------------

#: ICON-EU's further files in the fake run (the rest of ``bucket.EXTRA`` it does not list)
ICON_EXTRA = {
    "relative_humidity_2m": 80.0,
    "pressure_msl": 1013.0,
    "direct_radiation": 300.0,
    "diffuse_radiation": 100.0,
    "cloud_cover": 50.0,
    "snowfall_water_equivalent": 1.0,  # mm → 0.7 cm
    "soil_temperature_0cm": 5.0,
    "visibility": -5.0,  # implausible: null
}


def with_extras(fake, tmp_path, model=ICON_EU, extra=ICON_EXTRA, missing=()):
    """``complete`` plus constant further files (listed in meta.json; ``missing``:
    listed, but no file)."""
    hours = complete(fake, tmp_path, model)
    source = bucket.SOURCES[model.id]
    listed = {*extra, "temperature_2m", "precipitation", "wind_u_component_10m"}
    fake.add_meta(source.bucket, RUN, hours, variables=listed | {"wind_v_component_10m"})
    for name, value in extra.items():
        if name not in missing:
            data = np.full((NY, NX, len(hours)), value)
            fake.add(source.bucket, RUN, name, om_file(tmp_path, data))
    return hours


def test_further_variables_are_read_and_derived_like_the_api(tmp_path):
    fake = FakeBucket()
    with_extras(fake, tmp_path)
    with ThreadPoolExecutor(4) as pool:
        fetched = bucket.read_run(reader(fake), ICON_EU, RUN, STATIONS, cells(), pool, extra=True)
    assert fetched.extra_complete
    rows = fetched.rows
    assert rows.schema == pl.Schema(runs.SCHEMA)
    a = rows.filter(pl.col("station_id") == "a").sort("lead_h").row(0, named=True)
    assert a["relative_humidity_2m"] == 80
    # from the temperature at the station's elevation (11.76 °C) and the humidity
    assert a["dew_point_2m"] == pytest.approx(8.4)  # 8.42, to 1 decimal
    assert a["wind_direction_10m"] == 217  # u 3, v 4: from the south-west
    assert a["shortwave_radiation"] == 400  # direct + diffuse
    assert a["pressure_msl"] == pytest.approx(1013.0)
    assert a["cloud_cover"] == 50 and a["snowfall"] == pytest.approx(0.7)
    assert a["surface_temperature"] == pytest.approx(5.7)  # 5 + 0.65, moved like temperature
    assert a["visibility"] is None  # implausible
    assert a["cape"] is None and a["sunshine_duration"] is None  # not listed
    # without extra (the obce): none of them, the rest the same
    plain = read(fake, ICON_EU).rows
    assert plain.select(runs.EXTRA_VARIABLES).null_count().sum_horizontal().item() == (
        plain.height * len(runs.EXTRA_VARIABLES)
    )
    assert plain.select(runs.VARIABLES).equals(rows.select(runs.VARIABLES))


def test_a_listed_further_file_not_written_yet_leaves_the_run_to_read_again(tmp_path):
    fake = FakeBucket()
    with_extras(fake, tmp_path, missing=("cloud_cover",))
    with ThreadPoolExecutor(4) as pool:
        fetched = bucket.read_run(reader(fake), ICON_EU, RUN, STATIONS, cells(), pool, extra=True)
    assert fetched.rows is not None and not fetched.extra_complete
    assert fetched.rows["cloud_cover"].null_count() == fetched.rows.height
    assert fetched.rows["relative_humidity_2m"].null_count() == 0


def test_derivations():
    t = np.array([20.0, -5.0], dtype=np.float32)
    rh = np.array([50.0, 90.0], dtype=np.float32)
    td = bucket._dew_point(t, rh)
    assert td[0] == pytest.approx(9.26, abs=0.01)
    assert bucket._relative_humidity(t, td) == pytest.approx(rh, abs=0.01)
    u = np.array([0.0, -1.0, 0.0, 1.0])
    v = np.array([-1.0, 0.0, 1.0, 0.0])
    assert bucket._direction(u, v).tolist() == pytest.approx([0, 90, 180, 270])
    assert bucket._hpa(np.array([101300.0, 1013.0])).tolist() == [1013.0, 1013.0]
    assert bucket.meta_variables({"variables": "['cape', 'rain']"}) == {"cape", "rain"}
    assert bucket.meta_variables({"variables": ["cape"]}) == {"cape"}
    assert bucket.meta_variables({}) == set()


def test_extra_files_per_model():
    gfs = bucket.SOURCES["ncep_gfs_global"]
    found = gfs.extra_files(
        {
            "ncep_gfs013": {"relative_humidity_2m", "temperature_2m", "wind_u_component_10m"}
            | {"wind_v_component_10m", "shortwave_radiation"},
            "ncep_gfs025": {"pressure_msl", "cape", "visibility"},
        }
    )
    assert {v: m for v, (m, _) in found.items()} == {
        "relative_humidity_2m": "ncep_gfs013",
        "dew_point_2m": "ncep_gfs013",
        "wind_direction_10m": "ncep_gfs013",
        "shortwave_radiation": "ncep_gfs013",
        "pressure_msl": "ncep_gfs025",  # from the other GFS grid, as the gusts
        "cape": "ncep_gfs025",
        "visibility": "ncep_gfs025",
    }
    aladin = bucket.SOURCES["chmi_aladin_cz_1km"].extra_files(
        {"chmi_aladin_cz_1km": {"wind_direction_10m", "dew_point_2m", "relative_humidity_2m"}}
    )
    assert aladin["dew_point_2m"][1].files == ("dew_point_2m",)  # its own file first
    assert aladin["wind_direction_10m"][1].files == ("wind_direction_10m",)
    assert set(bucket.EXTRA) == set(runs.EXTRA_VARIABLES)
    assert set(bucket.EXTRA_PLAUSIBLE) == set(runs.EXTRA_VARIABLES)


# --- HTTP ------------------------------------------------------------------------------


def test_dropped_connections_are_retried(tmp_path):
    fake = FakeBucket()
    complete(fake, tmp_path, AIFS)
    path = f"{bucket.run_path('ecmwf_aifs025_single', RUN)}/meta.json"
    fake.fail[path] = 2
    om = f"{bucket.run_path('ecmwf_aifs025_single', RUN)}/temperature_2m.om"
    fake.fail[om] = 2
    assert read(fake, AIFS).rows is not None
    assert [r for r in fake.requests if r[1] == path].__len__() == 3


def test_errors_that_persist_propagate_and_missing_keys_are_none():
    def down(request):
        return httpx.Response(503)

    source = bucket.Bucket(
        httpx.Client(transport=httpx.MockTransport(down)), tries=2, sleep=lambda _: None
    )
    with pytest.raises(httpx.HTTPStatusError):
        source.meta("dwd_icon_eu", RUN)
    assert reader(FakeBucket()).meta("dwd_icon_eu", RUN) is None
    assert reader(FakeBucket()).open("data_run/x.om") is None


def test_range_requests_follow_fsspec():
    seen = []

    def handler(request):
        seen.append(request.headers.get("range"))
        return httpx.Response(206, content=b"x")

    source = bucket.Bucket(httpx.Client(transport=httpx.MockTransport(handler)))
    source.cat_file("https://b/f.om", 10, 20)  # end excluded, as in fsspec
    source.cat_file("https://b/f.om", 5)
    assert seen == ["bytes=10-19", "bytes=5-"]


# --- the collection -----------------------------------------------------------------------


def collect(fake, tmp_path, now=LATER, models=(AIFS, ICON_EU), **kw):
    return bucket.collect(
        reader(fake),
        STATIONS,
        list(models),
        tmp_path,
        now,
        cells=cells(),
        runs_=kw.pop("runs_", [RUN]),
        **kw,
    )


def test_collect_stores_complete_runs_and_records_the_bucket_gaps(tmp_path):
    fake = FakeBucket()
    complete(fake, tmp_path, AIFS)
    result = collect(fake, tmp_path)
    assert result.stored == {"2026101500": {"ecmwf_aifs025_single"}}
    assert result.missing == {"2026101500": {"dwd_icon_eu": "no meta.json (dwd_icon_eu)"}}
    state = runs.State.load(tmp_path / runs.STATE_NAME)
    assert state.fetched == {"2026101500": {"ecmwf_aifs025_single"}}
    assert state.bucket_missing == {"2026101500": {"dwd_icon_eu"}}
    # the API is asked for that model only
    assert [m.id for m in state.api_todo(RUN, [AIFS, ICON_EU], LATER)] == ["dwd_icon_eu"]
    stored = pl.read_parquet(tmp_path / "runs" / "2026-10.parquet")
    assert stored.height == 2 * 20
    # stored once: nothing is read again
    before = len(fake.requests)
    assert collect(fake, tmp_path).stored == {}
    assert len(fake.requests) == before
    assert "Missing in the bucket (asked from the API instead): 2026101500: dwd_icon_eu" in (
        bucket.summary(result)
    )


def test_a_young_incomplete_run_waits(tmp_path):
    result = collect(FakeBucket(), tmp_path, now=RUN + timedelta(hours=5))
    assert set(result.waiting["2026101500"]) == {"ecmwf_aifs025_single", "dwd_icon_eu"}
    assert runs.State.load(tmp_path / runs.STATE_NAME).bucket_missing == {}


def test_a_model_run_from_the_bucket_replaces_the_api_rows_of_it(tmp_path):
    fake = FakeBucket()
    complete(fake, tmp_path, AIFS)
    hourly = [  # as the API stored it before: every hour, no source
        (RUN, AIFS.id, sid, h, RUN + timedelta(hours=h), 1.0, 0.0, 1.0, None)
        for sid in "ab"
        for h in range(1, 121)
    ]
    other = [(RUN, "jma_gsm", "a", 6, RUN + timedelta(hours=6), 1.0, 0.0, 1.0, None)]
    old = pl.DataFrame(hourly + other, schema=runs.HOURLY_SCHEMA, orient="row")
    partitions.write_monthly(old, tmp_path / "runs", runs.KEYS, "run")
    collect(fake, tmp_path, models=[AIFS])
    stored = pl.read_parquet(tmp_path / "runs" / "2026-10.parquet")
    aifs = stored.filter(pl.col("model") == AIFS.id)
    assert aifs.height == 40 and set(aifs["source"]) == {"bucket"}  # no hourly rows left
    jma = stored.filter(pl.col("model") == "jma_gsm")
    assert jma.height == 1 and jma["cloud_cover"].to_list() == [None]  # an old row: null


def test_stored_model_runs_are_read_again_for_the_further_variables(tmp_path):
    fake = FakeBucket()
    complete(fake, tmp_path, ICON_EU)  # a run stored before: its meta lists nothing more
    assert collect(fake, tmp_path, models=[ICON_EU]).stored == {"2026101500": {"dwd_icon_eu"}}
    state = runs.State.load(tmp_path / runs.STATE_NAME)
    assert state.extra == {"2026101500": {"dwd_icon_eu"}}  # nothing listed: settled
    state.extra = {}  # as in the state before 2026-10-19
    state.save()
    with_extras(fake, tmp_path)
    result = collect(fake, tmp_path, models=[ICON_EU])
    assert result.stored == {} and result.refilled == {"2026101500": {"dwd_icon_eu"}}
    assert "1 stored ones read again" in bucket.summary(result)
    stored = pl.read_parquet(tmp_path / "runs" / "2026-10.parquet")
    assert stored.height == 2 * 92 and stored["relative_humidity_2m"].null_count() == 0
    assert runs.State.load(tmp_path / runs.STATE_NAME).extra == {"2026101500": {"dwd_icon_eu"}}
    before = len(fake.requests)
    assert collect(fake, tmp_path, models=[ICON_EU]).refilled == {}  # settled: not again
    assert len(fake.requests) == before


def test_a_young_run_with_a_further_file_missing_is_read_again_later(tmp_path):
    fake = FakeBucket()
    with_extras(fake, tmp_path, missing=("cloud_cover",))
    young = RUN + timedelta(hours=5)
    assert collect(fake, tmp_path, now=young, models=[ICON_EU]).stored
    assert runs.State.load(tmp_path / runs.STATE_NAME).extra == {}
    fake.add("dwd_icon_eu", RUN, "cloud_cover", om_file(tmp_path, np.full((NY, NX, 93), 40.0)))
    result = collect(fake, tmp_path, now=young + timedelta(hours=6), models=[ICON_EU])
    assert result.refilled == {"2026101500": {"dwd_icon_eu"}}
    stored = pl.read_parquet(tmp_path / "runs" / "2026-10.parquet")
    assert set(stored["cloud_cover"]) == {40.0}
    assert runs.State.load(tmp_path / runs.STATE_NAME).extra == {"2026101500": {"dwd_icon_eu"}}


def test_api_rows_not_in_the_bucket_are_settled_once_final(tmp_path):
    state = runs.State(tmp_path / runs.STATE_NAME, fetched={"2026101500": {"dwd_icon_eu"}})
    state.bucket_missing = {"2026101500": {"dwd_icon_eu"}}
    state.save()
    result = collect(FakeBucket(), tmp_path, models=[ICON_EU])
    assert result.refilled == {} and result.missing == {}
    after = runs.State.load(tmp_path / runs.STATE_NAME)
    assert after.extra == {"2026101500": {"dwd_icon_eu"}}
    assert after.fetched == {"2026101500": {"dwd_icon_eu"}}  # the API's rows stay


def test_collect_gives_up_when_the_bucket_keeps_failing(tmp_path):
    def down(request):
        raise httpx.ConnectError("unreachable", request=request)

    source = bucket.Bucket(
        httpx.Client(transport=httpx.MockTransport(down)), tries=1, sleep=lambda _: None
    )
    starts = [RUN - timedelta(hours=6 * i) for i in range(30)]
    result = bucket.collect(source, STATIONS, [AIFS], tmp_path, LATER, cells=cells(), runs_=starts)
    assert "keeps failing" in result.stopped
    assert len(result.failed) == bucket.MAX_ERRORS
    assert runs.State.load(tmp_path / runs.STATE_NAME).bucket_missing == {}


def test_collect_stops_at_its_time_limit(tmp_path):
    ticks = iter(range(0, 10_000, 100))
    result = collect(
        FakeBucket(),
        tmp_path,
        runs_=[RUN, RUN - timedelta(hours=6)],
        max_minutes=1,
        clock=lambda: next(ticks),
    )
    assert "time limit" in result.stopped


# --- the committed cells and the grid ------------------------------------------------------


def test_committed_cells_cover_every_station_and_bucket_model():
    committed = bucket.load_cells()
    stations = runs.load_stations()
    assert set(committed["bucket_model"]) == set(bucket.bucket_models())
    per_model = committed.group_by("bucket_model").agg(
        pl.col("station_id").n_unique().alias("n"),
        pl.col("ny").n_unique().alias("grids"),
        pl.col("grid_distance_km").max().alias("far"),
    )
    assert set(per_model["n"]) == {stations.height}
    assert set(per_model["grids"]) == {1}
    assert per_model["far"].max() < 40  # nearest cells (JMA GSM: 0.5°, up to ~33 km)
    # a surface height everywhere (water cells replaced by land ones) except where a
    # model has no data at all: ICON-D2 at its domain's edge in the far east
    no_height = committed.filter(pl.col("grid_elevation").is_null())
    assert no_height.select("bucket_model", "station_id").rows() == [
        ("dwd_icon_d2", "0-203-0-11792")
    ]
    assert committed.select("bucket_model", "station_id").is_unique().all()


WKT = (
    'GEOGCRS["WGS 84",DATUM["World Geodetic System 1984",ELLIPSOID["WGS 84",6378137,'
    '298.257223563]],CS[ellipsoidal,2],AXIS["latitude",north],AXIS["longitude",east],'
    'ANGLEUNIT["degree",0.0174532925199433]USAGE[SCOPE["grid"],BBOX[29.5,-23.5,70.5,62.5]]]'
)


def test_regular_grid_nearest_cell():
    grid = bucket.Grid("dwd_icon_eu", WKT, (657, 1377, 93))  # 0.0625°
    y, x = grid.nearest(50.0078, 14.4469)
    lat, lon = grid.latlon((y, x))
    assert abs(lat - 50.0078) <= 0.0625 / 2 and abs(lon - 14.4469) <= 0.0625 / 2
    assert (y, x) == (round((50.0078 - 29.5) / 0.0625), round((14.4469 + 23.5) / 0.0625))
    assert len(grid.around((0, 0))) == 4 and len(grid.around((5, 5))) == 9


def test_o1280_grid_nearest_cell():
    grid = bucket.Grid("ecmwf_ifs", "", (1, bucket.O1280_POINTS, 145))
    index = grid.nearest(50.0078, 14.4469)
    assert index[0] == 0
    lat, lon = grid.latlon(index)
    assert bucket.distance_km(50.0078, 14.4469, lat, lon) < 6  # ~9 km grid
    assert grid.latlon(grid.nearest(lat, lon)) == (lat, lon)
    assert grid.nearest(-89.99, 0.0)[1] == bucket.O1280_POINTS - 20  # last ring: 20 points


# --- the one-off import of the harvest ------------------------------------------------------


def harvest_rows(model, leads_, precipitation):
    return pl.DataFrame(
        {
            "run": RUN,
            "model": model,
            "station_id": "a",
            "lead_h": leads_,
            "valid_time": [RUN + timedelta(hours=h) for h in leads_],
            "temperature_2m": 10.0,
            "precipitation": precipitation,
            "wind_speed_10m": 2.0,
            "wind_gusts_10m": 3.0,
            "temperature_2m_grid": 9.0,
            "om_model": model,
        }
    ).cast({"lead_h": pl.Int16, "run": pl.Datetime("us", "UTC")})


def test_from_harvest_moves_the_early_precipitation():
    early = harvest_rows("dwd_icon_eu", [0, 1, 2], [0.5, 0.7, 0.0])
    right = harvest_rows("chmi_aladin_cz_1km", [0, 1, 2], [None, 0.5, -0.1])
    out = bucket.from_harvest(pl.concat([early, right])).collect().sort("model", "lead_h")
    assert out.schema == pl.Schema(runs.SCHEMA)
    assert out.filter(pl.col("model") == "dwd_icon_eu")["precipitation"].to_list() == [
        pytest.approx(0.5),
        pytest.approx(0.7),
    ]
    aladin = out.filter(pl.col("model") == "chmi_aladin_cz_1km")["precipitation"].to_list()
    assert aladin == [pytest.approx(0.5), 0.0]  # in place; below 0 → 0
    assert set(out["lead_h"]) == {1, 2} and set(out["source"]) == {"bucket"}


def test_complete_runs_and_merge_prefer_the_bucket():
    good = harvest_rows("ecmwf_aifs025_single", list(range(0, 121, 6)), 0.1)
    bad = harvest_rows("jma_gsm", list(range(0, 121, 6)), 0.1).with_columns(
        pl.lit(None, pl.Float64).alias("wind_speed_10m")
    )
    rows = bucket.from_harvest(pl.concat([good, bad])).collect()
    check = bucket.complete_runs(rows, list(MODELS.values()), 1)
    assert check.select("model", "complete").rows() == [
        ("ecmwf_aifs025_single", True),
        ("jma_gsm", False),
    ]
    assert check["reason"][1] == "wind_speed_10m at 0 of 1 stations"
    hourly = pl.DataFrame(
        [(RUN, "ecmwf_aifs025_single", "a", h, RUN, 1.0, 0.0, 1.0, None) for h in range(1, 121)]
        + [(RUN, "dwd_icon", "a", 1, RUN, 1.0, 0.0, 1.0, None)],
        schema=runs.HOURLY_SCHEMA,
        orient="row",
    )
    merged = bucket.merge(hourly, rows.filter(pl.col("model") == "ecmwf_aifs025_single"))
    assert merged.filter(pl.col("model") == "ecmwf_aifs025_single").height == 20
    assert merged.filter(pl.col("model") == "dwd_icon").height == 1
    assert bucket.merge(None, rows).height == rows.height


def test_native_leads_and_horizons():
    assert bucket.native_leads(AIFS, 120) == list(range(6, 121, 6))
    assert len(bucket.native_leads(ICON_EU, 120)) == 78 + 14
    ukmo = bucket.SOURCES["ukmo_global_deterministic_10km"]
    assert (ukmo.horizon(0), ukmo.horizon(6)) == (120, 60)
    assert set(bucket.SOURCES) == {m.id for m in MODELS.values() if m.enabled}
    assert bucket.SOURCES["ncep_gfs_global"].files()["wind_gusts_10m"] == [
        ("ncep_gfs025", "wind_gusts_10m")
    ]
    assert "wind_gusts_10m" not in bucket.SOURCES["jma_gsm"].files()
    assert math.isclose(bucket.LAPSE_RATE * 100, 0.65)


def test_points_are_read_in_row_segments():
    cells = [(3, 10), (3, 12), (3, 200), (1, 5), (3, 10)]
    assert bucket.segments(cells, gap=64) == [(1, 5, 5), (3, 10, 12), (3, 200, 200)]
    assert bucket.segments([(0, 0), (0, 64), (0, 129)], gap=64) == [(0, 0, 64), (0, 129, 129)]
