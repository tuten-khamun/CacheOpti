"""
Tests for LRU (Least Recently Used) capacity eviction and ordering.
Also verifies alternative policies (FIFO, LFU).
"""

import unittest
from cacheopti.core.engine import CacheEngine
from cacheopti.core.entry import CACHE_MISS
from cacheopti.core.policies import LRUPolicy, FIFOPolicy, LFUPolicy


class TestLRUEviction(unittest.TestCase):

    def test_lru_evicts_oldest_when_full(self):
        # Capacity of 3
        cache = CacheEngine(capacity=3, default_ttl_seconds=100.0, policy=LRUPolicy())

        cache.put("A", 1)  # [A]
        cache.put("B", 2)  # [B, A]
        cache.put("C", 3)  # [C, B, A]

        # Insert 4th item "D". "A" is the oldest, so "A" must be evicted
        cache.put("D", 4)  # [D, C, B], A evicted

        self.assertEqual(cache.evictions, 1)
        self.assertIs(cache.get("A"), CACHE_MISS)
        self.assertEqual(cache.get("B"), 2)
        self.assertEqual(cache.get("C"), 3)
        self.assertEqual(cache.get("D"), 4)

    def test_recently_accessed_entry_survives_eviction(self):
        # Capacity of 3
        cache = CacheEngine(capacity=3, default_ttl_seconds=100.0, policy=LRUPolicy())

        cache.put("A", 1)  # [A]
        cache.put("B", 2)  # [B, A]
        cache.put("C", 3)  # [C, B, A]

        # Re-access "A" -> promotes "A" to MRU head. Order: [A, C, B]
        # Now "B" is the least recently used!
        res_a = cache.get("A")
        self.assertEqual(res_a, 1)

        # Insert "D" -> "B" should be evicted, "A" must survive!
        cache.put("D", 4)

        self.assertEqual(cache.evictions, 1)
        self.assertEqual(cache.get("A"), 1)  # Survived!
        self.assertIs(cache.get("B"), CACHE_MISS)  # Evicted!
        self.assertEqual(cache.get("C"), 3)
        self.assertEqual(cache.get("D"), 4)

    def test_update_existing_key_does_not_evict_and_refreshes_mru(self):
        cache = CacheEngine(capacity=2, default_ttl_seconds=100.0, policy=LRUPolicy())

        cache.put("A", 1)
        cache.put("B", 2)

        # Overwrite "A" -> should promote "A" to MRU, size stays 2, no eviction
        cache.put("A", 100)
        self.assertEqual(cache.evictions, 0)
        self.assertEqual(len(cache._storage), 2)

        # Adding "C" should now evict "B", while "A" survives
        cache.put("C", 3)
        self.assertEqual(cache.evictions, 1)
        self.assertEqual(cache.get("A"), 100)
        self.assertIs(cache.get("B"), CACHE_MISS)

    def test_fifo_policy_evicts_oldest_insertion_regardless_of_reads(self):
        cache = CacheEngine(capacity=2, default_ttl_seconds=100.0, policy=FIFOPolicy())

        cache.put("A", 1)
        cache.put("B", 2)

        # Access A. Under FIFO, A is STILL the oldest inserted entry!
        cache.get("A")

        # Insert C -> A must be evicted under FIFO
        cache.put("C", 3)
        self.assertIs(cache.get("A"), CACHE_MISS)
        self.assertEqual(cache.get("B"), 2)

    def test_lfu_policy_evicts_least_frequently_used(self):
        cache = CacheEngine(capacity=2, default_ttl_seconds=100.0, policy=LFUPolicy())

        cache.put("A", 1)
        cache.put("B", 2)

        # Hit "A" 3 times
        cache.get("A")
        cache.get("A")
        cache.get("A")

        # "B" has only 1 initial access, so "B" is least frequent
        cache.put("C", 3)

        self.assertEqual(cache.get("A"), 1)
        self.assertIs(cache.get("B"), CACHE_MISS)  # Evicted because of low frequency


if __name__ == "__main__":
    unittest.main()
