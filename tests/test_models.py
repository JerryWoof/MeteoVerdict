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
        assert m.archive_from >= date(2024, 1, 1)  # Previous Runs archive starts 2024
        assert 1 <= len(m.lead_days) <= MAX_LEAD_DAY


@pytest.mark.parametrize(
    ("model_id", "lead_days"),
    [
        # measured live in September 2026: one day less than the forecast length
        ("dwd_icon_d2", (1,)),  # 2-day forecast
        ("chmi_aladin_cz_1km", (1, 2)),  # 3-day forecast
        ("meteofrance_arpege_europe", (1, 2, 3)),  # 4-day forecast
        ("ecmwf_ifs", (1, 2, 3, 4, 5)),  # 15 days, capped to the v1 scope
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
