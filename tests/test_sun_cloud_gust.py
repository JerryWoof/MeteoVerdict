import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from meteoverdict import runs
from meteoverdict import sun_cloud_gust as scg

NOW = datetime(2026, 10, 16, 5, 52, tzinfo=UTC)
POINTS = pl.DataFrame({"code": ["CZ0100", "CZ0201"], "lat": [50.07, 49.72], "lon": [14.47, 14.78]})
DOC = {
    "sunshine": {"default": {"a": -0.19, "b": 0.7, "d": 0.45}, "by_lead": {}},
    "cloud": {"default": {"a": 18.0, "b": 0.76}, "by_lead": {}},
    "gust": {"default": {"a": 1.0, "b": 1.0, "stations": {}}, "by_lead": {}},
}


def hourly_frame(okres="CZ0100", day=date(2026, 10, 17), sun=1800.0, cloud=40.0, hours=48):
    """Hourly plain means from 00 UTC on ``day``: ``sun`` s in the hours ending 07-15 UTC."""
    times = [
        datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(hours=h)
        for h in range(hours)
    ]
    return pl.DataFrame(
        {
            "okres": okres,
            "time": times,
            "cloud_cover": [cloud] * hours,
            "sunshine_duration": [sun if 7 <= t.hour <= 15 else 0.0 for t in times],
        },
        schema_overrides={"time": pl.Datetime("us", "UTC")},
    )


def test_day_length():
    assert scg.day_length(50.0, date(2026, 3, 21)) == pytest.approx(12.0, abs=0.1)
    assert scg.day_length(50.0, date(2026, 6, 21)) == pytest.approx(16.2, abs=0.2)
    assert scg.day_length(50.0, date(2026, 12, 21)) == pytest.approx(7.8, abs=0.2)


def test_sunshine_fit_recovers_the_coefficients_and_stays_within_the_day():
    rng = np.random.default_rng(0)
    length = rng.uniform(8, 16, 300)
    sun = rng.uniform(0, 1, 300) * length
    cloud = rng.uniform(0, 100, 300)
    observed = (-0.2 + 0.7 * sun / length + 0.45 * (1 - cloud / 100)) * length
    coef = scg.fit_sunshine(sun, cloud, length, observed)
    assert coef == pytest.approx({"a": -0.2, "b": 0.7, "d": 0.45}, abs=1e-9)
    # overcast without sun: not negative; clear and all sun: not above the day length
    assert scg.predict_sunshine(coef, [0.0], [100.0], [10.0])[0] == 0
    assert scg.predict_sunshine({"a": 0.5, "b": 1, "d": 1}, [10.0], [0.0], [10.0])[0] == 10


def test_scale_to_keeps_the_hours_within_an_hour():
    hours = np.array([0, 600, 1800, 3600, 3000, 0], float)
    down = scg.scale_to(hours, 4500)
    assert down.sum() == pytest.approx(4500)
    assert down[0] == down[-1] == 0
    assert down[2] / down[1] == pytest.approx(3)  # proportional
    up = scg.scale_to(hours, 10_000)
    assert up.sum() == pytest.approx(10_000)
    assert up.max() <= 3600 and up[3] == 3600
    # no room left: as much as fits
    assert scg.scale_to(hours, 20_000).sum() == pytest.approx(4 * 3600)
    assert scg.scale_to(np.zeros(5), 3600).sum() == 0


def test_correct_hourly_sums_to_the_corrected_day():
    hourly = hourly_frame()
    out = scg.correct_hourly(hourly, POINTS, DOC, NOW)
    assert out["sunshine_duration_raw"].to_list() == hourly["sunshine_duration"].to_list()
    by_day = dict(
        out.group_by(day=(pl.col("time") - pl.duration(hours=1)).dt.date())
        .agg(pl.col("sunshine_duration").sum() / 3600)
        .iter_rows()
    )
    for day in (date(2026, 10, 17), date(2026, 10, 18)):  # the 18th: 23 hours, enough
        length = scg.day_length(50.07, day)
        expected = float(scg.predict_sunshine(DOC["sunshine"]["default"], 4.5, 40.0, length))
        assert by_day[day] == pytest.approx(expected)
        assert expected < 4.5  # the models' sunshine is cut
    # the 16th has one hour (ending at 00 UTC on the 17th): kept as it was
    assert by_day[date(2026, 10, 16)] == 0
    # cloud: a + b·mean, clipped
    assert out["cloud_cover"].unique().to_list() == [pytest.approx(18.0 + 0.76 * 40)]
    clipped = scg.correct_hourly(hourly_frame(cloud=0.0), POINTS, DOC, NOW)
    assert clipped["cloud_cover"].min() == pytest.approx(18.0)
    assert scg.predict_cloud({"a": 18.0, "b": 0.9}, [100.0])[0] == 100


def test_correct_hourly_uses_the_lead_day_coefficients():
    doc = json.loads(json.dumps(DOC))
    doc["cloud"]["by_lead"]["2"] = {"a": 0.0, "b": 0.5}
    out = scg.correct_hourly(hourly_frame(), POINTS, doc, NOW)
    day1 = out.filter(pl.col("time").dt.date() == date(2026, 10, 17))["cloud_cover"]
    day2 = out.filter(pl.col("time").dt.date() == date(2026, 10, 18))["cloud_cover"]
    assert day1.unique().to_list() == [pytest.approx(48.4)]
    assert day2.unique().to_list() == [pytest.approx(20.0)]
    assert scg.coefficients(doc, "cloud", 9) == doc["cloud"]["default"]


def test_gust_station_residuals_and_okres_mapping():
    forecast = np.array([10, 12, 10, 12], float)
    observed = np.array([11, 13, 15, 17], float)  # the second station gusts 4 m/s more
    coef = scg.fit_gust(forecast, observed, ["low", "low", "high", "high"])
    assert coef["stations"]["high"] - coef["stations"]["low"] == pytest.approx(4)
    assert scg.predict_gust(coef, forecast, ["low", "low", "high", "high"]) == pytest.approx(
        observed
    )
    doc = {"gust": {"default": coef, "by_lead": {}, "okres_stations": {"CZ0100": "low"}}}
    low = scg.predict_gust(coef, [10.0], ["low"])[0]
    assert scg.correct_gust(doc, [10.0, 10.0], ["CZ0100", "CZ9999"]) == pytest.approx(
        [low, coef["a"] + coef["b"] * 10]
    )


def test_summits_never_represent_an_okres():
    stations = pl.DataFrame(
        {
            "id": ["summit", "valley", "far"],
            "lat": [50.07, 49.9, 51.5],
            "lon": [14.47, 14.6, 14.47],
            "elevation": [1300.0, 250.0, 200.0],
        }
    )
    mapping = scg.nearest_stations(POINTS, stations, ["summit", "valley", "far"], 40)
    assert dict(mapping.select("okres", "station").iter_rows()) == {
        "CZ0100": "valley",
        "CZ0201": "valley",
    }
    reps = scg.okres_gust_stations(runs.load_stations())
    assert "0-20000-0-11787" not in reps["station"].to_list()  # Lysá hora
    assert reps.filter(pl.col("okres") == "CZ0532")["station"].item() == "0-20000-0-11652"


def test_archive_rows_and_replacing_a_run(tmp_path):
    hourly = scg.correct_hourly(hourly_frame(), POINTS, DOC, NOW)
    rows = scg.archive_rows(hourly, NOW)
    assert rows["cloud_cover"].unique().to_list() == [40.0]  # the plain mean
    path = tmp_path / scg.archive_asset("2026-10")[1]
    scg.append_archive(path, rows)
    scg.append_archive(path, rows)
    later = scg.archive_rows(hourly, NOW + timedelta(hours=12))
    scg.append_archive(path, later)
    stored = pl.read_parquet(path)
    assert stored.height == 2 * rows.height
    assert stored["issued"].n_unique() == 2


def _archive(days: int) -> pl.DataFrame:
    """Archived runs issued at 05:52 on each of ``days`` days, two days each."""
    frames = []
    for i in range(days):
        issued = NOW - timedelta(days=days - i)
        day = issued.date()
        sun = 900.0 + 100 * (i % 7)
        frames.append(
            scg.archive_rows(hourly_frame("CZ0100", day, sun, 20.0 + 5 * (i % 5)), issued)
        )
    return pl.concat(frames)


def test_pairs_and_fit_replace_the_bootstrap_after_21_days():
    archive = _archive(30)
    observed = pl.DataFrame(
        {
            "station": "s1",
            "day": [NOW.date() - timedelta(days=d) for d in range(40)],
            "observed": [3.0 + (d % 4) for d in range(40)],
        }
    )
    mapping = pl.DataFrame({"okres": ["CZ0100"], "station": ["s1"], "km": [1.0]})
    pairs = scg.sunshine_pairs(archive, observed, mapping, POINTS)
    assert set(pairs["lead_day"].unique()) == {1}  # hours 0-47: day 0 is lead 0 (left out)
    assert pairs["sun_h"].min() >= 9 * 900 / 3600 - 1e-9
    previous = scg.load()
    doc = scg.fit(previous, NOW.date(), sunshine=pairs)
    assert doc["sunshine"]["source"] == "observations"
    # today's pairs are not used (ČHMÚ publishes the day after)
    used = pairs.filter(pl.col("day") < NOW.date())
    assert doc["sunshine"]["days"] == used["day"].n_unique() >= scg.MIN_DAYS
    assert set(doc["sunshine"]["by_lead"]) == {"1"}
    assert doc["cloud"] == previous["cloud"]  # no cloud pairs: unchanged
    few = scg.fit(
        previous, NOW.date(), sunshine=pairs.filter(pl.col("day") > NOW.date() - timedelta(days=10))
    )
    assert few["sunshine"] == previous["sunshine"]

    cloud_obs = pl.DataFrame(
        {"station": "s1", "time": archive["time"].unique(), "observed": 50.0},
        schema_overrides={"time": pl.Datetime("us", "UTC")},
    )
    cloud = scg.cloud_pairs(archive, cloud_obs, mapping)
    assert cloud.height > 0
    assert cloud["lead_day"].min() == 1
    assert scg.fit(previous, NOW.date(), cloud=cloud)["cloud"]["default"] == pytest.approx(
        {"a": 50.0, "b": 0.0}, abs=1e-6
    )


def test_gust_forecasts_from_the_single_runs():
    run = datetime(2026, 10, 14, tzinfo=UTC)
    rows = []
    for model, extra in (("m1", 0.0), ("m2", 2.0), ("short", 0.0)):
        for lead in range(1, 49):
            if model == "short" and lead > 30:
                continue
            rows.append(
                (
                    run,
                    model,
                    "st",
                    lead,
                    run + timedelta(hours=lead),
                    5.0 + extra + (lead == 30) * 5,
                )
            )
    frame = pl.DataFrame(
        rows,
        schema={
            "run": pl.Datetime("us", "UTC"),
            "model": pl.String,
            "station_id": pl.String,
            "lead_h": pl.Int16,
            "valid_time": pl.Datetime("us", "UTC"),
            "wind_gusts_10m": pl.Float32,
        },
        orient="row",
    )
    out = scg.gust_forecasts(frame, ["st"])
    day1 = out.filter(pl.col("day") == date(2026, 10, 15))
    # m1 10, m2 12; "short" has only 6 values on the 15th: left out
    assert day1["forecast"].item() == pytest.approx(11.0)
    assert day1["lead_day"].item() == 1


def test_the_bootstrap_has_provenance():
    doc = scg.load()
    assert "research sample" in doc["provenance"] and doc["fitted"].startswith("2026-10-16")
    for variable in scg.VARIABLES:
        assert doc[variable]["source"] == "bootstrap"
        assert doc[variable]["days"] >= scg.MIN_DAYS
    assert doc["sunshine"]["default"]["b"] > 0
    assert all(s != "0-20000-0-11464" for s in doc["gust"]["default"]["stations"])  # Milešovka


def test_outlook_parts_add_up_to_the_corrected_days():
    from pathlib import Path

    import httpx

    from meteoverdict import combine, outlook

    fixtures = Path(__file__).parent / "fixtures"
    codes = ["CZ0100", "CZ0201"]
    now = datetime(2026, 10, 12, 8, 25, tzinfo=UTC)
    weights = []
    for code in codes:
        doc = json.loads((fixtures / "weights" / f"{code}.json").read_text("utf-8"))
        weights.append(
            pl.DataFrame(doc["rows"], schema=doc["columns"], orient="row").with_columns(
                pl.lit(code).alias("region"), pl.col("lead_day").cast(pl.Int8)
            )
        )
    weights = pl.concat(weights)
    models = sorted(weights["model"].unique().to_list())
    payload = json.loads((fixtures / "open-meteo" / "forecast-2-okresy.json").read_text("utf-8"))
    points = combine.okres_points().filter(pl.col("code").is_in(codes)).sort("code")

    # the mocked API end to end: cloud corrected, the plain means kept beside it
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        _, hourly = outlook.outlook(client, weights, points, now=now, corrections=DOC)
    known = hourly.drop_nulls("cloud_cover_raw")
    assert known["cloud_cover"].to_numpy() == pytest.approx(
        scg.predict_cloud(DOC["cloud"]["default"], known["cloud_cover_raw"])
    )

    # 30 minutes of sunshine in every hour ending 07-14 UTC
    fc = outlook.parse(payload, codes, models).with_columns(
        pl.when(pl.col("time").dt.hour().is_between(7, 14))
        .then(1800.0)
        .otherwise(0.0)
        .alias("sunshine_duration")
    )
    hourly = scg.correct_hourly(outlook.combine_hourly(fc, weights, now), points, DOC, now)
    table = outlook.summarise(hourly, outlook.probability(fc, weights, now))
    tomorrow = table.filter(pl.col("okres") == "CZ0201", pl.col("day") == date(2026, 10, 13))
    by_part = dict(zip(tomorrow["part"], tomorrow["sunshine"], strict=True))
    length = scg.day_length(
        points.filter(pl.col("code") == "CZ0201")["lat"].item(), date(2026, 10, 13)
    )
    cloud = hourly.filter(
        pl.col("okres") == "CZ0201",
        pl.col("time").dt.date() == date(2026, 10, 13),
        pl.col("time").dt.hour().is_between(6, 16),
    )["cloud_cover_raw"].mean()
    expected = float(scg.predict_sunshine(DOC["sunshine"]["default"], 4.0, cloud, length))
    assert by_part["day"] == pytest.approx(expected)
    assert by_part["morning"] + by_part["afternoon"] == pytest.approx(expected)
    assert by_part["morning"] == pytest.approx(by_part["afternoon"])  # proportional
