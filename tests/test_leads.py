from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from meteoverdict import leads

RUN = datetime(2026, 10, 10, 6, tzinfo=UTC)
CZ1, LAMB = "chmi_aladin_cz_1km", "chmi_aladin_central_europe_2km"
A, B = "0-20000-0-11520", "0-20000-0-11406"


def archive(model=CZ1, run=RUN, station=A, steps=range(0, 4), temp=None, accum=None, wind=None):
    """Archive rows like ``aladin.extract_run``: one per lead hour."""
    steps = list(steps)
    n = len(steps)
    return pl.DataFrame(
        {
            "model": [model] * n,
            "run": [run] * n,
            "lead_h": pl.Series(steps, dtype=pl.Int16),
            "station_id": [station] * n,
            "temperature_2m": pl.Series(temp or [10.0 + s for s in steps], dtype=pl.Float32),
            "wind_speed_10m": pl.Series(wind or [2.0] * n, dtype=pl.Float32),
            "precipitation_accum": pl.Series(
                accum or [None, *[0.5 * s for s in steps[1:]]], dtype=pl.Float32
            ),
            "valid_time": [run + timedelta(hours=s) for s in steps],
        }
    )


def obs(station, start, values, variable="temperature_2m"):
    return pl.DataFrame(
        {
            "station_id": [station] * len(values),
            "time": [start + timedelta(hours=i) for i in range(len(values))],
            "variable": [variable] * len(values),
            "value": pl.Series(values, dtype=pl.Float32),
            "quality": pl.Series([0] * len(values), dtype=pl.UInt8),
            "source": ["now"] * len(values),
        }
    )


def test_archive_names_and_files(tmp_path):
    assert leads.run_of("chmi_aladin_cz_1km_2026101006.parquet") == (CZ1, RUN)
    assert leads.run_of("obs-2026-10.parquet") is None
    folder = tmp_path / "aladin-2026-10"
    folder.mkdir()
    for name in ("chmi_aladin_cz_1km_2026100918.parquet", "chmi_aladin_cz_1km_2026101006.parquet"):
        archive().write_parquet(folder / name)
    (folder / "notes.parquet").write_bytes(b"")
    assert [p.name for p in leads.archive_files(tmp_path, since=RUN)] == [
        "chmi_aladin_cz_1km_2026101006.parquet"
    ]
    assert len(leads.archive_files(tmp_path)) == 2


def test_forecast_hours_hourly_precipitation_from_accumulation():
    # accumulated 0.3, 0.3, 1.0 at leads 1..3; a tiny decrease is packing noise
    rows = archive(accum=[None, 0.3, 0.3, 1.0]).vstack(
        archive(station=B, accum=[None, 0.2, 0.19, 0.5])
    )
    fc = leads.forecast_hours(rows).collect()
    assert fc["lead_h"].min() == 1  # the analysis is not scored
    rain = fc.filter(pl.col("variable") == "precipitation").sort("station_id", "lead_h")
    by_station = {s: g["forecast"].to_list() for (s,), g in rain.group_by("station_id")}
    assert by_station[A] == pytest.approx([0.3, 0.0, 0.7], abs=1e-6)
    assert by_station[B] == pytest.approx([0.2, 0.0, 0.31], abs=1e-6)
    temp = fc.filter(pl.col("variable") == "temperature_2m", pl.col("station_id") == A)
    assert sorted(temp["forecast"].to_list()) == [11.0, 12.0, 13.0]
    assert temp.sort("lead_h")["valid_time"].to_list() == [
        RUN + timedelta(hours=h) for h in (1, 2, 3)
    ]


def test_precipitation_needs_the_previous_lead():
    rows = archive(steps=[0, 1, 3], accum=[None, 0.4, 1.0])  # lead 2 missing
    fc = leads.forecast_hours(rows).collect().filter(pl.col("variable") == "precipitation")
    assert fc.sort("lead_h")["lead_h"].to_list() == [1]


def test_pairs_use_the_valid_time_and_a_common_sample():
    rows = pl.concat(
        [
            archive(model=CZ1, temp=[0, 11, 12, 13]),
            archive(model=LAMB, temp=[0, 10, 10, 10]),
            archive(model=CZ1, station=B),  # only one model at B: left out
        ]
    )
    observed = obs(A, RUN, [9.0, 10.0, 11.0, 12.0]).vstack(obs(B, RUN, [9.0, 9.0, 9.0, 9.0]))
    p = leads.pairs(leads.forecast_hours(rows), observed)
    assert set(p["station_id"]) == {A}
    assert p.filter(pl.col("variable") != "temperature_2m").height == 0  # no wind/rain obs
    cz = p.filter(pl.col("model") == CZ1).sort("lead_h")
    # lead 2 is valid at 08 UTC: forecast 12, observed 11
    assert cz.select("lead_h", "forecast", "observed").rows() == [
        (1, 11, 10),
        (2, 12, 11),
        (3, 13, 12),
    ]
    assert set(p["run_hour"]) == {"06"}


def test_lead_scores_by_lead_hour_run_hour_and_kraj():
    run2 = RUN + timedelta(hours=6)
    rows = pl.concat(
        [
            archive(run=RUN, temp=[0, 11, 12, 13]),
            archive(run=run2, temp=[0, 14, 12, 12]),
        ]
    )
    observed = obs(A, RUN, [10.0] * 10)
    p = leads.pairs(leads.forecast_hours(rows), observed)
    stations = pl.DataFrame({"id": [A], "kraj_code": ["CZ010"], "kraj": ["Hlavní město Praha"]})
    table = leads.lead_scores(p, stations)
    cz = table.filter(pl.col("region") == "cz", pl.col("run_hour") == "all")
    lead1 = cz.filter(pl.col("lead_h") == 1).row(0, named=True)
    # errors at H+1: 06 run +1, 12 run +4 → MAE 2.5, bias 2.5, RMSE sqrt(8.5)
    assert (lead1["n"], lead1["runs"], lead1["stations"]) == (2, 2, 1)
    assert lead1["mae"] == pytest.approx(2.5)
    assert lead1["bias"] == pytest.approx(2.5)
    assert lead1["rmse"] == pytest.approx(8.5**0.5)
    assert lead1["a_0p1"] is None  # counts only for precipitation
    by_hour = table.filter(pl.col("region") == "cz", pl.col("lead_h") == 1)
    assert by_hour["run_hour"].to_list() == ["all", "06", "12"]
    assert by_hour.filter(pl.col("run_hour") == "12")["mae"].item() == pytest.approx(4)
    kraj = table.filter(pl.col("region") == "CZ010")
    assert kraj["run_hour"].unique().to_list() == ["all"]
    assert kraj.filter(pl.col("lead_h") == 1)["mae"].item() == pytest.approx(2.5)


def test_precipitation_contingency_counts():
    rows = archive(accum=[None, 0.0, 0.5, 0.5])  # hourly 0.0, 0.5, 0.0
    observed = obs(A, RUN + timedelta(hours=1), [0.2, 0.3, 0.0], "precipitation")
    table = leads.lead_scores(leads.pairs(leads.forecast_hours(rows), observed))
    rain = table.filter(pl.col("variable") == "precipitation", pl.col("run_hour") == "all")
    counts = {
        r["lead_h"]: (r["a_0p1"], r["b_0p1"], r["c_0p1"], r["d_0p1"])
        for r in rain.iter_rows(named=True)
    }
    assert counts == {1: (0, 0, 1, 0), 2: (1, 0, 0, 0), 3: (0, 0, 0, 1)}


def test_publication_delays_and_document():
    old = archive()  # written before ``published`` existed
    new = archive(model=LAMB).with_columns(
        pl.lit(RUN + timedelta(hours=4, minutes=24)).alias("published")
    )
    assert leads.publication_delays(old) == {CZ1: None}
    delays = leads.publication_delays(pl.concat([old, new], how="diagonal_relaxed"))
    assert delays == {CZ1: None, LAMB: 4.4}

    rows = pl.concat([archive(model=CZ1), archive(model=LAMB)])
    p = leads.pairs(leads.forecast_hours(rows), obs(A, RUN, [10.0] * 5))
    table = leads.lead_scores(p)
    doc = leads.document(
        table, p, datetime(2026, 10, 13, 7, tzinfo=UTC), delays, {CZ1: "ALADIN 1 km"}
    )
    assert doc["columns"] == leads.COLUMNS
    assert len(doc["rows"]) == table.height
    assert doc["first_run"] == doc["last_run"] == "2026-10-10T06:00Z"
    assert doc["models"][CZ1] == {
        "name": "ALADIN 1 km",
        "runs": 1,
        "pairs": 3,
        "publication_delay_h": None,
    }
    assert doc["models"][LAMB]["publication_delay_h"] == 4.4
    assert doc["regions"] == {"cz": "Česko"}
    empty = leads.document(table.clear(), p.clear(), datetime(2026, 10, 13, tzinfo=UTC))
    assert (empty["rows"], empty["first_run"], empty["models"]) == ([], None, {})


class FakeStore:
    def __init__(self, files):
        self.files = files  # {tag: {name: bytes}}
        self.downloaded = []

    def assets(self, tag):
        return {n: {"name": n, "size": len(b)} for n, b in self.files.get(tag, {}).items()}

    def download(self, tag, name, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[tag][name])
        self.downloaded.append(name)
        return dest


def test_download_archive_only_new_runs_since(tmp_path):
    store = FakeStore(
        {
            "aladin-2026-10": {
                "chmi_aladin_cz_1km_2026100900.parquet": b"old",
                "chmi_aladin_cz_1km_2026101006.parquet": b"run",
                "README.txt": b"x",
            }
        }
    )
    assert (
        leads.download_archive(store, tmp_path, ["2026-09", "2026-10"], RUN, log=lambda _: None)
        == 1
    )
    assert store.downloaded == ["chmi_aladin_cz_1km_2026101006.parquet"]
    assert leads.download_archive(store, tmp_path, ["2026-10"], RUN, log=lambda _: None) == 0
