"""Inflation calculator: historical conversion and forward projection.

Supports the United States (1850+) and 190 countries via the World Bank CPI index.
"""

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
from .data import (
    DEFAULT_COUNTRY,
    DEFAULT_FORWARD_RATE,
    Currency,
    Freshness,
    Series,
    country_codes,
    country_list,
    current_year,
    expected_data_year,
    freshness,
    get_country,
    load_series,
    resolve_index,
    world_meta,
)

__all__ = [
    "Conversion",
    "Currency",
    "DEFAULT_COUNTRY",
    "DEFAULT_FORWARD_RATE",
    "Freshness",
    "ProjectionPoint",
    "Series",
    "average_inflation",
    "convert",
    "country_codes",
    "country_list",
    "cumulative_inflation",
    "current_year",
    "expected_data_year",
    "freshness",
    "get_country",
    "load_series",
    "project",
    "purchasing_power",
    "resolve_index",
    "stats",
    "world_meta",
    "year_over_year",
]
