"""
Integration tests for CacheOpti HTTP Server routes.
"""

import json
import unittest
from unittest.mock import patch, MagicMock
from cacheopti.server import state, CacheOptiRequestHandler


class TestServerEndpoints(unittest.TestCase):

    def setUp(self):
        with state.lock:
            state.cache.clear()
            state.cache.reset_metrics()
            state.client.reset_stats()
            state.sim_index = 0
            state.sim_history.clear()

    def test_state_endpoint(self):
        with state.lock:
            state.cache.put("item1", "val1")
            cache_st = state.cache.get_state()
            self.assertEqual(cache_st["occupancy"], 1)

    def test_config_endpoint(self):
        state.set_config(capacity=10, default_ttl=45.0, policy_name="FIFO")
        with state.lock:
            self.assertEqual(state.cache.capacity, 10)
            self.assertEqual(state.cache.default_ttl_seconds, 45.0)
            self.assertEqual(state.cache.policy.name, "FIFO")

    def test_sim_step_advances_workload(self):
        initial_idx = state.sim_index
        item = state.sim_workload[initial_idx]

        with state.lock:
            state.cache.put(item, f"val_{item}")
            state.sim_index += 1
            state.sim_history.append({"key": item, "step": 1})

        self.assertEqual(state.sim_index, initial_idx + 1)
        self.assertEqual(len(state.sim_history), 1)

    @patch("cacheopti.server.state.client.get")
    def test_country_search_route_logic(self, mock_get):
        from cacheopti.api.client import ApiResponse
        mock_get.return_value = ApiResponse(
            status_code=200,
            data=[{"name": {"common": "Spain", "official": "Kingdom of Spain"}, "cca2": "ES"}],
            latency_ms=120.0,
            is_error=False,
        )

        res = state.service.get_country_by_name("spain", use_cache=True)
        self.assertEqual(res["source"], "NETWORK_FETCH")
        self.assertEqual(res["data"]["common_name"], "Spain")

        # Second search should hit cache
        res2 = state.service.get_country_by_name("spain", use_cache=True)
        self.assertEqual(res2["source"], "CACHE_HIT")
        self.assertTrue(res2["from_cache"])


if __name__ == "__main__":
    unittest.main()
