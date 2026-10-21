"""US inflation calculator: historical conversion and forward projection."""

from .calc import (
    Conversion,
    ProjectionPoint,
    average_inflation,
    convert,
    cumulative_inflation,
    project,
    purchasing_power,
    stats,
    year_over_year,
)
from .data import DEFAULT_FORWARD_RATE, Series, current_year, load_series, resolve_index

__all__ = [
    "Conversion",
    "DEFAULT_FORWARD_RATE",
    "ProjectionPoint",
    "Series",
    "average_inflation",
    "convert",
    "cumulative_inflation",
    "current_year",
    "load_series",
    "project",
    "purchasing_power",
    "resolve_index",
    "stats",
    "year_over_year",
]
