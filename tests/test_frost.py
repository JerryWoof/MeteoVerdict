import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import polars as pl
import pytest
from typer.testing import CliRunner

from meteoverdict import combine, frost, outlook
from meteoverdict.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
CODES = ["CZ0100", "CZ0201"]
NOW = datetime(2026, 10, 12, 8, 25, tzinfo=UTC)  # when the saved answer was fetched
PAYLOAD = json.loads((FIXTURES / "open-meteo" / "forecast-2-okresy.json").read_text("utf-8"))


def utc(day, hour):
    return datetime(2026, 10, day, hour, tzinfo=UTC)


def hourly(start, hours, temp, **columns):
    times = [start + timedelta(hours=h) for h in range(hours)]
    return pl.DataFrame(
        {
            "time": times,
            "temperature_2m": [temp(t) for t in times],
            **{k: [v] * hours for k, v in columns.items()},
        }
    )


def test_a_night_is_18_to_06_utc_labelled_by_its_end():
    # 12 Oct 12 UTC .. 14 Oct 11 UTC; the coldest hour of each night is at 03 UTC
    frame = hourly(
        utc(12, 12),
        48,
        lambda t: -1.0 if t.hour == 3 else (20.0 if t.hour == 12 else 5.0),
        wind_speed_10m=1.0,
        cloud_cover=40.0,
    ).with_columns(pl.lit("s1").alias("station_id"))
    nights = frost.night_minima(frame, ["station_id"]).sort("night")
    assert nights["night"].to_list() == [date(2026, 10, 13), date(2026, 10, 14)]
    assert nights["fmin"].to_list() == [-1.0, -1.0]
    assert nights["hours"].to_list() == [12, 12]
    assert nights["cloud"].to_list() == [pytest.approx(0.4)] * 2
    # a night with fewer than MIN_NIGHT_HOURS hours is left out
    short = frame.filter(pl.col("time") < utc(14, 2))
    assert frost.night_minima(short, ["station_id"])["night"].to_list() == [date(2026, 10, 13)]


def test_observed_nights_from_the_chmi_daily_archive():
    daily = pl.DataFrame(
        {
            "station": ["s1", "s1", "s1", "s2"],
            "time": [utc(13, 6), utc(13, 6), utc(13, 20), utc(13, 6)],
            "element": ["TMInoc", "TPM", "TMI", "TPM"],
            "vtype": ["06:00", "06:00", "20:00", "06:00"],
            "value": [-0.7, -2.8, -0.7, 1.0],
        }
    )
    obs = frost.observed_nights(daily)
    # s2 has no air minimum: left out
    assert obs.rows() == [("s1", date(2026, 10, 13), pytest.approx(-0.7), pytest.approx(-2.8))]


def pairs_for(biases, stations, nights=20, wind=3.0):
    """Every model and station: forecast = obs + model bias + station bias."""
    rows = []
    for n in range(nights):
        night = date(2026, 9, 1) + timedelta(days=n)
        for station, station_bias in stations.items():
            tmin = 5.0 + (n % 5)
            for model, bias in biases.items():
                rows.append((station, model, 1, night, tmin + bias + station_bias, wind, tmin))
    return pl.DataFrame(
        rows,
        schema={
            "station_id": pl.String,
            "model": pl.String,
            "lead_day": pl.Int8,
            "night": pl.Date,
            "fmin": pl.Float64,
            "wind": pl.Float64,
            "tmin": pl.Float64,
        },
        orient="row",
    )


def test_fit_model_and_shrunk_station_biases():
    pairs = pairs_for({"a": 2.0, "b": 0.5}, {"warm": -1.0, "cold": 1.0})
    cal = frost.fit(pairs)
    bias = dict(zip(cal.model_bias["model"], cal.model_bias["bias"], strict=True))
    assert bias == {"a": pytest.approx(2.0), "b": pytest.approx(0.5)}
    stations = dict(zip(cal.stations["station_id"], cal.stations["bias"], strict=True))
    # 20 nights: shrunk by 20 / (20 + 10)
    assert stations == {"cold": pytest.approx(2 / 3), "warm": pytest.approx(-2 / 3)}
    assert cal.first == date(2026, 9, 1) and cal.last == date(2026, 9, 20)
    # only the last window_nights nights count
    assert frost.fit(pairs, window_nights=10).stations["nights"].to_list() == [10, 10]
    # the corrected minimum of the training nights: what is left is the shrinkage
    ens = frost.station_ensemble(pairs, cal, clear_calm=False).join(
        pairs.group_by("station_id", "night").agg(pl.col("tmin").first()),
        on=["station_id", "night"],
    )
    error = (ens["min"] - ens["tmin"]).abs()
    assert error.max() == pytest.approx(1 / 3)
    assert cal.sigma == pytest.approx(1 / 3, rel=0.05)


def test_calibration_round_trip(tmp_path):
    stations = pl.DataFrame(
        {"id": ["cold", "warm"], "name": ["Cold", "Warm"], "okres_code": ["X", "X"]}
    ).with_columns(pl.Series("elevation", [600.0, 200.0]))
    cal = frost.fit(pairs_for({"a": 2.0}, {"warm": -1.0, "cold": 1.0}), stations)
    back = frost.Calibration.read(cal.write(tmp_path / "frost.json"))
    assert back.stations["name"].to_list() == ["Cold", "Warm"]
    assert back.stations["okres"].to_list() == ["X", "X"]
    assert back.model_bias["lead_day"].dtype == pl.Int8
    assert back.clear_calm["intercept"] == 1.33
    assert back.sigma == pytest.approx(cal.sigma, abs=1e-3)


def test_clear_calm_cools_clear_calm_nights_and_warms_overcast_windy_ones():
    term = frost.clear_calm(pl.col("cloud"), pl.col("wind"), frost.CLEAR_CALM)
    frame = pl.DataFrame({"cloud": [0.0, 1.0, 1.0, None], "wind": [1.0, 4.0, 9.0, 1.0]})
    values = frame.select(term).to_series().to_list()
    assert values[0] == pytest.approx(1.33 - 0.36)
    assert values[1] == pytest.approx(1.33 - 1.12 - 0.36 * 4)
    assert values[2] == pytest.approx(1.33 - 1.12 - 0.36 * 5)  # wind capped at 5 m/s
    assert values[3] == 0.0  # without cloud no term


def test_probability_and_ground_offset():
    assert frost.probability(0.0, 1.6) == pytest.approx(0.5)
    assert frost.probability(1.6, 1.6) == pytest.approx(0.1587, abs=1e-4)
    assert frost.probability(None, 1.6) is None
    offset = pl.DataFrame({"c": [0.0, 1.0], "w": [0.0, 4.0]}).select(
        frost.ground_offset(pl.col("c"), pl.col("w"))
    )
    assert offset.to_series().to_list() == [pytest.approx(-5.0), pytest.approx(-2.1)]


MODELS = sorted(
    {
        key.removeprefix("temperature_2m_")
        for key in PAYLOAD[0]["hourly"]
        if key.startswith("temperature_2m_")
    }
)
FC = outlook.parse(PAYLOAD, CODES, MODELS)


def calibration(stations=None):
    """Every model 1 °C too warm at lead 1 (used for all leads); two stations in Benešov."""
    model_bias = pl.DataFrame({"model": sorted(FC["model"].unique().to_list())}).with_columns(
        pl.lit(1, pl.Int8).alias("lead_day"), pl.lit(1.0).alias("bias"), pl.lit(30).alias("n")
    )
    if stations is None:
        stations = pl.DataFrame(
            {
                "station_id": ["low", "high"],
                "name": ["Valley", "Hill"],
                "okres": ["CZ0201", "CZ0201"],
                "elevation": [330.0, 480.0],
                "bias": [1.0, -1.0],
                "bias_calm": [1.0, -1.0],
                "bias_windy": [1.0, -1.0],
                "nights": [30, 30],
            }
        )
    return frost.Calibration(model_bias, stations, sigma=1.6)


def test_point_nights_carry_lead_and_elevation():
    nights = frost.point_nights(FC, PAYLOAD, CODES, NOW)
    assert nights.columns == list(frost.ARCHIVE_COLUMNS)
    # the night ending today (12 Oct) is over; 13 Oct is lead 1
    assert nights["night"].min() == date(2026, 10, 13)
    first = nights.filter(pl.col("night") == date(2026, 10, 13))
    assert set(first["lead_day"]) == {1}
    assert dict(first.select("okres", "elevation").unique().rows()) == {
        "CZ0100": 217.0,
        "CZ0201": 430.0,
    }


def test_okres_minimum_coldest_site_and_warnings():
    nights = frost.point_nights(FC, PAYLOAD, CODES, NOW)
    cal = calibration()
    out = frost.okres_nights(nights, cal).sort("okres", "night")
    one = nights.filter(pl.col("okres") == "CZ0201", pl.col("night") == date(2026, 10, 13))
    model_only = (one["fmin"] - 1.0).mean()
    cloud, wind = one["cloud"].mean(), one["wind"].mean()
    term = 1.33 - 1.12 * cloud - 0.36 * min(wind, 5)
    row = out.filter(pl.col("okres") == "CZ0201", pl.col("night") == date(2026, 10, 13)).row(
        0, named=True
    )
    # okres: the mean station bias of the okres (0 here) at the okres point
    assert row["night_min"] == pytest.approx(model_only - term)
    # the valley station (bias +1, 100 m lower than the point) is the coldest site
    assert row["coldest_site"] == "Valley"
    assert row["coldest_min"] == pytest.approx(model_only + 0.0065 * 100 - 1.0 - term)
    assert row["frost_probability"] == pytest.approx(frost.probability(row["night_min"], 1.6))
    assert row["frost"] == (row["night_min"] <= 1.0)
    ground = row["night_min"] - 5.0 + 1.5 * cloud + 0.35 * wind
    assert row["ground_min"] == pytest.approx(ground)
    assert row["ground_frost"] == (ground <= 0)
    # Praha has no calibrated station: no coldest site, no station correction
    praha = out.filter(pl.col("okres") == "CZ0100")
    assert praha["coldest_site"].is_null().all()
    assert praha["night_min"].is_not_null().all()


def test_wind_split_takes_the_calm_or_windy_station_bias():
    nights = frost.point_nights(FC, PAYLOAD, CODES, NOW)
    stations = calibration().stations.with_columns(
        pl.lit(5.0).alias("bias_calm"), pl.lit(-5.0).alias("bias_windy")
    )
    cal = calibration(stations)
    plain = frost.okres_nights(nights, cal)
    cal.split_wind = True
    split = frost.okres_nights(nights, cal)
    winds = (
        nights.group_by("okres", "night")
        .agg(pl.col("wind").mean())
        .join(plain, on=["okres", "night"])
    ).join(
        split.select("okres", "night", pl.col("night_min").alias("split")), on=["okres", "night"]
    )
    benesov = winds.filter(pl.col("okres") == "CZ0201")
    expected = pl.when(pl.col("wind") < 2).then(-5.0).otherwise(5.0)
    assert (
        benesov.select((pl.col("split") - pl.col("night_min") - expected).abs().max()).item() < 1e-9
    )


def test_outlook_gets_the_frost_fields_on_night_and_day_rows(tmp_path):
    weights = pl.concat(
        [
            pl.DataFrame(doc["rows"], schema=doc["columns"], orient="row").with_columns(
                pl.lit(code).alias("region"), pl.col("lead_day").cast(pl.Int8)
            )
            for code in CODES
            for doc in [json.loads((FIXTURES / "weights" / f"{code}.json").read_text("utf-8"))]
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PAYLOAD)

    points = combine.okres_points().filter(pl.col("code").is_in(CODES)).sort("code")
    nights: list[pl.DataFrame] = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        table, _ = outlook.outlook(
            client, weights, points, now=NOW, frost_calibration=calibration(), nights=nights
        )
    assert nights and nights[0].height > 0
    filled = table.filter(pl.col("night_min").is_not_null())
    assert set(filled["part"]) == {"night", "day"}
    assert filled["day"].min() == date(2026, 10, 13)
    # the same night on both rows of its day
    pairs = filled.group_by("okres", "day").agg(pl.col("night_min").n_unique())
    assert (pairs["night_min"] == 1).all()
    path = outlook.write(table, points, tmp_path / "outlook.json", NOW)
    doc = json.loads(path.read_text("utf-8"))
    assert doc["columns"] == [*outlook.COLUMNS, *frost.OUTLOOK_COLUMNS]
    rows = [dict(zip(doc["columns"], r, strict=True)) for r in doc["rows"]]
    night = next(
        r
        for r in rows
        if r["okres"] == "CZ0201" and r["day"] == "2026-10-13" and r["part"] == "night"
    )
    assert night["coldest_site"] == "Valley"
    assert isinstance(night["frost"], bool) and isinstance(night["ground_frost"], bool)
    assert 0 <= night["frost_probability"] <= 1
    # without a calibration the fields are there, empty
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        plain, _ = outlook.outlook(client, weights, points, now=NOW)
    assert plain["night_min"].is_null().all()


def test_archive_merges_runs_by_month(tmp_path):
    nights = frost.point_nights(FC, PAYLOAD, CODES, NOW)
    frost.write_archive(nights, tmp_path)
    frost.write_archive(nights, tmp_path)  # the same run again replaces its rows
    later = frost.point_nights(FC, PAYLOAD, CODES, NOW + timedelta(hours=12))
    (written,) = frost.write_archive(later, tmp_path)
    assert written.name == "2026-10.parquet"
    stored = pl.read_parquet(written)
    assert stored.height == nights.height + later.height
    assert frost.archive_name("2026-10") == "outlook-nights-2026-10.parquet"


def test_clear_calm_refit_needs_enough_nights_and_recovers_the_term():
    cal = calibration(
        pl.DataFrame(
            {
                "station_id": ["s"],
                "name": ["S"],
                "okres": ["X"],
                "elevation": [300.0],
                "bias": [0.0],
                "bias_calm": [0.0],
                "bias_windy": [0.0],
                "nights": [30],
            }
        )
    )
    model = cal.model_bias["model"][0]
    rows, obs = [], []
    for n in range(40):
        night = date(2026, 9, 1) + timedelta(days=n)
        cloud, wind = (n % 7) / 6, 0.5 + (n % 5)
        tmin = 3.0
        # forecast too warm by 0.5 - 1.0 * cloud - 0.2 * wind, after the model bias of 1
        fmin = tmin + 1.0 + 0.5 - 1.0 * cloud - 0.2 * min(wind, 5)
        rows.append((NOW, "X", model, night, 1, fmin, wind, cloud, 12, 300.0))
        obs.append(("s", night, tmin, None))
    archive = pl.DataFrame(rows, schema=list(frost.ARCHIVE_COLUMNS), orient="row").with_columns(
        pl.col("lead_day").cast(pl.Int8)
    )
    observed = pl.DataFrame(obs, schema=["station_id", "night", "tmin", "ground"], orient="row")
    refit = frost.refit_clear_calm(archive, observed, cal)
    assert refit["intercept"] == pytest.approx(0.5, abs=1e-3)
    assert refit["cloud"] == pytest.approx(-1.0, abs=1e-3)
    assert refit["wind"] == pytest.approx(-0.2, abs=1e-3)
    assert refit["nights"] == 40
    few = frost.refit_clear_calm(archive.head(10), observed, cal)
    assert few == cal.clear_calm


def test_frost_fit_command_on_local_files(tmp_path):
    today = datetime.now(UTC).date()
    fc_rows, daily_rows = [], []
    for night in [today - timedelta(days=d) for d in range(1, 21)]:
        evening = datetime.combine(night - timedelta(days=1), datetime.min.time(), UTC)
        for h in range(18, 30):  # 18 UTC to 05 UTC
            for model, bias in (("a", 2.0), ("b", 1.0)):
                fc_rows.append(("s1", evening + timedelta(hours=h), model, 1, 3.0 + bias, 1.0))
        six = datetime.combine(night, datetime.min.time(), UTC) + timedelta(hours=6)
        daily_rows += [("s1", six, "TMInoc", 3.0), ("s1", six, "TPM", 0.0)]
    fc = pl.DataFrame(
        fc_rows,
        schema=["station_id", "time", "model", "lead_day", "temperature_2m", "wind_speed_10m"],
        orient="row",
    ).with_columns(pl.col("lead_day").cast(pl.Int8))
    (tmp_path / "fc").mkdir()
    for (month,), part in fc.group_by(pl.col("time").dt.strftime("%Y-%m")):
        part.write_parquet(tmp_path / "fc" / f"{month}.parquet")
    folder = tmp_path / "chmi" / f"chmi-{today.year}"
    folder.mkdir(parents=True)
    pl.DataFrame(
        daily_rows, schema=["station", "time", "element", "value"], orient="row"
    ).with_columns(pl.lit("06:00").alias("vtype")).write_parquet(
        folder / f"chmi-daily-{today:%Y-%m}.parquet"
    )
    pl.DataFrame(
        {"id": ["s1"], "name": ["One"], "okres_code": ["X"], "elevation": [250.0]}
    ).write_parquet(tmp_path / "stations.parquet")
    out = tmp_path / "frost.json"
    result = CliRunner().invoke(
        app,
        [
            "frost-fit",
            "--data-dir", str(tmp_path),
            "--chmi-dir", str(tmp_path / "chmi"),
            "--stations", str(tmp_path / "stations.parquet"),
            "--out", str(out),
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    cal = frost.Calibration.read(out)
    bias = dict(zip(cal.model_bias["model"], cal.model_bias["bias"], strict=True))
    assert bias == {"a": pytest.approx(2.0), "b": pytest.approx(1.0)}
    assert cal.stations["name"].to_list() == ["One"]
    assert cal.clear_calm["intercept"] == frost.CLEAR_CALM["intercept"]
