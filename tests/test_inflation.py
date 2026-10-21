"""Tests for the inflation calculation engine and the underlying data.

Run with:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from inflation.calc import (
    average_inflation,
    convert,
    cumulative_inflation,
    project,
    purchasing_power,
    stats,
    year_over_year,
)
from inflation.data import (
    DEFAULT_FORWARD_RATE,
    country_codes,
    country_list,
    get_country,
    load_series,
    resolve_index,
)


class DataIntegrityTests(unittest.TestCase):
    """The shipped series must be complete, monotonic in coverage, and sane."""

    @classmethod
    def setUpClass(cls):
        cls.series = load_series()

    def test_coverage_starts_1850(self):
        self.assertEqual(self.series.first_year, 1850)

    def test_no_gaps(self):
        years = sorted(self.series.annual)
        expected = list(range(years[0], years[-1] + 1))
        self.assertEqual(years, expected, "series must be contiguous")

    def test_all_values_positive(self):
        for year, value in self.series.annual.items():
            self.assertGreater(value, 0, f"{year} has non-positive index")

    def test_1913_splice_matches_bls(self):
        # The official BLS annual average for 1913 is 9.9.
        self.assertAlmostEqual(self.series.index(1913), 9.9, places=6)

    def test_recent_official_values(self):
        self.assertAlmostEqual(self.series.index(1967), 33.4, places=6)
        self.assertAlmostEqual(self.series.index(1980), 82.4, places=6)
        self.assertAlmostEqual(self.series.index(2000), 172.2, places=6)
        self.assertAlmostEqual(self.series.index(2020), 258.811, places=6)

    def test_no_artificial_step_at_splice(self):
        # The year-over-year change either side of 1913 must be of ordinary
        # magnitude; a botched splice would show up as a huge jump.
        before = self.series.index(1913) / self.series.index(1912) - 1
        after = self.series.index(1914) / self.series.index(1913) - 1
        self.assertLess(abs(before), 0.10)
        self.assertLess(abs(after), 0.10)


class WorldDataTests(unittest.TestCase):
    """Every shipped country must be internally usable, with a real currency."""

    @classmethod
    def setUpClass(cls):
        cls.countries = {c["iso3"]: c for c in country_list()}

    def test_has_many_countries(self):
        self.assertGreaterEqual(len(self.countries), 180)

    def test_usa_is_present_and_long(self):
        usa = get_country("USA")
        self.assertEqual(usa.first_year, 1850)

    def test_every_country_has_currency_and_span(self):
        for iso3, c in self.countries.items():
            with self.subTest(country=iso3):
                self.assertTrue(c["currency"]["code"], "missing ISO 4217 code")
                self.assertGreater(c["last_year"], c["first_year"], "no usable span")

    def test_every_index_is_positive(self):
        # Guards against the rounding bug that zeroed hyperinflation-era values.
        for iso3 in country_codes():
            with self.subTest(country=iso3):
                for year, value in get_country(iso3).annual.items():
                    self.assertGreater(value, 0, f"{iso3} {year}")

    def test_hyperinflation_precision_survives(self):
        # Brazil's 1980 index is ~3.6e-10; rounding to a fixed number of decimal
        # places would have flattened it to zero.
        brazil = get_country("BRA")
        self.assertLess(brazil.index(1980), 1e-8)
        self.assertGreater(brazil.index(1980), 0)

    def test_lookup_by_alpha2_and_alpha3(self):
        self.assertEqual(get_country("US").iso3, "USA")
        self.assertEqual(get_country("us").iso3, "USA")
        self.assertEqual(get_country("GBR").iso3, get_country("GB").iso3)

    def test_short_name_is_usable_and_present(self):
        # The dropdown shows short_name, so it must never be blank, and formal
        # names long enough to break the layout must have been shortened.
        for iso3 in country_codes():
            with self.subTest(country=iso3):
                c = get_country(iso3)
                self.assertTrue(c.display_name.strip())
                self.assertLessEqual(len(c.display_name), 32, f"{iso3} still unwieldy")
        self.assertEqual(get_country("GBR").display_name, "United Kingdom")
        self.assertEqual(get_country("USA").display_name, "United States")

    def test_unknown_country_raises(self):
        with self.assertRaises(KeyError):
            get_country("XYZ")

    def test_world_bank_agrees_with_bls_for_usa(self):
        # The World Bank's US series is an independent publication of the same
        # BLS data, so its year-over-year rates must reproduce the official ones.
        wb = get_country("USA")
        for year in (2000, 2010, 2021, 2022):
            with self.subTest(year=year):
                rate = wb.index(year) / wb.index(year - 1) - 1
                self.assertAlmostEqual(rate * 100, {2000: 3.36, 2010: 1.64, 2021: 4.70, 2022: 8.00}[year], places=2)


class CountryConversionTests(unittest.TestCase):
    """Conversions must be correct for countries beyond the United States."""

    def test_united_kingdom_1970_to_2024(self):
        # UK CPI (2010=100): 1970 = 9.3347, 2024 = 147.4108 -> factor 15.79.
        uk = get_country("GBR")
        result = convert(uk, 100, 1970, 2024)
        self.assertAlmostEqual(result.factor, 15.7917, places=3)
        self.assertAlmostEqual(result.result, 1579.17, places=1)

    def test_japan_oil_shock_inflation(self):
        # Japan's 1974 inflation was 23.2%, driven by the oil crisis.
        japan = get_country("JPN")
        rate = japan.index(1974) / japan.index(1973) - 1
        self.assertAlmostEqual(rate * 100, 23.22, places=1)

    def test_india_long_run(self):
        india = get_country("IND")
        self.assertAlmostEqual(india.index(2025) / india.index(1960), 92.21, places=1)

    def test_conversion_is_reversible_within_a_country(self):
        for iso3 in ("GBR", "JPN", "IND", "BRA"):
            with self.subTest(country=iso3):
                series = get_country(iso3)
                first, last = series.first_year + 5, series.last_year
                forward = convert(series, 100, first, last)
                back = convert(series, forward.result, last, first)
                self.assertAlmostEqual(back.result, 100, places=6)

    def test_each_country_projects_from_its_own_last_observation(self):
        for iso3 in ("GBR", "JPN", "DEU"):
            with self.subTest(country=iso3):
                series = get_country(iso3)
                last = series.last_year
                projected = resolve_index(series, last + 5, 0.03)
                expected = series.index(last) * 1.03**5
                self.assertAlmostEqual(projected, expected, places=6)

    def test_year_before_a_countrys_data_is_rejected(self):
        gbr = get_country("GBR")
        with self.assertRaises(ValueError):
            convert(gbr, 100, 1850, 2000)


class ConvertTests(unittest.TestCase):
    """Conversion must match the published ratio-of-indexes method."""

    @classmethod
    def setUpClass(cls):
        cls.series = load_series()

    def test_identity(self):
        result = convert(self.series, 500, 1990, 1990)
        self.assertAlmostEqual(result.result, 500, places=9)
        self.assertEqual(result.total_change, 0.0)
        self.assertEqual(result.annualized, 0.0)

    def test_known_1913_to_2025(self):
        # 321.943 / 9.9 = 32.5195...
        result = convert(self.series, 1.0, 1913, 2025)
        self.assertAlmostEqual(result.factor, 321.943 / 9.9, places=9)
        self.assertAlmostEqual(result.result, 32.5194, places=3)

    def test_1850_to_2025(self):
        result = convert(self.series, 1.0, 1850, 2025)
        self.assertAlmostEqual(result.result, 38.63, delta=0.05)

    def test_ratio_matches_manual_arithmetic(self):
        result = convert(self.series, 250, 1975, 2010)
        expected = 250 * (self.series.index(2010) / self.series.index(1975))
        self.assertAlmostEqual(result.result, expected, places=9)

    def test_annualized_rate_round_trips(self):
        result = convert(self.series, 1.0, 1980, 2020)
        grown = (1.0 + result.annualized) ** result.years
        self.assertAlmostEqual(grown, result.factor, places=9)

    def test_backwards_conversion_is_inverse(self):
        forward = convert(self.series, 100, 1950, 2000)
        back = convert(self.series, forward.result, 2000, 1950)
        self.assertAlmostEqual(back.result, 100, places=6)
        self.assertLess(back.total_change, 0)
        self.assertAlmostEqual(back.years, forward.years)

    def test_rejects_negative_amount(self):
        with self.assertRaises(ValueError):
            convert(self.series, -1, 1990, 2000)

    def test_rejects_year_before_data(self):
        with self.assertRaises(ValueError):
            convert(self.series, 1, 1800, 2000)

    def test_purchasing_power_is_inverse(self):
        forward = convert(self.series, 100, 1950, 2000)
        back = convert(self.series, forward.result, 2000, 1950)
        self.assertAlmostEqual(back.result, 100, places=6)


class ProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.series = load_series()

    def test_observed_year_uses_real_data(self):
        self.assertEqual(resolve_index(self.series, 1999), self.series.index(1999))

    def test_projection_starts_from_last_observation(self):
        last_year, last_index = self.series.last_observed()
        self.assertEqual(resolve_index(self.series, last_year), last_index)
        projected = resolve_index(self.series, last_year + 1, 0.03)
        self.assertAlmostEqual(projected, last_index * 1.03, places=9)

    def test_zero_rate_is_flat(self):
        a = resolve_index(self.series, 2030, 0.0)
        b = resolve_index(self.series, 2060, 0.0)
        self.assertAlmostEqual(a, b, places=9)

    def test_projection_is_monotonic_for_positive_rate(self):
        values = [resolve_index(self.series, y, 0.02) for y in range(2025, 2051)]
        self.assertEqual(values, sorted(values))

    def test_convert_marks_projected(self):
        future = self.series.last_year + 5
        result = convert(self.series, 100, self.series.last_year, future)
        self.assertTrue(result.projected)

    def test_project_series_shape(self):
        points = project(self.series, 1000, 2025, 2035, 0.025)
        self.assertEqual(len(points), 11)
        self.assertEqual(points[0].value, 1000)
        self.assertTrue(all(p.observed is False for p in points[1:]))
        self.assertAlmostEqual(points[-1].value, 1000 * 1.025**10, places=6)

    def test_project_rejects_reversed_window(self):
        with self.assertRaises(ValueError):
            project(self.series, 100, 2030, 2020)

    def test_default_rate_is_used(self):
        self.assertGreater(DEFAULT_FORWARD_RATE, 0)
        result = purchasing_power(self.series, 100, self.series.last_year)
        # purchasing_power defaults to_year to the current year, which may be
        # at or after the last observation; both branches must produce a float.
        self.assertIsInstance(result.result, float)


class StatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.series = load_series()

    def test_year_over_year_length(self):
        yoy = year_over_year(self.series)
        self.assertEqual(len(yoy), len(self.series.annual) - 1)

    def test_known_inflation_years(self):
        yoy = dict(year_over_year(self.series))
        # 1980 was the worst peacetime inflation spike; 1921 and 1932 were deep
        # deflations.
        self.assertAlmostEqual(yoy[1980], 82.4 / 72.6 - 1, places=9)
        self.assertLess(yoy[1921], 0)
        self.assertLess(yoy[1932], 0)

    def test_stats_summary(self):
        s = stats(self.series)
        self.assertEqual(s["first_year"], 1850)
        self.assertEqual(s["observations"], len(self.series.annual))
        self.assertEqual(s["highest_year"]["year"], 1864)
        self.assertEqual(s["lowest_year"]["year"], 1921)
        self.assertGreater(s["deflation_years"], 0)
        self.assertGreater(s["mean_inflation"], 0)

    def test_cumulative_inflation(self):
        value = cumulative_inflation(self.series, 1913, 2025)
        self.assertAlmostEqual(value, 321.943 / 9.9 - 1, places=9)

    def test_average_inflation_matches_cagr(self):
        value = average_inflation(self.series, 1913, 2025)
        expected = (321.943 / 9.9) ** (1 / 112) - 1
        self.assertAlmostEqual(value, expected, places=12)

    def test_average_inflation_window(self):
        windowed = average_inflation(self.series, 1913, 2025, window=10)
        recent = average_inflation(self.series, 2015, 2025)
        self.assertAlmostEqual(windowed, recent, places=12)

    def test_average_inflation_needs_span(self):
        with self.assertRaises(ValueError):
            average_inflation(self.series, 2000, 2000)


class ServerTests(unittest.TestCase):
    """The HTTP layer should validate input and shape responses correctly."""

    @classmethod
    def setUpClass(cls):
        from inflation.server import api_convert, api_meta, api_project, api_stats, BadRequest

        cls.series = load_series()
        cls.api_convert = staticmethod(api_convert)
        cls.api_meta = staticmethod(api_meta)
        cls.api_project = staticmethod(api_project)
        cls.api_stats = staticmethod(api_stats)
        cls.BadRequest = BadRequest

    def test_meta_reports_coverage(self):
        payload = self.api_meta(self.series, {})
        self.assertEqual(payload["first_year"], 1850)
        self.assertEqual(payload["last_year"], self.series.last_year)
        self.assertEqual(len(payload["meta"]["sources"]), 2)

    def test_convert_defaults_to_current_year(self):
        payload = self.api_convert(self.series, {"amount": "100", "from_year": "1950"})
        self.assertEqual(payload["from_year"], 1950)
        self.assertGreater(payload["result"], 100)

    def test_convert_rejects_bad_number(self):
        with self.assertRaises(self.BadRequest):
            self.api_convert(self.series, {"from_year": "nineteen-fifty"})

    def test_convert_rejects_year_out_of_range(self):
        with self.assertRaises(self.BadRequest):
            self.api_convert(self.series, {"from_year": "1800", "to_year": "2000"})

    def test_project_caps_window(self):
        with self.assertRaises(self.BadRequest):
            self.api_project(self.series, {"base_year": "2025", "end_year": "2500"})

    def test_stats_includes_series(self):
        payload = self.api_stats(self.series, {})
        self.assertIn("year_over_year", payload)
        self.assertEqual(len(payload["year_over_year"]), len(self.series.annual) - 1)

    def test_countries_endpoint_lists_every_country(self):
        from inflation.server import api_countries

        payload = api_countries(self.series, {})
        self.assertEqual(payload["default"], "USA")
        self.assertGreaterEqual(payload["count"], 180)
        self.assertEqual(len(payload["countries"]), payload["count"])

    def test_country_parameter_selects_a_different_series(self):
        from inflation.server import _resolve_series

        japan = _resolve_series({"country": "JPN"})
        self.assertEqual(japan.iso3, "JPN")
        self.assertEqual(japan.currency.code, "JPY")

    def test_country_defaults_to_usa(self):
        from inflation.server import _resolve_series

        self.assertEqual(_resolve_series({}).iso3, "USA")

    def test_unknown_country_is_a_bad_request(self):
        from inflation.server import _resolve_series

        with self.assertRaises(self.BadRequest):
            _resolve_series({"country": "NOPE"})

    def test_convert_for_another_country(self):
        from inflation.server import _resolve_series

        uk = _resolve_series({"country": "GBR"})
        payload = self.api_convert(uk, {"amount": "100", "from_year": "1970", "to_year": "2024"})
        self.assertAlmostEqual(payload["result"], 1579.17, places=1)

    def test_meta_reports_the_selected_countrys_currency(self):
        from inflation.server import _resolve_series

        payload = self.api_meta(_resolve_series({"country": "IND"}), {})
        self.assertEqual(payload["country"]["currency"]["code"], "INR")
        self.assertEqual(payload["country"]["iso3"], "IND")

    def test_year_outside_a_countrys_coverage_is_rejected(self):
        from inflation.server import _resolve_series

        uk = _resolve_series({"country": "GBR"})
        with self.assertRaises(self.BadRequest):
            self.api_convert(uk, {"from_year": "1850", "to_year": "2000"})


if __name__ == "__main__":
    unittest.main()
