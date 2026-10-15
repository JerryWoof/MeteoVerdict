from datetime import date, timedelta

import polars as pl
import pytest

from meteoverdict import station_check as sc

DAY = date(2026, 9, 30)
#: s1-s3 main stations in kraj A, s4-s6 climate stations in kraj A, s7-s9 in kraj B
IDS = [f"s{i}" for i in range(1, 10)]
STATIONS = pl.DataFrame(
    {
        "id": IDS,
        "name": [f"Station {i}" for i in range(1, 10)],
        "lat": [50.0 + i / 100 for i in range(9)],
        "lon": [14.0 + i / 100 for i in range(9)],
        "elevation": [300.0] * 9,
        "okres_code": ["CZ0201"] * 6 + ["CZ0202"] * 3,
        "okres": ["Benešov"] * 6 + ["Beroun"] * 3,
        "kraj_code": ["CZ020"] * 6 + ["CZ064"] * 3,
        "kraj": ["Středočeský kraj"] * 6 + ["Jihomoravský kraj"] * 3,
        "elevation_class": ["lowland"] * 9,
    }
)
KINDS = pl.DataFrame({"id": IDS, "network": ["main"] * 3 + ["climate"] * 6})


def scores(error, days=20, variable="temperature_2m", lead_days=(1,)):
    """error(model, station, day index) -> (mean error, mean absolute error), n = 4."""
    rows = []
    for model in ("a", "b", "c", "blend"):
        for station in IDS:
            for i in range(days):
                for lead in lead_days:
                    err, abs_err = error(model, station, i)
                    rows.append(
                        {
                            "date": DAY - timedelta(days=i),
                            "station_id": station,
                            "model": model,
                            "lead_day": lead,
                            "variable": variable,
                            "n": 4,
                            "sum_err": err * 4,
                            "sum_abs_err": abs_err * 4,
                            "sum_sq_err": abs_err * abs_err * 4,
                        }
                    )
    return pl.DataFrame(rows).cast({"n": pl.UInt16, "lead_day": pl.Int8})


def test_networks_from_meta2():
    meta2 = pl.DataFrame(
        {
            "OBS_TYPE": ["10M", "10M", "DLY"],
            "WSI": ["s4", "s4", "s7"],
            "EG_EL_ABBREVIATION": ["T", "SRA10M", "SRA"],
            "NAME": ["Teplota", "Srážka", "Srážka"],
            "UN_DESCRIPTION": ["°C", "mm", "mm"],
            "HEIGHT": ["2", "1", "1"],
        }
    )
    stations = pl.DataFrame({"id": ["0-20000-0-11520", "s4", "s7", "s8"]})
    kinds = sc.networks(stations, meta2)
    assert kinds["network"].to_list() == ["main", "climate", "precipitation", "other"]
    subsets = sc.subsets_by_network(KINDS)
    assert subsets["main"] == ["s1", "s2", "s3"]
    assert len(subsets["climate"]) == 6
    assert subsets["manual_precipitation"] == []


def test_same_ranking_for_a_subset_where_models_behave_alike():
    # model a is best everywhere, c worst; a little day-to-day noise
    def error(model, station, i):
        base = {"a": 1.0, "b": 1.5, "c": 2.0, "blend": 1.2}[model]
        return 0.0, base + (i % 3) * 0.05

    table = sc.compare_subsets(
        scores(error), STATIONS, {"all": None, "main": ["s1", "s2", "s3"]}, resamples=100
    )
    cz = table.filter(pl.col("level") == "cz", pl.col("subset") == "main")
    assert cz.filter(pl.col("rank") == 1)["model"].to_list() == ["a"]
    assert cz["stations"].unique().to_list() == [3]
    assert cz.filter(pl.col("model") == "blend")["rank"].to_list() == [None]
    # kraj B has 3 stations of all, none of the main subset: left out there
    kraje = table.filter(pl.col("level") == "kraj")
    assert set(kraje.filter(pl.col("subset") == "main")["region"]) == {"CZ020"}
    assert set(kraje.filter(pl.col("subset") == "all")["region"]) == {"CZ020", "CZ064"}

    summary = sc.summarize(table)
    row = summary.filter(pl.col("level") == "cz").row(0, named=True)
    assert row["spearman"] == pytest.approx(1.0)
    assert row["same_best"] and row["within_ci"]
    assert row["best_base"] == row["best"] == "a"
    assert row["mean_mae_diff"] == pytest.approx(0.0)
    over = sc.overview(summary)
    assert over.filter(pl.col("level") == "cz")["same_best"].to_list() == [1.0]


def test_a_subset_with_another_best_model():
    # model b is much better at the main stations, a everywhere else
    def error(model, station, i):
        main = station in ("s1", "s2", "s3")
        base = {"a": 1.0, "b": 0.5 if main else 3.0, "c": 2.0, "blend": 1.5}[model]
        return 0.0, base + (i % 2) * 0.1

    table = sc.compare_subsets(
        scores(error),
        STATIONS,
        {"all": None, "main": ["s1", "s2", "s3"]},
        levels=("cz",),
        resamples=100,
    )
    row = sc.summarize(table).row(0, named=True)
    assert (row["best_base"], row["best"]) == ("a", "b")
    assert not row["same_best"]
    assert not row["within_ci"]  # every day says the same: a real difference
    assert row["spearman"] == pytest.approx(-0.5)


def test_spearman():
    assert sc.spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
    assert sc.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert sc.spearman([1, 2], [1, 2]) is None
    assert sc.spearman([1, 1, 1], [1, 2, 3]) is None


def test_suspicious_stations():
    # s5 is 3 °C colder than forecast by every model (a frost hollow), s9 has three
    # times the errors of its okres, the others err a little both ways
    def error(model, station, i):
        if station == "s5":
            return 3.0, 3.0
        if station == "s9":
            return 0.0, 3.0
        return (0.2 if i % 2 else -0.2), 1.0

    frame = scores(error, variable="temperature_2m_06utc", lead_days=(1, 2))
    errors = sc.station_errors(frame)
    assert errors.filter(pl.col("station_id") == "s5")["agree"].to_list() == [1.0]
    assert errors["models"].unique().to_list() == [3]  # not the blend
    assert errors["days"].unique().to_list() == [20]
    daily = sc.daily_errors(frame)
    flagged = sc.suspicious_stations(errors, daily, STATIONS, KINDS)
    assert set(flagged["station_id"]) == {"s5", "s9"}
    s5 = flagged.filter(pl.col("station_id") == "s5").row(0, named=True)
    assert s5["compared_to"] == "okres"
    assert s5["bias_excess"] == pytest.approx(3.0)
    assert "frost hollow" in s5["hint"]
    assert s5["network"] == "climate"
    s9 = flagged.filter(pl.col("station_id") == "s9").row(0, named=True)
    assert s9["ratio"] == pytest.approx(3.0)  # MAE 3 against its okres's median of 1
    assert "far above its okres" in s9["hint"]
    # too few days: nothing to say
    assert sc.suspicious_stations(errors, daily, STATIONS, min_days=21).is_empty()
    top = sc.top_stations(flagged, 1)
    assert top["station_id"].to_list() == ["s5"]
    assert top["flagged"].to_list() == [1]


def test_stations_are_compared_on_their_own_days():
    # a stormy week: every station errs by 5 mm; s9 only reported that week (a manual
    # gauge whose other days are not in yet), so its MAE is high but not unusual
    def error(model, station, i):
        return (-5.0, 5.0) if i < 5 else (0.0, 1.0)

    frame = scores(error, days=25, variable="precipitation_24h")
    frame = frame.filter(
        (pl.col("station_id") != "s9") | (pl.col("date") > DAY - timedelta(days=5))
    )
    errors = sc.station_errors(frame)
    flagged = sc.suspicious_stations(errors, sc.daily_errors(frame), STATIONS, min_days=5)
    assert flagged.is_empty()
    s9 = errors.filter(pl.col("station_id") == "s9").row(0, named=True)
    assert s9["mae"] == pytest.approx(5.0)  # against 1.8 for the others over all days


def test_wind_and_precipitation_hints():
    assert "sheltered" in sc._hint("wind_speed_10m", 2.0, 1.0)
    assert "exposed" in sc._hint("wind_speed_10m", -2.0, 1.0)
    assert "warmer" in sc._hint("temperature_2m", -2.0, 1.0)
    assert "gauge" in sc._hint("precipitation_24h", 0.0, 3.0)


def test_report_is_markdown():
    def error(model, station, i):
        if station == "s5":
            return 3.0, 3.0
        return 0.0, {"a": 1.0, "b": 1.5, "c": 2.0, "blend": 1.2}[model] + (i % 3) * 0.05

    frame = scores(error)
    table = sc.compare_subsets(
        frame, STATIONS, {"all": None, "main": ["s1", "s2", "s3"]}, resamples=50
    )
    variables = ("temperature_2m",)
    flagged = sc.suspicious_stations(
        sc.station_errors(frame, variables), sc.daily_errors(frame, variables), STATIONS, KINDS
    )
    text = sc.report(sc.summarize(table), flagged)
    assert "## Czechia" in text and "## Kraje" in text
    assert "| main | temperature_2m | 1 | 3 |" in text
    assert "Station 5" in text
    table = pl.DataFrame({"x": [None, 1.234], "ok": [True, False], "name": ["a", "b"]})
    assert sc.markdown_table(table).splitlines() == [
        "| x | ok | name |",
        "|---|---|---|",
        "| - | yes | a |",
        "| 1.23 | no | b |",
    ]
