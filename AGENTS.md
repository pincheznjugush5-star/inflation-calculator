# AGENTS.md

Repository guidance for agent sessions. Read this before making changes.

## What this project is

A self-contained inflation calculator covering 190 countries: historical currency
conversion from 1850 (United States) or 1960 (most others), plus forward projection.
Python standard library only, no build step, no front-end dependencies.

## Commands

```bash
python3 -m inflation.server --port 12000      # run the app
python3 -m unittest discover -s tests -v      # test suite (must stay green)
python3 tools/refresh.py                      # refresh all data and verify
python3 tools/refresh.py --check              # report freshness only, no writes
python3 tools/fetch_cpi.py                    # refresh the US series alone
python3 tools/fetch_world.py                  # refresh all other countries alone
```

GitHub Actions runs the suite on every push and pull request
(`.github/workflows/ci.yml`) and refreshes the data weekly
(`.github/workflows/refresh-data.yml`). The refresh job commits only when the
data actually changed.

## Layout and responsibilities

| Path | Responsibility |
| --- | --- |
| `data/cpi.json` | US series (1850+). Generated, but checked in so the app runs offline. |
| `data/countries.json` | Every country: index values, currency, coverage. Generated and checked in. |
| `inflation/data.py` | Country registry, series loading, resolving an index for a year (including projection beyond observed data). |
| `inflation/calc.py` | All inflation arithmetic: convert, project, statistics. Pure functions. |
| `inflation/server.py` | HTTP layer only. Validates input, resolves the country, calls `calc`, serialises JSON. |
| `tools/fetch_cpi.py` | Fetch, splice, and validate the US series. |
| `tools/fetch_world.py` | Fetch every other country's index plus currency metadata. |
| `tools/refresh.py` | Orchestrate both fetchers, run the tests, report freshness. |
| `web/` | Front end. `app.js` contains hand-rolled SVG charting. |
| `tests/` | Unit tests. |

## Conventions

- Keep the dependency surface at zero. If a task seems to need a library, prefer
  the standard library and ask before adding a dependency.
- `calc.py` holds logic; `server.py` holds transport. Do not put arithmetic in the
  server, and do not put HTTP concerns in `calc`.
- Every API endpoint takes an optional `country` parameter and defaults to `USA`.
  Keep that default so existing links and callers keep working.
- Calculation functions raise `ValueError` for bad input; the server converts that
  to HTTP 400. `BadRequest` is the server-level exception.
- Front-end assets are plain ES2020. No frameworks, no CDN links, so the app keeps
  working offline.

## Data integrity (important)

The accuracy of this tool is its whole point. When touching data or arithmetic:

- Two sources feed the US series: BLS CPI-U for 1913+, Minneapolis Fed historical
  estimates for 1850-1912, rescaled so 1913 matches exactly. A test asserts there is
  no artificial step at the seam. Preserve that property.
- Every other country uses the World Bank index (`FP.CPI.TOTL`, 2010 = 100). The
  United States deliberately keeps the BLS series because it is longer and better.
- **Never round index values to a fixed number of decimals.** Several countries ran
  hyperinflation and their early index values are as small as 1e-8 (Brazil 1980 is
  3.6e-10). Rounding flattened them to zero and broke those countries. Store full
  precision. A test guards this.
- Never silently substitute, interpolate, or smooth pre-1913 US values. They are
  estimates and the code and UI must say so.
- The BLS public API rate-limits unregistered callers and caps requests at 10 years.
  The fetcher caches per-chunk responses in `.cache/` and falls back to the cache on
  failure. Keep that behaviour.
- Projections compound from the last observed index value, never from a fitted
  trend line. The assumed rate is a user input and is documented as an assumption,
  not a forecast.
- Coverage differs per country. Asking for a year outside a country's range must be
  a clear error, never a silent extrapolation.

## Data licensing (important)

The bundled data is redistributed, so its licence terms constrain the code rather
than being an afterthought. See the README for the full notices.

- Country and currency **names** come from the Unicode CLDR. Do not reintroduce
  the `UNTERM ...` or `official_name_en` columns from `datasets/country-codes`:
  the upstream project marks them restricted, because the UN terms of use allow
  no redistribution or derivative works. A test guards the shipped names against
  the tell-tale markers of those columns ("(the)", trailing "*", "Special
  Administrative Region").
- The World Bank (CC BY 4.0) and the Unicode CLDR (Unicode Licence v3) both
  require attribution. Keep their entries in `data/countries.json` under
  `meta.sources` and in the README.
- `_cache` in `tools/fetch_world.py` stores *parsed* output, not raw responses.
  Bump `CACHE_VERSION` whenever the parsing changes shape, or a stale entry will
  be served as though it reflected the new logic.

## Testing expectations

Tests use `unittest` and assert against known official figures rather than against
the code's own output. When changing arithmetic, update or add tests that pin the
result to an independently verifiable number. Run the full suite before considering
a change complete.

