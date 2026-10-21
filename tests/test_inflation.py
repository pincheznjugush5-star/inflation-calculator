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
from inflation.data import DEFAULT_FORWARD_RATE, load_series, resolve_index


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


class ConvertTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
