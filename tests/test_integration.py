"""
Integration tests for CacheOpti end-to-end flows.
Tests complete pipeline: cache engine, dynamic API service, TTL expiration, and metrics.
"""

import unittest
from unittest.mock import patch, MagicMock
import requests
from cacheopti.core.engine import CacheEngine
from cacheopti.api.client import DynamicApiClient
from cacheopti.api.country_service import CountryService


SAMPLE_GERMANY = [
    {
        "name": {"common": "Germany", "official": "Federal Republic of Germany"},
        "cca2": "DE",
        "cca3": "DEU",
        "capital": ["Berlin"],
        "region": "Europe",
        "subregion": "Western Europe",
        "population": 83240525,
        "currencies": {"EUR": {"name": "Euro"}},
        "languages": {"deu": "German"},
        "flag": "🇩🇪",
        "flags": {"png": "https://flagcdn.com/w320/de.png"},
    }
]


class TestIntegrationFlow(unittest.TestCase):

    @patch.object(requests.Session, "get")
    def test_full_country_caching_and_expiration_flow(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_GERMANY
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        clock_val = 1000.0
        cache = CacheEngine(capacity=2, default_ttl_seconds=10.0, clock_fn=lambda: clock_val)
        service = CountryService(cache_engine=cache, api_client=DynamicApiClient())

        # 1. First fetch: miss -> external request
        r1 = service.get_country_by_name("germany")
        self.assertEqual(r1["source"], "NETWORK_FETCH")
        self.assertEqual(service.client.total_network_requests, 1)

        # 2. Second fetch: hit -> zero external request
        r2 = service.get_country_by_name("germany")
        self.assertEqual(r2["source"], "CACHE_HIT")
        self.assertEqual(service.client.total_network_requests, 1)

        # 3. Advance clock past 10s TTL
        clock_val += 11.0

        # 4. Third fetch: expired -> triggers a fresh external request
        r3 = service.get_country_by_name("germany")
        self.assertEqual(r3["source"], "NETWORK_FETCH")
        self.assertEqual(service.client.total_network_requests, 2)


if __name__ == "__main__":
    unittest.main()
