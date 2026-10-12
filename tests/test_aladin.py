import bz2
from datetime import UTC, datetime
from pathlib import Path

import eccodes
import httpx
import numpy as np
import polars as pl
import pytest

from meteoverdict import aladin

FIXTURES = Path(__file__).parent / "fixtures" / "chmi" / "aladin"
OROGRAPHY = FIXTURES / "ALADCZ1K4opendata_2026101100_SURFGEOPOTENTIEL.grb.bz2"
LISTING = (FIXTURES / "listing-CZ_1km-00.html").read_text(encoding="utf-8")
CZ = aladin.DOMAINS[0]
RUN = datetime(2026, 10, 11, 0, tzinfo=UTC)
STATIONS = pl.DataFrame(
    {
        "id": ["0-20000-0-11520", "0-20000-0-11406", "0-20000-0-04030"],
        "lat": [50.007778, 50.068333, 64.127653],  # Praha-Libuš, Cheb, Reykjavik
        "lon": [14.446944, 12.391389, -21.903905],
    }
)
GRIB_FIELDS = {"CLSTEMPERATURE": 11, "CLSWIND_SPEED": 32, "SURFPREC_TOTAL": 61}


def real_message() -> bytes:
    return bz2.decompress(OROGRAPHY.read_bytes())


def field_file(field: str, steps: range) -> bytes:
    """A GRIB1 file like ČHMÚ's: the real orography message cloned once per step.

    Value at every grid point = step + 1000 * field number, so tests can check that
    the right step and field land in the right column.
    """
    template = eccodes.codes_new_from_message(real_message())
    n = eccodes.codes_get(template, "numberOfValues")
    out = b""
    for step in steps:
        gid = eccodes.codes_clone(template)
        eccodes.codes_set(gid, "indicatorOfParameter", GRIB_FIELDS[field])
        eccodes.codes_set(gid, "timeRangeIndicator", 1 if step == 0 else 10)
        eccodes.codes_set(gid, "P2", step)
        base = 1000 * list(GRIB_FIELDS).index(field)
        eccodes.codes_set_values(gid, np.full(n, float(base + step)))
        out += eccodes.codes_get_message(gid)
        eccodes.codes_release(gid)
    eccodes.codes_release(template)
    return bz2.compress(out)


@pytest.fixture(scope="module")
def server_files() -> dict[str, bytes]:
    files = {f: field_file(f, range(0, 4)) for f in ("CLSTEMPERATURE", "CLSWIND_SPEED")}
    files["SURFPREC_TOTAL"] = field_file("SURFPREC_TOTAL", range(1, 4))  # no step 0, as served
    files["SURFGEOPOTENTIEL"] = OROGRAPHY.read_bytes()
    return files


def mock_server(server_files, listing=LISTING, fail=()) -> tuple[httpx.Client, list[str]]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        if path.endswith("/00/"):
            return httpx.Response(200, text=listing)
        if path.endswith("/"):
            return httpx.Response(200, text="<html></html>")
        for field, body in server_files.items():
            if path.endswith(f"_{field}.grb.bz2") and field not in fail:
                return httpx.Response(200, content=body)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_names_and_urls():
    assert aladin.file_url(CZ, RUN, "CLSTEMPERATURE") == (
        "https://opendata.chmi.cz/meteorology/weather/nwp_aladin/CZ_1km/00/"
        "ALADCZ1K4opendata_2026101100_CLSTEMPERATURE.grb.bz2"
    )
    assert aladin.archive_name(CZ, RUN) == "chmi_aladin_cz_1km_2026101100.parquet"
    assert aladin.release_tag(RUN) == "aladin-2026-10"


def test_available_runs_need_every_field(server_files):
    # the real listing also has 2026101000, but only its temperature file
    client, _ = mock_server(server_files)
    assert aladin.available_runs(client, CZ) == [RUN]


def test_download_handles_multi_stream_bz2(tmp_path):
    body = bz2.compress(b"GRIB-part-1") + bz2.compress(b"GRIB-part-2")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    )
    out = aladin.download_bz2(client, "https://example.test/x.bz2", tmp_path / "x")
    assert out.read_bytes() == b"GRIB-part-1GRIB-part-2"


def test_real_grid_and_nearest_points(tmp_path):
    path = tmp_path / "oro.grb"
    path.write_bytes(real_message())
    lats, lons, geopotential = aladin.grid_coordinates(path)
    assert lats.size == 501 * 290
    assert (lats.min(), lats.max(), lons.min(), lons.max()) == pytest.approx(
        (48.5, 51.098, 12.0, 18.995)
    )
    index, distance = aladin.nearest_grid_points(
        lats, lons, STATIONS["lat"].to_numpy(), STATIONS["lon"].to_numpy()
    )
    # 1 km grid: nearest point within ~0.7 km; Reykjavik is outside the domain
    assert distance[0] < 0.8 and distance[1] < 0.8
    assert distance[2] > aladin.MAX_DISTANCE_KM
    # model terrain at Praha-Libuš (station 302 m) is a few metres off
    assert geopotential[index[0]] / aladin.GRAVITY == pytest.approx(302, abs=30)


def test_extract_run(tmp_path, server_files):
    client, _ = mock_server(server_files)
    table = aladin.extract_run(client, CZ, RUN, STATIONS, tmp_path)
    assert table["station_id"].unique().sort().to_list() == ["0-20000-0-11406", "0-20000-0-11520"]
    assert table.height == 2 * 4  # stations inside the domain x steps 0..3
    libus = table.filter(pl.col("station_id") == "0-20000-0-11520").sort("lead_h")
    assert libus["lead_h"].to_list() == [0, 1, 2, 3]
    assert libus["valid_time"].to_list() == [
        datetime(2026, 10, 11, h, tzinfo=UTC) for h in range(4)
    ]
    # synthetic values: step + 1000 * field number; temperature converted K -> °C
    assert libus["temperature_2m"].to_list() == pytest.approx([s - 273.15 for s in range(4)])
    assert libus["wind_speed_10m"].to_list() == pytest.approx([1000 + s for s in range(4)])
    assert libus["precipitation_accum"].to_list()[0] is None  # no step 0 in the file
    assert libus["precipitation_accum"].to_list()[1:] == pytest.approx([2001, 2002, 2003])
    assert libus["grid_elevation"][0] == pytest.approx(302, abs=30)
    assert not list(tmp_path.iterdir())  # GRIB files are deleted after use


def test_archive_skips_existing_and_keeps_going_on_failure(tmp_path, server_files):
    client, _ = mock_server(server_files)
    store = aladin.LocalStore(tmp_path / "archive")
    first = aladin.archive(client, store, STATIONS, domains=(CZ,), log=lambda _: None)
    assert first.archived == ["chmi_aladin_cz_1km_2026101100.parquet"]
    saved = pl.read_parquet(tmp_path / "archive" / "aladin-2026-10" / first.archived[0])
    assert saved.height == 8

    again = aladin.archive(client, store, STATIONS, domains=(CZ,), log=lambda _: None)
    assert (again.archived, again.skipped, again.failed) == ([], 1, [])

    broken, _ = mock_server(server_files, fail=("SURFPREC_TOTAL",))
    other = aladin.LocalStore(tmp_path / "other")
    failed = aladin.archive(broken, other, STATIONS, domains=(CZ,), log=lambda _: None)
    assert failed.failed == ["chmi_aladin_cz_1km_2026101100.parquet"]
    assert other.names("aladin-2026-10") == set()


def test_listing_failure_of_one_domain_does_not_stop_the_other(tmp_path, server_files):
    lambert = aladin.DOMAINS[1]
    client, _ = mock_server(server_files)
    broken = aladin.Domain(lambert.model, "Missing_Folder", lambert.prefix)

    def handler(request):
        if "Missing_Folder" in request.url.path:
            return httpx.Response(503)
        return client._transport.handle_request(request)

    flaky = httpx.Client(transport=httpx.MockTransport(handler))
    store = aladin.LocalStore(tmp_path)
    result = aladin.archive(flaky, store, STATIONS, domains=(broken, CZ), log=lambda _: None)
    assert result.failed == ["chmi_aladin_central_europe_2km listing"]
    assert result.archived == ["chmi_aladin_cz_1km_2026101100.parquet"]
