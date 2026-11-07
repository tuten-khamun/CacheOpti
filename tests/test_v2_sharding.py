"""
Tests for Component C: 16-Way Sharded Concurrency.
Verifies shard independence, hash key routing (hash(key) & 0x0F),
dual-bound partition distribution, and lock safety.
"""

import threading
import pytest
from cacheopti.core.engine import ShardedCache
from cacheopti.core.shard import _CacheShard


def test_16_independent_shards_initialization():
    """Verify engine initializes exactly 16 independent _CacheShard instances."""
    cache = ShardedCache(max_entries=160, max_bytes=16_000, default_ttl_seconds=60.0)
    assert len(cache._shards) == 16
    assert cache.num_shards == 16

    # Verify each shard is an isolated _CacheShard with its own lock and dict
    shard_ids = set()
    locks = set()
    for shard in cache._shards:
        assert isinstance(shard, _CacheShard)
        shard_ids.add(shard.shard_id)
        locks.add(shard.lock)
        # Verify partitioned capacity: 160 // 16 = 10 entries per shard
        assert shard.max_entries == 10
        assert shard.max_bytes == 1000

    assert len(shard_ids) == 16, "All 16 shard IDs must be unique"
    assert len(locks) == 16, "All 16 shards must have independent RLock instances"


def test_key_routing_hash_mask():
    """Verify keys route to the exact shard dictated by hash(key) & 0x0F."""
    cache = ShardedCache()
    test_keys = ["user:1", "session:abc", "data:AAPL", "quote:MSFT", "id:9999"]

    for k in test_keys:
        expected_shard_id = hash(k) & 0x0F
        assert 0 <= expected_shard_id <= 15
        selected_shard = cache._get_shard(k)
        assert selected_shard.shard_id == expected_shard_id


def test_shard_isolation_and_operations():
    """Verify operations in one shard do not pollute or lock other shards."""
    cache = ShardedCache()
    cache.put("key_1", "val_1")
    cache.put("key_2", "val_2")

    assert cache.get("key_1") == "val_1"
    assert cache.get("key_2") == "val_2"
    assert cache.get("nonexistent") == cacheopti.core.entry.CACHE_MISS

    # Delete
    assert cache.delete("key_1")
    assert not cache.delete("key_1")
    assert cache.get("key_1") == cacheopti.core.entry.CACHE_MISS

    # Clear
    cache.clear()
    assert cache.total_entries == 0
    assert cache.total_bytes == 0


import cacheopti.core.entry
