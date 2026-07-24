#!/usr/bin/env python3
"""Tests for worldpop-population CLI."""

import sys
import os
import json
import importlib.util
import unittest
from unittest.mock import patch, MagicMock

# Load the module from scripts/worldpop-population.py
_script_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "worldpop-population.py")
_spec = importlib.util.spec_from_file_location("worldpop_population", _script_path)
wp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wp)


def _make_api_response(data):
    """Create a mock response for requests.get."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = data
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestSearchDatasets(unittest.TestCase):
    @patch("requests.get")
    def test_search_by_country(self, mock_get):
        mock_get.return_value = _make_api_response([
            {"id": 1, "title": "Population density", "country": "China", "iso3": "CHN", "year": 2020},
            {"id": 2, "title": "Population density", "country": "India", "iso3": "IND", "year": 2020},
        ])
        results = wp.search_datasets(country="China")
        self.assertIsNotNone(results)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["country"], "China")

    @patch("requests.get")
    def test_search_by_code(self, mock_get):
        mock_get.return_value = _make_api_response([
            {"id": 1, "title": "Pop", "country": "China", "iso3": "CHN", "year": 2020},
            {"id": 2, "title": "Pop", "country": "India", "iso3": "IND", "year": 2020},
        ])
        results = wp.search_datasets(code="CHN")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["iso3"], "CHN")

    @patch("requests.get")
    def test_search_by_year(self, mock_get):
        mock_get.return_value = _make_api_response([
            {"id": 1, "title": "Pop", "country": "China", "iso3": "CHN", "year": 2020},
            {"id": 2, "title": "Pop", "country": "China", "iso3": "CHN", "year": 2010},
        ])
        results = wp.search_datasets(year=2020)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["year"], 2020)

    @patch("requests.get")
    def test_search_no_match(self, mock_get):
        mock_get.return_value = _make_api_response([
            {"id": 1, "title": "Pop", "country": "China", "iso3": "CHN", "year": 2020},
        ])
        results = wp.search_datasets(country="Atlantis")
        self.assertEqual(len(results), 0)

    @patch("requests.get")
    def test_search_api_failure(self, mock_get):
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError()
        results = wp.search_datasets(country="China")
        self.assertIsNone(results)


class TestFetchJson(unittest.TestCase):
    @patch("requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = _make_api_response([{"id": 1}])
        result = wp.fetch_json("https://example.com/api")
        self.assertEqual(result, [{"id": 1}])

    @patch("requests.get")
    def test_timeout(self, mock_get):
        import requests as req
        mock_get.side_effect = req.exceptions.Timeout()
        result = wp.fetch_json("https://example.com/api")
        self.assertIsNone(result)


class TestCLI(unittest.TestCase):
    @patch("requests.get")
    def test_search_with_results(self, mock_get):
        mock_get.return_value = _make_api_response([
            {"id": 1, "title": "Pop", "country": "China", "iso3": "CHN", "year": 2020}
        ])
        args = wp.argparse.Namespace(country="China", code=None, year=None, type=None, json=False)
        rc = wp.cmd_search(args)
        self.assertEqual(rc, 0)

    @patch("requests.get")
    def test_search_empty(self, mock_get):
        mock_get.return_value = _make_api_response([
            {"id": 1, "title": "Pop", "country": "China", "iso3": "CHN", "year": 2020}
        ])
        args = wp.argparse.Namespace(country="Atlantis", code=None, year=None, type=None, json=False)
        rc = wp.cmd_search(args)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
