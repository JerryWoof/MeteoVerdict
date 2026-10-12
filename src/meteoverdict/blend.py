"""A simple multi-model mean as a baseline (roadmap 5.3).

Does a plain average of all models beat every single one? The ``blend`` pseudo-model
is the mean of the models' forecasts for each station, hour and lead day, per
variable, where at least ``MIN_MEMBERS`` models have a value. Its members change with
the lead day (only the global models reach D+5) and with the archive starts.

Some members are only 3- or 6-hourly (Open-Meteo interpolates the hours between), so
the blend is scored like a 6-hourly model: temperature and wind at 00, 06, 12 and 18
UTC, precipitation over 6-hour periods and whole days, where every member is at a
native hour. Its scores are kept next to the models' but it is not ranked among them:
``meteoverdict.ranking`` compares it with the best single model instead.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from meteoverdict.forecasts import KEYS, SCHEMA
from meteoverdict.models import MAX_LEAD_DAY, VARIABLES, Model

ID = "blend"
MIN_MEMBERS = 3
MODEL = Model(
    id=ID,
    name="Mean of all models",
    provider="meteoverdict",
    grid="",
    step_hours=6,
    forecast_days=MAX_LEAD_DAY,
    max_lead_day=MAX_LEAD_DAY,
    archive_from=date(2024, 1, 1),
)


def forecasts(fc: pl.LazyFrame | pl.DataFrame, models: list[Model]) -> pl.LazyFrame:
    """Blend rows (``model`` = ``blend``) from the forecasts of ``models``."""
    members = [m.id for m in models if m.id != ID]
    means = [
        pl.when(pl.col(v).count() >= MIN_MEMBERS).then(pl.col(v).mean()).alias(v) for v in VARIABLES
    ]
    return (
        fc.lazy()
        .filter(pl.col("model").is_in(members))
        .group_by("station_id", "time", "lead_day")
        .agg(means)
        .with_columns(pl.lit(ID).alias("model"))
        .filter(pl.any_horizontal(pl.col(v).is_not_null() for v in VARIABLES))
        .select(list(SCHEMA))
        .cast(SCHEMA)
        .sort(KEYS)
    )
