import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import polars as pl
import pytest

from meteoverdict import combine, outlook, rain_calibration

FIXTURES = Path(__file__).parent / "fixtures"
CODES = ["CZ0100", "CZ0201"]
# the saved answer was fetched at 08:25 UTC on 12 October 2026
NOW = datetime(2026, 10, 12, 8, 25, tzinfo=UTC)


def weights_of(code):
    doc = json.loads((FIXTURES / "weights" / f"{code}.json").read_text("utf-8"))
    return pl.DataFrame(doc["rows"], schema=doc["columns"], orient="row").with_columns(
        pl.lit(code).alias("region"), pl.col("lead_day").cast(pl.Int8)
    )


WEIGHTS = pl.concat([weights_of(c) for c in CODES])
MODELS = sorted(WEIGHTS["model"].unique().to_list())
PAYLOAD = json.loads((FIXTURES / "open-meteo" / "forecast-2-okresy.json").read_text("utf-8"))
FC = outlook.parse(PAYLOAD, CODES, MODELS)


def test_request_and_cost():
    points = pl.DataFrame({"code": CODES, "lat": [50.0668, 49.717], "lon": [14.466, 14.7767]})
    params = outlook.request_params(points, ["a", "b"])
    assert params["latitude"] == "50.0668,49.717"
    assert params["hourly"] == (
        "temperature_2m,precipitation,wind_speed_10m,cloud_cover,sunshine_duration"
    )
    assert params["models"] == "a,b" and params["timezone"] == "GMT"
    # 77 okresy, 5 variables x 11 models: 5.5 calls each; 19 models: 9.5
    assert outlook.cost(77, 11) == pytest.approx(423.5)
    assert outlook.cost(77, 19) == pytest.approx(731.5)
    assert outlook.cost(77, 19) <= outlook.MAX_CALLS
    # one request up to 500 calls (Open-Meteo: 600 a minute)
    assert outlook.parts(77, 11) == [77]
    assert outlook.parts(77, 19) == [39, 38]
    assert all(outlook.cost(n, 19) <= outlook.MAX_REQUEST for n in outlook.parts(77, 19))
    assert outlook.parts(0, 19) == []


def test_fetch_in_parts_gives_one_answer():
    points = pl.DataFrame(
        {
            "code": [f"c{i}" for i in range(77)],
            "lat": [50.0] * 77,
            "lon": [14.0 + i / 100 for i in range(77)],
        }
    )
    asked = []

    def handler(request):
        lons = request.url.params["longitude"].split(",")
        asked.append(len(lons))
        answers = [{"longitude": float(x), "hourly": {}} for x in lons]
        for i, item in enumerate(answers[1:], 1):
            item["location_id"] = i
        return httpx.Response(200, json=answers)

    waits = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = outlook.fetch(client, points, [f"m{i}" for i in range(19)], waits.append)
    assert asked == [39, 38] and waits == [outlook.PART_PAUSE]
    assert [item["location_id"] for item in payload] == list(range(77))
    assert [item["longitude"] for item in payload] == points["lon"].to_list()


def test_parse_the_saved_answer():
    assert FC["okres"].unique().sort().to_list() == CODES
    assert FC["model"].n_unique() == 11
    d2 = FC.filter(pl.col("okres") == "CZ0201", pl.col("model") == "dwd_icon_d2")
    assert d2["time"].max() < FC["time"].max()  # ICON-D2 ends after about two days
    assert FC.filter(pl.col("temperature_2m").is_null()).is_empty()


def test_combined_hour_matches_the_formula():
    hourly = outlook.combine_hourly(FC, WEIGHTS, NOW)
    when = datetime(2026, 10, 12, 12, tzinfo=UTC)
    got = hourly.filter(pl.col("okres") == "CZ0201", pl.col("time") == when)
    rows = FC.filter(pl.col("okres") == "CZ0201", pl.col("time") == when)
    w = WEIGHTS.filter(
        pl.col("region") == "CZ0201",
        pl.col("variable") == "temperature_2m",
        pl.col("lead_day") == 1,
    )
    joined = rows.join(w, on="model")  # no model ends at 12 UTC today: no fading
    expected = (
        joined["weight"] * (joined["temperature_2m"] - joined["correction"])
    ).sum() / joined["weight"].sum()
    assert got["temperature_2m"].item() == pytest.approx(expected)
    assert got["models"].item() == 11
    assert got["cloud_cover"].item() == pytest.approx(rows["cloud_cover"].mean())
    assert hourly.filter(pl.col("precipitation") < 0).is_empty()


def test_models_fade_out_at_their_end():
    fc = outlook.with_lead_and_fade(FC, NOW).filter(pl.col("okres") == "CZ0201")
    d2 = fc.filter(pl.col("model") == "dwd_icon_d2").sort("time")
    assert d2["fade"].tail(4).to_list() == [1.0, 0.75, 0.5, 0.25]
    assert d2["fade"].head(-4).unique().to_list() == [1.0]
    ifs = fc.filter(pl.col("model") == "ecmwf_ifs")  # reaches the end: never fades
    assert ifs["fade"].unique().to_list() == [1.0]
    assert fc.filter(pl.col("time") == NOW.replace(minute=0))["lead_day"].unique().to_list() == [1]
    assert fc["lead_day"].max() == 5


def test_lead_days_fall_back_to_the_nearest_shorter_one():
    w = pl.DataFrame(
        {
            "region": ["X", "X"],
            "variable": ["temperature_2m"] * 2,
            "lead_day": pl.Series([1, 3], dtype=pl.Int8),
            "model": ["a", "a"],
            "weight": [1.0, 1.0],
            "correction": [0.1, 0.3],
        }
    )
    lead = outlook._lead_weights(w).sort("lead_day")
    assert lead["lead_day"].to_list() == [1, 2, 3, 4, 5]
    assert lead["correction"].to_list() == [0.1, 0.1, 0.3, 0.3, 0.3]


def test_probability_is_the_share_of_wet_models_not_weighted():
    # hours ending 05-10 UTC: 06-12 Prague
    times = [datetime(2026, 10, 13, h, tzinfo=UTC) for h in range(5, 11)]
    fc = pl.DataFrame(
        {
            "okres": "X",
            "time": times * 3,
            "model": ["a"] * 6 + ["b"] * 6 + ["c"] * 6,
            "temperature_2m": 10.0,
            "precipitation": [0.1] * 6 + [0.0] * 6 + [0.01] * 6,  # a: 0.6 mm, wet
            "wind_speed_10m": 1.0,
            "cloud_cover": 50.0,
        }
    ).with_columns(pl.col("time").cast(pl.Datetime("us", "UTC")))
    w = pl.DataFrame(
        {
            "region": "X",
            "variable": "precipitation",
            "lead_day": pl.Series([1, 1, 1], dtype=pl.Int8),
            "model": ["a", "b", "c"],
            "weight": [0.5, 0.25, 0.25],
            "correction": 0.0,
        }
    )
    p = outlook.probability(fc, w, datetime(2026, 10, 13, tzinfo=UTC))
    morning = p.filter(pl.col("part") == "morning")
    assert morning["day"].item() == date(2026, 10, 13)
    # a has half the precipitation weight, but every model counts the same
    assert morning["rain_probability"].item() == pytest.approx(1 / 3)


@pytest.mark.parametrize(
    ("cloud", "rain", "chance", "temp", "expected"),
    [
        (10, 0, 0, 10, "clear"),
        (50, 0, 0, 10, "partly"),
        (90, 0, 0.1, 10, "cloudy"),
        (90, 0.1, 0.4, 10, "showers"),
        (90, 2.0, 0.8, 10, "rain"),
        (90, 2.0, 0.8, 1.5, "sleet"),
        (90, 2.0, 0.8, -3, "snow"),
        (90, 0.05, 0.8, 10, "showers"),  # likely but too little to call it rain
        (90, 0.25, 0.8, 10, "showers"),  # wet in the models, but under RAIN_MM combined
        (90, 0.3, 0.8, 10, "rain"),
        (None, None, None, None, None),
    ],
)
def test_symbols(cloud, rain, chance, temp, expected):
    assert outlook.symbol(cloud, rain, chance, temp) == expected


def test_parts_and_days_in_prague_time(tmp_path):
    hourly = outlook.combine_hourly(FC, WEIGHTS, NOW)
    table = outlook.summarise(hourly, outlook.probability(FC, WEIGHTS, NOW))
    benesov = table.filter(pl.col("okres") == "CZ0201")
    # the answer starts at 00 UTC = 02:00 in Prague: today's night has 4 hours, still kept
    assert benesov["day"].min() == date(2026, 10, 12)
    assert benesov.filter(pl.col("day") == date(2026, 10, 12))["part"].to_list() == [
        "night",
        "morning",
        "afternoon",
        "evening",
        "day",
    ]
    assert benesov["day"].n_unique() == 6
    day = benesov.filter(pl.col("part") == "day")
    assert (day["tmin"] <= day["tmax"]).all()
    assert day["rain_probability"].is_between(0, 1).all()
    assert (
        day["symbol"].is_in(["clear", "partly", "cloudy", "showers", "rain", "sleet", "snow"]).all()
    )
    points = pl.DataFrame(
        {"code": CODES, "name": ["Praha", "Benešov"], "lat": [50.0, 49.7], "lon": [14.4, 14.7]}
    )
    table = outlook.with_sun(table, points)
    path = outlook.write(table, points, tmp_path / "outlook.json", NOW)
    doc = json.loads(path.read_text("utf-8"))
    assert doc["parts"] == ["night", "morning", "afternoon", "evening"]
    assert doc["days"][0] == "2026-10-12" and len(doc["days"]) == 6
    assert doc["columns"] == [*outlook.COLUMNS, *outlook.GUST_COLUMNS]
    assert doc["okresy"][1]["name"] == "Benešov"
    assert {r[0] for r in doc["rows"]} == set(CODES)
    row = dict(zip(doc["columns"], doc["rows"][0], strict=True))
    # 50.0 N 14.4 E on 12 October 2026: 07:19:34 and 18:17:21 Prague time (astral)
    assert (row["okres"], row["day"]) == ("CZ0100", "2026-10-12")
    assert (row["sunrise"], row["sunset"]) == ("07:19", "18:17")
    # the saved answer has no sunshine: null, not 0 h
    assert row["sunshine"] is None


def test_sunshine_hours_are_the_sum_of_the_plain_hourly_mean():
    # every model: 30 minutes of sunshine in each hour 08-16 Prague time (the hours ending
    # 07-14 UTC)
    hour = pl.col("time").dt.hour()
    fc = FC.with_columns(
        pl.when(hour.is_between(7, 14)).then(1800.0).otherwise(0.0).alias("sunshine_duration")
    )
    hourly = outlook.combine_hourly(fc, WEIGHTS, NOW)
    table = outlook.summarise(hourly, outlook.probability(fc, WEIGHTS, NOW))
    tomorrow = table.filter(pl.col("okres") == "CZ0201", pl.col("day") == date(2026, 10, 13))
    by_part = dict(zip(tomorrow["part"], tomorrow["sunshine"], strict=True))
    assert by_part == {"night": 0, "morning": 2.0, "afternoon": 2.0, "evening": 0, "day": 4.0}


def test_sums_belong_to_the_hour_before_their_time():
    # 22 UTC on 16 October is midnight in Prague: the instant values start the 17th, the
    # rain of the hour ending then (23-24 CEST) is the 16th's evening
    times = pl.Series(
        [datetime(2026, 10, 16, 22, tzinfo=UTC), datetime(2026, 10, 17, 4, tzinfo=UTC)]
    )
    frame = pl.DataFrame({"time": times})
    instant = outlook._local(frame)
    assert instant["day"].to_list() == [date(2026, 10, 17)] * 2
    assert instant["part"].to_list() == ["night", "morning"]
    ending = outlook._local(frame, hour_ending=True)
    assert ending["day"].to_list() == [date(2026, 10, 16), date(2026, 10, 17)]
    assert ending["part"].to_list() == ["evening", "night"]


def test_sunshine_is_clipped_to_the_hour():
    # published values seen: 3605.6 s and -1.0 s in an hour
    model = pl.col("model") == MODELS[0]
    fc = FC.with_columns(
        pl.when(model).then(3605.6).otherwise(3600.0).alias("sunshine_duration")
    ).filter(pl.col("okres") == "CZ0201")
    assert outlook.combine_hourly(fc, WEIGHTS, NOW)["sunshine_duration"].max() == 3600.0
    fc = fc.with_columns(pl.when(model).then(-1.0).otherwise(0.0).alias("sunshine_duration"))
    assert outlook.combine_hourly(fc, WEIGHTS, NOW)["sunshine_duration"].min() == 0.0


def test_outlook_end_to_end_with_a_mocked_api():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.open-meteo.com"
        assert request.url.params["models"] == ",".join(MODELS)
        return httpx.Response(200, json=PAYLOAD)

    points = combine.okres_points().filter(pl.col("code").is_in(CODES)).sort("code")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        table, hourly = outlook.outlook(client, WEIGHTS, points, now=NOW)
    assert table["okres"].unique().sort().to_list() == CODES
    assert hourly["okres"].unique().sort().to_list() == CODES


def test_hourly_file(tmp_path):
    hourly = outlook.combine_hourly(FC, WEIGHTS, NOW)
    path = outlook.write_hourly(hourly, tmp_path / "outlook-hourly.json", NOW)
    doc = json.loads(path.read_text("utf-8"))
    assert len(doc["time"]) == 144
    assert doc["time"][0] == "2026-10-12T00:00Z"
    assert set(doc["okresy"]) == set(CODES)
    benesov = doc["okresy"]["CZ0201"]
    assert set(benesov) == set(outlook.HOURLY)
    assert all(len(v) == 144 for v in benesov.values())
    noon = hourly.filter(
        pl.col("okres") == "CZ0201", pl.col("time") == datetime(2026, 10, 12, 12, tzinfo=UTC)
    )
    assert benesov["temperature_2m"][12] == round(noon["temperature_2m"].item(), 1)


def test_too_expensive_requests_are_refused():
    points = pl.DataFrame({"code": ["x"] * 200, "lat": [50.0] * 200, "lon": [14.0] * 200})
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    with httpx.Client(transport=transport) as client, pytest.raises(ValueError, match="MAX_CALLS"):
        outlook.fetch(client, points, MODELS, lambda _: None)


def test_outlook_retries_server_errors_and_non_json_answers():
    points = pl.DataFrame({"code": ["CZ0100"], "lat": [50.0], "lon": [14.4]})
    answers = iter(
        [
            httpx.Response(502, text="<html>Bad gateway</html>"),
            httpx.Response(200, text=""),
            httpx.Response(200, json={"ok": 1}),
        ]
    )
    waits = []
    with httpx.Client(transport=httpx.MockTransport(lambda r: next(answers))) as client:
        assert outlook.fetch(client, points, ["a"], waits.append) == {"ok": 1}
    assert waits == [30, 60]
    always = httpx.MockTransport(lambda r: httpx.Response(503, text="<html>down</html>"))
    with (
        httpx.Client(transport=always) as client,
        pytest.raises(RuntimeError, match="unavailable after 4"),
    ):
        outlook.fetch(client, points, ["a"], lambda _: None)
    bad = httpx.MockTransport(lambda r: httpx.Response(400, text="not json"))
    with (
        httpx.Client(transport=bad) as client,
        pytest.raises(RuntimeError, match="HTTP 400: not json"),
    ):
        outlook.fetch(client, points, ["a"], lambda _: None)


def test_a_model_without_weights_in_an_okres_is_left_out_there():
    # a newly added model gets weights okres by okres, as its scores come in
    partial = WEIGHTS.filter(~((pl.col("region") == "CZ0100") & (pl.col("model") == "ecmwf_ifs")))
    hourly = outlook.combine_hourly(FC, partial, NOW)
    full = outlook.combine_hourly(FC, WEIGHTS, NOW)
    praha = pl.col("okres") == "CZ0100"
    assert hourly.filter(praha)["temperature_2m"].null_count() == 0
    assert not hourly.filter(praha)["temperature_2m"].equals(full.filter(praha)["temperature_2m"])
    assert hourly.filter(~praha).equals(full.filter(~praha))
    # and the request asks only for models with weights somewhere
    assert sorted(partial["model"].unique()) == MODELS


def test_the_regression_weights_and_slot_corrections_are_used():
    # temperature D+1 in Benešov: a regression on two models, corrections by hour
    benesov = (pl.col("region") == "CZ0201") & (pl.col("variable") == "temperature_2m")
    pair = ["ecmwf_ifs", "dwd_icon_eu"]
    regression = pl.col("model").is_in(pair) & benesov & (pl.col("lead_day") == 1)
    slots = dict(zip(combine.SLOT_CORRECTIONS, [0.0, 1.0, 2.0, 3.0], strict=True))
    w = WEIGHTS.with_columns(
        pl.when(regression)
        .then(pl.when(pl.col("model") == "ecmwf_ifs").then(0.8).otherwise(0.2))
        .alias("mos_weight"),
        pl.when(regression).then(2).alias("mos_models"),
        *(pl.when(regression).then(v).otherwise(pl.col("correction")).alias(c)
          for c, v in slots.items()),
    )  # fmt: skip
    hourly = outlook.combine_hourly(FC, w, NOW)
    for hour, correction in ((12, 2.0), (15, 2.5)):
        when = datetime(2026, 10, 12, hour, tzinfo=UTC)
        rows = FC.filter(pl.col("okres") == "CZ0201", pl.col("time") == when)
        value = dict(rows.select("model", "temperature_2m").rows())
        expected = 0.8 * (value["ecmwf_ifs"] - correction) + 0.2 * (
            value["dwd_icon_eu"] - correction
        )
        got = hourly.filter(pl.col("okres") == "CZ0201", pl.col("time") == when)
        assert got["temperature_2m"].item() == pytest.approx(expected)
    # other okresy and variables as before
    full = outlook.combine_hourly(FC, WEIGHTS, NOW)
    praha = pl.col("okres") == "CZ0100"
    for v in ("temperature_2m", "wind_speed_10m", "precipitation"):
        new, old = hourly.filter(praha)[v], full.filter(praha)[v]
        assert new.to_list() == pytest.approx(old.to_list(), nan_ok=True)


def calibration(flag_at=0.01):
    """A made-up calibration: wetter with more wet models, heavy rain flagged early."""
    return rain_calibration.Calibration(
        intercept=-3.0,
        coefficients=[4.0] + [0.0] * (len(rain_calibration.FEATURES) - 1),
        heavy_intercept=-6.0,
        heavy_coefficients=[2.0] + [0.0] * (len(rain_calibration.HEAVY_FEATURES) - 1),
        heavy_flag_at=flag_at,
        weights={},
        first=date(2026, 7, 1),
        last=date(2026, 10, 11),
        days=90,
        cases=1000,
    )


@pytest.mark.parametrize(
    ("share", "chance", "showers_at", "expected"),
    [
        (0.6, 0.45, 0.4, "rain"),  # rain by the raw share, whatever the calibrated chance
        (0.4, 0.45, 0.4, "showers"),
        (0.4, 0.35, 0.4, "cloudy"),  # 0.35 calibrated is not enough for showers
        (0.4, 0.35, 0.3, "showers"),
    ],
)
def test_symbols_with_a_calibrated_chance(share, chance, showers_at, expected):
    assert outlook.symbol(90, 1.0, chance, 10, share, showers_at) == expected


def test_calibrated_probability_and_heavy_rain(tmp_path):
    points = combine.okres_points().filter(pl.col("code").is_in(CODES))
    raw = outlook.probability(FC, WEIGHTS, NOW)
    assert raw["heavy_rain"].null_count() == raw.height
    chances = outlook.probability(FC, WEIGHTS, NOW, calibration(), points)
    keys = ["okres", "day", "part"]
    both = chances.join(raw.select(*keys, pl.col("rain_probability").alias("raw")), on=keys)
    parts = both.filter(pl.col("part") != "day")
    days = both.filter(pl.col("part") == "day")
    assert parts["calibrated"].all() and not days["calibrated"].any()
    assert (parts["model_share"] == parts["raw"]).all()
    # no model weights: every model weighs 1, so wshare is the share
    p = 1 / (1 + (3.0 - 4.0 * parts["model_share"]).exp())
    expected = rain_calibration.BLEND * p + (1 - rain_calibration.BLEND) * parts["model_share"]
    assert (parts["rain_probability"] - expected).abs().max() < 1e-9
    # whole days keep the raw share; their heavy rain is the highest of their parts
    assert (days["rain_probability"] == days["raw"]).all()
    highest = parts.group_by("okres", "day").agg(pl.col("heavy_rain_probability").max())
    joined = days.join(highest, on=["okres", "day"], suffix="_parts")
    assert (joined["heavy_rain_probability"] == joined["heavy_rain_probability_parts"]).all()
    assert parts["heavy_rain"].any()

    hourly = outlook.combine_hourly(FC, WEIGHTS, NOW)
    table = outlook.summarise(hourly, chances)
    assert "model_share" not in table.columns
    path = outlook.write(outlook.with_sun(table, points), points, tmp_path / "o.json", NOW)
    doc = json.loads(path.read_text("utf-8"))
    at = doc["columns"].index("heavy_rain")
    assert doc["columns"][at - 1 : at + 1] == ["heavy_rain_probability", "heavy_rain"]
    assert {r[at] for r in doc["rows"]} <= {True, False}
    # without a calibration the new fields are there, null
    table = outlook.with_sun(outlook.summarise(hourly, raw), points)
    doc = json.loads(outlook.write(table, points, tmp_path / "r.json", NOW).read_text("utf-8"))
    assert {tuple(r[at - 1 : at + 1]) for r in doc["rows"]} == {(None, None)}


# --- every model's own forecast: the per-okres files and the archive -------------------
def test_per_model_files(tmp_path):
    hourly = outlook.combine_hourly(FC, WEIGHTS, NOW)
    (tmp_path / "CZ9999.json").write_text("{}", "utf-8")  # an okres of an older run
    paths = outlook.write_models(FC, hourly, tmp_path, NOW)
    assert sorted(p.name for p in paths) == [f"{c}.json" for c in CODES]
    assert not (tmp_path / "CZ9999.json").exists()
    doc = json.loads((tmp_path / "CZ0201.json").read_text("utf-8"))
    assert doc["generated"] == "2026-10-12T08:25+00:00"
    assert doc["okres"] == "CZ0201"
    assert "Open-Meteo.com" in doc["attribution"] and "CC BY-SA 4.0" in doc["licence"]
    assert len(doc["time"]) == 144 and doc["time"][0] == "2026-10-12T00:00Z"
    assert set(doc["variables"]) == {*outlook.VARIABLES, *outlook.EXTRA_VARIABLES}
    # our combined series as in outlook-hourly.json, every hour
    assert set(doc["combined"]) == set(outlook.HOURLY)
    assert all(len(v) == 144 for v in doc["combined"].values())
    # each model raw, as Open-Meteo gave it (no correction), rounded
    assert set(doc["models"]) == set(FC.filter(pl.col("okres") == "CZ0201")["model"])
    raw = PAYLOAD[1]["hourly"]
    for model, series in doc["models"].items():
        for variable, values in series.items():
            given = raw[f"{variable}_{model}"]
            half = 0.5 * 10 ** -outlook.MODEL_DIGITS[variable] + 1e-9
            for ours, theirs in zip(values, given, strict=False):
                assert (ours is None) == (theirs is None)
                # Open-Meteo gives wind in m/s with 2 decimals (converted from km/h)
                assert ours is None or abs(ours - theirs) <= half
            # cut after the model's last hour, never before
            assert all(v is None for v in given[len(values) :])
            assert values[-1] is not None
    # a model ending early (ICON-D2: 48 h) is shorter than a global one
    assert len(doc["models"]["dwd_icon_d2"]["temperature_2m"]) < 144
    assert len(doc["models"]["ecmwf_ifs025"]["temperature_2m"]) == 144
    # variables the answer lacks (no sunshine asked in the fixture) are left out
    assert all("sunshine_duration" not in s for s in doc["models"].values())


def test_per_model_files_round_and_stay_small(tmp_path):
    fc = FC.with_columns(
        pl.lit(12.345).alias("temperature_2m"),
        pl.lit(0.123).alias("precipitation"),
        pl.lit(3.456).alias("wind_speed_10m"),
        pl.lit(47.6).alias("cloud_cover"),
        pl.lit(3599.6).alias("sunshine_duration"),
    )
    hourly = outlook.combine_hourly(fc, WEIGHTS, NOW)
    outlook.write_models(fc, hourly, tmp_path, NOW)
    text = (tmp_path / "CZ0100.json").read_text("utf-8")
    model = json.loads(text)["models"]["ecmwf_ifs025"]
    assert model["temperature_2m"][0] == 12.3
    assert model["precipitation"][0] == 0.12
    assert model["wind_speed_10m"][0] == 3.5
    assert model["cloud_cover"][0] == 48 and model["sunshine_duration"][0] == 3600
    assert '"cloud_cover":[48,' in text  # whole numbers without ".0"
    # 11 models with every value filled in: well under the 100 kB a file may take with
    # all 19 models (about 19/11 of this)
    assert len(text.encode()) * 19 / 11 < 100_000


def test_extra_variables_are_null_from_the_api_and_left_out_of_the_files(tmp_path):
    # the API fallback does not ask for them: columns there, all null
    assert all(FC[v].null_count() == FC.height for v in outlook.EXTRA_VARIABLES)
    hourly = outlook.combine_hourly(FC, WEIGHTS, NOW)
    outlook.write_models(FC, hourly, tmp_path, NOW)
    doc = json.loads((tmp_path / "CZ0201.json").read_text("utf-8"))
    for series in doc["models"].values():
        assert not set(series) & set(outlook.EXTRA_VARIABLES)  # never 0, never a null series


def test_extra_variables_in_the_files_null_digits_units(tmp_path):
    ours = FC.filter(pl.col("okres") == "CZ0100")
    ifs = pl.col("model") == "ecmwf_ifs025"
    n = ours.filter(ifs).height
    ours = ours.with_columns(
        # IFS has them, with a gap in the middle; everyone else has none
        pl.when(ifs).then(pl.lit(81.6)).alias("relative_humidity_2m"),
        pl.when(ifs).then(pl.lit(1013.26)).alias("pressure_msl"),
        pl.when(ifs).then(pl.lit(271.4)).alias("wind_direction_10m"),
        pl.when(ifs).then(pl.lit(0.126)).alias("snowfall"),
        pl.when(ifs).then(pl.lit(12345.6)).alias("visibility"),
    )
    gap = pl.int_range(pl.len()).over("model") == 10
    ours = ours.with_columns(pl.when(ifs).then(pl.lit(0.0)).alias("cape"))
    ours = ours.with_columns(
        pl.when(ifs & gap).then(None).otherwise(pl.col("snowfall")).alias("snowfall")
    )
    hourly = outlook.combine_hourly(ours, WEIGHTS, NOW)
    outlook.write_models(ours, hourly, tmp_path, NOW)
    doc = json.loads((tmp_path / "CZ0100.json").read_text("utf-8"))
    ifs_doc = doc["models"]["ecmwf_ifs025"]
    assert ifs_doc["relative_humidity_2m"][0] == 82  # whole %, an int
    assert ifs_doc["pressure_msl"][0] == 1013.3
    assert ifs_doc["wind_direction_10m"][0] == 271
    assert ifs_doc["snowfall"][0] == 0.13 and ifs_doc["snowfall"][10] is None
    assert ifs_doc["visibility"][0] == 12346
    assert ifs_doc["cape"][0] == 0  # a real zero stays 0
    for model, series in doc["models"].items():
        if model != "ecmwf_ifs025":
            assert not set(series) & set(outlook.EXTRA_VARIABLES)  # lacks them: left out
    assert all(len(v) <= len(doc["time"]) for v in ifs_doc.values())
    # every extra variable has a unit and digits; the keys of the five stay as they were
    assert set(outlook.EXTRA_VARIABLES) <= set(doc["variables"]) <= set(outlook.MODEL_UNITS)
    assert set(outlook.EXTRA_VARIABLES) <= set(outlook.MODEL_DIGITS)
    assert list(doc["variables"])[:5] == list(outlook.VARIABLES)
    assert doc["variables"]["temperature_2m"] == "°C"
    assert n > 10
    # the combined series (and outlook-hourly.json) carry none of them
    assert set(doc["combined"]) == set(outlook.HOURLY)


def test_model_archive_merges_runs_without_duplicates(tmp_path):
    # one file per UTC day of the run, one release per month
    assert outlook.model_archive_asset(NOW) == (
        "outlook-models-2026-10",
        "outlook-models-2026-10-12.parquet",
    )
    late = datetime(2026, 10, 31, 23, 50, tzinfo=UTC)
    assert outlook.model_archive_asset(late)[1] == "outlook-models-2026-10-31.parquet"
    prague = late.astimezone(ZoneInfo("Europe/Prague"))  # already 1 November there
    assert outlook.model_archive_asset(prague) == outlook.model_archive_asset(late)
    path = tmp_path / outlook.model_archive_asset(NOW)[1]
    first = outlook.model_archive_rows(FC, NOW)
    assert first.height == FC.height
    assert first["issued"].unique().to_list() == [NOW]
    outlook.append_model_archive(path, first)
    later = NOW.replace(hour=14)
    outlook.append_model_archive(path, outlook.model_archive_rows(FC, later))
    # the same run again (a re-run, a retried upload) replaces itself
    changed = FC.with_columns(pl.col("temperature_2m") + 1)
    outlook.append_model_archive(path, outlook.model_archive_rows(changed, later))
    stored = pl.read_parquet(path)
    assert stored.schema == pl.Schema(outlook.MODEL_ARCHIVE_SCHEMA)
    assert stored.height == 2 * FC.height
    assert stored.select("issued", "okres", "model", "time").is_unique().all()
    at = stored.filter(pl.col("issued") == later).sort("okres", "model", "time")
    expected = changed.sort("okres", "model", "time")["temperature_2m"]
    assert (at["temperature_2m"].cast(pl.Float64) - expected).abs().max() < 1e-5


def test_outlook_hands_over_the_models_forecasts():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PAYLOAD)

    points = combine.okres_points().filter(pl.col("code").is_in(CODES)).sort("code")
    forecasts = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        outlook.outlook(client, WEIGHTS, points, now=NOW, forecasts=forecasts)
    assert len(forecasts) == 1
    assert forecasts[0].equals(FC)


# --- every model's parts of day for all okresy (the model switch of the forecast map) ----
def _parts_days():
    hourly = outlook.combine_hourly(FC, WEIGHTS, NOW)
    table = outlook.summarise(hourly, outlook.probability(FC, WEIGHTS, NOW))
    return table["day"].unique().sort().to_list()


def test_model_symbol_rule():
    # rain from the model's own total of at least 0.3 mm, never showers
    assert outlook.model_symbol(10, 0.3, 8) == "rain"
    assert outlook.model_symbol(10, 0.29, 8) == "clear"
    assert outlook.model_symbol(50, 1.0, 1.5) == "sleet"
    assert outlook.model_symbol(50, 1.0, 0.5) == "snow"
    assert outlook.model_symbol(29.9, 0, 8) == "clear"
    assert outlook.model_symbol(30, None, 8) == "partly"
    assert outlook.model_symbol(65, 0.1, 8) == "cloudy"
    assert outlook.model_symbol(None, None, 8) is None


def test_model_periods_follow_the_outlook_rules():
    fc = FC.filter(pl.col("okres") == "CZ0201", pl.col("model") == "ecmwf_ifs025")
    periods = outlook.model_periods(fc)
    local = fc.with_columns(
        pl.col("time").dt.convert_time_zone("Europe/Prague").alias("at"),
        (pl.col("time") - pl.duration(hours=1))
        .dt.convert_time_zone("Europe/Prague")
        .alias("before"),
    )
    day = date(2026, 10, 13)
    afternoon = local.filter(
        pl.col("at").dt.date() == day, pl.col("at").dt.hour().is_between(12, 17)
    )
    sums = local.filter(
        pl.col("before").dt.date() == day, pl.col("before").dt.hour().is_between(12, 17)
    )
    row = periods.filter(pl.col("day") == day, pl.col("part") == "afternoon").row(0, named=True)
    assert row["tmin"] == afternoon["temperature_2m"].min()
    assert row["tmax"] == afternoon["temperature_2m"].max()
    assert row["wind"] == afternoon["wind_speed_10m"].max()
    assert row["cloud"] == pytest.approx(afternoon["cloud_cover"].mean())
    # precipitation in the hour before its time
    assert row["precipitation"] == pytest.approx(sums["precipitation"].sum())
    whole = periods.filter(pl.col("day") == day, pl.col("part") == "day").row(0, named=True)
    daytime = local.filter(pl.col("at").dt.date() == day, pl.col("at").dt.hour().is_between(6, 17))
    assert whole["cloud"] == pytest.approx(daytime["cloud_cover"].mean())
    assert whole["tmax"] == local.filter(pl.col("at").dt.date() == day)["temperature_2m"].max()


def test_model_periods_null_beyond_the_horizon():
    d2 = FC.filter(pl.col("model") == "dwd_icon_d2")
    last = d2.drop_nulls("temperature_2m")["time"].max()
    periods = outlook.model_periods(FC).filter(pl.col("model") == "dwd_icon_d2")
    # every period ends at or before the model's last hour (+1 for the hour-ending sums)
    ends = periods.with_columns(
        pl.col("day").cast(pl.Datetime("us")).dt.replace_time_zone("Europe/Prague").alias("start")
    )
    assert ends["start"].max() <= last
    end_day = last.astimezone(ZoneInfo("Europe/Prague")).date()
    # the model ends inside the day: no whole day, no parts after its end
    assert periods.filter(pl.col("day") == end_day, pl.col("part") == "day").is_empty()
    assert periods.filter(pl.col("day") > end_day).is_empty()
    # a global model has every whole day of the outlook
    ifs = outlook.model_periods(FC).filter(
        pl.col("model") == "ecmwf_ifs025", pl.col("part") == "day"
    )
    assert ifs.filter(pl.col("okres") == "CZ0201").height >= 5


def _synthetic(hours, temperature, precipitation, cloud=None):
    """One okres and model "m" from 12 Dec 2026 00:00 UTC, ``hours`` hours (as
    web/src/models.test.js synthetic): each variable a function of the hour index,
    None for no value."""
    times = [datetime(2026, 12, 12, tzinfo=UTC) + timedelta(hours=i) for i in range(hours)]
    return pl.DataFrame(
        {
            "okres": "CZ0100",
            "time": times,
            "model": "m",
            "temperature_2m": [temperature(i) for i in range(hours)],
            "precipitation": [precipitation(i) for i in range(hours)],
            "wind_speed_10m": [None] * hours,
            "cloud_cover": [cloud(i) if cloud else None for i in range(hours)],
            "sunshine_duration": [None] * hours,
        },
        schema={
            "okres": pl.String,
            "time": pl.Datetime("us", "UTC"),
            "model": pl.String,
            **{v: pl.Float64 for v in outlook.VARIABLES},
        },
    )


def _period(periods, day, part):
    rows = periods.filter(pl.col("day") == date.fromisoformat(day), pl.col("part") == part)
    return rows.row(0, named=True) if rows.height else None


def test_model_periods_one_hour_short_of_a_day():
    # the model's last hour 13 Dec 22:00 UTC = 23:00 Prague: every hour of that evening,
    # but no rain for 23-24 (ICON-D2)
    periods = outlook.model_periods(
        _synthetic(
            72,
            lambda i: 5.0 if i < 47 else None,
            lambda i: 0.1 if i < 47 else None,
            lambda i: 50.0 if i < 47 else None,
        )
    )
    for part in ("night", "morning", "afternoon"):
        assert _period(periods, "2026-12-13", part), part
    evening = _period(periods, "2026-12-13", "evening")
    assert evening
    # the rain of the five hours it has
    assert evening["precipitation"] == pytest.approx(0.5)
    # the whole day stays strict
    assert _period(periods, "2026-12-13", "day") is None
    assert _period(periods, "2026-12-12", "day")
    # two hours short: the evening is not covered (its 23:00 is missing)
    shorter = outlook.model_periods(
        _synthetic(72, lambda i: 5.0 if i < 46 else None, lambda i: 0.1 if i < 46 else None)
    )
    assert _period(shorter, "2026-12-13", "evening") is None
    assert _period(shorter, "2026-12-13", "afternoon")
    # a gap inside a part (not at the model's end) still leaves it out
    gap = outlook.model_periods(_synthetic(72, lambda i: 5.0, lambda i: None if i == 43 else 0.1))
    assert _period(gap, "2026-12-13", "evening") is None
    assert _period(gap, "2026-12-14", "night")


def test_model_parts_files(tmp_path):
    days = _parts_days()
    (tmp_path / "old_model.json").write_text("{}", "utf-8")
    paths = outlook.write_model_parts(FC, WEIGHTS, days, tmp_path, NOW)
    assert not (tmp_path / "old_model.json").exists()
    assert len(paths) == 12 and paths[-1].name == "index.json"
    index = json.loads((tmp_path / "index.json").read_text("utf-8"))
    ranks = [m["mean_rank"] for m in index["models"]]
    assert ranks == sorted(ranks) and None not in ranks
    expected = WEIGHTS.group_by("model").agg(pl.col("rank").mean()).sort("rank")["model"]
    assert [m["model"] for m in index["models"]] == expected.to_list()
    doc = json.loads((tmp_path / "dwd_icon_d2.json").read_text("utf-8"))
    assert doc["model"] == "dwd_icon_d2" and doc["generated"] == "2026-10-12T08:25+00:00"
    assert doc["rain_probability"] is None
    assert doc["parts"] == ["night", "morning", "afternoon", "evening", "day"]
    assert doc["days"] == [d.isoformat() for d in days]
    assert doc["columns"] == list(outlook.MODEL_PART_COLUMNS)
    assert "Open-Meteo.com" in doc["attribution"]
    last = FC.filter(pl.col("model") == "dwd_icon_d2").drop_nulls("temperature_2m")["time"].max()
    assert doc["last_hour"] == last.strftime("%Y-%m-%dT%H:%MZ")
    n = len(days) * 5
    for code in CODES:
        columns = doc["okresy"][code]
        assert all(len(v) == n for v in columns.values())
        # nothing after the model's horizon: the last days are null throughout
        assert all(v is None for v in columns["tmax"][3 * 5 :])
        assert any(v is not None for v in columns["tmax"][:5])
        for i, s in enumerate(columns["symbol"]):
            if s is None:
                continue
            name = doc["symbols"][s]
            assert name != "showers"
            wet = (columns["precipitation"][i] or 0) >= outlook.RAIN_MM
            assert (name in ("rain", "sleet", "snow")) == wet or columns["precipitation"][i] == 0.3
    # the same values as model_periods, rounded
    periods = outlook.model_periods(FC).filter(
        pl.col("model") == "dwd_icon_d2", pl.col("okres") == "CZ0100"
    )
    first = periods.filter(pl.col("day") == days[1], pl.col("part") == "afternoon").row(
        0, named=True
    )
    i = 1 * 5 + 2
    assert doc["okresy"]["CZ0100"]["tmax"][i] == round(first["tmax"], 1)
    assert doc["symbols"][doc["okresy"]["CZ0100"]["symbol"][i]] == first["symbol"]


def test_model_parts_files_stay_small(tmp_path):
    # 77 okresy with every value filled in (a global model, sunshine too): under 100 kB
    codes = [f"CZ{i:04d}" for i in range(77)]
    one = FC.filter(pl.col("okres") == "CZ0100", pl.col("model") == "ecmwf_ifs025")
    fc = pl.concat([one.with_columns(pl.lit(c).alias("okres")) for c in codes]).with_columns(
        pl.col("temperature_2m") + 0.123,
        (pl.col("precipitation") + 0.137),
        pl.lit(2345.0).alias("sunshine_duration"),
    )
    outlook.write_model_parts(fc, WEIGHTS, _parts_days(), tmp_path, NOW)
    size = (tmp_path / "ecmwf_ifs025.json").stat().st_size
    assert 50_000 < size < 100_000


def test_last_day_keeps_only_parts_with_every_relied_on_model():
    """D+5: a part needs a temperature of every model with 4 % weight or more; ``day`` all four."""
    now = datetime(2026, 10, 23, 9, 13, tzinfo=UTC)
    last = date(2026, 10, 28)
    weights = pl.DataFrame({
        "region": ["CZ1"] * 4, "variable": ["temperature_2m"] * 4, "lead_day": [5] * 4,
        "model": ["a", "b", "c", "d"], "weight": [0.5, 0.45, 0.04, 0.01],
    })  # fmt: skip
    # a has all day, b stops at 12:00 local (11 UTC), c all day, d (1 %) never has a value
    hours = [datetime(2026, 10, 28, h, tzinfo=UTC) for h in range(0, 23)]
    rows = []
    for t in hours:
        for model in ("a", "b", "c"):
            if model != "b" or t.hour < 11:
                rows.append({"okres": "CZ1", "time": t, "model": model, "temperature_2m": 5.0})
    fc = pl.DataFrame(rows)
    parts = ["night", "morning", "afternoon", "evening", "day"]
    table = pl.DataFrame({
        "okres": ["CZ1"] * 10 + ["CZ2"], "day": [last] * 5 + [date(2026, 10, 27)] * 5 + [last],
        "part": parts + parts + ["night"], "tmin": [1.0] * 11,
    })  # fmt: skip
    out = outlook.gate_last_day(table, fc, weights, now)
    got = {(r["okres"], r["day"], r["part"]) for r in out.iter_rows(named=True)}
    assert ("CZ1", last, "night") in got and ("CZ1", last, "morning") in got
    assert ("CZ1", last, "afternoon") not in got
    assert ("CZ1", last, "evening") not in got
    assert ("CZ1", last, "day") not in got
    d4 = {p for (o, d, p) in got if o == "CZ1" and d == date(2026, 10, 27)}
    assert d4 == set(parts)  # D+4 untouched
    assert ("CZ2", last, "night") in got  # an okres without weights is not gated
