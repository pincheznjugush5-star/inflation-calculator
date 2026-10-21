"""Inflation arithmetic: historical conversion and forward projection."""

from __future__ import annotations

from dataclasses import dataclass, field

from .data import DEFAULT_FORWARD_RATE, Series, current_year, resolve_index


@dataclass
class Conversion:
    amount: float
    from_year: int
    to_year: int
    from_index: float
    to_index: float
    result: float
    total_change: float  # fractional change, e.g. 0.5 == +50%
    annualized: float  # compound annual rate over the span
    years: int
    projected: bool = field(default=False)  # True if to_year is beyond the data

    @property
    def factor(self) -> float:
        return self.to_index / self.from_index


def convert(
    series: Series,
    amount: float,
    from_year: int,
    to_year: int,
    forward_rate: float = DEFAULT_FORWARD_RATE,
) -> Conversion:
    """Convert `amount` of `from_year` dollars into `to_year` dollars.

    Uses the standard ratio-of-indexes method:
        to = amount * (index[to_year] / index[from_year])

    Either direction is allowed: converting today's money back into the money of
    an earlier year is just the inverse ratio and is reported with a negative
    total change.
    """
    if amount < 0:
        raise ValueError("amount must be non-negative")

    from_index = resolve_index(series, from_year, forward_rate)
    to_index = resolve_index(series, to_year, forward_rate)
    result = amount * (to_index / from_index)
    total_change = (to_index / from_index) - 1.0
    years = abs(to_year - from_year)
    annualized = ((to_index / from_index) ** (1.0 / years) - 1.0) if years > 0 else 0.0

    return Conversion(
        amount=amount,
        from_year=from_year,
        to_year=to_year,
        from_index=from_index,
        to_index=to_index,
        result=result,
        total_change=total_change,
        annualized=annualized,
        years=years,
        projected=to_year > series.last_year,
    )


@dataclass
class ProjectionPoint:
    year: int
    index: float
    value: float
    observed: bool


def project(
    series: Series,
    amount: float,
    base_year: int,
    end_year: int,
    forward_rate: float = DEFAULT_FORWARD_RATE,
) -> list[ProjectionPoint]:
    """Value of `amount` (in base_year dollars) for each year up to end_year."""
    if end_year < base_year:
        raise ValueError("end_year must not be before base_year")
    base_index = resolve_index(series, base_year, forward_rate)
    points: list[ProjectionPoint] = []
    for year in range(base_year, end_year + 1):
        index = resolve_index(series, year, forward_rate)
        points.append(
            ProjectionPoint(
                year=year,
                index=index,
                value=amount * (index / base_index),
                observed=year <= series.last_year,
            )
        )
    return points


def purchasing_power(
    series: Series,
    amount: float,
    from_year: int,
    to_year: int | None = None,
    forward_rate: float = DEFAULT_FORWARD_RATE,
) -> Conversion:
    """What `amount` from `from_year` is worth in `to_year` (default: this year).

    This is the inverse view of :func:`convert`: it answers "how much would
    today's money have to be to buy what this bought then" by reporting the
    real value of the original sum in today's terms.
    """
    if to_year is None:
        to_year = current_year()
    return convert(series, amount, from_year, to_year, forward_rate)


def cumulative_inflation(series: Series, from_year: int, to_year: int) -> float:
    """Fractional change in the index between two observed years."""
    return series.index(to_year) / series.index(from_year) - 1.0


def average_inflation(
    series: Series, from_year: int, to_year: int, window: int | None = None
) -> float:
    """Compound annual inflation rate between two years.

    With `window`, only the last `window` years of the span are used, which is
    useful for recent-trend estimates.
    """
    if window is not None:
        from_year = max(from_year, to_year - window)
    years = to_year - from_year
    if years <= 0:
        raise ValueError("need at least one year between from_year and to_year")
    return (series.index(to_year) / series.index(from_year)) ** (1.0 / years) - 1.0


def year_over_year(series: Series) -> list[tuple[int, float]]:
    """Annual inflation rate for every year where a prior year is available."""
    years = sorted(series.annual)
    out = []
    for prev, cur in zip(years, years[1:]):
        if cur != prev + 1:
            continue
        out.append((cur, series.annual[cur] / series.annual[prev] - 1.0))
    return out


def stats(series: Series) -> dict:
    """Summary statistics used by the dashboard."""
    yoy = year_over_year(series)
    rates = [r for _, r in yoy]
    highest = max(yoy, key=lambda t: t[1])
    lowest = min(yoy, key=lambda t: t[1])
    deflations = [(y, r) for y, r in yoy if r < 0]
    return {
        "first_year": series.first_year,
        "last_year": series.last_year,
        "observations": len(series.annual),
        "mean_inflation": sum(rates) / len(rates),
        "highest_year": {"year": highest[0], "rate": highest[1]},
        "lowest_year": {"year": lowest[0], "rate": lowest[1]},
        "deflation_years": len(deflations),
        "cumulative_since_first": series.annual[series.last_year] / series.annual[series.first_year] - 1.0,
    }
