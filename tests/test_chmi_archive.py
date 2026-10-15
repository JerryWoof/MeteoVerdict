import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import polars as pl
import pytest

from meteoverdict import chmi_archive as ca
from meteoverdict.chmi import BASE_URL

LIBUS, BRNO = "0-20000-0-11520", "0-20000-0-11723"


def doc(header: str, rows: list[list]) -> dict:
    """A ČHMÚ JSON document (envelope as in docs/data-sources.md)."""
    return {"data": {"type": "DataCollection", "data": {"header": header, "values": rows}}}


def ten_minute(wsi: str, day: str, quality: float = 5.0) -> dict:
    return doc(
        "STATION,ELEMENT,DT,VAL,FLAG,QUALITY",
        [
            [wsi, "T", f"{day}T00:00:00Z", 9.5, "", quality],
            [wsi, "T", f"{day}T00:10:00Z", "", "", 4.0],
            [wsi, "SCEa", f"{day}T00:00:00Z", 3.0, "P", quality],
        ],
    )


def hourly(wsi: str, day: str) -> dict:
    return doc(
        "STATION,ELEMENT,DT,VAL,FLAG,QUALITY",
        [
            [wsi, "SRA1H", f"{day}T01:00:00Z", 0.4, "", 5.0],
            [wsi, "ww", f"{day}T01:00:00Z", 61, "", 5],
        ],
    )


DAILY = doc(
    "STATION,ELEMENT,VTYPE,DT,VAL,FLAG,QUALITY",
    [
        [LIBUS, "T", "AVG", "1971-01-01T00:00:00Z", -1.5, "", 0.0],
        [LIBUS, "T", "06:00", "1971-01-01T06:00:00Z", -3.0, "", 0.0],
        [LIBUS, "SRA", "06:00", "1971-01-01T06:00:00Z", 0.1, "T", 0.0],
    ],
)
MONTHLY = doc(
    "STATION,ELEMENT,YEAR,MONTH,TIMEFUNCTION,MDFUNCTION,VALUE,FLAG_REPEAT,FLAG_INTERRUPTED",
    [
        [LIBUS, "T", "1971", "02", "AVG", "AVG", 0.4, "", ""],
        [LIBUS, "SRA", "1971", "02", "06:00", "SUM", 12.5, "*", "x"],
    ],
)
RECENT_MONTHLY = doc(
    "STATION,ELEMENT,TIMEFUNCTION,MDFUNCTION,VALUE,FLAG_REPEAT,FLAG_INTERRUPTED",
    [[LIBUS, "T", "AVG", "AVG", 14.1, "", ""]],
)
PENTADIC = doc(
    "STATION,ELEMENT,YEAR,MONTH,PENTADE,TIMEFUNCTION,MDFUNCTION,VALUE,FLAG_REPEAT,FLAG_INTERRUPTED",
    [[LIBUS, "T", "1971", "03", 4, "AVG", "AVG", 2.0, "", ""]],
)
YEARLY = doc(
    "STATION,ELEMENT,YEAR,TIMEFUNCTION,MDFUNCTION,VALUE,FLAG_REPEAT,FLAG_INTERRUPTED",
    [[LIBUS, "T", "1971", "AVG", "AVG", 8.9, "", ""]],
)
PHENOMENA = doc("STATION,PHENOMENON,DT", [[LIBUS, "BO", "1971-05-13"]])


def listing(*files: tuple[str, int] | str) -> str:
    """An nginx directory listing as opendata.chmi.cz serves it."""
    lines = ['<html><body><h1>Index</h1><hr><pre><a href="../">../</a>']
    for f in files:
        name, size = (f, "-") if isinstance(f, str) else f
        lines.append(f'<a href="{name}">{name}</a>{" " * 20}15-Oct-2026 00:02{" " * 10}{size}')
    return "\n".join(lines) + "</pre><hr></body></html>"


class Server:
    """Fake opendata.chmi.cz: path → JSON document or listing HTML."""

    def __init__(self, files: dict[str, object]) -> None:
        self.files = files
        self.seen: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = str(request.url).removeprefix(BASE_URL + "/")
        self.seen.append(path)
        body = self.files.get(path)
        if body is None:
            return httpx.Response(404)
        if isinstance(body, str):
            return httpx.Response(200, text=body)
        return httpx.Response(200, json=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def test_parse_name():
    assert ca.parse_name(f"10m-{LIBUS}-20261014.json") == ca.FileName("10min", LIBUS, "20261014")
    assert ca.parse_name("1h-0-203-0-42108066001-202503.json") == ca.FileName(
        "1hour", "0-203-0-42108066001", "202503"
    )
    assert ca.parse_name(f"dly-{LIBUS}.json") == ca.FileName("daily", LIBUS, None)
    assert ca.parse_name(f"5d-{LIBUS}-202609.json").resolution == "pentadic"
    assert ca.parse_name("meta2-20261015.json") is None
    assert ca.parse_name("Klimatologicka_data_popis.pdf") is None


def test_parse_listing():
    entries = ca.parse_listing(listing("2025/", (f"dly-{LIBUS}.json", 74381712)))
    assert entries == [
        ca.Entry("2025/", "15-Oct-2026 00:02", -1),
        ca.Entry(f"dly-{LIBUS}.json", "15-Oct-2026 00:02", 74381712),
    ]
    assert ca.signature(entries) == ca.signature(list(reversed(entries)))
    assert ca.signature(entries[:1]) != ca.signature(entries)


def test_normalize_every_kind():
    t = ca.normalize(
        pl.DataFrame(
            ten_minute(LIBUS, "2026-10-14")["data"]["data"]["values"],
            schema=["STATION", "ELEMENT", "DT", "VAL", "FLAG", "QUALITY"],
            orient="row",
        ),
        "10min",
    )
    assert t.schema == pl.Schema(ca.SCHEMA)
    assert t["value"].to_list() == [3.0, 9.5, None]  # sorted by time, then element
    assert t["flag"].to_list() == ["P", None, None]
    assert t["quality"].to_list() == [5, 5, 4]

    def norm(document, resolution, stamp=None):
        from meteoverdict.chmi import parse_collection

        return ca.normalize(parse_collection(document), resolution, stamp)

    daily = norm(DAILY, "daily")
    assert daily.select("element", "vtype").rows() == [
        ("T", "AVG"),
        ("SRA", "06:00"),
        ("T", "06:00"),
    ]
    monthly = norm(MONTHLY, "monthly")
    assert monthly["time"].to_list() == [datetime(1971, 2, 1, tzinfo=UTC)] * 2
    assert monthly.filter(pl.col("element") == "SRA").select("vtype", "func", "flag", "flag2").row(
        0
    ) == (
        "06:00",
        "SUM",
        "*",
        "x",
    )
    # recent monthly files have no YEAR/MONTH: they come from the file name
    assert norm(RECENT_MONTHLY, "monthly", "202609")["time"].to_list() == [
        datetime(2026, 9, 1, tzinfo=UTC)
    ]
    assert norm(PENTADIC, "pentadic")["time"].to_list() == [datetime(1971, 3, 16, tzinfo=UTC)]
    assert norm(YEARLY, "yearly")["time"].to_list() == [datetime(1971, 1, 1, tzinfo=UTC)]
    phenomena = norm(PHENOMENA, "phenomena")
    assert phenomena.select("time", "element", "value").row(0) == (
        datetime(1971, 5, 13, tzinfo=UTC),
        "BO",
        None,
    )


def test_write_and_read_back(tmp_path: Path):
    from meteoverdict.chmi import parse_collection

    table = ca.normalize(parse_collection(DAILY), "daily")
    path = ca.write(table, tmp_path / "x.parquet")
    assert pl.read_parquet(path).equals(table)


def now_server(today: str = "20261015") -> Server:
    days = ["20261013", "20261014", today]
    files: dict[str, object] = {
        "now/data/": listing(
            *[f"10m-{w}-{d}.json" for w in (LIBUS, BRNO) for d in days],
            *[f"1h-{w}-{d}.json" for w in (LIBUS,) for d in days],
        ),
        "now/metadata/": listing("meta1-20261014.json", "meta2-20261014.json"),
        "now/metadata/meta1-20261014.json": doc("WSI,FULL_NAME", [[LIBUS, "Praha, Libuš"]]),
        "now/metadata/meta2-20261014.json": doc("WSI,EG_EL_ABBREVIATION", [[LIBUS, "T"]]),
        # the current month's day files in recent/: the 12th is no longer in now/
        "recent/data/10min/": listing(f"10m-{LIBUS}-20261012.json", f"10m-{LIBUS}-20261013.json"),
        "recent/data/1hour/": listing(f"1h-{LIBUS}-20261012.json"),
        f"recent/data/10min/10m-{LIBUS}-20261012.json": ten_minute(LIBUS, "2026-10-12", 0.0),
        f"recent/data/1hour/1h-{LIBUS}-20261012.json": hourly(LIBUS, "2026-10-12"),
    }
    for d in days:
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        for w in (LIBUS, BRNO):
            files[f"now/data/10m-{w}-{d}.json"] = ten_minute(w, iso)
        files[f"now/data/1h-{LIBUS}-{d}.json"] = hourly(LIBUS, iso)
    return Server(files)


def test_days_from_now_and_recent(tmp_path: Path):
    server = now_server()
    store = ca.LocalStore(tmp_path / "archive")
    with server.client() as client:
        result = ca.archive(
            client, store, tmp_path / "work", ["days"], today=date(2026, 10, 15), log=lambda _: None
        )
    # today is incomplete; the 12th comes from recent/, the others from now/
    assert result.done == [
        "chmi-now-2026-10-14.parquet",
        "chmi-now-2026-10-13.parquet",
        "chmi-now-2026-10-12.parquet",
    ]
    day = pl.read_parquet(tmp_path / "archive/chmi-now-2026/chmi-now-2026-10-14.parquet")
    assert day["station"].unique().sort().to_list() == [LIBUS, BRNO]
    assert set(day["resolution"]) == {"10min", "1hour"}
    assert day.select(ca.SORT).equals(day.select(ca.SORT).sort(ca.SORT, nulls_last=False))
    old = pl.read_parquet(tmp_path / "archive/chmi-now-2026/chmi-now-2026-10-12.parquet")
    assert old["quality"].unique().sort().to_list() == [0, 4, 5]  # recent/: partly checked
    with zipfile.ZipFile(tmp_path / "archive/chmi-now-2026/chmi-meta-2026-10-14.zip") as z:
        assert sorted(z.namelist()) == ["meta1-20261014.json", "meta2-20261014.json"]
    assert not (tmp_path / "archive/chmi-now-2026/chmi-meta-2026-10-13.zip").exists()
    # a second run finds everything archived and downloads no data file
    server.seen.clear()
    with server.client() as client:
        again = ca.archive(
            client, store, tmp_path / "work", ["days"], today=date(2026, 10, 15), log=lambda _: None
        )
    assert again.done == []
    assert all(p.endswith("/") for p in server.seen)


def history_server() -> Server:
    files: dict[str, object] = {
        "historical/data/daily/": listing((f"dly-{LIBUS}.json", 100), (f"dly-{BRNO}.json", 5)),
        "historical/data/monthly/": listing((f"mly-{LIBUS}.json", 10)),
        "historical/data/pentadic/": listing((f"5d-{LIBUS}.json", 10)),
        "historical/data/yearly/": listing((f"yrs-{LIBUS}.json", 10)),
        "historical/data/phenomena/": listing((f"ph-{LIBUS}.json", 10)),
        f"historical/data/daily/dly-{LIBUS}.json": DAILY,
        f"historical/data/daily/dly-{BRNO}.json": doc(
            "STATION,ELEMENT,VTYPE,DT,VAL,FLAG,QUALITY", []
        ),
        f"historical/data/monthly/mly-{LIBUS}.json": MONTHLY,
        f"historical/data/pentadic/5d-{LIBUS}.json": PENTADIC,
        f"historical/data/yearly/yrs-{LIBUS}.json": YEARLY,
        f"historical/data/phenomena/ph-{LIBUS}.json": PHENOMENA,
        # closed months: 10 min and 1 h of 2025
        "historical/data/10min/": listing("2025/", "2017/"),
        "historical/data/1hour/": listing("2025/"),
        "historical/data/10min/2025/": listing(
            f"10m-{LIBUS}-202512.json", f"10m-{BRNO}-202512.json"
        ),
        "historical/data/1hour/2025/": listing(f"1h-{LIBUS}-202511.json"),
        f"historical/data/10min/2025/10m-{LIBUS}-202512.json": ten_minute(LIBUS, "2025-12-01", 0.0),
        f"historical/data/10min/2025/10m-{BRNO}-202512.json": ten_minute(BRNO, "2025-12-01", 0.0),
        f"historical/data/1hour/2025/1h-{LIBUS}-202511.json": hourly(LIBUS, "2025-11-30"),
        # recent/: September 2026 monthly, and October 2025 (in historical/ already)
        "recent/data/monthly/09/": listing(f"mly-{LIBUS}-202609.json"),
        "recent/data/monthly/10/": listing(f"mly-{LIBUS}-202510.json"),
        f"recent/data/monthly/09/mly-{LIBUS}-202609.json": RECENT_MONTHLY,
        "recent/data/daily/": listing(f"dly-{LIBUS}-202610.json"),
        f"recent/data/daily/dly-{LIBUS}-202610.json": doc(
            "STATION,ELEMENT,VTYPE,DT,VAL,FLAG,QUALITY",
            [[LIBUS, "T", "AVG", "2026-10-01T00:00:00Z", 11.0, "", 0.0]],
        ),
    }
    return Server(files)


def test_history_months_and_recent_resume(tmp_path: Path):
    server = history_server()
    store = ca.LocalStore(tmp_path / "archive")
    parts = ["recent", "history", "months"]
    with server.client() as client:
        result = ca.archive(client, store, tmp_path / "work", parts, log=lambda _: None)
    assert result.done == [
        "chmi-daily-2026-10.parquet",
        "chmi-monthly-2026-09.parquet",
        "chmi-history-0-20000-0-11520.parquet",
        "chmi-10min-2025-12.parquet",
        "chmi-1hour-2025-11.parquet",
    ]
    history = pl.read_parquet(tmp_path / f"archive/chmi-history-0/chmi-history-{LIBUS}.parquet")
    assert history.group_by("resolution").len().sort("resolution").rows() == [
        ("daily", 3),
        ("monthly", 2),
        ("pentadic", 1),
        ("phenomena", 1),
        ("yearly", 1),
    ]
    month = pl.read_parquet(tmp_path / "archive/chmi-2025/chmi-10min-2025-12.parquet")
    assert month["station"].unique(maintain_order=True).to_list() == [LIBUS, BRNO]
    state = json.loads((tmp_path / "archive/chmi-state/chmi-archive-state.json").read_text())
    assert set(state["units"]) == {
        "daily|2026-10",
        "monthly|2026-09",
        f"history|{LIBUS}",
        f"history|{BRNO}",
        "10min|2025-12",
        "1hour|2025-11",
    }
    # nothing changed: the next run only reads listings
    server.seen.clear()
    with server.client() as client:
        assert ca.archive(client, store, tmp_path / "work", parts, log=lambda _: None).done == []
    assert all(p.endswith("/") for p in server.seen)
    # ČHMÚ rewrites the daily file of October: only that month is done again
    server.files["recent/data/daily/"] = listing((f"dly-{LIBUS}-202610.json", 999))
    with server.client() as client:
        assert ca.archive(client, store, tmp_path / "work", parts, log=lambda _: None).done == [
            "chmi-daily-2026-10.parquet"
        ]


def test_time_budget_stops_and_resumes(tmp_path: Path):
    server = history_server()
    store = ca.LocalStore(tmp_path / "archive")
    ticks = iter(range(0, 10_000, 60))  # every look at the clock is a minute later
    with server.client() as client:
        first = ca.archive(
            client,
            store,
            tmp_path / "work",
            ["months"],
            max_minutes=1.5,
            log=lambda _: None,
            clock=lambda: next(ticks),
        )
    assert first.done == ["chmi-10min-2025-12.parquet"]
    assert first.pending == 1
    with server.client() as client:
        second = ca.archive(client, store, tmp_path / "work", ["months"], log=lambda _: None)
    assert second.done == ["chmi-1hour-2025-11.parquet"]


def test_trial_with_stations_keeps_no_state(tmp_path: Path):
    server = history_server()
    store = ca.LocalStore(tmp_path / "archive")
    with server.client() as client:
        result = ca.archive(
            client,
            store,
            tmp_path / "work",
            ["history", "months"],
            stations={BRNO},
            log=lambda _: None,
        )
    assert result.done == ["chmi-10min-2025-12.parquet"]  # Brno's history file is empty
    month = pl.read_parquet(tmp_path / "archive/chmi-2025/chmi-10min-2025-12.parquet")
    assert month["station"].unique().to_list() == [BRNO]
    assert not (tmp_path / "archive/chmi-state").exists()


def test_unreadable_file_is_left_out_and_counted(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ca.time, "sleep", lambda _: None)
    server = history_server()
    server.files[f"historical/data/daily/dly-{LIBUS}.json"] = ""  # ČHMÚ: 200, empty body
    del server.files[f"historical/data/monthly/mly-{LIBUS}.json"]  # listed, then gone
    store = ca.LocalStore(tmp_path / "archive")
    with server.client() as client:
        result = ca.archive(client, store, tmp_path / "work", ["history"], log=lambda _: None)
    assert result.unreadable == 2
    assert result.failed == []
    history = pl.read_parquet(tmp_path / f"archive/chmi-history-0/chmi-history-{LIBUS}.parquet")
    assert sorted(history["resolution"].unique()) == ["pentadic", "phenomena", "yearly"]


def test_failed_upload_is_retried_next_time(tmp_path: Path):
    class Broken(ca.LocalStore):
        def put(self, tag, name, path):
            if name.startswith("chmi-history"):
                raise OSError("upload failed")
            super().put(tag, name, path)

    server = history_server()
    with server.client() as client:
        result = ca.archive(
            client, Broken(tmp_path / "archive"), tmp_path / "work", ["history"], log=lambda _: None
        )
    assert result.failed == [f"chmi-history-{LIBUS}.parquet"]
    state = json.loads((tmp_path / "archive/chmi-state/chmi-archive-state.json").read_text())
    assert f"history|{LIBUS}" not in state["units"]
    with server.client() as client:
        again = ca.archive(
            client,
            ca.LocalStore(tmp_path / "archive"),
            tmp_path / "work",
            ["history"],
            log=lambda _: None,
        )
    assert again.done == [f"chmi-history-{LIBUS}.parquet"]


class FakeReleases:
    def __init__(self, root: Path, assets: dict[str, dict[str, bytes]]) -> None:
        self.root, self.data = root, assets
        self.downloads: list[str] = []

    def tags(self, prefix=""):
        return sorted(t for t in self.data if t.startswith(prefix))

    def assets(self, tag):
        out = {}
        for name, content in self.data.get(tag, {}).items():
            path = self.root / name
            path.write_bytes(content)
            out[name] = {"name": name, "size": len(content), "label": ca.sha256(path)}
        return out

    def download(self, tag, name, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.data[tag][name])
        self.downloads.append(f"{tag}/{name}")
        return dest


def test_mirror_and_sync_skip_unchanged(tmp_path: Path):
    (tmp_path / "labels").mkdir()
    releases = FakeReleases(
        tmp_path / "labels",
        {
            "chmi-2025": {"chmi-10min-2025-12.parquet": b"a"},
            "chmi-state": {"s.json": b"{}"},
            "data-latest": {"x": b"x"},
        },
    )
    copied = ca.mirror(releases, tmp_path / "mirror", log=lambda _: None)
    assert copied == ["chmi-2025/chmi-10min-2025-12.parquet", "chmi-state/s.json"]
    assert (tmp_path / "mirror/chmi-2025/chmi-10min-2025-12.parquet").read_bytes() == b"a"
    assert ca.mirror(releases, tmp_path / "mirror", log=lambda _: None) == []
    releases.data["chmi-2025"]["chmi-10min-2025-12.parquet"] = b"b"
    n = ca.sync(
        releases,
        tmp_path / "mirror",
        [("chmi-2025", "chmi-10min-2025-12.parquet"), ("chmi-2024", "missing.parquet")],
        log=lambda _: None,
    )
    assert n == 1


def test_listing_retries_server_errors():
    answers = iter([httpx.Response(503), httpx.Response(200, text=listing("a/"))])
    waits = []
    with httpx.Client(transport=httpx.MockTransport(lambda r: next(answers))) as client:
        assert [e.name for e in ca.list_dir(client, "x/", sleep=waits.append)] == ["a/"]
    assert waits == [2]
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as client:
        assert ca.list_dir(client, "x/") == []
    failing = httpx.MockTransport(lambda r: httpx.Response(500))
    with httpx.Client(transport=failing) as client, pytest.raises(httpx.HTTPStatusError):
        ca.list_dir(client, "x/", sleep=lambda _: None)
