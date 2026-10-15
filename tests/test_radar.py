import io
import json
import tarfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import h5py
import httpx
import numpy as np
import polars as pl
import pytest
from PIL import Image
from typer.testing import CliRunner

from meteoverdict import radar
from meteoverdict.cli import app

FIXTURES = Path(__file__).parent / "fixtures" / "chmi" / "radar"
MAXZ_PNG = (FIXTURES / "pacz2gmaps3.z_max3d.20261015.1035.0.png").read_bytes()
MAXZ_HDF = (FIXTURES / "T_PABV23_C_OKPR_20261015103500.hdf").read_bytes()
MERGE_HDF = (FIXTURES / "T_PASV23_C_OKPR_20261015101000.hdf").read_bytes()
ECHOTOP_HDF = (FIXTURES / "T_PADV23_C_OKPR_20261015103500.hdf").read_bytes()
NOWCAST_TAR = (FIXTURES / "pacz2gmaps3.fct_z_max.20261015.1035.ft60s10.tar").read_bytes()
STATIONS = pl.DataFrame(
    {
        "id": ["0-20000-0-11520", "0-20000-0-11406", "0-20000-0-04030"],
        "lat": [50.007778, 50.068333, 64.127653],  # Praha-Libuš, Cheb, Reykjavik
        "lon": [14.446944, 12.391389, -21.903905],
    }
)


def test_products_and_names():
    assert radar.parse_products("observed") == radar.PRESETS["observed"]
    assert "fct_maxz-hdf5" in radar.parse_products("forecast")
    assert "fct_maxz-hdf5" not in radar.parse_products("observed")
    assert radar.parse_products("maxz-hdf5, merge1h-png") == ("maxz-hdf5", "merge1h-png")
    with pytest.raises(ValueError, match="unknown"):
        radar.parse_products("maxz,radar")
    day = date(2026, 10, 14)
    assert radar.release_tag(day) == "radar-2026-10"
    assert radar.asset_name("maxz-hdf5", day) == "maxz-hdf5-20261014.tar"
    assert radar.asset_name("merge1h-stations", day) == "merge1h-stations-20261014.parquet"
    assert radar.asset_name("merge1h-hourly", day) == "merge1h-hourly-20261014.npz"
    assert radar.stamp(datetime(2026, 10, 14, 9, 5, tzinfo=UTC)) == "202610140905"
    assert radar.parse_stamp("202610140905") == datetime(2026, 10, 14, 9, 5, tzinfo=UTC)


def test_every_product_pattern_matches_a_real_name():
    names = {
        "maxz-hdf5": "T_PABV23_C_OKPR_20261015103500.hdf",
        "maxz-png": "pacz2gmaps3.z_max3d.20261015.1035.0.png",
        "maxz-png_masked": "pacz2gmaps3.z_max3d.20261015.1035.0.png",
        "cappi2km-hdf5": "T_PANV23_C_OKPR_20261015103500.hdf",
        "cappi2km-png": "pacz2gmaps3.z_cappi020.20261015.1035.0.png",
        "echotop-hdf5": "T_PADV23_C_OKPR_20261015103500.hdf",
        "merge1h-hdf5": "T_PASV23_C_OKPR_20261015101000.hdf",
        "merge1h-png": "pacz2gmaps3.merge.20261015.1010.60.png",
        "fct_maxz-hdf5": "T_PABV23_C_OKPR_20261015.1035.ft60s10.tar",
        "fct_maxz-png": "pacz2gmaps3.fct_z_max.20261015.1035.ft60s10.tar",
        "fct_maxz-png_masked": "pacz2gmaps3.fct_z_max.20261015.1035.ft60s10.tar",
        "fct_cappi2km-hdf5": "T_PANV23_C_OKPR_20261015.1035.ft60s10.tar",
        "fct_cappi2km-png": "pacz2gmaps3.fct_z_cappi020.20261015.1035.ft60s10.tar",
    }
    assert set(names) == set(radar.BY_KEY)
    for key, name in names.items():
        found = radar.parse_listing(radar.BY_KEY[key], f'<a href="{name}">{name}</a>')
        assert list(found) in (
            [datetime(2026, 10, 15, 10, 35, tzinfo=UTC)],
            [datetime(2026, 10, 15, 10, 10, tzinfo=UTC)],
        ), key


def test_parse_real_listing():
    html = (FIXTURES / "listing-maxz-png_masked.html").read_text(encoding="utf-8")
    found = radar.parse_listing(radar.BY_KEY["maxz-png_masked"], html + '<a href="4_unpack/">')
    assert len(found) == 8
    first = next(iter(found))
    assert first == datetime(2026, 10, 8, 0, 0, tzinfo=UTC)
    assert found[first] == "pacz2gmaps3.z_max3d.20261008.0000.0.png"


def test_complete_days():
    times = [datetime(2026, 10, d, h, tzinfo=UTC) for d in (13, 14, 15) for h in (0, 23)]
    now = datetime(2026, 10, 15, 2, 59, tzinfo=UTC)
    assert radar.complete_days(times, now) == [date(2026, 10, 13)]
    assert radar.complete_days(times, now + timedelta(minutes=1)) == [
        date(2026, 10, 13),
        date(2026, 10, 14),
    ]


def test_web_frame_is_the_grid_with_transparent_frame():
    frame = Image.open(io.BytesIO(radar.web_frame(MAXZ_PNG)))
    assert frame.size == (radar.GRID_COLS, radar.GRID_ROWS)
    rgba = np.array(frame.convert("RGBA"))
    source = np.array(Image.open(io.BytesIO(MAXZ_PNG)).convert("RGBA"))[
        radar.PNG_TOP :, : radar.GRID_COLS
    ]
    opaque = rgba[..., 3] == 255
    assert opaque.any()
    assert (rgba[opaque][:, :3] == source[opaque][:, :3]).all()  # ČHMÚ colours kept
    assert not (opaque & (rgba[..., :3].sum(axis=2) == 0)).any()  # no black title or frame
    assert set(np.unique(rgba[..., 3])) <= {0, radar.NO_COVERAGE_ALPHA, 255}
    hidden = np.array(Image.open(io.BytesIO(radar.web_frame(MAXZ_PNG, 0))).convert("RGBA"))
    assert set(np.unique(hidden[..., 3])) == {0, 255}
    with pytest.raises(ValueError, match="unexpected PNG"):
        buffer = io.BytesIO()
        Image.new("RGB", (10, 10)).save(buffer, format="PNG")
        radar.web_frame(buffer.getvalue())


def test_png_crop_lines_up_with_the_hdf5_grid():
    """Echoes in the cropped PNG are where the HDF5 grid (same time) has ≥ 4 dBZ."""
    with h5py.File(io.BytesIO(MAXZ_HDF)) as f:
        where = dict(f["where"].attrs)
        codes = f["dataset1/data1/data"][()].astype(float)
    assert (where["xsize"], where["ysize"]) == (radar.GRID_COLS, radar.GRID_ROWS)
    assert where["LL_lon"] == pytest.approx(radar.GRID_WEST)
    assert where["LL_lat"] == pytest.approx(radar.GRID_SOUTH)
    assert where["UR_lon"] == pytest.approx(radar.GRID_EAST)
    assert where["UR_lat"] == pytest.approx(radar.GRID_NORTH)
    dbz = np.where((codes > 0) & (codes < 255), codes * 0.5 - 32, np.nan)
    hdf_echo = dbz >= 4
    frame = np.array(Image.open(io.BytesIO(radar.web_frame(MAXZ_PNG))).convert("RGBA"))
    png_echo = (frame[..., 3] == 255) & ~np.all(frame[..., :3] == 196, axis=2)
    overlap = (hdf_echo & png_echo).sum() / (hdf_echo | png_echo).sum()
    assert overlap > 0.99
    # the grid edges match the Web Mercator size: 598 x 1555.7 m
    x, _ = radar.mercator(np.array([radar.GRID_WEST, radar.GRID_EAST]), np.array([50, 50]))
    assert x[1] - x[0] == pytest.approx(radar.GRID_COLS * where["xscale"], abs=50)


def test_read_merge_and_grid_cells():
    merge = radar.read_merge(MERGE_HDF)
    assert merge.time == datetime(2026, 10, 15, 10, 10, tzinfo=UTC)
    assert merge.codes.shape == (radar.GRID_ROWS, radar.GRID_COLS)
    mm = merge.mm()
    assert np.nanmax(mm) == pytest.approx(0.1)
    assert np.isnan(mm).any()  # outside the MERGE domain
    rows, cols = radar.grid_cells(
        merge.where,
        np.array([radar.GRID_WEST + 1e-6, radar.GRID_EAST - 1e-6, 14.446944, -21.9]),
        np.array([radar.GRID_NORTH - 1e-6, radar.GRID_SOUTH + 1e-6, 50.007778, 64.1]),
    )
    assert (rows[0], cols[0]) == (0, 0)
    assert (rows[1], cols[1]) == (radar.GRID_ROWS - 1, radar.GRID_COLS - 1)
    assert 0 < rows[2] < radar.GRID_ROWS and 0 < cols[2] < radar.GRID_COLS
    assert (rows[3], cols[3]) == (-1, -1)


def merge_at(when: datetime, value: int) -> bytes:
    """The real MERGE file with another end time and a constant code inside the domain."""
    buffer = io.BytesIO(MERGE_HDF)
    out = io.BytesIO()
    out.write(buffer.getvalue())
    with h5py.File(out, "r+") as f:
        f["dataset1/what"].attrs["enddate"] = np.bytes_(f"{when:%Y%m%d}")
        f["dataset1/what"].attrs["endtime"] = np.bytes_(f"{when:%H%M}00")
        data = f["dataset1/data1/data"]
        codes = data[()]
        codes[codes < 32766] = value
        data[...] = codes
    return out.getvalue()


def test_station_values_and_hourly():
    base = datetime(2026, 10, 14, tzinfo=UTC)
    fields = [radar.read_merge(merge_at(base + timedelta(minutes=10 * i), i)) for i in range(0, 13)]
    hours = radar.hourly(fields)
    assert [f.time.hour for f in hours] == [0, 1, 2]
    table = radar.station_values(hours, STATIONS)
    assert table.columns == ["station_id", "time", "precipitation", "grid_row", "grid_col"]
    assert table["station_id"].unique().sort().to_list() == ["0-20000-0-11406", "0-20000-0-11520"]
    libus = table.filter(pl.col("station_id") == "0-20000-0-11520").sort("time")
    assert libus["precipitation"].to_list() == pytest.approx([0.0, 0.6, 1.2])
    assert libus["time"].dtype == pl.Datetime("us", "UTC")


def test_nowcast_frames():
    frames = radar.nowcast_frames(NOWCAST_TAR)
    assert [lead for _, lead, _ in frames] == [10, 20, 30, 40, 50, 60]
    assert frames[0][0] == datetime(2026, 10, 15, 10, 45, tzinfo=UTC)
    assert Image.open(io.BytesIO(radar.web_frame(frames[0][2]))).size == (598, 378)


# --- a fake opendata.chmi.cz --------------------------------------------------------


SATELLITE_PATH = "/meteorology/weather/satellite/geo/"


def fake_server(files: dict[str, dict[str, bytes]], fail: set[str] = frozenset()):
    """``files``: product folder (``maxz/png_masked``, satellite: ``satellite/wv062``) →
    file name → content. ``fail``: names answering 500."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith(SATELLITE_PATH):
            path = "satellite/" + path.removeprefix(SATELLITE_PATH)
        path = path.removeprefix("/meteorology/weather/radar/composite/")
        seen.append(path)
        if path.endswith("/"):
            names = files.get(path.rstrip("/"), {})
            body = "".join(f'<a href="{n}">{n}</a>\n' for n in sorted(names))
            return httpx.Response(200, text=f'<pre><a href="../">../</a>\n{body}</pre>')
        folder, name = path.rsplit("/", 1)
        if name in fail:
            return httpx.Response(500)
        if name in files.get(folder, {}):
            return httpx.Response(200, content=files[folder][name])
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def day_files(day: datetime, hours: int = 2) -> dict[str, dict[str, bytes]]:
    png, merge_png, merge_hdf, maxz_hdf, top_hdf = {}, {}, {}, {}, {}
    for i in range(hours * 12):
        t = day + timedelta(minutes=5 * i)
        png[f"pacz2gmaps3.z_max3d.{t:%Y%m%d.%H%M}.0.png"] = MAXZ_PNG
        maxz_hdf[f"T_PABV23_C_OKPR_{t:%Y%m%d%H%M}00.hdf"] = MAXZ_HDF
        top_hdf[f"T_PADV23_C_OKPR_{t:%Y%m%d%H%M}00.hdf"] = ECHOTOP_HDF
        if t.minute % 10 == 0:
            merge_png[f"pacz2gmaps3.merge.{t:%Y%m%d.%H%M}.60.png"] = MAXZ_PNG
            merge_hdf[f"T_PASV23_C_OKPR_{t:%Y%m%d%H%M}00.hdf"] = merge_at(t, 3)
    return {
        "maxz/png_masked": png,
        "merge1h/png": merge_png,
        "merge1h/hdf5": merge_hdf,
        "maxz/hdf5": maxz_hdf,
        "echotop/hdf5": top_hdf,
    }


def tar_names(path: Path) -> list[str]:
    with tarfile.open(path) as tar:
        return tar.getnames()


def test_archive_packs_days_and_skips_what_is_stored(tmp_path):
    day = datetime(2026, 10, 14, tzinfo=UTC)
    files = day_files(day)
    for folder, names in day_files(day + timedelta(days=1), hours=1).items():
        files[folder] |= names  # today: not complete yet
    client, _ = fake_server(files)
    store = radar.LocalStore(tmp_path)
    now = datetime(2026, 10, 15, 8, tzinfo=UTC)
    keys = ("maxz-png_masked", "merge1h-hdf5")
    result = radar.archive(client, store, keys, now, STATIONS, log=lambda _: None)
    assert not result.failed
    folder = tmp_path / "radar-2026-10"
    assert sorted(p.name for p in folder.iterdir()) == [
        "maxz-png_masked-20261014.tar",
        "merge1h-hdf5-20261014.tar",
        "merge1h-hourly-20261014.npz",
        "merge1h-stations-20261014.parquet",
        "web-20261014.tar",
    ]
    names = tar_names(folder / "maxz-png_masked-20261014.tar")
    assert len(names) == 24 and names[0] == "pacz2gmaps3.z_max3d.20261014.0000.0.png"
    web = tar_names(folder / "web-20261014.tar")
    assert web[0] == "index.json"
    assert "maxz/202610140005.png" in web and "merge1h/202610140010.png" in web
    with tarfile.open(folder / "web-20261014.tar") as tar:
        index = json.load(tar.extractfile("index.json"))
    assert index["maxz"][0] == "202610140000" and len(index["merge1h"]) == 12
    assert len(index["echotop"]) == 24 and len(index["cells"]) == 24
    assert len(index["motion"]) == 23  # not for the first frame of the day
    assert "echotop/202610140005.png" in web and "cells/202610140005.json" in web
    assert "motion/202610140005.json" in web and "motion/202610140000.json" not in web
    assert set(index["satellite"]) == {"vis-ir", "night-M", "wv062"}
    assert index["scales"]["maxz"][0][:2] == [4, "#380070"]
    grids = np.load(folder / "merge1h-hourly-20261014.npz")
    assert grids["acrr"].shape == (2, 378, 598) and list(grids["time"]) == [
        "202610140000",
        "202610140100",
    ]
    stations = pl.read_parquet(folder / "merge1h-stations-20261014.parquet")
    assert stations["precipitation"].to_list() == pytest.approx([0.3] * 4)
    assert result.sizes["web-20261014.tar"] > 0

    client, seen = fake_server(files)
    again = radar.archive(client, store, keys, now, STATIONS, log=lambda _: None)
    assert again.archived == [] and again.skipped == 2
    assert all(p.endswith("/") for p in seen)  # only the listings were read


def test_archive_keeps_going_when_a_file_fails(tmp_path):
    day = datetime(2026, 10, 14, tzinfo=UTC)
    files = day_files(day)
    client, _ = fake_server(files, fail={"T_PASV23_C_OKPR_20261014001000.hdf"})
    store = radar.LocalStore(tmp_path)
    now = datetime(2026, 10, 16, tzinfo=UTC)
    result = radar.archive(
        client, store, ("maxz-png_masked", "merge1h-hdf5"), now, None, log=lambda _: None
    )
    assert "merge1h-hdf5-20261014.tar" in result.failed
    assert "maxz-png_masked-20261014.tar" in result.archived
    assert "web-20261014.tar" in result.archived
    assert "merge1h-hourly-20261014.npz" not in result.archived  # its source failed
    assert not (tmp_path / "radar-2026-10" / "merge1h-stations-20261014.parquet").exists()


def test_archive_only_given_days_and_without_derived(tmp_path):
    files = day_files(datetime(2026, 10, 13, tzinfo=UTC))
    for folder, names in day_files(datetime(2026, 10, 14, tzinfo=UTC)).items():
        files[folder] |= names
    client, _ = fake_server(files)
    result = radar.archive(
        client,
        radar.LocalStore(tmp_path),
        ("maxz-png_masked",),
        datetime(2026, 10, 16, tzinfo=UTC),
        days=[date(2026, 10, 14)],
        derived=False,
        log=lambda _: None,
    )
    assert result.archived == ["maxz-png_masked-20261014.tar"]


def test_update_live_adds_prunes_and_keeps_the_nowcast(tmp_path):
    day = datetime(2026, 10, 15, 8, tzinfo=UTC)
    files = day_files(day)
    files["fct_maxz/png_masked"] = {"pacz2gmaps3.fct_z_max.20261015.0955.ft60s10.tar": NOWCAST_TAR}
    client, _ = fake_server(files)
    now = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
    index = radar.update_live(client, tmp_path, now, hours=1, log=lambda _: None)
    assert index["maxz"][0] == "202610150900" and len(index["maxz"]) == 12
    assert index["nowcast"]["base"] == "202610150955"
    assert [f["lead"] for f in index["nowcast"]["frames"]] == [10, 20, 30, 40, 50, 60]
    assert (tmp_path / "nowcast" / "202610151045.png").exists()
    assert json.loads((tmp_path / "index.json").read_text())["generated"] == "2026-10-15T10:00:00Z"
    assert "CC BY 4.0" in (tmp_path / "README.md").read_text()
    assert index["echotop"] == index["maxz"] == index["cells"]
    assert index["motion"] == index["maxz"]  # the frame before the window is used too
    motion = json.loads((tmp_path / "motion" / "202610150930.json").read_text())
    assert (motion["nx"], motion["ny"], motion["dt_s"]) == (19, 12, 300)
    assert motion["u"] == [0.0] * 19 * 12  # the same file every time: no motion
    assert json.loads((tmp_path / "cells" / "202610150930.json").read_text()) == []

    client, seen = fake_server(files)
    later = radar.update_live(
        client, tmp_path, now + timedelta(minutes=30), hours=1, log=lambda _: None
    )
    assert later["maxz"][0] == "202610150930"
    assert later["echotop"][0] == later["motion"][0] == later["cells"][0] == "202610150930"
    assert not (tmp_path / "maxz" / "202610150900.png").exists()
    assert not (tmp_path / "echotop" / "202610150900.png").exists()
    assert not any("ft60s10.tar" in p and not p.endswith("/") for p in seen)  # same nowcast
    assert not any(p.endswith(".hdf") for p in seen)  # derived frames all there


class FakeReleases:
    def __init__(self, assets: dict[str, dict[str, bytes]]) -> None:
        self.data = assets
        self.downloads: list[str] = []

    def tags(self, prefix: str = "") -> list[str]:
        return sorted(t for t in self.data if t.startswith(prefix))

    def assets(self, tag: str) -> dict[str, dict]:
        return {n: {"name": n, "size": len(c)} for n, c in self.data[tag].items()}

    def download(self, tag: str, name: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.data[tag][name])
        self.downloads.append(name)
        return dest


def test_mirror_copies_new_and_changed_assets(tmp_path):
    store = FakeReleases(
        {
            "radar-2026-09": {"maxz-hdf5-20260930.tar": b"old"},
            "radar-2026-10": {"maxz-hdf5-20261014.tar": b"abc", "web-20261014.tar": b"xy"},
            "data-2026-10": {"obs-2026-10.parquet": b"no"},
        }
    )
    assert radar.mirror(store, tmp_path, since="2026-10", log=lambda _: None) == 2
    assert (tmp_path / "radar-2026-10" / "web-20261014.tar").read_bytes() == b"xy"
    assert not (tmp_path / "radar-2026-09").exists()
    assert radar.mirror(store, tmp_path, log=lambda _: None) == 1  # only September now


def test_cli_checks_options(tmp_path):
    runner = CliRunner()
    result = runner.invoke(app, ["archive-radar"])
    assert result.exit_code != 0 and "exactly one" in result.output
    result = runner.invoke(app, ["archive-radar", "--out-dir", str(tmp_path), "--products", "x"])
    assert result.exit_code != 0 and "unknown products" in result.output
