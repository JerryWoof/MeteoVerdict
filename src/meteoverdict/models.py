"""The model catalogue in ``models.yaml``: which Open-Meteo models we verify."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

#: Lead days in scope (ROADMAP "Scope v1": D+1 to D+5).
MAX_LEAD_DAY = 5

_FIELDS = {"id", "name", "provider", "grid", "step_hours", "forecast_days", "archive_from"}
_OPTIONAL = {"enabled", "note"}


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
    archive_from: date
    enabled: bool = True
    note: str = ""

    @property
    def lead_days(self) -> tuple[int, ...]:
        """Lead days (``_previous_dayN``) that can exist within the forecast length."""
        return tuple(range(1, min(MAX_LEAD_DAY, math.floor(self.forecast_days)) + 1))


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
    model = Model(**entry)
    if model.step_hours not in (1, 3, 6) or model.forecast_days < 1:
        raise ModelCatalogError(f"{model.id}: implausible step_hours or forecast_days")
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
