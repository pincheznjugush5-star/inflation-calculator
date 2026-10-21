#!/usr/bin/env python3
"""HTTP server for the inflation calculator.

Serves the single-page UI from web/ and a small JSON API under /api/.
Uses only the Python standard library so it runs anywhere.

    python3 -m inflation.server --port 12000
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .calc import (
    average_inflation,
    convert,
    project,
    purchasing_power,
    stats,
    year_over_year,
)
from .data import DEFAULT_FORWARD_RATE, current_year, load_series

WEB_DIR = Path(__file__).resolve().parents[1] / "web"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class BadRequest(Exception):
    pass


def _int(params: dict, key: str, default: int | None = None) -> int:
    if key not in params:
        if default is None:
            raise BadRequest(f"missing required parameter: {key}")
        return default
    try:
        return int(params[key])
    except (TypeError, ValueError):
        raise BadRequest(f"parameter {key} must be an integer") from None


def _float(params: dict, key: str, default: float) -> float:
    if key not in params:
        return default
    try:
        return float(params[key])
    except (TypeError, ValueError):
        raise BadRequest(f"parameter {key} must be a number") from None


def api_meta(series, params: dict) -> dict:
    return {
        "first_year": series.first_year,
        "last_year": series.last_year,
        "current_year": current_year(),
        "default_forward_rate": DEFAULT_FORWARD_RATE,
        "meta": series.meta,
    }


def api_series(series, params: dict) -> dict:
    return {
        "annual": {str(y): v for y, v in sorted(series.annual.items())},
        "first_year": series.first_year,
        "last_year": series.last_year,
    }


def api_convert(series, params: dict) -> dict:
    amount = _float(params, "amount", 1.0)
    from_year = _int(params, "from_year")
    to_year = _int(params, "to_year", current_year())
    forward_rate = _float(params, "forward_rate", DEFAULT_FORWARD_RATE)
    _check_years(series, from_year, to_year)
    result = convert(series, amount, from_year, to_year, forward_rate)
    return {
        "amount": result.amount,
        "from_year": result.from_year,
        "to_year": result.to_year,
        "from_index": result.from_index,
        "to_index": result.to_index,
        "result": result.result,
        "factor": result.factor,
        "total_change": result.total_change,
        "annualized": result.annualized,
        "years": result.years,
        "projected": result.projected,
    }


def api_project(series, params: dict) -> dict:
    amount = _float(params, "amount", 1.0)
    base_year = _int(params, "base_year", current_year())
    end_year = _int(params, "end_year", current_year() + 10)
    forward_rate = _float(params, "forward_rate", DEFAULT_FORWARD_RATE)
    if end_year < base_year:
        raise BadRequest("end_year must not be before base_year")
    if end_year - base_year > 200:
        raise BadRequest("projection window is limited to 200 years")
    _check_years(series, base_year, end_year)
    points = project(series, amount, base_year, end_year, forward_rate)
    return {
        "base_year": base_year,
        "end_year": end_year,
        "forward_rate": forward_rate,
        "points": [
            {"year": p.year, "value": p.value, "index": p.index, "observed": p.observed}
            for p in points
        ],
    }


def api_stats(series, params: dict) -> dict:
    result = stats(series)
    result["year_over_year"] = [{"year": y, "rate": r} for y, r in year_over_year(series)]
    return result


def _check_years(series, from_year: int, to_year: int) -> None:
    for label, year in (("from_year", from_year), ("to_year", to_year)):
        if year < series.first_year:
            raise BadRequest(f"{label} {year} is before the earliest data ({series.first_year})")
        if year > 2200:
            raise BadRequest(f"{label} {year} is unrealistically far in the future")


ROUTES = {
    "/api/meta": api_meta,
    "/api/series": api_series,
    "/api/convert": api_convert,
    "/api/project": api_project,
    "/api/stats": api_stats,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "InflationCalculator/1.0"

    def log_message(self, fmt, *args):  # keep the console readable
        if self.path.startswith("/api/"):
            super().log_message(fmt, *args)

    def do_GET(self):  # noqa: N802 (stdlib naming)
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            if parsed.path in ROUTES:
                payload = ROUTES[parsed.path](load_series(), params)
                self._send_json(200, payload)
            elif parsed.path == "/":
                self._send_file(WEB_DIR / "index.html")
            elif parsed.path.startswith("/api/"):
                self._send_json(404, {"error": f"unknown endpoint {parsed.path}"})
            else:
                self._send_static(parsed.path)
        except BadRequest as exc:
            self._send_json(400, {"error": str(exc)})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except BrokenPipeError:
            pass
        except Exception as exc:  # pragma: no cover - defensive
            self._send_json(500, {"error": f"internal error: {exc}"})

    def _send_static(self, path: str) -> None:
        rel = path.lstrip("/")
        candidate = (WEB_DIR / rel).resolve()
        if WEB_DIR not in candidate.parents and candidate != WEB_DIR:
            self._send_json(403, {"error": "forbidden"})
            return
        if not candidate.is_file():
            self._send_json(404, {"error": "not found"})
            return
        self._send_file(candidate)

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self._send_json(404, {"error": "not found"})
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=12000)
    args = ap.parse_args()
    load_series()  # fail fast if data is missing
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Inflation calculator on http://{args.host}:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        httpd.shutdown()


if __name__ == "__main__":
    main()
