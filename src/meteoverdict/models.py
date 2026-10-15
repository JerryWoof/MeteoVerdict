"""The model catalogue in ``models.yaml``: which Open-Meteo models we verify."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

#: Lead days in scope (ROADMAP "Scope v1": D+1 to D+5).
MAX_LEAD_DAY = 5

#: Hours added to 24 x lead day when deciding a run's output step (see Model.native_step).
LEAD_MARGIN_H = 6

#: First day of Open-Meteo's Single Runs archive for most models (00 UTC run, measured
#: live 2026-10-13: the 2026-04-01 12 UTC runs are missing, 2026-04-02 00 UTC are there).
RUNS_FROM = date(2026, 4, 2)

#: UTC hours of the runs in Open-Meteo's Single Runs API (``run_hours`` narrows them).
RUN_HOURS = (0, 6, 12, 18)

#: Forecast variables we verify (Open-Meteo names).
VARIABLES = ("temperature_2m", "precipitation", "wind_speed_10m")

_FIELDS = {
    "id",
    "name",
    "provider",
    "grid",
    "step_hours",
    "forecast_days",
    "max_lead_day",
    "archive_from",
}
_OPTIONAL = {
    "enabled",
    "note",
    "variable_from",
    "coarser_after_h",
    "coarser_step_h",
    "runs_from",
    "run_hours",
}


class ModelCatalogError(ValueError):
    """``models.yaml`` is malformed."""


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    provider: str
    grid: str
    step_hours: int
    forecast_days: float
    max_lead_day: int
    archive_from: date
    enabled: bool = True
    note: str = ""
    variable_from: dict[str, date] = field(default_factory=dict)
    coarser_after_h: int | None = None
    coarser_step_h: int | None = None
    #: first day (00 UTC run) in Open-Meteo's Single Runs archive; None = ``RUNS_FROM``
    runs_from: date | None = None
    #: UTC hours of its runs in the Single Runs API (GEM Global: 00 and 12 only)
    run_hours: tuple[int, ...] = RUN_HOURS

    def available_from(self, variable: str) -> date:
        """First day with D+1 forecasts of ``variable`` in the Previous Runs archive."""
        if variable not in VARIABLES:
            raise KeyError(variable)
        return self.variable_from.get(variable, self.archive_from)

    def native_step(self, lead_day: int) -> int:
        """Output step (hours) of the runs behind ``_previous_day{lead_day}``.

        The run used is at least 24 x lead_day hours old; allow 6 more hours for run
        spacing and delivery delay before deciding that its output has become coarser.
        """
        lead_hours = 24 * lead_day + LEAD_MARGIN_H
        if self.coarser_after_h is not None and lead_hours > self.coarser_after_h:
            return self.coarser_step_h
        return self.step_hours

    def step_at(self, lead_h: int) -> int:
        """Output step (hours) of a single run at ``lead_h`` hours after its start."""
        if self.coarser_after_h is not None and lead_h > self.coarser_after_h:
            return self.coarser_step_h
        return self.step_hours

    def native_hour(self, lead_h: int) -> bool:
        """True if a single run has its own output at ``lead_h`` (not interpolated)."""
        return lead_h % self.step_at(lead_h) == 0

    @property
    def single_runs_from(self) -> date:
        """First day whose runs are in Open-Meteo's Single Runs archive."""
        return self.runs_from or RUNS_FROM

    @property
    def lead_days(self) -> tuple[int, ...]:
        """Lead days (``_previous_dayN``) the archive fills for this model."""
        return tuple(range(1, self.max_lead_day + 1))


def _parse(entry: Any, index: int) -> Model:
    if not isinstance(entry, dict):
        raise ModelCatalogError(f"models[{index}] is not a mapping")
    missing = _FIELDS - entry.keys()
    unknown = entry.keys() - _FIELDS - _OPTIONAL
    if missing or unknown:
        raise ModelCatalogError(
            f"models[{index}]: missing {sorted(missing)}, unknown {sorted(unknown)}"
        )
    if not isinstance(entry["archive_from"], date):
        raise ModelCatalogError(f"models[{index}]: archive_from must be a YYYY-MM-DD date")
    numbers = (entry["step_hours"], entry["forecast_days"])
    if any(isinstance(n, bool) or not isinstance(n, int | float) for n in numbers):
        raise ModelCatalogError(f"models[{index}]: step_hours and forecast_days must be numbers")
    if not isinstance(entry.get("runs_from", date.min), date):
        raise ModelCatalogError(f"models[{index}]: runs_from must be a YYYY-MM-DD date")
    run_hours = entry.get("run_hours", list(RUN_HOURS))
    if (
        not isinstance(run_hours, list)
        or not run_hours
        or any(isinstance(h, bool) or h not in RUN_HOURS for h in run_hours)
    ):
        raise ModelCatalogError(f"models[{index}]: run_hours must be a list of {RUN_HOURS}")
    if not isinstance(entry.get("enabled", True), bool):
        raise ModelCatalogError(f"models[{index}]: enabled must be true or false")
    variable_from = entry.get("variable_from") or {}
    if not isinstance(variable_from, dict) or not all(
        var in VARIABLES and isinstance(day, date) and day > entry["archive_from"]
        for var, day in variable_from.items()
    ):
        raise ModelCatalogError(
            f"models[{index}]: variable_from must map {VARIABLES} to dates after archive_from"
        )
    model = Model(
        **{**entry, "variable_from": variable_from, "run_hours": tuple(sorted(set(run_hours)))}
    )
    if model.step_hours not in (1, 3, 6) or model.forecast_days < 1:
        raise ModelCatalogError(f"{model.id}: implausible step_hours or forecast_days")
    if (model.coarser_after_h is None) != (model.coarser_step_h is None) or (
        model.coarser_step_h is not None and model.coarser_step_h not in (3, 6)
    ):
        raise ModelCatalogError(f"{model.id}: coarser_after_h and coarser_step_h go together")
    longest = min(MAX_LEAD_DAY, math.floor(model.forecast_days))
    if isinstance(model.max_lead_day, bool) or model.max_lead_day not in range(1, longest + 1):
        raise ModelCatalogError(f"{model.id}: max_lead_day must be 1..{longest}")
    return model


def load_models(path: Path | None = None) -> list[Model]:
    """Read the catalogue (default: the ``models.yaml`` shipped with the package)."""
    text = (
        path.read_text(encoding="utf-8")
        if path
        else files("meteoverdict").joinpath("models.yaml").read_text(encoding="utf-8")
    )
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict) or not isinstance(doc.get("models"), list):
        raise ModelCatalogError("expected a top-level 'models' list")
    models = [_parse(entry, i) for i, entry in enumerate(doc["models"])]
    ids = [m.id for m in models]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ModelCatalogError(f"duplicate model ids: {duplicates}")
    return models


def enabled_models(path: Path | None = None) -> list[Model]:
    return [m for m in load_models(path) if m.enabled]
