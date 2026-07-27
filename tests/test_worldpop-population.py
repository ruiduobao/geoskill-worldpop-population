#!/usr/bin/env python3
"""Tests for worldpop-population CLI v2.

The v1 tests assumed ``GET /rest/data`` returned a flat list of dataset objects.
The current WorldPop API actually returns ``{"data": [{alias, name, ...}, ...]}``
at the top level (a category list), so the v2 code now navigates two levels.
Tests below reflect v2.
"""

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


def _mock_json_resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    r.text = json.dumps(payload)
    return r


CATEGORIES = {
    "data": [
        {"alias": "pop", "name": "Population Counts"},
        {"alias": "births", "name": "Births"},
        {"alias": "urban_change", "name": "Urban change"},
    ]
}

POP_WPGP = {
    "data": [
        {"id": "6524", "title": "Population 2020 China", "popyear": "2020",
         "iso3": "CHN", "country": "China"},
        {"id": "6525", "title": "Population 2020 India", "popyear": "2020",
         "iso3": "IND", "country": "India"},
        {"id": "5500", "title": "Population 2010 China", "popyear": "2010",
         "iso3": "CHN", "country": "China"},
    ]
}


class TestListCategories(unittest.TestCase):
    @patch("requests.get")
    def test_returns_top_level_aliases(self, mock_get):
        mock_get.return_value = _mock_json_resp(CATEGORIES)
        cats = wp.list_categories()
        self.assertEqual(len(cats), 3)
        self.assertEqual(cats[0]["alias"], "pop")


class TestSearchDatasets(unittest.TestCase):
    @patch("requests.get")
    def test_search_by_code_year(self, mock_get):
        mock_get.return_value = _mock_json_resp(POP_WPGP)
        hits = wp.search_datasets(code="CHN", year=2020, limit=5)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["iso3"], "CHN")
        self.assertEqual(hits[0]["popyear"], "2020")

    @patch("requests.get")
    def test_search_by_country_substring(self, mock_get):
        mock_get.return_value = _mock_json_resp(POP_WPGP)
        hits = wp.search_datasets(country="india", limit=5)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["iso3"], "IND")

    @patch("requests.get")
    def test_search_no_match(self, mock_get):
        mock_get.return_value = _mock_json_resp(POP_WPGP)
        hits = wp.search_datasets(code="ZZZ", year=2020, limit=5)
        self.assertEqual(hits, [])

    @patch("requests.get")
    def test_search_api_failure(self, mock_get):
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError()
        hits = wp.search_datasets(code="CHN", year=2020)
        self.assertEqual(hits, [])


class TestPickDataset(unittest.TestCase):
    def test_pick_returns_single(self):
        ds = wp.pick_dataset([{"id": 1}])
        self.assertEqual(ds["id"], 1)

    def test_pick_picks_most_recent(self):
        ds = wp.pick_dataset([
            {"id": 1, "popyear": "2010"},
            {"id": 2, "popyear": "2020"},
        ])
        self.assertEqual(ds["id"], 2)

    def test_pick_empty(self):
        self.assertIsNone(wp.pick_dataset([]))


class TestPickGeoUrl(unittest.TestCase):
    def test_picks_first_tif(self):
        ds = {"files": [
            {"url": "https://example.com/foo.txt"},
            {"url": "https://example.com/bar.tif"},
        ]}
        self.assertEqual(wp._pick_geo_url(ds), "https://example.com/bar.tif")

    def test_falls_back_to_data_file(self):
        ds = {"data_file": "GIS/Population/x.tif"}
        self.assertTrue(wp._pick_geo_url(ds).endswith("/x.tif"))

    def test_returns_none_when_empty(self):
        self.assertIsNone(wp._pick_geo_url({}))


class TestGeocodePlace(unittest.TestCase):
    @patch("requests.get")
    def test_resolves_known_city(self, mock_get):
        mock_get.return_value = _mock_json_resp({
            "results": [{"name": "Tokyo", "latitude": 35.6895,
                         "longitude": 139.6917, "country_code": "JP", "iso3": "JPN"}]
        })
        out = wp.geocode_place("Tokyo")
        self.assertIsNotNone(out)
        self.assertEqual(out["iso3"], "JPN")
        self.assertAlmostEqual(out["lat"], 35.6895, places=3)

    @patch("requests.get")
    def test_returns_none_when_no_results(self, mock_get):
        mock_get.return_value = _mock_json_resp({"results": []})
        self.assertIsNone(wp.geocode_place("Atlantis"))

    @patch("requests.get")
    def test_returns_none_on_error(self, mock_get):
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError()
        self.assertIsNone(wp.geocode_place("Tokyo"))


class TestCLI(unittest.TestCase):
    @patch("requests.get")
    def test_search_subcommand_runs(self, mock_get):
        mock_get.return_value = _mock_json_resp(POP_WPGP)
        # Build a namespace matching cmd_search expectations
        args = wp.argparse.Namespace(
            country=None, code="CHN", year=2020, type=None,
            category=None, limit=5, json=False,
        )
        rc = wp.cmd_search(args)
        self.assertEqual(rc, 0)

    @patch("requests.get")
    def test_search_subcommand_empty(self, mock_get):
        mock_get.return_value = _mock_json_resp(POP_WPGP)
        args = wp.argparse.Namespace(
            country=None, code="ZZZ", year=2020, type=None,
            category=None, limit=5, json=False,
        )
        rc = wp.cmd_search(args)
        self.assertEqual(rc, 0)


class TestBboxValidation(unittest.TestCase):
    """The v1 input format `bbox nargs=4` should be plumbed as floats."""

    def test_bbox_argparse_parses_four_floats(self):
        # Sanity-check: argparse with nargs=4 + type=float parses correctly
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"))
        ns = p.parse_args(["--bbox", "1.0", "2.0", "3.0", "4.0"])
        self.assertEqual(ns.bbox, [1.0, 2.0, 3.0, 4.0])


if __name__ == "__main__":
    unittest.main()
