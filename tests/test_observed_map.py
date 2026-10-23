import json
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import chmi_archive as ca
from meteoverdict import observed_map as om

DAY = date(2026, 10, 15)  # summer time: the Prague day is 22:00 UTC the day before → 22:00 UTC
A, B, C = "0-203-0-A", "0-203-0-B", "0-203-0-C"
STATIONS = pl.DataFrame(
    {
        "id": [A, B, C],
        "lat": [50.5, 50.6, 49.2],
        "lon": [14.1, 14.2, 16.6],
        "okres_code": ["CZ0423", "CZ0423", "CZ0642"],
    }
)
POINTS = pl.DataFrame(
    {
        "code": ["CZ0423", "CZ0642", "CZ0100"],
        "name": ["Litoměřice", "Brno-město", "Praha"],
        "lat": [50.53, 49.2, 50.08],
        "lon": [14.13, 16.6, 14.44],
    }
)


def utc(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def obs(items: list[tuple]) -> pl.DataFrame:
    """(station, time, field, kind, value) → observation rows."""
    return pl.DataFrame(items, schema=om.OBS_SCHEMA, orient="row")


def full_day(station: str, day: date, temp=lambda h: 10.0, rain=0.0, hours=None) -> list[tuple]:
    """A station measuring every 10 minutes and every hour of a Prague day (UTC+2)."""
    start = utc(day, 0) - timedelta(hours=2)
    rows = []
    for i in range(1, 24 * 6 + 1):
        t = start + timedelta(minutes=10 * i)
        h = (i - 1) // 6  # local hour of the 10 minutes
        rows += [
            (station, t, "tmax", "end10", temp(h) + 0.5),
            (station, t, "tmin", "end10", temp(h) - 0.5),
        ]
        rows.append((station, t, "gust", "end10", 5.0 + (h == 14)))
    for h in range(24):
        if hours is not None and h not in hours:
            continue
        end = start + timedelta(hours=h + 1)
        rows += [
            (station, end, "r", "end1h", rain),
            (station, end, "ssv", "end1h", 10.0 if 8 <= h < 16 else 0.0),
        ]
        at = start + timedelta(hours=h)
        rows += [(station, at, "wind", "inst", 2.0 + h / 10), (station, at, "n", "inst", 4.0)]
    return rows


def test_parts_of_day_follow_prague_time_and_interval_ends():
    # 04:10 UTC ends the 10 minutes from 06:00 Prague: morning; 04:00 UTC ends 05:50-06:00: night
    rows = obs(
        [
            (A, utc(DAY, 4, 10), "tmax", "end10", 9.0),
            (A, utc(DAY, 4, 0), "tmax", "end10", 7.0),
            # an hourly total ending 04:00 UTC is the hour 05-06 Prague: night
            (A, utc(DAY, 4, 0), "r", "end1h", 1.0),
            # a value at the full hour 04:00 UTC is at 06:00 Prague: morning (as the outlook)
            (A, utc(DAY, 4, 0), "wind", "inst", 3.0),
        ]
    )
    table = om._with_period(rows)
    got = dict(
        zip(zip(table["field"], table["time"].dt.minute(), strict=True), table["part"], strict=True)
    )
    assert got[("tmax", 10)] == "morning"
    assert got[("tmax", 0)] == "night"
    assert got[("r", 0)] == "night"
    assert got[("wind", 0)] == "morning"
    assert set(table["day"].to_list()) == {DAY}


def test_expected_hours_and_daylight_handle_the_clock_change():
    assert om.expected_hours(DAY, "night") == 6
    assert om.expected_hours(DAY, "day") == 24
    change = date(2026, 10, 25)  # back to CET: 02:00-03:00 twice
    assert om.expected_hours(change, "night") == 7
    assert om.expected_hours(change, "day") == 25
    light = om.daylight(50.5, 14.1, DAY)
    night, morning, afternoon, evening, day = light
    assert night == 0 and evening < 0.5
    assert 4 < morning < 5 and afternoon == 6.0
    assert day == pytest.approx(morning + afternoon + evening, abs=0.11)


def test_station_values_per_period():
    rows = obs(full_day(A, DAY, temp=lambda h: float(h), rain=0.2))
    table = om.station_periods(rows, lambda s, d: [0.0, 4.5, 6.0, 0.2, 10.7])
    by = {r["part"]: r for r in table.filter(pl.col("day") == DAY).iter_rows(named=True)}
    assert by["night"]["tmin"] == -0.5 and by["night"]["tmax"] == 5.5
    assert by["afternoon"]["tmax"] == 17.5
    assert by["day"]["tmax"] == 23.5 and by["day"]["tmin"] == -0.5
    assert by["morning"]["r"] == pytest.approx(1.2)
    assert by["day"]["r"] == pytest.approx(4.8)
    assert by["afternoon"]["gust"] == 6.0  # 14-15 h local
    # SSV1H in 0.1 h: 10 = one hour of sun in each hour 8-16 local
    assert by["morning"]["ssv"] == pytest.approx(4.0)
    assert by["day"]["ssv"] == pytest.approx(8.0)
    assert by["night"]["ssv"] is None  # no daylight
    assert by["evening"]["ssv"] is None  # 0.2 h of daylight only
    assert by["morning"]["cloud"] == 50.0  # 4 octas
    assert by["evening"]["wind"] == pytest.approx(2.0 + 2.3)  # the value at 23:00 local


def test_humidity_pressure_and_direction_per_period():
    items = full_day(A, DAY)
    start = utc(DAY, 0) - timedelta(hours=2)
    for h in range(24):
        at = start + timedelta(hours=h)
        # the wind comes from 350° and 10° alternately: the circular mean is north, not 180°
        items += [
            (A, at, "rh", "inst", 60.0 + h),
            (A, at, "pres", "inst", 1010.0),
            (A, at, "dir", "inst", 350.0 if h % 2 else 10.0),
        ]
    table = om.station_periods(obs(items))
    by = {r["part"]: r for r in table.filter(pl.col("day") == DAY).iter_rows(named=True)}
    assert by["night"]["rh"] == pytest.approx(62.5)  # hours 0-5 local: 60 … 65
    assert by["day"]["pres"] == 1010.0
    assert min(by["day"]["dir"], 360 - by["day"]["dir"]) < 1e-6
    # the station mean over an okres (one station here) keeps the direction
    okres = om.okres_periods(table, STATIONS).filter(
        pl.col("okres") == "CZ0423", pl.col("part") == "day"
    )
    assert okres["n_h"][0] == 1 and okres["rh"][0] == pytest.approx(71.5)


def test_incomplete_periods_have_no_value():
    rows = obs(full_day(A, DAY, rain=0.5, hours=[h for h in range(24) if h != 9]))
    table = om.station_periods(rows)
    by = {r["part"]: r for r in table.filter(pl.col("day") == DAY).iter_rows(named=True)}
    # a precipitation total needs every hour of the period
    assert by["morning"]["r"] is None
    assert by["day"]["r"] is None
    assert by["afternoon"]["r"] == pytest.approx(3.0)
    # temperature needs 80 % of the hours: a morning with only two hours has none
    short = obs(
        [r for r in full_day(B, DAY) if not (r[2] in ("tmax", "tmin") and 4 < r[1].hour < 10)]
    )
    morning = om.station_periods(short).filter(pl.col("day") == DAY, pl.col("part") == "morning")
    assert morning["tmax"].to_list() == [None]


def test_okres_values_are_means_with_extremes_and_counts():
    rows = obs(
        full_day(A, DAY, temp=lambda h: 10.0, rain=0.1)
        + full_day(B, DAY, temp=lambda h: 14.0, rain=0.3)
        + [r for r in full_day(C, DAY) if r[2] in ("tmax", "tmin")]
    )
    values = om.station_periods(rows)
    okres = om.okres_periods(values, STATIONS)
    day = {
        r["okres"]: r
        for r in okres.filter(pl.col("day") == DAY, pl.col("part") == "day").iter_rows(named=True)
    }
    lit = day["CZ0423"]
    assert lit["tmax"] == pytest.approx(12.5) and lit["tmax_hi"] == 14.5
    assert lit["tmin_lo"] == 9.5
    assert lit["r"] == pytest.approx(4.8) and lit["r_hi"] == pytest.approx(7.2)
    assert lit["n_t"] == 2 and lit["n_r"] == 2 and lit["n_g"] == 2
    assert lit["st"] == [A, B]
    brno = day["CZ0642"]
    assert brno["n_t"] == 1 and brno["n_r"] == 0 and brno["r"] is None


def test_an_okres_without_a_station_borrows_the_nearest_of_its_neighbours():
    # okres X has a rain gauge only; Y's stations lie 3, 8, 12, 25 and 40 km from X's
    # border; Z has nothing within 30 km
    own, y = "0-203-0-X1", [f"0-203-0-Y{i}" for i in range(5)]
    stations = pl.DataFrame(
        {"id": [own, *y], "okres_code": ["X", "Y", "Y", "Y", "Y", "Y"]},
    )
    km = [3.0, 8.0, 12.0, 25.0, 40.0]
    distance = pl.DataFrame(
        {
            "region": ["X"] * 6 + ["Y"] * 6 + ["Z"] * 6,
            "region_name": ["X"] * 6 + ["Y"] * 6 + ["Z"] * 6,
            "station_id": [own, *y] * 3,
            "distance_km": [0.0, *km, 5.0, 0, 0, 0, 0, 0, *[31.0 + i for i in range(6)]],
        }
    )

    def row(station, tmax, r=None, cloud=None):
        return {
            "station": station,
            "day": DAY,
            "part": "day",
            **dict.fromkeys(om.STATION_COLUMNS),
            "tmax": tmax,
            "tmin": None if tmax is None else tmax - 10,
            "r": r,
            "cloud": cloud,
        }

    values = pl.DataFrame(
        [
            row(own, None, r=1.0),
            row(y[0], None, r=2.0),  # nearest, but no temperature: the next ones lend it
            row(y[1], 10.0),
            row(y[2], 12.0),
            row(y[3], 14.0, cloud=50.0),
            row(y[4], 30.0),  # beyond 30 km: never
        ],
        schema={
            "station": pl.String,
            "day": pl.Date,
            "part": pl.String,
            **dict.fromkeys(om.STATION_COLUMNS, pl.Float64),
        },
    )
    got = {
        r["okres"]: r for r in om.okres_periods(values, stations, distance).iter_rows(named=True)
    }
    x = got["X"]
    # its own rain gauge, not borrowed
    assert x["r"] == 1.0 and x["n_r"] == 1 and x["b_r"] is None
    # temperature from the three nearest with one (Y1, Y2, Y3), nearest first
    assert x["b_t"] == [y[1], y[2], y[3]] and x["n_t"] == 3
    assert x["tmax"] == pytest.approx(12.0) and x["tmax_hi"] == 14.0 and x["tmin_lo"] == 0.0
    # cloud: the only one within 30 km
    assert x["b_c"] == [y[3]] and x["cloud"] == 50.0 and x["n_c"] == 1
    assert x["st"] == [own]  # its own stations only
    # Y has its own stations: borrows nothing (X's rain gauge is 5 km from Y)
    assert got["Y"]["b_r"] is None and got["Y"]["b_t"] is None and got["Y"]["n_t"] == 4
    # Z: nothing near enough, stays empty (a dash on the map)
    assert "Z" not in got
    # without distances nothing is borrowed (as before)
    plain = om.okres_periods(values, stations).filter(pl.col("okres") == "X").row(0, named=True)
    assert plain["n_t"] == 0 and plain["tmax"] is None


def test_daily_values_for_older_days():
    def row(station, element, vtype, hour, value, quality=0):
        return {
            "station": station,
            "resolution": "daily",
            "time": utc(DAY, hour),
            "element": element,
            "vtype": vtype,
            "func": None,
            "value": value,
            "flag": None,
            "flag2": None,
            "quality": quality,
        }

    daily = pl.DataFrame(
        [
            row(A, "TMA", "20:00", 20, 15.5),
            row(A, "TMI", "20:00", 20, 4.2),
            row(A, "SRA", "06:00", 6, 2.0),
            row(A, "SNO", "06:00", 6, 3.0),
            row(B, "SRA", "06:00", 6, 9.9, 1),  # suspect: left out
        ],
        schema=ca.SCHEMA,
    )
    days = om.station_days(daily)
    assert days.height == 1
    got = days.row(0, named=True)
    assert (got["tmax"], got["r"], got["sno"], got["part"]) == (15.5, 2.0, 3.0, "day")
    assert got["tmin"] == pytest.approx(4.2)
    assert got["wind"] is None and got["cloud"] is None
    phen = pl.DataFrame(
        [
            {"station": A, "resolution": "phenomena", "time": utc(DAY, 0), "element": code}
            for code in ("SN", "RO", "BO")
        ],
        schema=ca.SCHEMA,
    )
    extras = om.day_extras(daily, phen)
    assert extras.filter(pl.col("station") == A)["ph"].to_list() == [["BO", "SN"]]


def parts_run(issued: datetime, day: date, tmax: float) -> pl.DataFrame:
    table = pl.DataFrame(
        {
            "okres": ["CZ0423"] * 5,
            "day": [day] * 5,
            "part": list(om.PERIODS),
            "tmin": [5.0] * 5,
            "tmax": [tmax] * 5,
            "precipitation": [0.0, 0.4, 1.0, 0.0, 1.4],
            "rain_probability": [0.1, 0.55, 0.7, 0.2, 0.8],
            "wind": [3.0] * 5,
            "cloud": [80.0] * 5,
            "sunshine": [0.0, 1.0, 2.0, 0.0, 3.0],
            "symbol": ["cloudy", "rain", "rain", "cloudy", "rain"],
        }
    )
    # as the parts archive holds it: columns the table lacks are null
    return table.select(
        pl.lit(issued).dt.cast_time_unit("us").alias("issued"),
        "okres",
        "day",
        "part",
        *[
            (pl.col(c) if c in table.columns else pl.lit(None)).alias(c)
            for c in om.PARTS_ARCHIVE_COLUMNS
        ],
    ).cast(om.PARTS_ARCHIVE_SCHEMA)


def test_archive_names():
    run = utc(DAY, 4, 52)
    assert om.parts_archive_asset(run) == ("outlook-archive", "outlook-parts-2026-10.parquet")
    means = ("outlook-archive", "outlook-archive-2026-10.parquet")
    assert om.means_archive_asset("2026-10") == means
    assert om.HINDCAST_ASSET == ("outlook-archive", "outlook-hindcast.parquet")


def test_sky_symbol():
    assert [om.sky_symbol(c) for c in (None, 10.0, 30.0, 64.9, 65.0)] == [
        None,
        "clear",
        "partly",
        "partly",
        "cloudy",
    ]


def test_runs_beside_the_measured_day():
    archive = pl.concat(
        [
            parts_run(utc(DAY, 4, 50), DAY, 15.0),  # lead 0 (the day's own morning run)
            parts_run(utc(DAY - timedelta(days=1), 4, 50), DAY, 14.0),  # lead 1
            parts_run(utc(DAY - timedelta(days=1), 20, 50), DAY, 13.0),  # lead 1, newer
            parts_run(utc(DAY - timedelta(days=1), 22, 50), DAY, 13.5),  # 00:50 Prague: lead 0
            parts_run(utc(DAY - timedelta(days=3), 10, 50), DAY, 11.0),  # lead 3
        ]
    )
    picked = om.pick_runs(archive, DAY)
    # the same day: its first run (00:50 Prague), then the newest of each lead
    assert [(lead, at.hour) for lead, at in picked] == [(0, 22), (1, 20), (3, 10)]
    doc = om.forecast_doc(archive, DAY, om.PERIODS)
    assert [(f["lead"], f["kind"]) for f in doc] == [(0, "stored"), (1, "stored"), (3, "stored")]
    assert doc[1]["lead"] == 1 and doc[1]["issued"] == "2026-10-14T20:50Z"
    lit = doc[1]["okresy"]["CZ0423"]
    assert lit["tmax"] == [13] * 5 and lit["symbol"][1] == "rain"
    assert lit["rain_probability"][1] == 0.55
    # only runs of the day itself: its first one
    only = om.pick_runs(
        archive.filter(pl.col("issued") >= utc(DAY - timedelta(days=1), 22, 0)), DAY
    )
    assert [(lead, at.hour) for lead, at in only] == [(0, 22)]
    # a same-day run from the afternoon is not a forecast of the day any more
    late = om.pick_runs(parts_run(utc(DAY, 11, 0), DAY, 15.0), DAY)
    assert late == []


def sky_run(issued: datetime, day: date, cloud: float) -> pl.DataFrame:
    """The plain-means archive of one run: hourly cloud and sunshine of a Prague day."""
    start = utc(day, 0) - timedelta(hours=2)
    hours = [start + timedelta(hours=h) for h in range(25)]
    return pl.DataFrame(
        {
            "okres": ["CZ0423"] * len(hours),
            "issued": [issued] * len(hours),
            "time": hours,
            "cloud_cover": [cloud] * len(hours),
            "sunshine_duration": [1800.0] * len(hours),
        }
    ).cast({"issued": pl.Datetime("us", "UTC"), "time": pl.Datetime("us", "UTC")})


def rebuilt_rows(day: date, leads=(1, 2)) -> pl.DataFrame:
    rows = []
    for lead in leads:
        for part in om.PERIODS:
            rows.append(
                {
                    "lead": lead,
                    "trained_to": day - timedelta(days=lead + 1),
                    "okres": "CZ0423",
                    "day": day,
                    "part": part,
                    "tmin": 4.0,
                    "tmax": 10.0 + lead,
                    "precipitation": 0.0,
                    "rain_probability": 0.0,
                    "wind": 3.0,
                    "symbol": None,
                }
            )
    return (
        pl.DataFrame(rows)
        .with_columns(*[pl.lit(None).alias(c) for c in ("gust", "cloud", "sunshine")])
        .select(list(om.HINDCAST_SCHEMA))
        .cast(om.HINDCAST_SCHEMA)
    )


def test_forecasts_stored_first_then_rebuilt_with_the_stored_sky():
    stored = parts_run(utc(DAY - timedelta(days=2), 10, 50), DAY, 12.0)  # lead 2, stored
    means = pl.concat(
        [
            sky_run(utc(DAY, 1, 11), DAY, 10.0),  # 03:11 Prague: the same day's run
            sky_run(utc(DAY - timedelta(days=1), 10, 10), DAY, 90.0),  # lead 1
        ]
    )
    doc = om.forecast_doc(stored, DAY, om.PERIODS, rebuilt_rows(DAY), means)
    kinds = [(f["lead"], f["kind"]) for f in doc]
    # lead 0: only the sky was stored; lead 1 rebuilt (with the stored sky); lead 2 the
    # stored parts of day win over the rebuilt ones
    assert kinds == [(0, "stored_sky"), (1, "rebuilt"), (2, "stored")]
    same_day = doc[0]
    assert same_day["issued"] == "2026-10-15T01:11Z" and same_day["columns"] == [
        "cloud",
        "sunshine",
        "symbol",
    ]
    assert same_day["okresy"]["CZ0423"]["symbol"][4] == "clear"
    assert same_day["okresy"]["CZ0423"]["sunshine"][0] == 3.0  # six half-hours at night
    lead1 = doc[1]
    assert lead1["trained_to"] == "2026-10-13" and lead1["sky_issued"] == "2026-10-14T10:10Z"
    lit = lead1["okresy"]["CZ0423"]
    assert lit["tmax"] == [11] * 5 and lit["cloud"] == [90] * 5 and lit["symbol"] == ["cloudy"] * 5
    assert "gust" not in lead1["columns"]  # a column no okres has is left out
    assert doc[2]["okresy"]["CZ0423"]["tmax"] == [12] * 5


def write_archive(root, days: list[date], stations=(A, B)) -> None:
    """Captured days (chmi-now) with two stations, in the archive's own schema."""
    rows = []
    for day in days:
        for station in stations:
            for s, t, field, _kind, value in full_day(station, day, rain=0.1):
                element = {
                    "tmax": "TMA",
                    "tmin": "TMI",
                    "gust": "Fmax",
                    "r": "SRA1H",
                    "ssv": "SSV1H",
                    "wind": "F",
                    "n": "N",
                }[field]
                resolution = "1hour" if element in ("SRA1H", "SSV1H", "N") else "10min"
                rows.append((s, resolution, t, element, None, None, value, None, None, 0))
    frame = pl.DataFrame(rows, schema=ca.SCHEMA, orient="row")
    for day in {t.date() for t in frame["time"].to_list()}:
        tag, name = ca.day_asset(day)
        (root / tag).mkdir(parents=True, exist_ok=True)
        frame.filter(pl.col("time").dt.date() == day).write_parquet(root / tag / name)


def test_build_writes_days_index_and_forecasts(tmp_path):
    root = tmp_path / "chmi"
    write_archive(root, [DAY - timedelta(days=1), DAY])
    out = tmp_path / "observed"
    out.mkdir()
    (out / "2020-01-01.json").write_text("{}")  # a day no longer offered
    today = DAY + timedelta(days=1)
    archive = parts_run(utc(DAY - timedelta(days=1), 20, 50), DAY, 13.0)
    om.build(
        root,
        STATIONS,
        POINTS,
        out,
        today,
        parts_archive=archive,
        part_days=3,
        daily_days=5,
        min_stations=1,
        generated=utc(today, 5),
        log=lambda _: None,
    )
    index = json.loads((out / "index.json").read_text())
    assert [d["day"] for d in index["days"]] == ["2026-10-14", "2026-10-15"]
    assert index["days"][1] == {
        "day": "2026-10-15",
        "source": "hourly",
        "leads": [1],
        "kinds": ["stored"],
    }
    assert not (out / "2020-01-01.json").exists()
    doc = json.loads((out / "2026-10-15.json").read_text())
    assert doc["parts"] == list(om.PERIODS)
    lit = doc["okresy"]["CZ0423"]
    assert lit["n_t"] == [2] * 5 and lit["tmax"][4] == 10.5
    assert lit["r"][4] == 2.4 and lit["st"] == [A, B]
    # an okres without stations: nulls and zero counts
    assert (
        doc["okresy"]["CZ0100"]["tmax"] == [None] * 5 and doc["okresy"]["CZ0100"]["n_t"] == [0] * 5
    )
    assert doc["forecasts"][0]["okresy"]["CZ0423"]["tmax"] == [13] * 5
    stations = json.loads((out / "2026-10-15-stations.json").read_text())
    assert set(stations["stations"]) == {A, B}
    assert len(stations["stations"][A]) == len(om.PERIODS) * len(om.STATION_COLUMNS)


def test_build_marks_borrowed_stations(tmp_path):
    # Blansko has no station; C in Brno-město is 10 km from its border
    root = tmp_path / "chmi"
    write_archive(root, [DAY - timedelta(days=1), DAY], stations=(A, B, C))
    stations = STATIONS.with_columns(
        pl.Series("name", ["Alfa", "Beta", "Brno"]),
        pl.Series("okres", ["Litoměřice", "Litoměřice", "Brno-město"]),
    )
    points = pl.concat(
        [
            POINTS,
            pl.DataFrame({"code": ["CZ0641"], "name": ["Blansko"], "lat": [49.4], "lon": [16.7]}),
        ]
    )
    out = tmp_path / "observed"
    om.build(
        root,
        stations,
        points,
        out,
        DAY + timedelta(days=1),
        part_days=3,
        daily_days=3,
        min_stations=1,
        log=lambda _: None,
    )
    doc = json.loads((out / "2026-10-15.json").read_text())
    assert doc["borrow"] == {"max_km": 30.0, "stations": 3}
    blansko = doc["okresy"]["CZ0641"]
    assert blansko["n_t"] == [1] * 5 and blansko["tmax"][4] == 10.5
    assert blansko["borrowed"]["t"] == [[C]] * 5 and set(blansko["borrowed"]) == {
        "t",
        "r",
        "w",
        "g",
        "s",
        "c",
    }
    assert blansko["bst"] == [{"id": C, "name": "Brno", "okres": "Brno-město", "km": 10.2}]
    assert blansko["st"] == []
    # Praha: the nearest station is 43 km away, nothing borrowed
    praha = doc["okresy"]["CZ0100"]
    assert praha["n_t"] == [0] * 5 and "borrowed" not in praha and "bst" not in praha
    # okresy with stations of their own borrow nothing
    assert "borrowed" not in doc["okresy"]["CZ0423"]


def test_build_skips_a_day_the_archive_has_not_finished(tmp_path):
    root = tmp_path / "chmi"
    write_archive(root, [DAY])
    # the newest captured day ends at 22:00 UTC of DAY; the next Prague day is not complete
    rows = pl.read_parquet(root / "chmi-now-2026" / "chmi-now-2026-10-15.parquet")
    rows.filter(pl.col("time") < utc(DAY, 12)).write_parquet(
        root / "chmi-now-2026" / "chmi-now-2026-10-15.parquet"
    )
    out = tmp_path / "observed"
    om.build(
        root,
        STATIONS,
        POINTS,
        out,
        DAY + timedelta(days=1),
        part_days=2,
        daily_days=2,
        min_stations=1,
        log=lambda _: None,
    )
    assert json.loads((out / "index.json").read_text())["days"] == []


def test_wanted_assets_cover_the_days_read():
    wanted = om.wanted_assets(date(2026, 10, 17))
    assert ("chmi-now-2026", "chmi-now-2026-10-16.parquet") in wanted
    assert ("chmi-2026", "chmi-10min-2026-09.parquet") in wanted
    assert ("chmi-2026", "chmi-daily-2026-08.parquet") in wanted
    assert om.parts_archive_names(date(2026, 10, 17))[-1] == (
        "outlook-archive",
        "outlook-parts-2026-10.parquet",
    )


def test_cli_writes_the_folder_from_a_local_archive(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from meteoverdict.cli import app

    root = tmp_path / "chmi"
    yesterday = date.today() - timedelta(days=1)
    write_archive(root, [yesterday - timedelta(days=1), yesterday])
    stations = tmp_path / "stations.parquet"
    STATIONS.write_parquet(stations)
    parts = tmp_path / "parts"
    parts.mkdir()
    out = tmp_path / "observed"
    result = CliRunner().invoke(
        app,
        [
            "observed-map",
            "--archive",
            str(root),
            "--stations",
            str(stations),
            "--parts-dir",
            str(parts),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out / "index.json").exists()
    # --publish needs the releases
    bad = CliRunner().invoke(app, ["observed-map", "--stations", str(stations), "--publish"])
    assert bad.exit_code != 0


def test_high_sites_are_out_of_the_okres_mean_but_listed_with_the_nearest_station(tmp_path):
    # D stands 620 m above the okres's median (as Milešovka): in no okres mean, own station
    # values and the okres file's "high" keep it; "near" is the station nearest the point
    d = "0-203-0-D"
    stations = pl.DataFrame(
        {
            "id": [A, B, d],
            "name": ["Aa", "Bb", "Dd"],
            "lat": [50.5, 50.6, 50.53],
            "lon": [14.1, 14.2, 14.13],
            "okres_code": ["CZ0423"] * 3,
            "elevation": [200.0, 240.0, 840.0],
        }
    )
    rows = obs(
        full_day(A, DAY, temp=lambda h: 10.0)
        + full_day(B, DAY, temp=lambda h: 14.0)
        + full_day(d, DAY, temp=lambda h: -2.0)
    )
    values = om.station_periods(rows)
    okres = om.okres_periods(values, stations)
    lit = okres.filter(pl.col("day") == DAY, pl.col("part") == "day").row(0, named=True)
    assert lit["n_t"] == 2 and lit["tmax"] == pytest.approx(12.5) and lit["st"] == [A, B]
    assert lit["tmin_lo"] == 9.5  # not the high site's -2.5
    extras = pl.DataFrame(
        schema={"station": pl.String, "day": pl.Date, "sno": pl.Float64, "ph": pl.List(pl.String)}
    )
    doc = om.day_doc(DAY, "hourly", okres, extras, POINTS, stations, [], utc(DAY, 5), None, values)
    entry = doc["okresy"]["CZ0423"]
    assert [h["id"] for h in entry["high"]] == [d] and entry["high"][0]["elevation"] == 840
    assert entry["high"][0]["tmin"][4] == -2.5
    assert entry["near"]["id"] == d and entry["near"]["km"] < 1  # at the okres point
    assert "high" not in doc["okresy"]["CZ0642"]
