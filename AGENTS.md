# AGENTS.md

Repository guidance for agent sessions. Read this before making changes.

## What this project is

A self-contained US inflation calculator: historical dollar conversion from 1850 to
today, plus forward projection. Python standard library only, no build step, no
front-end dependencies.

## Commands

```bash
python3 -m inflation.server --port 12000      # run the app
python3 -m unittest discover -s tests -v      # test suite (must stay green)
python3 tools/fetch_cpi.py                    # refresh data/cpi.json
```

There is no packaging, linting, or CI configuration. Run the tests directly.

## Layout and responsibilities

| Path | Responsibility |
| --- | --- |
| `data/cpi.json` | The committed data artifact. Generated, but checked in so the app runs offline. |
| `inflation/data.py` | Loading the series, resolving an index for a year (including projection beyond observed data). |
| `inflation/calc.py` | All inflation arithmetic: convert, project, statistics. Pure functions. |
| `inflation/server.py` | HTTP layer only. Validates input, calls `calc`, serialises JSON. |
| `tools/fetch_cpi.py` | Fetch, splice, and validate the source data. |
| `web/` | Front end. `app.js` contains hand-rolled SVG charting. |
| `tests/` | Unit tests. |

## Conventions

- Keep the dependency surface at zero. If a task seems to need a library, prefer
  the standard library and ask before adding a dependency.
- `calc.py` holds logic; `server.py` holds transport. Do not put arithmetic in the
  server, and do not put HTTP concerns in `calc`.
- Calculation functions raise `ValueError` for bad input; the server converts that
  to HTTP 400. `BadRequest` is the server-level exception.
- Front-end assets are plain ES2020. No frameworks, no CDN links, so the app keeps
  working offline.

## Data integrity (important)

The accuracy of this tool is its whole point. When touching data or arithmetic:

- The series is a splice: BLS CPI-U for 1913+, Minneapolis Fed historical estimates
  for 1850-1912, rescaled so 1913 matches exactly. A test asserts there is no
  artificial step at the seam. Preserve that property.
- `tools/fetch_cpi.py` validates the merged series against known official anchor
  values and exits non-zero on drift. Keep the anchors when editing.
- Never silently substitute, interpolate, or smooth pre-1913 values. They are
  estimates and the code and UI must say so.
- The BLS public API rate-limits unregistered callers and caps requests at 10
  years. The fetcher caches per-chunk responses in `.cache/` and falls back to the
  cache on failure. Keep that behaviour.
- Projections compound from the last observed index value, never from a fitted
  trend line. The assumed rate is a user input and is documented as an assumption,
  not a forecast.

## Testing expectations

Tests use `unittest` and assert against known official CPI values rather than
against the code's own output. When changing arithmetic, update or add tests that
pin the result to an independently verifiable number. Run the full suite before
considering a change complete.
