#!/usr/bin/env python3
"""Fetch and merge US CPI annual averages from 1850 to the present.

Sources
-------
1850-1912  Federal Reserve Bank of Minneapolis, "Consumer Price Index, 1800-".
           Historical estimates (1967 = 100 base in the published table).
1913+      US Bureau of Labor Statistics, CPI-U (series CUUR0000SA0),
           annual averages, via the BLS public API v2.

The two series are joined at 1913. Because they use different index bases the
Minneapolis Fed figures are rescaled so that the 1913 value matches the official
BLS value exactly; the join is therefore continuous and produces no artificial
step in the inflation rate at the seam.

Run:  python3 tools/fetch_cpi.py [--offline]
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "data" / "cpi.json"
CACHE_DIR = ROOT / ".cache"

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_SERIES = "CUUR0000SA0"  # CPI-U, all items, US city average
MINFED_URL = (
    "https://www.minneapolisfed.org/about-us/monetary-policy/"
    "inflation-calculator/consumer-price-index-1800-"
)
UA = "Mozilla/5.0 (X11; Linux x86_64) inflation-calculator/1.0"

HISTORICAL_START = 1850
BLS_START = 1913

# Sanity anchors. If a refresh drifts from these the build fails loudly rather
# than silently shipping wrong numbers. Values are official BLS annual averages.
ANCHORS = {
    1913: 9.9,
    1929: 17.1,
    1945: 18.0,
    1967: 33.4,
    1980: 82.4,
    2000: 172.2,
    2020: 258.811,
}


def _get(url: str, data: bytes | None = None, timeout: int = 60) -> bytes:
    headers = {"User-Agent": UA}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _load_cache(name: str) -> dict:
    path = CACHE_DIR / name
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save_cache(name: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / name).write_text(json.dumps(data, indent=0) + "\n")


def fetch_bls(start: int, end: int) -> dict[int, float]:
    """Fetch BLS annual averages, caching per 10-year chunk.

    The public API caps requests at 10 years and rate-limits unregistered
    callers, so successful chunks are cached and reused when a request fails.
    """
    cache = {int(k): float(v) for k, v in _load_cache("bls_annual.json").items()}
    out: dict[int, float] = {}
    year = start
    while year <= end:
        chunk_end = min(year + 9, end)
        payload = json.dumps(
            {
                "seriesid": [BLS_SERIES],
                "startyear": str(year),
                "endyear": str(chunk_end),
                "annualaverage": True,
            }
        ).encode()
        try:
            raw = json.loads(_get(BLS_URL, payload))
            if raw.get("status") != "REQUEST_SUCCEEDED":
                raise RuntimeError(f"{raw.get('status')} {raw.get('message')}")
            for rec in raw["Results"]["series"][0]["data"]:
                if rec["period"] == "M13" and rec["value"] not in ("-", ""):
                    out[int(rec["year"])] = float(rec["value"])
        except Exception as exc:  # network or API limit: fall back to cache
            cached = {y: v for y, v in cache.items() if year <= y <= chunk_end}
            if not cached:
                raise RuntimeError(f"BLS {year}-{chunk_end} failed with no cache: {exc}") from exc
            print(f"  {year}-{chunk_end}: using cached values ({exc})", file=sys.stderr)
            out.update(cached)
        year = chunk_end + 1
    merged = dict(cache)
    merged.update(out)
    _save_cache("bls_annual.json", {str(k): v for k, v in merged.items()})
    return merged


def fetch_minneapolis_fed() -> dict[int, float]:
    """Scrape the Minneapolis Fed historical CPI table (1800-), with cache fallback."""
    try:
        page = _get(MINFED_URL).decode("utf-8", errors="replace")
    except Exception as exc:
        cache = {int(k): float(v) for k, v in _load_cache("minfed_annual.json").items()}
        if not cache:
            raise RuntimeError(f"Minneapolis Fed fetch failed with no cache: {exc}") from exc
        print(f"  using cached Minneapolis Fed values ({exc})", file=sys.stderr)
        return cache
    tables = re.findall(r"<table.*?</table>", page, re.S)
    if not tables:
        raise RuntimeError("Minneapolis Fed: no table found (page layout changed?)")
    out: dict[int, float] = {}
    for table in tables:
        for row in re.findall(r"<tr.*?</tr>", table, re.S):
            cells = [
                html_mod.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
            ]
            if len(cells) < 2 or not re.match(r"^\d{4}\*?$", cells[0]):
                continue
            year = int(cells[0].rstrip("*"))
            try:
                out[year] = float(cells[1].replace(",", ""))
            except ValueError:
                continue
    if not out:
        raise RuntimeError("Minneapolis Fed: table parsed but contained no rows")
    _save_cache("minfed_annual.json", {str(k): v for k, v in out.items()})
    return out


def build_series() -> dict:
    print("Fetching BLS CPI-U annual averages ...", flush=True)
    bls = fetch_bls(BLS_START, datetime.now(timezone.utc).year)
    print(f"  {len(bls)} years ({min(bls)}-{max(bls)})")

    print("Fetching Minneapolis Fed historical index ...", flush=True)
    hist_raw = fetch_minneapolis_fed()
    print(f"  {len(hist_raw)} years ({min(hist_raw)}-{max(hist_raw)})")

    if BLS_START not in bls or BLS_START not in hist_raw:
        raise RuntimeError("cannot splice: 1913 missing from one of the series")
    factor = bls[BLS_START] / hist_raw[BLS_START]

    series: dict[int, float] = {}
    for year in range(HISTORICAL_START, BLS_START):
        if year in hist_raw:
            series[year] = round(hist_raw[year] * factor, 4)
    series.update({y: v for y, v in bls.items() if y >= BLS_START})

    missing = [y for y in range(HISTORICAL_START, max(series) + 1) if y not in series]
    if missing:
        print(f"WARNING: no data for {missing[0]}..{missing[-1]} ({len(missing)} years)", file=sys.stderr)

    return {
        "meta": {
            "title": "US Consumer Price Index, annual averages, 1850-present",
            "index_base": "1982-84 = 100 (BLS CPI-U); earlier years rescaled to match",
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "splice_year": BLS_START,
            "sources": [
                {
                    "name": "US Bureau of Labor Statistics",
                    "series": BLS_SERIES,
                    "detail": "CPI-U, all items, US city average, annual average",
                    "url": "https://www.bls.gov/cpi/",
                    "coverage": f"{min(bls)}-{max(bls)}",
                },
                {
                    "name": "Federal Reserve Bank of Minneapolis",
                    "series": "Consumer Price Index, 1800-",
                    "detail": "Historical estimates, rescaled to the 1982-84=100 base",
                    "url": MINFED_URL,
                    "coverage": f"{HISTORICAL_START}-{BLS_START - 1}",
                },
            ],
            "caveat": (
                "Figures before 1913 are estimates reconstructed from historical "
                "price data and are materially less precise than the official "
                "CPI-U series. They are suitable for rough comparisons only."
            ),
        },
        "annual": {str(y): v for y, v in sorted(series.items())},
    }


def validate(doc: dict) -> None:
    annual = {int(k): v for k, v in doc["annual"].items()}
    errors = []
    for year, expected in ANCHORS.items():
        got = annual.get(year)
        if got is None:
            errors.append(f"{year}: missing (expected {expected})")
        elif abs(got - expected) > max(0.05, expected * 0.005):
            errors.append(f"{year}: got {got}, expected {expected}")
    if errors:
        raise SystemExit("validation failed:\n  " + "\n  ".join(errors))
    print(f"validation passed ({len(ANCHORS)} anchors, {len(annual)} years)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true", help="rebuild from .cache instead of the network")
    args = ap.parse_args()

    if args.offline:
        raise SystemExit("--offline is not supported yet; run online to refresh data/cpi.json")

    doc = build_series()
    validate(doc)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(doc, indent=1) + "\n")
    years = doc["annual"]
    print(f"wrote {OUT_PATH} ({len(years)} years, {min(years)}-{max(years)})")


if __name__ == "__main__":
    main()
