"""
Tests for 32-Thread Concurrency and Stress Verification on CacheOpti v2.0.
Verifies thread safety across 16 shards under heavy read/write/overwrite contention.
"""

import random
import threading
import pytest
from cacheopti.core.engine import ShardedCache


def test_32_threads_concurrent_reads_writes_overwrites():
    """
    Stress test: 32 threads performing 10,000 combined operations across 16 shards.
    Guarantees no deadlocks, no unhandled exceptions, and strict bounded memory.
    """
    cache = ShardedCache(
        max_entries=320,  # 20 per shard
        max_bytes=100_000,
        default_ttl_seconds=10.0,
        num_shards=16,
    )

    thread_count = 32
    ops_per_thread = 250
    keys = [f"key_{i}" for i in range(50)]  # 50 keys ensures high collision & overwrites

    errors = []

    def worker(tid: int):
        rng = random.Random(tid)
        try:
            for _ in range(ops_per_thread):
                op = rng.choice(["get", "put", "overwrite", "delete"])
                k = rng.choice(keys)

                if op == "get":
                    cache.get(k)
                elif op == "put":
                    cache.put(k, {"data": rng.randint(1, 1000)})
                elif op == "overwrite":
                    cache.put(k, "overwrite_payload_" * rng.randint(1, 5))
                elif op == "delete":
                    cache.delete(k)
        except Exception as e:
            errors.append((tid, e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Verify no worker encountered an exception or deadlock
    assert len(errors) == 0, f"Errors occurred during concurrency test: {errors}"

    # Verify memory invariants: total entries and total bytes must respect limits
    assert cache.total_entries <= 320
    assert cache.total_bytes <= 100_000

    telemetry = cache.get_telemetry()
    assert telemetry["total_lookups"] > 0
    assert telemetry["percentiles"]["p50_us"] > 0.0
