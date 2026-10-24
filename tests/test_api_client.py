"""
Tests for DynamicApiClient and CountryService using mock HTTP responses.
Ensures zero external network reliance during automated test runs.
"""

import unittest
from unittest.mock import patch, MagicMock
import requests
from cacheopti.core.engine import CacheEngine
from cacheopti.api.client import DynamicApiClient
from cacheopti.api.country_service import CountryService


SAMPLE_COUNTRY_JSON = [
    {
        "name": {"common": "France", "official": "French Republic"},
        "cca2": "FR",
        "cca3": "FRA",
        "capital": ["Paris"],
        "region": "Europe",
        "subregion": "Western Europe",
        "population": 67391582,
        "currencies": {"EUR": {"name": "Euro", "symbol": "€"}},
        "languages": {"fra": "French"},
        "flag": "🇫🇷",
        "flags": {"png": "https://flagcdn.com/w320/fr.png"},
    }
]


class TestApiClientAndService(unittest.TestCase):

    def setUp(self):
        self.cache = CacheEngine(capacity=5, default_ttl_seconds=60.0)
        self.client = DynamicApiClient(base_url="https://mock.restcountries.com/v3.1")
        self.service = CountryService(cache_engine=self.cache, api_client=self.client)

    @patch.object(requests.Session, "get")
    def test_first_call_fetches_from_network_and_caches(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_COUNTRY_JSON
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        # First request: Cache Miss -> Network Fetch
        res1 = self.service.get_country_by_name("france")
        self.assertEqual(res1["source"], "NETWORK_FETCH")
        self.assertFalse(res1["from_cache"])
        self.assertEqual(res1["data"]["common_name"], "France")
        self.assertEqual(self.client.total_network_requests, 1)
        self.assertEqual(self.service.service_hits, 0)
        self.assertEqual(self.service.service_misses, 1)

        # Second request: Cache Hit -> ZERO additional network calls!
        res2 = self.service.get_country_by_name("france")
        self.assertEqual(res2["source"], "CACHE_HIT")
        self.assertTrue(res2["from_cache"])
        self.assertEqual(res2["data"]["common_name"], "France")
        self.assertEqual(self.client.total_network_requests, 1)  # STILL 1!
        self.assertEqual(self.service.service_hits, 1)

        # Avoided request metric
        stats = self.service.get_service_stats()
        self.assertEqual(stats["estimated_external_requests_avoided"], 1)

    @patch.object(requests.Session, "get")
    def test_dynamic_api_key_header_attached_when_configured(self, mock_get):
        auth_client = DynamicApiClient(
            base_url="https://api.custom.com",
            api_key="secret-token-123",
            auth_type="header",
            header_name="X-API-Key",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        auth_client.get("test-endpoint")
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["headers"].get("X-API-Key"), "secret-token-123")

    @patch.object(requests.Session, "get")
    def test_api_timeout_handled_gracefully(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        res = self.service.get_country_by_name("slow-country")
        self.assertTrue(res["is_error"])
        self.assertEqual(res["source"], "NETWORK_ERROR")
        self.assertIn("timed out", res["error_message"].lower())
        self.assertEqual(self.client.total_network_errors, 1)
        # Error response should not be cached
        self.assertEqual(len(self.cache._storage), 0)


if __name__ == "__main__":
    unittest.main()
