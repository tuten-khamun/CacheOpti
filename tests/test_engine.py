"""
Tests for CacheEngine core lookup, storage, and falsy-value handling.
"""

import unittest
from cacheopti.core.engine import CacheEngine
from cacheopti.core.entry import CACHE_MISS, is_cache_miss
from cacheopti.core.key_builder import build_cache_key


class TestCacheEngineCore(unittest.TestCase):

    def setUp(self):
        self.cache = CacheEngine(capacity=5, default_ttl_seconds=60.0)

    def test_first_lookup_produces_miss(self):
        result = self.cache.get("non_existent_key")
        self.assertIs(result, CACHE_MISS)
        self.assertTrue(is_cache_miss(result))
        self.assertEqual(self.cache.misses, 1)
        self.assertEqual(self.cache.hits, 0)

    def test_repeating_same_key_produces_hit(self):
        self.cache.put("user:1", {"name": "Alice"})
        result = self.cache.get("user:1")
        self.assertEqual(result, {"name": "Alice"})
        self.assertEqual(self.cache.hits, 1)
        self.assertEqual(self.cache.misses, 0)
        self.assertEqual(self.cache.hit_rate, 1.0)

        # Repeating again produces another hit
        result2 = self.cache.get("user:1")
        self.assertEqual(result2, {"name": "Alice"})
        self.assertEqual(self.cache.hits, 2)

    def test_different_keys_do_not_collide(self):
        k1 = build_cache_key("test", 1, flag=True)
        k2 = build_cache_key("test", 2, flag=True)
        k3 = build_cache_key("test", "1", flag=True)  # type difference int vs str

        self.assertNotEqual(k1, k2)
        self.assertNotEqual(k1, k3)

        self.cache.put(k1, "value_1")
        self.cache.put(k2, "value_2")
        self.cache.put(k3, "value_3")

        self.assertEqual(self.cache.get(k1), "value_1")
        self.assertEqual(self.cache.get(k2), "value_2")
        self.assertEqual(self.cache.get(k3), "value_3")

    def test_cached_falsy_values_handled_correctly(self):
        """Verify that falsy values are returned as hits, NOT misses."""
        falsy_cases = [
            ("key_none", None),
            ("key_false", False),
            ("key_zero", 0),
            ("key_empty_str", ""),
            ("key_empty_list", []),
            ("key_empty_dict", {}),
        ]

        for key, val in falsy_cases:
            with self.subTest(key=key, val=val):
                self.cache.put(key, val)
                res = self.cache.get(key)
                self.assertIsNot(res, CACHE_MISS)
                self.assertFalse(is_cache_miss(res))
                self.assertEqual(res, val)

    def test_delete_and_clear(self):
        self.cache.put("k1", "v1")
        self.cache.put("k2", "v2")
        self.assertEqual(len(self.cache._storage), 2)

        # Delete single key
        deleted = self.cache.delete("k1")
        self.assertTrue(deleted)
        self.assertIs(self.cache.get("k1"), CACHE_MISS)

        # Clear entire cache
        self.cache.clear()
        self.assertEqual(len(self.cache._storage), 0)
        self.assertIs(self.cache.get("k2"), CACHE_MISS)

    def test_state_and_metrics_consistency(self):
        self.cache.put("a", 10)
        self.cache.get("a")  # hit
        self.cache.get("b")  # miss
        self.cache.get("c")  # miss

        state = self.cache.get_state()
        self.assertEqual(state["capacity"], 5)
        self.assertEqual(state["occupancy"], 1)
        self.assertEqual(state["hits"], 1)
        self.assertEqual(state["misses"], 2)
        self.assertEqual(state["total_lookups"], 3)
        self.assertAlmostEqual(state["hit_rate_pct"], 33.33, places=1)


if __name__ == "__main__":
    unittest.main()
