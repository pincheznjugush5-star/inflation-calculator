# US Inflation Calculator

Convert US dollars between any two years from **1850 to today**, and look forward
to see what inflation does to your money. Built on official Consumer Price Index
data from the Bureau of Labor Statistics and the Federal Reserve Bank of Minneapolis.

No third-party dependencies. Python 3.9+ standard library only, and a
dependency-free front end, so it runs anywhere and works offline.

## Quick start

```bash
python3 -m inflation.server --port 12000
```

Then open <http://localhost:12000>.

### Other commands

```bash
python3 -m unittest discover -s tests -v   # run the test suite
python3 tools/fetch_cpi.py                 # refresh data/cpi.json from source
```

## What it does

| Mode | What it answers |
| --- | --- |
| **Convert** | "What is $X of year A worth in year B?" |
| **Look ahead** | "What will $X be worth in N years, at an assumed rate?" |
| **History** | Every annual inflation rate since 1850, plus deflation episodes |
| **Data** | Full series and source provenance |

Conversions work in both directions, so you can also ask what an earlier year's
money a modern amount corresponds to.

## How the maths works

Conversion uses the ratio-of-indexes method published by the BLS:

```
value_in_year_2 = amount_in_year_1 × (index[year_2] / index[year_1])
```

The compound annual rate over a span is the geometric mean:

```
annual_rate = (index[year_2] / index[year_1]) ** (1 / years) - 1
```

Future years compound the assumed rate annually, starting from the **last measured
index value** rather than from a trend line fitted to history:

```
index[future] = index[last_observed] × (1 + assumed_rate) ** (future - last_observed)
```

The assumed rate is a user-controlled input, not a forecast. The default is 2.5%.

## Data sources

The series is a splice of two sources, joined at 1913.

| Coverage | Source | Notes |
| --- | --- | --- |
| 1913 – present | US Bureau of Labor Statistics, CPI-U (series `CUUR0000SA0`) | Official annual averages, via the BLS public API |
| 1850 – 1912 | Federal Reserve Bank of Minneapolis, *Consumer Price Index, 1800-* | Historical estimates, rescaled to the modern index base |

The Minneapolis Fed table uses a different index base, so its values are rescaled
by the ratio of the two series' 1913 values. The join is therefore exact by
construction and introduces no artificial step in the inflation rate at the seam.
This is verified by a test.

Every build re-checks the merged series against known official values (1913, 1929,
1945, 1967, 1980, 2000, 2020) and fails loudly on any drift.

### Accuracy caveats

- **Pre-1913 figures are estimates.** They are reconstructed from historical price
  data and are materially less precise than the official CPI-U. Independent
  sources differ by roughly 1–7% for individual pre-1913 years. Treat them as
  close approximations suitable for rough comparisons, not precise measurements.
- **Annual averages only.** This does not do month-by-month or
  inflation-adjusted-in-real-time calculations.
- **One index, one basket.** CPI-U measures an urban consumer's basket. Your own
  experience will differ, especially for housing, healthcare, and education, which
  have outrun the headline index.
- **Projections are assumptions.** Inflation is volatile and no single rate
  predicts it. Try a range of rates to see the spread.

## JSON API

All endpoints are `GET` and return JSON.

| Endpoint | Parameters | Returns |
| --- | --- | --- |
| `/api/meta` | – | Coverage, default rate, source provenance |
| `/api/series` | – | Full annual index |
| `/api/convert` | `amount`, `from_year`, `to_year`, `forward_rate` | Converted value, factor, total and annualized change |
| `/api/project` | `amount`, `base_year`, `end_year`, `forward_rate` | Year-by-year projected values |
| `/api/stats` | – | Summary statistics and full year-over-year series |

Example:

```bash
curl "http://localhost:12000/api/convert?amount=100&from_year=1913&to_year=2025"
# {"result": 3251.94, "factor": 32.52, "total_change": 31.52, "annualized": 0.0316, ...}
```

Invalid input returns `400` with an `{"error": "..."}` body.

## Project layout

```
data/cpi.json          merged annual index + provenance metadata
inflation/data.py      series loading and index resolution (incl. projection)
inflation/calc.py      conversion, projection, statistics
inflation/server.py    HTTP server and JSON API
tools/fetch_cpi.py     fetches, splices, and validates the data
web/                   front end (HTML, CSS, hand-rolled SVG charts)
tests/                 unit tests
```

`data/cpi.json` is committed so the app works without network access. Re-run
`tools/fetch_cpi.py` to refresh it; results are cached in `.cache/` so a refresh
survives API rate limits.

## Licence and disclaimer

Data is public domain or publicly published by the respective agencies. This tool
is for information only and is not financial advice.
