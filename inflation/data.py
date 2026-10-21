"""US consumer price index data access."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "cpi.json"

# Default assumed annual inflation used to project years beyond the last
# observed data point. This is a forward-looking assumption, not a measurement.
DEFAULT_FORWARD_RATE = 0.025

# CPI-U was introduced in 1978; this is the first year for which the modern
# index is the appropriate series. Used only for labelling in the UI.
CPI_U_START = 1978


@dataclass(frozen=True)
class Series:
    """An annual-average consumer price index series."""

    annual: dict[int, float]
    meta: dict

    @property
    def first_year(self) -> int:
        return min(self.annual)

    @property
    def last_year(self) -> int:
        return max(self.annual)

    def has(self, year: int) -> bool:
        return year in self.annual

    def index(self, year: int) -> float:
        """Observed index value for `year`; raises KeyError if not measured."""
        return self.annual[year]

    def last_observed(self) -> tuple[int, float]:
        return self.last_year, self.annual[self.last_year]


@lru_cache(maxsize=1)
def load_series() -> Series:
    doc = json.loads(DATA_PATH.read_text())
    annual = {int(k): float(v) for k, v in doc["annual"].items()}
    return Series(annual=annual, meta=doc.get("meta", {}))


def resolve_index(series: Series, year: int, forward_rate: float = DEFAULT_FORWARD_RATE) -> float:
    """Index value for `year`, projecting forward from the last observed year.

    Years at or before the last observation return measured values. Later years
    are compounded at `forward_rate` per year from the last observation, so the
    projection always starts from a real data point rather than extrapolating a
    trend line fitted to history.
    """
    if year <= series.last_year:
        if year < series.first_year:
            raise ValueError(f"{year} is before the earliest data ({series.first_year})")
        return series.index(year)
    base_year, base_index = series.last_observed()
    return base_index * (1.0 + forward_rate) ** (year - base_year)


def current_year() -> int:
    return date.today().year
