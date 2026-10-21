import io
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from meteoverdict import radar, satellite, storms
from meteoverdict.cli import app

FIXTURES = Path(__file__).parent / "fixtures" / "chmi"
MAXZ_1030 = (FIXTURES / "radar" / "T_PABV23_C_OKPR_20261015103000.hdf").read_bytes()
MAXZ_1035 = (FIXTURES / "radar" / "T_PABV23_C_OKPR_20261015103500.hdf").read_bytes()
ECHOTOP = (FIXTURES / "radar" / "T_PADV23_C_OKPR_20261015103500.hdf").read_bytes()
SAT_JPG = (FIXTURES / "satellite" / "202610151030_geo_wv062_ce.jpg").read_bytes()
SAT_LISTING = (FIXTURES / "satellite" / "listing-wv062.html").read_text(encoding="utf-8")
T0 = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
SHAPE = (radar.GRID_ROWS, radar.GRID_COLS)


def test_scales():
    maxz = storms.SCALES["maxz"]
    assert [row[0] for row in maxz] == list(range(4, 61, 4))
    assert maxz[13][:2] == [56, "#a00000"] and maxz[13][3:] == ["hail possible", "možné kroupy"]
    assert storms.rain_rate(23.0) == pytest.approx(1.0, abs=0.05)  # Marshall-Palmer
    assert maxz[9][2] == pytest.approx(11.5) and maxz[9][3] == "heavy"
    assert maxz[0][3:] == ["drizzle", "mrholení"]
    assert storms.SCALES["merge1h"][0] == [0.1, "#380070"]
    edges = [row[0] for row in storms.SCALES["echotop"]]
    assert edges == sorted(edges) and 10 in edges
    json.dumps(storms.SCALES)  # serialisable


def test_read_composites_and_echotop_png():
    dbz = storms.read_composite(MAXZ_1035)
    assert dbz.quantity == "DBZH" and dbz.values.shape == SHAPE
    assert dbz.time == datetime(2026, 10, 15, 10, 35, tzinfo=UTC)
    assert np.nanmax(dbz.values) == pytest.approx(23.0)
    assert np.nanmin(dbz.values) == -32.0 and np.isnan(dbz.values).any()
    top = storms.read_composite(ECHOTOP)
    assert top.quantity == "HGHT" and np.nanmax(top.values) == pytest.approx(8.6)  # km
    image = Image.open(io.BytesIO(storms.echotop_png(top)))
    assert image.size == (radar.GRID_COLS, radar.GRID_ROWS) and image.mode == "P"
    index = np.array(image)
    assert ((index > 0) == (top.values > 0)).all()  # transparent without echo or data
    rgba = np.array(image.convert("RGBA"))
    row, col = np.unravel_index(np.nanargmax(top.values), SHAPE)
    assert bytes(rgba[row, col, :3]).hex() == "fed976"  # 8 to 10 km
    with pytest.raises(ValueError, match="quantity"):
        storms.read_composite(radar_merge())


def radar_merge() -> bytes:
    return (FIXTURES / "radar" / "T_PASV23_C_OKPR_20261015101000.hdf").read_bytes()


def blob(center: tuple[float, float], peak: float = 50.0, radius: float = 6.0) -> np.ndarray:
    """A dBZ field: one round echo (peak in the middle) on no echo (-32)."""
    rows, cols = np.mgrid[0 : SHAPE[0], 0 : SHAPE[1]].astype(np.float32)
    distance = np.hypot(rows - center[0], cols - center[1])
    field = peak - 3.0 * distance
    field[distance > radius * 3] = -32.0
    return field.astype(np.float32)


def rain_field(shift: tuple[float, float] = (0, 0)) -> np.ndarray:
    """A textured rain area, moved by (rows, columns)."""
    rng = np.random.default_rng(1)
    noise = rng.normal(size=(48, 76)).astype(np.float32)
    big = np.array(Image.fromarray(noise).resize((SHAPE[1] + 40, SHAPE[0] + 40), Image.BICUBIC))
    r0, c0 = 20 - int(shift[0]), 20 - int(shift[1])
    field = 25 + 12 * big[r0 : r0 + SHAPE[0], c0 : c0 + SHAPE[1]]
    field[:, :150] = -32.0  # no echo in the west
    return field.astype(np.float32)


def test_motion_follows_the_echoes():
    before, after = rain_field(), rain_field((-2, 3))  # 3 cells east, 2 north
    flow = storms.dense_flow(before, after)
    u, v = storms.coarse_motion(flow, before, after)
    assert u.shape == (12, 19)
    east = u[:, 8:]
    assert np.median(east) == pytest.approx(3.0, abs=0.4)
    assert np.median(v[:, 8:]) == pytest.approx(-2.0, abs=0.4)
    assert np.isfinite(u).all() and np.isfinite(v).all()  # filled in the west too
    assert abs(u[:, 0].mean()) > 1.0  # from the echoes nearby, not zero
    data = storms.motion_json(u, v, 300)
    assert (data["nx"], data["ny"], data["dt_s"]) == (19, 12, 300)
    assert len(data["u"]) == len(data["v"]) == 19 * 12
    assert data["u"][-1] == round(float(u[-1, -1]), 1)  # row-major
    nothing = np.full(SHAPE, -32.0, np.float32)
    u0, v0 = storms.coarse_motion(storms.dense_flow(nothing, nothing), nothing, nothing)
    assert not u0.any() and not v0.any()


def test_cells_hail_and_tracking():
    top = np.full(SHAPE, np.nan, np.float32)
    top[:] = 4.0
    top[100:140, 280:330] = 11.0
    first = np.maximum(blob((120, 300), peak=58), blob((300, 100), peak=44))
    small = blob((50, 500), peak=41, radius=0.3)  # one cell ≥ 40 dBZ: too small
    first = np.maximum(first, small)
    cells = storms.storm_cells(T0, first, top)
    assert [c["max_dbz"] for c in cells] == [58.0, 44.0]
    hail, other = cells
    assert hail["hail"] and not other["hail"]
    assert hail["echotop_km"] == 11.0 and other["echotop_km"] == 4.0
    lon, lat = storms.cell_lonlat(np.array([120.5]), np.array([300.5]))
    assert (hail["lon"], hail["lat"]) == pytest.approx((lon[0], lat[0]), abs=1e-3)
    assert 90 < hail["area_km2"] < 130 and hail["speed_kmh"] is None
    assert hail["track"] == [[hail["lon"], hail["lat"]]]
    assert hail["id"] == "202610151200-1" and other["id"] == "202610151200-2"

    # five minutes later both moved 4 cells east; a new cell appeared
    second = np.maximum(blob((120, 304), peak=57), blob((300, 104), peak=45))
    second = np.maximum(second, blob((250, 450), peak=47))
    flow = storms.dense_flow(first, second)
    later = storms.storm_cells(T0 + timedelta(minutes=5), second, top, (T0, first, cells), flow)
    by_id = {c["id"]: c for c in later}
    assert set(by_id) == {"202610151200-1", "202610151200-2", "202610151205-2"}
    moved = by_id["202610151200-1"]
    assert len(moved["track"]) == 2 and moved["track"][0] == hail["track"][0]
    assert moved["dir_deg"] == pytest.approx(90, abs=15)  # to the east
    km = 4 * 1.5557 * math.cos(math.radians(moved["lat"]))
    assert moved["speed_kmh"] == pytest.approx(km * 12, rel=0.25)

    # tracks keep the last 30 minutes
    track = [[14.0 + i / 100, 50.0] for i in range(9)]
    known = [{**later[0], "track": track}]
    again = storms.storm_cells(
        T0 + timedelta(minutes=10),
        second,
        top,
        (T0 + timedelta(minutes=5), second, known),
        storms.dense_flow(second, second),
    )
    assert len(next(c for c in again if c["id"] == later[0]["id"])["track"]) == 7
    # after a gap of more than 15 minutes there is no matching
    gap = storms.storm_cells(T0 + timedelta(minutes=30), second, top, (T0, first, cells), flow)
    assert all(c["id"].startswith("202610151230-") for c in gap)
    assert all(c["speed_kmh"] is None for c in gap)


def test_real_composites_motion():
    before, after = storms.read_composite(MAXZ_1030), storms.read_composite(MAXZ_1035)
    flow = storms.dense_flow(before.values, after.values)
    u, v = storms.coarse_motion(flow, before.values, after.values)
    assert u.shape == (12, 19) and np.isfinite(u).all()
    assert np.abs(u).max() < 10 and np.abs(v).max() < 10  # cells per 5 minutes
    assert storms.storm_cells(after.time, after.values, None) == []  # at most 23 dBZ


# --- satellite ---------------------------------------------------------------------


def test_satellite_listing_crop_and_bounds():
    files = satellite.parse_listing(SAT_LISTING + '<a href="x_geo_wv062_ce.jpg">')
    assert files[0].time == datetime(2026, 10, 7, 4, 45, tzinfo=UTC)
    assert {f.region for f in files} == {"ce", "cz", "eu"}
    assert files[0].name == "202610070445_geo_wv062_ce.jpg" and files[0].product == "wv062"
    (west, south), (east, north) = satellite.crop_bounds()
    assert (west, south, east, north) == pytest.approx((3.49, 44.49, 25.51, 55.50), abs=0.01)
    assert west < radar.GRID_WEST and east > radar.GRID_EAST
    assert south < radar.GRID_SOUTH and north > radar.GRID_NORTH
    frame = Image.open(io.BytesIO(satellite.web_frame(SAT_JPG)))
    left, top, right, bottom = satellite.CROP
    assert frame.format == "WEBP" and frame.size == (right - left, bottom - top)
    # the crop edges are whole pixels of the ce grid: x and y map back exactly
    x, _ = radar.mercator(np.array([west, east]), np.array([50, 50]))
    assert (x[1] - x[0]) / satellite.CE_PIXEL == pytest.approx(right - left, abs=1e-3)
    with pytest.raises(ValueError, match="size"):
        buffer = io.BytesIO()
        Image.new("RGB", (100, 80)).save(buffer, format="JPEG")
        satellite.web_frame(buffer.getvalue())


def satellite_server(times: list[datetime], fail: frozenset = frozenset()):
    names = {
        p: [f"{t:%Y%m%d%H%M}_geo_{p}_{r}.jpg" for t in times for r in satellite.REGIONS]
        for p in satellite.PRODUCTS
    }
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/meteorology/weather/satellite/geo/")
        seen.append(path)
        product, _, name = path.partition("/")
        if not name:
            links = "".join(f'<a href="{n}">{n}</a>\n' for n in names.get(product, []))
            return httpx.Response(200, text=f"<pre>{links}</pre>")
        if name in fail:
            return httpx.Response(500)
        return (
            httpx.Response(200, content=SAT_JPG) if name in names[product] else httpx.Response(404)
        )

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_satellite_web_frames(tmp_path):
    times = [T0 + timedelta(minutes=15 * i) for i in range(6)]
    client, seen = satellite_server(times)
    entry = satellite.web_frames(client, tmp_path, T0 + timedelta(minutes=30), log=lambda _: None)
    assert entry["wv062"]["frames"] == [
        "202610151230",
        "202610151245",
        "202610151300",
        "202610151315",
    ]
    assert (
        entry["vis-ir"]["ext"] == "webp" and entry["night-M"]["bounds"] == satellite.crop_bounds()
    )
    assert (tmp_path / "satellite" / "wv062" / "202610151300.webp").exists()
    assert not any("_cz." in p or "_eu." in p for p in seen)  # only the ce region
    client, seen = satellite_server(times)
    later = satellite.web_frames(client, tmp_path, T0 + timedelta(minutes=75), log=lambda _: None)
    # out of the window, but kept for PRUNE_GRACE (30 min): 12:30 goes, 12:45 stays
    assert later["wv062"]["frames"] == ["202610151245", "202610151300", "202610151315"]
    assert all(p.endswith("/") for p in seen)  # nothing downloaded again
    index = radar.frame_index(tmp_path)
    assert index["satellite"]["wv062"]["frames"] == ["202610151245", "202610151300", "202610151315"]
    assert "EUMETSAT" in index["satellite_attribution"] and "2026" in index["satellite_attribution"]


def test_satellite_archive(tmp_path):
    day = datetime(2026, 10, 14, tzinfo=UTC)
    times = [day + timedelta(minutes=15 * i) for i in range(4)] + [day + timedelta(days=1)]
    client, _ = satellite_server(times, fail=frozenset({"202610140015_geo_night-M_eu.jpg"}))
    store = radar.LocalStore(tmp_path)
    now = datetime(2026, 10, 15, 0, 59, tzinfo=UTC)
    result = satellite.archive(client, store, now, log=lambda _: None)
    assert result.archived == []  # 14 Oct is complete only from 01:00
    result = satellite.archive(client, store, now + timedelta(minutes=1), log=lambda _: None)
    assert len(result.archived) == 8 and result.failed == ["night-M-eu-20261014.tar"]
    folder = tmp_path / "satellite-2026-10"
    assert (folder / "wv062-ce-20261014.tar").exists()
    client, _ = satellite_server(times)
    again = satellite.archive(client, store, now + timedelta(minutes=1), log=lambda _: None)
    assert again.archived == ["night-M-eu-20261014.tar"] and again.skipped == 8
    only = satellite.archive(
        client,
        radar.LocalStore(tmp_path / "x"),
        now,
        ("wv062",),
        ("ce",),
        [date(2026, 10, 14)],
        log=lambda _: None,
    )
    assert only.archived == ["wv062-ce-20261014.tar"]


def test_mirror_with_satellite(tmp_path):
    store = FakeReleases(
        {
            "radar-2026-10": {"web-20261014.tar": b"xy"},
            "satellite-2026-10": {"wv062-ce-20261014.tar": b"s"},
        }
    )
    assert radar.mirror(store, tmp_path, log=lambda _: None) == 1
    count = radar.mirror(store, tmp_path, log=lambda _: None, prefixes=("radar-", "satellite-"))
    assert count == 1 and (tmp_path / "satellite-2026-10" / "wv062-ce-20261014.tar").exists()


class FakeReleases:
    def __init__(self, assets: dict[str, dict[str, bytes]]) -> None:
        self.data = assets

    def tags(self, prefix: str = "") -> list[str]:
        return sorted(t for t in self.data if t.startswith(prefix))

    def assets(self, tag: str) -> dict[str, dict]:
        return {n: {"name": n, "size": len(c)} for n, c in self.data[tag].items()}

    def download(self, tag: str, name: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.data[tag][name])
        return dest


def test_cli_satellite_options(tmp_path):
    runner = CliRunner()
    result = runner.invoke(app, ["archive-satellite"])
    assert result.exit_code != 0 and "exactly one" in result.output
    result = runner.invoke(
        app, ["archive-satellite", "--out-dir", str(tmp_path), "--regions", "us"]
    )
    assert result.exit_code != 0 and "regions" in result.output


def test_derive_frames_waits_for_the_echo_top(tmp_path):
    files = {("maxz", T0): MAXZ_1030, ("maxz", T0 + timedelta(minutes=5)): MAXZ_1035}
    files[("echotop", T0)] = ECHOTOP

    class Load:
        def __call__(self, layer, when):
            return files.get((layer, when))

        def latest(self, layer):
            return max(w for kind, w in files if kind == layer)

    times = [T0, T0 + timedelta(minutes=5)]
    assert radar.derive_frames(tmp_path, times, Load(), T0, log=lambda _: None) == 1
    assert sorted(p.name for p in (tmp_path / "cells").iterdir()) == ["202610151200.json"]
    assert not (tmp_path / "motion" / "202610151205.json").exists()
    files[("echotop", T0 + timedelta(minutes=5))] = ECHOTOP  # now it is out
    assert radar.derive_frames(tmp_path, times, Load(), T0, log=lambda _: None) == 1
    assert (tmp_path / "motion" / "202610151205.json").exists()
    assert (tmp_path / "echotop" / "202610151205.png").exists()
