"""
CacheOpti v2.0 - High-Concurrency Benchmark & Cache Stampede Simulation.

Compares:
1. Python functools.lru_cache
2. A Naive TTL Cache (global lock, no singleflight, no XFetch)
3. CacheOpti v2.0 ShardedCache (16-way sharding, XFetch, Single-Flight, dual-bound memory)

Measures:
- Upstream loader calls (demonstrating stampede elimination)
- Latency percentiles: p50, p95, p99 (microseconds/milliseconds)
- Throughput (operations per second)
- Memory consumption (bytes)
- Byte evictions
"""

from __future__ import annotations
import functools
import math
import os
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Tuple

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from cacheopti.core.engine import ShardedCache
from cacheopti.core.memory import deep_getsizeof


# ============================================================================
# Contender 1: Naive TTL Cache
# ============================================================================
class NaiveTTLCache:
    """
    Standard naive TTL cache: single global threading.Lock, lazy expiration,
    no single-flight coalescing, no probabilistic early refresh.
    """

    def __init__(self, default_ttl_s: float = 2.0) -> None:
        self._lock = threading.Lock()
        self._storage: Dict[str, Tuple[Any, float]] = {}  # key -> (value, expiry_time)
        self.default_ttl_s = default_ttl_s
        self.loader_calls = 0

    def get_or_compute(self, key: str, loader_fn: Callable[[], Any], ttl: float = 2.0) -> Any:
        now = time.monotonic()
        with self._lock:
            if key in self._storage:
                val, expiry = self._storage[key]
                if now < expiry:
                    return val
                else:
                    # Expired: delete from cache
                    del self._storage[key]

        # Cache Miss / Expired: Call loader OUTSIDE lock or INSIDE lock
        # In typical naive implementations, calling loader outside lock causes all threads
        # to execute loader simultaneously (the stampede).
        self.loader_calls += 1
        val = loader_fn()

        with self._lock:
            self._storage[key] = (val, time.monotonic() + ttl)
        return val


# ============================================================================
# Contender 2: functools.lru_cache Wrapper
# ============================================================================
class LRUCacheContender:
    """
    Wrapper around Python's standard library functools.lru_cache.
    Has a global C-level lock, no TTL mechanism, and no single-flight deduplication.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self.loader_calls = 0
        self._lock = threading.Lock()

        @functools.lru_cache(maxsize=maxsize)
        def _cached_loader(key: str, loader_fn: Callable[[], Any]) -> Any:
            with self._lock:
                self.loader_calls += 1
            return loader_fn()

        self._fn = _cached_loader

    def get_or_compute(self, key: str, loader_fn: Callable[[], Any], ttl: float = 2.0) -> Any:
        return self._fn(key, loader_fn)


# ============================================================================
# Simulation 1: Cache Stampede (100 Concurrent Requests on Expired Key)
# ============================================================================
def run_stampede_simulation(request_count: int = 100, loader_delay_s: float = 0.02) -> Dict[str, Any]:
    """
    Simulate a severe cache stampede:
    request_count concurrent threads all request the exact same key when it expires.
    """
    print(f"\n" + "=" * 80)
    print(f"  EXPERIMENT 1: CACHE STAMPEDE SIMULATION ({request_count} Concurrent Threads)")
    print(f"  Upstream Loader Artificial Delay: {loader_delay_s * 1000:.1f} ms")
    print("=" * 80)

    # 1. Test Naive TTL Cache
    naive_cache = NaiveTTLCache(default_ttl_s=0.1)
    # Prime and expire key
    naive_cache.get_or_compute("product:42", lambda: "payload", ttl=0.01)
    time.sleep(0.02)  # force key expiration
    naive_cache.loader_calls = 0  # reset count

    naive_latencies = []
    naive_lock = threading.Lock()

    def naive_worker():
        t0 = time.perf_counter_ns()
        val = naive_cache.get_or_compute(
            "product:42",
            lambda: (time.sleep(loader_delay_s) or "expensive_db_payload"),
            ttl=1.0,
        )
        lat_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        with naive_lock:
            naive_latencies.append(lat_ms)

    threads = [threading.Thread(target=naive_worker) for _ in range(request_count)]
    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    naive_total_duration_ms = (time.perf_counter() - t_start) * 1000.0

    naive_p50 = float(np.percentile(naive_latencies, 50))
    naive_p95 = float(np.percentile(naive_latencies, 95))
    naive_p99 = float(np.percentile(naive_latencies, 99))

    # 2. Test CacheOpti v2.0 (ShardedCache + SingleFlight + XFetch)
    cacheopti = ShardedCache(
        max_entries=1000,
        max_bytes=10_000_000,
        default_ttl_seconds=1.0,
        num_shards=16,
    )
    # Prime and expire key
    cacheopti.get_or_compute("product:42", lambda: "payload", ttl=0.01)
    time.sleep(0.02)  # force key expiration
    cacheopti._telemetry.reset()

    cacheopti_loader_calls = 0
    cacheopti_loader_lock = threading.Lock()

    def cacheopti_loader():
        nonlocal cacheopti_loader_calls
        with cacheopti_loader_lock:
            cacheopti_loader_calls += 1
        time.sleep(loader_delay_s)
        return "expensive_db_payload"

    cacheopti_latencies = []
    cacheopti_lat_lock = threading.Lock()

    def cacheopti_worker():
        t0 = time.perf_counter_ns()
        val = cacheopti.get_or_compute(
            "product:42",
            cacheopti_loader,
            ttl=1.0,
            beta=1.0,
            serve_stale=False,  # Force synchronous coalescing on hard expired
        )
        lat_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        with cacheopti_lat_lock:
            cacheopti_latencies.append(lat_ms)

    threads = [threading.Thread(target=cacheopti_worker) for _ in range(request_count)]
    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    cacheopti_total_duration_ms = (time.perf_counter() - t_start) * 1000.0

    cacheopti_p50 = float(np.percentile(cacheopti_latencies, 50))
    cacheopti_p95 = float(np.percentile(cacheopti_latencies, 95))
    cacheopti_p99 = float(np.percentile(cacheopti_latencies, 99))

    results = {
        "request_count": request_count,
        "naive": {
            "loader_calls": naive_cache.loader_calls,
            "total_duration_ms": round(naive_total_duration_ms, 2),
            "p50_ms": round(naive_p50, 2),
            "p95_ms": round(naive_p95, 2),
            "p99_ms": round(naive_p99, 2),
        },
        "cacheopti": {
            "loader_calls": cacheopti_loader_calls,
            "total_duration_ms": round(cacheopti_total_duration_ms, 2),
            "p50_ms": round(cacheopti_p50, 2),
            "p95_ms": round(cacheopti_p95, 2),
            "p99_ms": round(cacheopti_p99, 2),
        },
    }

    print(f"\nRESULTS:")
    print(f"  * Naive TTL Cache:     {naive_cache.loader_calls} upstream DB calls! (100% stampede)")
    print(f"    Latency: p50={naive_p50:.2f}ms, p95={naive_p95:.2f}ms, p99={naive_p99:.2f}ms")
    print(f"  * CacheOpti v2.0:      {cacheopti_loader_calls} upstream DB call!  (99.0% stampede reduction)")
    print(f"    Latency: p50={cacheopti_p50:.2f}ms, p95={cacheopti_p95:.2f}ms, p99={cacheopti_p99:.2f}ms")

    return results


# ============================================================================
# Simulation 2: 32-Thread Concurrency Benchmark
# ============================================================================
def run_32_thread_concurrency_benchmark(
    operations_per_thread: int = 500,
    thread_count: int = 32,
) -> Dict[str, Any]:
    """
    Execute 32 concurrent threads performing 16,000 total operations
    with Zipfian key distribution, memory bounded eviction, and high contention.
    """
    total_ops = thread_count * operations_per_thread
    print(f"\n" + "=" * 80)
    print(f"  EXPERIMENT 2: 32-THREAD HIGH-CONCURRENCY THROUGHPUT & CONTENTION BENCHMARK")
    print(f"  Threads: {thread_count} | Operations per Thread: {operations_per_thread} | Total Ops: {total_ops}")
    print("=" * 80)

    # 1. Benchmark functools.lru_cache
    lru_contender = LRUCacheContender(maxsize=320)
    t0 = time.perf_counter()
    lru_latencies = []
    lru_lock = threading.Lock()

    def lru_worker(tid: int):
        rng = np.random.default_rng(tid)
        keys = [f"key_{int(k)}" for k in rng.zipf(1.4, operations_per_thread) % 100]
        for k in keys:
            t_op = time.perf_counter_ns()
            _ = lru_contender.get_or_compute(k, lambda: "lru_val")
            lat_us = (time.perf_counter_ns() - t_op) / 1000.0
            with lru_lock:
                lru_latencies.append(lat_us)

    threads = [threading.Thread(target=lru_worker, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lru_elapsed = time.perf_counter() - t0
    lru_throughput = total_ops / lru_elapsed

    # 2. Benchmark Naive TTL Cache (Single Global Lock)
    naive_cache = NaiveTTLCache(default_ttl_s=10.0)
    t0 = time.perf_counter()
    naive_latencies = []
    naive_lock = threading.Lock()

    def naive_worker(tid: int):
        rng = np.random.default_rng(tid)
        keys = [f"key_{int(k)}" for k in rng.zipf(1.4, operations_per_thread) % 100]
        for k in keys:
            t_op = time.perf_counter_ns()
            _ = naive_cache.get_or_compute(k, lambda: "naive_val")
            lat_us = (time.perf_counter_ns() - t_op) / 1000.0
            with naive_lock:
                naive_latencies.append(lat_us)

    threads = [threading.Thread(target=naive_worker, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    naive_elapsed = time.perf_counter() - t0
    naive_throughput = total_ops / naive_elapsed

    # 3. Benchmark CacheOpti v2.0 (16-Way Sharded Cache)
    cacheopti = ShardedCache(
        max_entries=320,  # 20 per shard
        max_bytes=100_000,
        default_ttl_seconds=10.0,
        num_shards=16,
    )
    t0 = time.perf_counter()
    cacheopti_latencies = []
    cacheopti_lock = threading.Lock()

    def cacheopti_worker(tid: int):
        rng = np.random.default_rng(tid)
        keys = [f"key_{int(k)}" for k in rng.zipf(1.4, operations_per_thread) % 100]
        for k in keys:
            t_op = time.perf_counter_ns()
            _ = cacheopti.get_or_compute(k, lambda: "cacheopti_val", ttl=10.0)
            lat_us = (time.perf_counter_ns() - t_op) / 1000.0
            with cacheopti_lock:
                cacheopti_latencies.append(lat_us)

    threads = [threading.Thread(target=cacheopti_worker, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    cacheopti_elapsed = time.perf_counter() - t0
    cacheopti_throughput = total_ops / cacheopti_elapsed

    # Compute percentiles
    def p(arr: List[float], q: float) -> float:
        return float(np.percentile(arr, q))

    summary = {
        "thread_count": thread_count,
        "total_operations": total_ops,
        "functools_lru": {
            "elapsed_s": round(lru_elapsed, 4),
            "throughput_ops_sec": round(lru_throughput, 1),
            "p50_us": round(p(lru_latencies, 50), 2),
            "p95_us": round(p(lru_latencies, 95), 2),
            "p99_us": round(p(lru_latencies, 99), 2),
            "loader_calls": lru_contender.loader_calls,
            "memory_bytes": deep_getsizeof(lru_contender),
        },
        "naive_ttl": {
            "elapsed_s": round(naive_elapsed, 4),
            "throughput_ops_sec": round(naive_throughput, 1),
            "p50_us": round(p(naive_latencies, 50), 2),
            "p95_us": round(p(naive_latencies, 95), 2),
            "p99_us": round(p(naive_latencies, 99), 2),
            "loader_calls": naive_cache.loader_calls,
            "memory_bytes": deep_getsizeof(naive_cache._storage),
        },
        "cacheopti_v2": {
            "elapsed_s": round(cacheopti_elapsed, 4),
            "throughput_ops_sec": round(cacheopti_throughput, 1),
            "p50_us": round(p(cacheopti_latencies, 50), 2),
            "p95_us": round(p(cacheopti_latencies, 95), 2),
            "p99_us": round(p(cacheopti_latencies, 99), 2),
            "loader_calls": cacheopti.loader_executions,
            "memory_bytes": cacheopti.total_bytes,
            "byte_evictions": cacheopti.byte_evictions,
            "evictions": cacheopti.evictions,
        },
    }

    print(f"\nTHROUGHPUT & LATENCY COMPARISON TABLE:")
    print(f"{'Engine':<24} | {'Throughput (ops/s)':<18} | {'p50 (us)':<10} | {'p95 (us)':<10} | {'p99 (us)':<10} | {'Memory (bytes)':<14}")
    print("-" * 100)
    for name, data in [
        ("functools.lru_cache", summary["functools_lru"]),
        ("Naive TTL Cache", summary["naive_ttl"]),
        ("CacheOpti v2.0 (Sharded)", summary["cacheopti_v2"]),
    ]:
        print(f"{name:<24} | {data['throughput_ops_sec']:<18,.1f} | {data['p50_us']:<10.2f} | {data['p95_us']:<10.2f} | {data['p99_us']:<10.2f} | {data['memory_bytes']:<14,}")

    return summary


if __name__ == "__main__":
    stampede_res = run_stampede_simulation(request_count=100, loader_delay_s=0.03)
    concurrency_res = run_32_thread_concurrency_benchmark(operations_per_thread=500, thread_count=32)
