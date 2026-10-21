#!/usr/bin/env python3
"""Refresh the shipped CPI data and verify the result.

Runs both fetchers, compares the rebuilt data against what was committed,
runs the test suite, and reports what moved. The app ships its data as
committed JSON, so without this it silently drifts out of date as new annual
figures are published and as the BLS and World Bank revise history.

    python3 tools/refresh.py              # fetch, compare, test
    python3 tools/refresh.py --check      # fail if data is stale, change nothing

Exit status is non-zero if a fetch fails, a validation anchor drifts, the
tests fail, or (with --check) a refresh is overdue. That makes it safe to run
from a schedule: silence means the data is current and correct.

Output is written so a caller can tell whether anything actually changed, by
looking for the CHANGED / UNCHANGED marker on stdout.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = ("data/cpi.json", "data/countries.json")


def run(label: str, argv: list[str]) -> None:
    print(f"\n=== {label} ===", flush=True)
    result = subprocess.run(argv, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"{label} failed (exit {result.returncode})")


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text())


def compare_years(before: dict, after: dict) -> list[str]:
    """Year-level differences in a country's annual index."""
    a, b = before.get("annual", {}), after.get("annual", {})
    notes = []
    added = sorted(set(b) - set(a), key=int)
    removed = sorted(set(a) - set(b), key=int)
    if added:
        notes.append(f"new years: {', '.join(added)}")
    if removed:
        notes.append(f"dropped years: {', '.join(removed)}")
    revised = [y for y in sorted(set(a) & set(b), key=int) if a[y] != b[y]]
    if revised:
        shown = ", ".join(revised[:8]) + (" ..." if len(revised) > 8 else "")
        notes.append(f"{len(revised)} revised values ({shown})")
    return notes


def report_changes(before: dict, after: dict) -> bool:
    """Print what changed. Returns True if anything did."""
    changed = False

    # United States: the long series, year by year.
    us_before = before.get("cpi", {})
    us_after = after.get("cpi", {})
    notes = compare_years(us_before, us_after)
    if notes:
        changed = True
        print("\nUnited States (BLS + Minneapolis Fed):")
        for note in notes:
            print(f"  - {note}")

    # Every other country: coverage and currency only, plus a value spot check.
    cb = before.get("countries", {}).get("countries", {})
    ca = after.get("countries", {}).get("countries", {})
    added = sorted(set(ca) - set(cb))
    removed = sorted(set(cb) - set(ca))
    if added:
        changed = True
        print(f"\nNew countries: {', '.join(added)}")
    if removed:
        changed = True
        print(f"\nCountries no longer published: {', '.join(removed)}")

    extended, revised = [], []
    for iso3 in sorted(set(cb) & set(ca)):
        b, a = cb[iso3], ca[iso3]
        if a["last_year"] > b["last_year"]:
            extended.append(f"{iso3} -> {a['last_year']}")
        if b.get("currency", {}).get("code") != a.get("currency", {}).get("code"):
            revised.append(f"{iso3} currency {b['currency']['code']} -> {a['currency']['code']}")
    if extended:
        changed = True
        print(f"\nCountries extended to a newer year ({len(extended)}):")
        for item in extended[:15]:
            print(f"  - {item}")
        if len(extended) > 15:
            print(f"  ... and {len(extended) - 15} more")
    if revised:
        changed = True
        print(f"\nCurrency changes: {', '.join(revised)}")

    # Any change to the newest year across all countries.
    def newest(doc: dict) -> int:
        return max(c["last_year"] for c in doc.get("countries", {}).get("countries", {}).values())

    if cb and ca and newest(after["countries"]) != newest(before["countries"]):
        print(f"\nNewest data year: {newest(before['countries'])} -> {newest(after['countries'])}")

    return changed


def freshness_of(doc: dict) -> dict:
    """The freshness block the app itself would report for this document."""
    sys.path.insert(0, str(ROOT))
    from inflation.data import expected_data_year  # local import: needs ROOT on path

    newest = max(c["last_year"] for c in doc["countries"].values())
    expected = expected_data_year()
    return {
        "newest_year": newest,
        "expected_year": expected,
        "lag_years": max(0, expected - newest),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="do not fetch; just fail if the committed data is stale",
    )
    args = ap.parse_args()

    if args.check:
        doc = load("data/countries.json")
        state = freshness_of(doc)
        if state["lag_years"]:
            raise SystemExit(
                f"stale: newest data year is {state['newest_year']} but "
                f"{state['expected_year']} should be available. Run tools/refresh.py."
            )
        print(
            f"fresh: newest data year is {state['newest_year']}, "
            f"expected {state['expected_year']}"
        )
        return

    before = {name: load(name) for name in DATA_FILES if (ROOT / name).exists()}

    run("Fetching US series", [sys.executable, "tools/fetch_cpi.py"])
    run("Fetching world series", [sys.executable, "tools/fetch_world.py"])

    after = {name: load(name) for name in DATA_FILES}

    print("\n=== Changes vs committed data ===")
    changed = report_changes(before, after)
    print("\nCHANGED" if changed else "\nUNCHANGED")

    # The suite includes a test that the shipped data is not stale, so this
    # also fails if the fetch succeeded but did not actually bring us current.
    run("Test suite", [sys.executable, "-m", "unittest", "discover", "-s", "tests"])

    state = freshness_of(after["data/countries.json"])
    print(
        f"\nData current through {state['newest_year']} "
        f"(expected {state['expected_year']}, lag {state['lag_years']})"
    )
    if state["lag_years"]:
        raise SystemExit(
            f"refreshed but still stale: the upstream sources have not yet "
            f"published {state['expected_year']}"
        )
    print("refresh complete")


if __name__ == "__main__":
    main()
