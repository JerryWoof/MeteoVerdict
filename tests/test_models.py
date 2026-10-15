from datetime import date

import pytest

from meteoverdict.models import MAX_LEAD_DAY, ModelCatalogError, enabled_models, load_models

# The v1 candidates from ROADMAP.md "Scope v1" (all cover Czechia, see docs/data-sources.md).
ROADMAP_CANDIDATES = {
    "chmi_aladin_cz_1km",
    "chmi_aladin_central_europe_2km",
    "dwd_icon_d2",
    "dwd_icon_eu",
    "ecmwf_ifs",
    "ecmwf_aifs025_single",
    "ncep_gfs_global",
    "ukmo_global_deterministic_10km",
    "meteofrance_arpege_europe",
    "geosphere_arome_austria",
}


def test_shipped_catalogue_is_valid_and_contains_roadmap_candidates():
    models = load_models()
    assert {m.id for m in enabled_models()} >= ROADMAP_CANDIDATES
    for m in models:
        # mostly 2024; JMA GSM back to the probe's start (2021-01-01)
        assert m.archive_from >= date(2021, 1, 1)
        assert 1 <= len(m.lead_days) <= MAX_LEAD_DAY


@pytest.mark.parametrize(
    ("model_id", "lead_days"),
    [
        # measured live in September 2026: one day less than the forecast length
        ("dwd_icon_d2", (1,)),  # 2-day forecast
        ("chmi_aladin_cz_1km", (1, 2)),  # 3-day forecast
        ("meteofrance_arpege_europe", (1, 2, 3)),  # 4-day forecast
        ("ecmwf_ifs", (1, 2, 3, 4, 5)),  # 15 days, capped to the v1 scope
        # added 2026-10-15, measured on September 2026
        ("cma_grapes_global", (1, 2, 3, 4)),  # 10-day forecast, D+5 empty in the archive
        ("meteofrance_arpege_world", (1, 2, 3)),  # 4-day forecast
        ("dwd_icon", (1, 2, 3, 4, 5)),
        ("gem_global", (1, 2, 3, 4, 5)),
        ("jma_gsm", (1, 2, 3, 4, 5)),
        ("ncep_aigfs025", (1, 2, 3, 4, 5)),
        ("knmi_harmonie_arome_europe", (1,)),
    ],
)
def test_lead_days_are_the_measured_ones(model_id, lead_days):
    model = next(m for m in load_models() if m.id == model_id)
    assert model.lead_days == lead_days


VALID = """
models:
  - id: a
    name: A
    provider: P
    grid: 1 km
    step_hours: 1
    forecast_days: 2
    max_lead_day: 1
    archive_from: 2024-01-01
"""


def write(tmp_path, text):
    path = tmp_path / "models.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_custom_catalogue_defaults_to_enabled(tmp_path):
    (model,) = load_models(write(tmp_path, VALID))
    assert model.enabled is True
    assert model.note == ""


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("[]", "top-level 'models'"),
        ("models: [1]", "not a mapping"),
        (VALID.replace("    grid: 1 km\n", ""), "missing \\['grid'\\]"),
        (VALID + "    colour: red\n", "unknown \\['colour'\\]"),
        (VALID.replace("2024-01-01", "January 2024"), "YYYY-MM-DD"),
        (VALID.replace("step_hours: 1", "step_hours: 2"), "implausible"),
        (VALID.replace("forecast_days: 2", "forecast_days: 2 days"), "must be numbers"),
        (VALID + "    enabled: maybe\n", "true or false"),
        (VALID + "    run_hours: [0, 3]\n", "run_hours"),
        (VALID + "    run_hours: []\n", "run_hours"),
        (VALID + "    run_hours: 12\n", "run_hours"),
        (VALID.replace("forecast_days: 2", "forecast_days: 0.5"), "implausible"),
        (VALID.replace("max_lead_day: 1", "max_lead_day: 3"), "max_lead_day must be 1..2"),
        (VALID.replace("max_lead_day: 1", "max_lead_day: 0"), "max_lead_day"),
        (VALID + VALID.replace("models:\n", ""), "duplicate model ids: \\['a'\\]"),
    ],
)
def test_malformed_catalogue_is_rejected(tmp_path, text, match):
    with pytest.raises(ModelCatalogError, match=match):
        load_models(write(tmp_path, text))


def test_available_from_uses_per_variable_starts():
    arpege = next(m for m in load_models() if m.id == "meteofrance_arpege_europe")
    assert arpege.available_from("temperature_2m") == date(2024, 1, 19)
    assert arpege.available_from("wind_speed_10m") == date(2026, 8, 7)
    with pytest.raises(KeyError):
        arpege.available_from("snowfall")


@pytest.mark.parametrize(
    "variable_from",
    [
        "    variable_from:\n      snowfall: 2025-01-01\n",
        "    variable_from:\n      precipitation: soon\n",
        "    variable_from:\n      precipitation: 2023-12-31\n",  # before archive_from
        "    variable_from: [precipitation]\n",
    ],
)
def test_bad_variable_from_is_rejected(tmp_path, variable_from):
    with pytest.raises(ModelCatalogError, match="variable_from"):
        load_models(write(tmp_path, VALID + variable_from))


@pytest.mark.parametrize(
    ("model_id", "steps"),
    [
        ("chmi_aladin_cz_1km", [1, 1]),
        ("dwd_icon_eu", [1, 1, 1, 3]),  # 3-hourly after 78 h
        ("ecmwf_ifs", [1, 1, 1, 3, 3]),  # after 90 h
        ("ncep_gfs_global", [1, 1, 1, 1, 3]),  # after 120 h
        ("ukmo_global_deterministic_10km", [1, 1, 3, 3, 3]),  # after 54 h
        ("ecmwf_aifs025_single", [6] * 5),
        ("dwd_icon", [1, 1, 1, 3, 3]),  # after 78 h
        ("gem_global", [1, 1, 1, 3, 3]),  # after 84 h (measured)
        ("meteofrance_arpege_world", [1, 3, 3]),  # after 48 h
        ("cma_grapes_global", [3] * 4),
        ("jma_gsm", [6] * 5),
        ("ncep_aigfs025", [6] * 5),
    ],
)
def test_native_step_per_lead_day(model_id, steps):
    model = next(m for m in load_models() if m.id == model_id)
    assert [model.native_step(n) for n in model.lead_days] == steps


def test_coarser_fields_go_together(tmp_path):
    with pytest.raises(ModelCatalogError, match="go together"):
        load_models(write(tmp_path, VALID + "    coarser_after_h: 24\n"))
    with pytest.raises(ModelCatalogError, match="go together"):
        load_models(write(tmp_path, VALID + "    coarser_after_h: 24\n    coarser_step_h: 2\n"))


def test_run_hours_default_and_narrowed(tmp_path):
    (model,) = load_models(write(tmp_path, VALID))
    assert model.run_hours == (0, 6, 12, 18)
    (model,) = load_models(write(tmp_path, VALID + "    run_hours: [12, 0]\n"))
    assert model.run_hours == (0, 12)
    gem = next(m for m in load_models() if m.id == "gem_global")
    assert gem.run_hours == (0, 12)
