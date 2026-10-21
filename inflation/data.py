"""Consumer price index data access, for the United States and other countries.

The United States has its own long series (1850+, official BLS CPI-U) built by
``tools/fetch_cpi.py``. Every other country uses the World Bank CPI index
(``FP.CPI.TOTL``, 2010 = 100), which generally starts in 1960. Both live in the
country registry written by ``tools/fetch_world.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
COUNTRIES_PATH = DATA_DIR / "countries.json"

DEFAULT_COUNTRY = "USA"

# Default assumed annual inflation used to project years beyond the last
# observed data point. This is a forward-looking assumption, not a measurement.
DEFAULT_FORWARD_RATE = 0.025


@dataclass(frozen=True)
class Currency:
    code: str
    name: str
    symbol: str


@dataclass(frozen=True)
class Series:
    """An annual-average consumer price index series for one country."""

    iso3: str
    iso2: str
    name: str
    currency: Currency
    index_base: str
    source: str
    short_name: str = ""
    source_detail: str = ""
    annual: dict[int, float] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Name for the interface: shorter and friendlier than the formal one."""
        return self.short_name or self.name

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

    def summary(self) -> dict:
        return {
            "iso3": self.iso3,
            "iso2": self.iso2,
            "name": self.name,
            "short_name": self.display_name,
            "currency": {
                "code": self.currency.code,
                "name": self.currency.name,
                "symbol": self.currency.symbol,
            },
            "index_base": self.index_base,
            "source": self.source,
            "source_detail": self.source_detail,
            "first_year": self.first_year,
            "last_year": self.last_year,
            "observations": len(self.annual),
        }


@lru_cache(maxsize=1)
def _registry() -> tuple[dict, dict]:
    doc = json.loads(COUNTRIES_PATH.read_text())
    countries = {}
    for iso3, raw in doc["countries"].items():
        ccy = raw["currency"]
        countries[iso3] = Series(
            iso3=iso3,
            iso2=raw.get("iso2", ""),
            name=raw["name"],
            short_name=raw.get("short_name") or raw["name"],
            currency=Currency(
                code=ccy.get("code", ""),
                name=ccy.get("name", ""),
                symbol=ccy.get("symbol", "") or ccy.get("code", ""),
            ),
            index_base=raw.get("index_base", ""),
            source=raw.get("source", ""),
            source_detail=raw.get("source_detail", ""),
            annual={int(y): float(v) for y, v in raw["annual"].items()},
        )
    return countries, doc.get("meta", {})


def country_codes() -> list[str]:
    return sorted(_registry()[0])


def country_list() -> list[dict]:
    """Summaries for every available country, sorted by name."""
    countries = _registry()[0]
    return sorted((c.summary() for c in countries.values()), key=lambda c: c["name"])


def get_country(iso3: str) -> Series:
    """Look up a country by ISO 3166 alpha-3 or alpha-2 code."""
    countries = _registry()[0]
    key = (iso3 or "").strip().upper()
    if key in countries:
        return countries[key]
    if len(key) == 2:
        for series in countries.values():
            if series.iso2.upper() == key:
                return series
    raise KeyError(f"unknown country: {iso3}")


def load_series(iso3: str = DEFAULT_COUNTRY) -> Series:
    """The price index series for a country. Defaults to the United States."""
    return get_country(iso3)


def world_meta() -> dict:
    return _registry()[1]


def resolve_index(series: Series, year: int, forward_rate: float = DEFAULT_FORWARD_RATE) -> float:
    """Index value for `year`, projecting forward from the last observed year.

    Years at or before the last observation return measured values. Later years
    are compounded at `forward_rate` per year from the last observation, so the
    projection always starts from a real data point rather than extrapolating a
    trend line fitted to history.
    """
    if year <= series.last_year:
        if year < series.first_year:
            raise ValueError(
                f"{year} is before the earliest {series.name} data ({series.first_year})"
            )
        return series.index(year)
    base_year, base_index = series.last_observed()
    return base_index * (1.0 + forward_rate) ** (year - base_year)


def current_year() -> int:
    return date.today().year


def expected_data_year() -> int:
    """The newest year that should have a complete annual average.

    An annual average is only published after the year ends, so the current
    calendar year is never complete and the previous year is the target.
    """
    return current_year() - 1


@dataclass(frozen=True)
class Freshness:
    """How current the shipped data is.

    The data files are a snapshot rebuilt by the fetch tools, so the app can
    drift out of date between refreshes. This makes that drift visible instead
    of leaving it implied by a timestamp in the footer.
    """

    generated_utc: str
    generated_on: date | None
    age_days: int | None
    newest_year: int
    expected_year: int

    @property
    def lag_years(self) -> int:
        """Years by which the newest data trails what should be available."""
        return max(0, self.expected_year - self.newest_year)

    @property
    def stale(self) -> bool:
        return self.lag_years > 0

    def summary(self) -> dict:
        return {
            "generated_utc": self.generated_utc,
            "generated_on": self.generated_on.isoformat() if self.generated_on else None,
            "age_days": self.age_days,
            "newest_year": self.newest_year,
            "expected_year": self.expected_year,
            "lag_years": self.lag_years,
            "stale": self.stale,
        }


def freshness() -> Freshness:
    """Data vintage across every country, and whether a refresh is overdue."""
    countries, meta = _registry()
    newest_year = max(series.last_year for series in countries.values())

    raw = meta.get("generated_utc", "") or ""
    generated_on = None
    if raw:
        try:
            generated_on = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            ).date()
        except ValueError:
            generated_on = None

    return Freshness(
        generated_utc=raw,
        generated_on=generated_on,
        age_days=(date.today() - generated_on).days if generated_on else None,
        newest_year=newest_year,
        expected_year=expected_data_year(),
    )
