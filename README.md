# Inflation Calculator

Convert money between any two years, look ahead at what inflation does to it, and
explore inflation history. Covers **190 countries**, with the United States reaching
back to 1850.

Built on official price index data: the US Bureau of Labor Statistics, the Federal
Reserve Bank of Minneapolis, and the World Bank.

No third-party dependencies. Python 3.9+ standard library only, and a
dependency-free front end, so it runs anywhere and works offline.

## Quick start

```bash
python3 -m inflation.server --port 12000
```

Then open <http://localhost:12000>. Add `?country=JPN` (or any ISO 3166 code) to
link straight to a country.

### Other commands

```bash
python3 -m unittest discover -s tests -v   # run the test suite
python3 tools/fetch_cpi.py                 # refresh the US series
python3 tools/fetch_world.py               # refresh every other country
```

### Hosting

The server reads `PORT` and `HOST` from the environment, so it deploys to any
platform that injects a port (Render, Railway, Fly, Heroku, a container) with no
changes. `--port` and `--host` still take precedence when passed explicitly.

```bash
PORT=8080 python3 -m inflation.server
```

`Procfile` and `render.yaml` are included. There is nothing to install: the app
is standard library only, so there is no build step and no dependency cache to
warm.

## What it does

| Mode | What it answers |
| --- | --- |
| **Convert** | "What is 100 of year A worth in year B?" |
| **Look ahead** | "What will it be worth in N years, at an assumed rate?" |
| **History** | Every annual inflation rate, plus deflation episodes |
| **Data** | Full series and source provenance |

Conversions work in both directions, so you can also ask what an earlier year's
money corresponds to. Pick the country from the selector in the header.

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

The assumed rate is a user-controlled input, not a forecast. The default is 2.5%,
and the interface offers each country's own historical average as a one-click
alternative.

## Data sources

| Coverage | Countries | Source |
| --- | --- | --- |
| 1850 – present | United States | BLS CPI-U (`CUUR0000SA0`) for 1913+, Minneapolis Fed historical estimates before that |
| 1960 – present (mostly) | 189 others | World Bank `FP.CPI.TOTL`, consumer price index, 2010 = 100 |

The United States keeps its own long series because the official BLS data is higher
quality and reaches 110 years further back than the World Bank's.

For the pre-1913 US years, the Minneapolis Fed table uses a different index base,
so its values are rescaled by the ratio of the two series' 1913 values. The join is
exact by construction and introduces no artificial step in the inflation rate at the
seam; a test asserts this.

Both pipelines validate against known official values and fail loudly on drift.
`tools/fetch_world.py` additionally checks that every country has a usable span, a
currency code, and strictly positive index values.

### Independent verification

The World Bank publishes a US series derived from the same BLS data. Its year-over-
year rates reproduce the official BLS rates exactly for the years checked
(2000: 3.36%, 2010: 1.64%, 2021: 4.70%, 2022: 8.00%), which is asserted in the test
suite. Spot checks against national statistics for the UK, Japan, and India also
agree.

### Accuracy caveats

- **Pre-1913 US figures are estimates.** Independent sources differ by roughly 1–7%
  for individual pre-1913 years. Treat them as close approximations, not precise
  measurements. They are marked with an asterisk in the data table.
- **Coverage varies by country.** Most series start around 1960; some start later.
  Each country's page states its own range, and asking for a year outside it is a
  clear error rather than a silent guess.
- **Cross-country comparisons are approximate.** Each index measures a different
  national basket of goods, so comparing "US inflation" to "Indian inflation" is
  comparing two different things measured two different ways.
- **Redenominations.** Several countries (Brazil, Peru, Angola) redenominated their
  currency during hyperinflation. Because prices and the currency were redenominated
  together, the index ratio still gives the correct real change, but the nominal
  number is expressed in today's units.
- **One index, one basket.** CPI measures an average urban consumer. Your own
  experience will differ, especially for housing, healthcare, and education, which
  have outrun headline indices almost everywhere.
- **Projections are assumptions.** Inflation is volatile and no single rate predicts
  it. Try a range of rates to see the spread.

## JSON API

All endpoints are `GET` and return JSON. Every endpoint accepts an optional
`country` parameter (ISO 3166 alpha-3 or alpha-2); it defaults to `USA`.

| Endpoint | Parameters | Returns |
| --- | --- | --- |
| `/api/countries` | – | Every country with its currency and coverage |
| `/api/meta` | `country` | Coverage, default rate, source provenance |
| `/api/series` | `country` | Full annual index |
| `/api/convert` | `country`, `amount`, `from_year`, `to_year`, `forward_rate` | Converted value, factor, total and annualized change |
| `/api/project` | `country`, `amount`, `base_year`, `end_year`, `forward_rate` | Year-by-year projected values |
| `/api/stats` | `country` | Summary statistics and full year-over-year series |

Examples:

```bash
curl "http://localhost:12000/api/convert?amount=100&from_year=1913&to_year=2025"
# {"result": 3251.95, "factor": 32.52, "total_change": 31.52, ...}

curl "http://localhost:12000/api/convert?country=GBR&amount=100&from_year=1970&to_year=2024"
# {"result": 1579.17, "factor": 15.79, ...}
```

Invalid input returns `400` with an `{"error": "..."}` body.

## Project layout

```
data/cpi.json          US series (1850+), built by fetch_cpi.py
data/countries.json    every country: index, currency, coverage
inflation/data.py      country registry, series loading, index resolution
inflation/calc.py      conversion, projection, statistics
inflation/server.py    HTTP server and JSON API
tools/fetch_cpi.py     fetches and splices the US series
tools/fetch_world.py   fetches every other country plus currency metadata
web/                   front end (HTML, CSS, hand-rolled SVG charts)
tests/                 unit tests
```

Both data files are committed so the app works without network access. Re-run the
fetch tools to refresh them; responses are cached in `.cache/`.

## Licence and disclaimer

The code is released under the MIT License (see `LICENSE`).

The bundled data is not covered by that licence. It is redistributed under the
terms of its sources:

| Source | Terms |
| --- | --- |
| US Bureau of Labor Statistics (CPI-U) | US government work, public domain |
| Federal Reserve Bank of Minneapolis | Publicly published historical estimates |
| World Bank (CPI, `FP.CPI.TOTL`) | [CC BY 4.0](https://datacatalog.worldbank.org/public-licenses) — attribution required |
| Unicode CLDR (country display names) | [Unicode License v3](https://www.unicode.org/license.txt) — notice required |
| GeoNames (capital, continent, TLD, languages) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — credit required |
| `datasets/country-codes` | [ODC-PDDL-1.0](https://opendatacommons.org/licenses/pddl/1.0/) for the maintainers' own work |

The World Bank requires attribution, which the app displays in its footer and
in the Data panel, and which is recorded in `data/countries.json` under
`meta.sources`. If you redistribute the data, keep those attributions.

Two deliberate exclusions, because the upstream licence does not permit
shipping them:

- The UNTERM name columns in `datasets/country-codes` are **restricted**. The
  UN terms of use allow personal, non-commercial use only, with no right to
  redistribute or create derivative works, and the upstream project says so
  explicitly. Country names therefore come from the Unicode CLDR instead,
  which is redistributable. This is also why the names read "United Kingdom"
  rather than "United Kingdom of Great Britain and Northern Ireland".
- ISO's rights in the country and currency *codes* are unclear. The codes are
  used as published and are not modified or relicensed.

Notice for the Unicode CLDR data:

```
Copyright © 1991-2026 Unicode, Inc. All rights reserved.
Distributed under the Terms of Use in https://www.unicode.org/copyright.html

Permission is hereby granted, free of charge, to any person obtaining a copy
of the Unicode data files and any associated documentation (the "Data Files")
or Unicode software and any associated documentation (the "Software") to deal
in the Data Files or Software without restriction, including without
limitation the rights to use, copy, modify, merge, publish, distribute, and/or
sell copies of the Data Files or Software, and to permit persons to whom the
Data Files or Software are furnished to do so, provided that either (a) this
copyright and permission notice appear with all copies of the Data Files or
Software, or (b) this copyright and permission notice appear in associated
Documentation.
```

Not endorsed by or affiliated with the United Nations, ISO, SIX Group, the
World Bank, the Bureau of Labor Statistics, GeoNames, or Unicode, Inc.

This tool is for information only and is not financial advice.
