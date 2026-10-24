"""
Tests for TTL (Time To Live) expiration mechanics and monotonic clock calculations.
"""

import unittest
from cacheopti.core.engine import CacheEngine
from cacheopti.core.entry import CACHE_MISS


class TestCacheTTL(unittest.TestCase):

    def setUp(self):
        self.current_time = 100.0

        def fake_clock() -> float:
            return self.current_time

        self.fake_clock = fake_clock
        self.cache = CacheEngine(
            capacity=5,
            default_ttl_seconds=10.0,
            clock_fn=self.fake_clock,
        )

    def test_entry_valid_within_ttl(self):
        self.cache.put("key1", "val1")
        # Advance time by 5s (less than 10s TTL)
        self.current_time += 5.0

        result = self.cache.get("key1")
        self.assertEqual(result, "val1")
        self.assertEqual(self.cache.hits, 1)
        self.assertEqual(self.cache.expirations, 0)

    def test_expired_entry_not_returned_and_purged_lazily(self):
        self.cache.put("key1", "val1")
        # Advance time by 10.1s (past 10s TTL)
        self.current_time += 10.1

        result = self.cache.get("key1")
        self.assertIs(result, CACHE_MISS)
        self.assertEqual(self.cache.misses, 1)
        self.assertEqual(self.cache.expirations, 1)
        # Verify node is purged from internal storage
        self.assertNotIn("key1", self.cache._storage)

    def test_per_entry_ttl_override(self):
        # Default is 10s, but we assign a 2s TTL to short_lived
        self.cache.put("short_lived", "fast", ttl_seconds=2.0)
        self.cache.put("long_lived", "slow", ttl_seconds=20.0)

        # Advance by 3 seconds
        self.current_time += 3.0

        self.assertIs(self.cache.get("short_lived"), CACHE_MISS)
        self.assertEqual(self.cache.get("long_lived"), "slow")

    def test_purge_expired_sweeps_stale_entries(self):
        self.cache.put("item1", "v1", ttl_seconds=5.0)
        self.cache.put("item2", "v2", ttl_seconds=15.0)
        self.cache.put("item3", "v3", ttl_seconds=5.0)

        self.assertEqual(len(self.cache._storage), 3)

        # Advance by 6 seconds -> item1 and item3 are expired
        self.current_time += 6.0
        purged = self.cache.purge_expired()
        self.assertEqual(purged, 2)
        self.assertEqual(len(self.cache._storage), 1)
        self.assertIn("item2", self.cache._storage)

    def test_remaining_ttl_reported_accurately(self):
        self.cache.put("item", "data", ttl_seconds=10.0)
        self.current_time += 4.0

        entries = self.cache.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertAlmostEqual(entries[0].remaining_ttl, 6.0, places=2)
        self.assertFalse(entries[0].is_expired)


if __name__ == "__main__":
    unittest.main()
