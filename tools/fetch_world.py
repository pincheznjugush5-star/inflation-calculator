#!/usr/bin/env python3
"""Fetch per-country consumer price indices and currency metadata.

Sources
-------
World Bank, indicator FP.CPI.TOTL ("Consumer price index, 2010 = 100").
    Annual index for ~190 economies, generally from 1960. This is the series
    used for every country other than the United States.

datasets/country-codes (ISO 3166 + ISO 4217)
    Authoritative country / currency code mapping.

The United States keeps the long, higher-quality series built by
tools/fetch_cpi.py (1850+, official BLS CPI-U) instead of the World Bank one.

Run:  python3 tools/fetch_world.py
"""

from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "data" / "countries.json"
CACHE_DIR = ROOT / ".cache"

WB_CPI_URL = (
    "https://api.worldbank.org/v2/country/all/indicator/FP.CPI.TOTL"
    "?format=json&per_page=20000&date=1960:2026"
)
COUNTRY_CODES_URL = (
    "https://raw.githubusercontent.com/datasets/country-codes/main/data/country-codes.csv"
)
UA = "Mozilla/5.0 (X11; Linux x86_64) inflation-calculator/1.0"

# Names for the interface. The canonical `name` is the CLDR display name, and
# `short_name` is a curated override for the handful of names that are awkward
# in a dropdown: CLDR abbreviates some ("UK", "US"), uses ampersands
# ("Antigua & Barbuda"), or separates disambiguators with a dash
# ("Congo - Kinshasa"). Everything else keeps its CLDR name.
#
# Both come from CLDR rather than the UNTERM/official columns, because the
# upstream country-codes file marks those columns as restricted: the UN terms
# of use allow no redistribution or derivative works, so they are not shipped.
# CLDR is redistributable under the Unicode licence with a notice, which
# ATTRIBUTION covers (see the README).
DISPLAY_NAMES = {
    "ATG": "Antigua and Barbuda",
    "COD": "DR Congo",
    "COG": "Congo",
    "CIV": "Ivory Coast",
    "GBR": "United Kingdom",
    "KNA": "St Kitts and Nevis",
    "STP": "Sao Tome and Principe",
    "TTO": "Trinidad and Tobago",
    "USA": "United States",
    "VCT": "St Vincent and the Grenadines",
}

# Currency symbols for common currencies; anything not listed falls back to the
# ISO 4217 code, which is always correct even when it is less familiar.
CURRENCY_SYMBOLS = {
    "USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "JPY": "\u00a5", "CNY": "\u00a5",
    "INR": "\u20b9", "KRW": "\u20a9", "RUB": "\u20bd", "TRY": "\u20ba", "THB": "\u0e3f",
    "VND": "\u20ab", "NGN": "\u20a6", "PHP": "\u20b1", "CRC": "\u20a1", "ILS": "\u20aa",
    "UAH": "\u20b4", "KZT": "\u20b8", "GHS": "\u20b5", "BRL": "R$", "ZAR": "R",
    "AUD": "A$", "CAD": "C$", "NZD": "NZ$", "HKD": "HK$", "SGD": "S$",
    "MXN": "Mex$", "ARS": "AR$", "CLP": "CLP$", "COP": "COL$", "CHF": "CHF",
    "SEK": "kr", "NOK": "kr", "DKK": "kr", "PLN": "z\u0142", "CZK": "K\u010d",
    "HUF": "Ft", "RON": "lei", "BGN": "лв", "HRK": "kn", "ISK": "kr",
    "IDR": "Rp", "MYR": "RM", "PKR": "\u20a8", "BDT": "\u09f3", "LKR": "Rs",
    "EGP": "E\u00a3", "SAR": "SR", "AED": "AED", "QAR": "QR", "KWD": "KD",
    "MAD": "DH", "DZD": "DA", "TND": "DT", "KES": "KSh", "TZS": "TSh",
    "UGX": "USh", "ETB": "Br", "ZMW": "ZK", "BWP": "P", "MUR": "\u20a8",
    "TWD": "NT$", "MNT": "\u20ae", "KHR": "\u17db", "LAK": "\u20ad", "MMK": "K",
    "NPR": "\u20a8", "AFN": "\u060b", "IRR": "\ufdfc", "IQD": "ID", "JOD": "JD",
    "LBP": "L\u00a3", "SYP": "S\u00a3", "YER": "YR", "OMR": "OR", "BHD": "BD",
    "GTQ": "Q", "HNL": "L", "NIO": "C$", "PAB": "B/.", "DOP": "RD$", "JMD": "J$",
    "TTD": "TT$", "BBD": "Bds$", "BSD": "B$", "BZD": "BZ$", "GYD": "G$",
    "PYG": "\u20b2", "UYU": "$U", "BOB": "Bs", "PEN": "S/", "VES": "Bs.S",
    "ECU": "$", "CUP": "\u20b1", "HTG": "G", "RSD": "din", "MKD": "den",
    "ALL": "L", "MDL": "L", "BYN": "Br", "GEL": "\u20be", "AMD": "\u058f",
    "AZN": "\u20bc", "UZS": "so\u02bcm", "KGS": "som", "TJS": "SM",
    "TMT": "m", "MNT ": "\u20ae", "BTC": "\u20bf",
}


def _get(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _cache(name: str, fetch):
    path = CACHE_DIR / name
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    try:
        data = fetch()
    except Exception as exc:
        if path.exists():
            print(f"  {name}: using cache ({exc})", file=sys.stderr)
            return json.loads(path.read_text())
        raise
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


# Bumped whenever the parsing below changes shape. The cache holds parsed
# output, not raw responses, so a stale entry would otherwise be served as if
# it reflected the current logic.
CACHE_VERSION = 2


def fetch_country_meta() -> dict[str, dict]:
    """ISO country -> {iso2, name, currency_code, currency_name}."""

    def _do():
        text = _get(COUNTRY_CODES_URL).decode("utf-8", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text)))
        out = {}
        for row in rows:
            iso3 = (row.get("ISO3166-1-Alpha-3") or "").strip()
            if len(iso3) != 3:
                continue
            # The CLDR display name is the customary English short form
            # ("South Korea", "United Kingdom") and is redistributable. The
            # UNTERM and official_name columns are the formal names but are
            # restricted upstream, so they are deliberately not used.
            name = (row.get("CLDR display name") or "").strip() or iso3
            out[iso3] = {
                "iso2": (row.get("ISO3166-1-Alpha-2") or "").strip(),
                "name": name,
                "currency_code": (row.get("ISO4217-currency_alphabetic_code") or "").strip(),
                "currency_name": (row.get("ISO4217-currency_name") or "").strip(),
                "independent": (row.get("is_independent") or "").strip().lower() == "yes",
            }
        return out

    return _cache(f"country_meta.v{CACHE_VERSION}.json", _do)


def fetch_world_cpi() -> dict[str, dict[int, float]]:
    """ISO3 -> {year: index}. One bulk request covers every country."""

    def _do():
        raw = json.loads(_get(WB_CPI_URL))
        if not isinstance(raw, list) or len(raw) < 2 or not raw[1]:
            raise RuntimeError(f"unexpected World Bank response: {str(raw)[:200]}")
        out: dict[str, dict[str, float]] = {}
        for rec in raw[1]:
            iso3 = (rec.get("countryiso3code") or "").strip()
            value = rec.get("value")
            if not iso3 or value is None:
                continue
            out.setdefault(iso3, {})[rec["date"]] = float(value)
        return out

    cached = _cache(f"world_cpi.v{CACHE_VERSION}.json", _do)
    return {iso3: {int(y): v for y, v in years.items()} for iso3, years in cached.items()}


def build() -> dict:
    print("Fetching country and currency metadata ...", flush=True)
    meta = fetch_country_meta()
    print(f"  {len(meta)} territories")

    print("Fetching World Bank CPI index for all economies ...", flush=True)
    world = fetch_world_cpi()
    print(f"  {len(world)} economies with data")

    us_path = ROOT / "data" / "cpi.json"
    if not us_path.exists():
        raise SystemExit(
            "data/cpi.json is missing. Run tools/fetch_cpi.py first: the United "
            "States keeps its long official series rather than the World Bank one."
        )
    us = json.loads(us_path.read_text())
    us_annual = {int(y): v for y, v in us["annual"].items()}

    countries: dict[str, dict] = {}
    for iso3, series in world.items():
        info = meta.get(iso3)
        if not info:
            continue  # not a recognised territory
        if len(series) < 2:
            continue  # a single observation cannot support a conversion
        if not info["currency_code"]:
            # Without a currency code the money cannot be labelled, so the
            # country cannot be presented as a currency calculator.
            continue
        years = sorted(series)
        code = info["currency_code"]
        countries[iso3] = {
            "iso3": iso3,
            "iso2": info["iso2"],
            "name": info["name"],
            "short_name": DISPLAY_NAMES.get(iso3, info["name"]),
            "currency": {
                "code": code or "",
                "name": info["currency_name"] or code or "",
                "symbol": CURRENCY_SYMBOLS.get(code, code or ""),
            },
            "index_base": "2010 = 100",
            "first_year": years[0],
            "last_year": years[-1],
            "source": "World Bank",
            "source_detail": "Consumer price index (FP.CPI.TOTL), all items, annual average.",
            # Stored at full precision: several countries (Angola, Brazil, Peru)
            # ran hyperinflation, so early index values are as small as 1e-8 and
            # would be destroyed by rounding to a fixed number of decimals.
            "annual": {str(y): series[y] for y in years},
        }

    # The United States keeps its longer, official BLS-based series.
    us_info = meta.get("USA", {})
    countries["USA"] = {
        "iso3": "USA",
        "iso2": us_info.get("iso2", "US"),
        "name": "United States",
        "short_name": "United States",
        "currency": {
            "code": "USD",
            "name": us_info.get("currency_name") or "US Dollar",
            "symbol": "$",
        },
        "index_base": "1982-84 = 100",
        "first_year": min(us_annual),
        "last_year": max(us_annual),
        "source": "US Bureau of Labor Statistics",
        "source_detail": (
            "CPI-U, all items, US city average (1913+); Federal Reserve Bank of "
            "Minneapolis historical estimates rescaled to the modern base (pre-1913)."
        ),
        "annual": {str(y): us_annual[y] for y in sorted(us_annual)},
    }

    return {
        "meta": {
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "index_base": "2010 = 100 (World Bank); 1982-84 = 100 (United States)",
            "sources": [
                {
                    "name": "World Bank",
                    "series": "FP.CPI.TOTL",
                    "detail": "Consumer price index, all items, annual average, 2010 = 100",
                    "url": "https://data.worldbank.org/indicator/FP.CPI.TOTL",
                },
                {
                    "name": "datasets/country-codes",
                    "series": "ISO 3166 / ISO 4217",
                    "detail": "Country and currency code mapping",
                    "url": COUNTRY_CODES_URL,
                },
                {
                    "name": "Unicode CLDR",
                    "series": "cldr-localenames-full",
                    "detail": (
                        "Country display names. Redistributed under the Unicode "
                        "Licence v3; the copyright notice is in the README."
                    ),
                    "url": "https://github.com/unicode-org/cldr-json",
                },
                {
                    "name": "GeoNames",
                    "series": "countryInfo",
                    "detail": "Capital, continent, TLD and language columns, via country-codes",
                    "url": "https://www.geonames.org/",
                },
            ],
            "caveat": (
                "Coverage varies by country. Many series start around 1960. "
                "Each index is a national consumer price measure and baskets "
                "differ between countries, so cross-country comparisons are "
                "approximate. High-inflation countries may have redenominated "
                "their currency; the index ratio accounts for this because "
                "prices and currency were redenominated together."
            ),
        },
        "countries": dict(sorted(countries.items())),
    }


def validate(doc: dict) -> None:
    countries = doc["countries"]
    if "USA" not in countries:
        raise SystemExit("validation failed: USA missing")
    if len(countries) < 150:
        raise SystemExit(f"validation failed: only {len(countries)} countries, expected 150+")
    us = countries["USA"]
    if us["first_year"] != 1850:
        raise SystemExit(f"validation failed: US series starts {us['first_year']}, expected 1850")
    # Every country needs a usable span and positive values at full precision.
    for iso3, c in countries.items():
        if c["first_year"] >= c["last_year"]:
            raise SystemExit(f"validation failed: {iso3} has no span")
        bad = [y for y, v in c["annual"].items() if not (v > 0)]
        if bad:
            raise SystemExit(f"validation failed: {iso3} has non-positive values at {sorted(bad)[:3]}")
    missing_ccy = [i for i, c in countries.items() if not c["currency"]["code"]]
    print(
        f"validation passed: {len(countries)} countries, "
        f"{sum(1 for c in countries.values() if c['currency']['code'])} with currencies"
        + (f", {len(missing_ccy)} missing currency codes" if missing_ccy else "")
    )


def main() -> None:
    doc = build()
    validate(doc)
    OUT_PATH.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    size = OUT_PATH.stat().st_size
    print(f"wrote {OUT_PATH} ({len(doc['countries'])} countries, {size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
