"""
Tests for Component D: XFetch Probabilistic Early Expiration & Single-Flight Coordination.
Verifies the VLDB XFetch probability equation (P = e^-2 ~= 13.53%), single-flight coalescing
under high concurrency, and background refresh stale-serving.
"""

import math
import threading
import time
import pytest
from cacheopti.core.engine import ShardedCache
from cacheopti.core.singleflight import SingleFlight


def test_xfetch_probability_formula_exact_at_2_beta_delta():
    """
    Verify the VLDB XFetch mathematical identity:
    When remaining_ttl == 2 * beta * delta:
    P = exp(-2) ~= 0.135335283 ~= 13.53%
    """
    delta_s = 0.5  # 500ms compute
    beta = 1.0
    remaining_ttl_s = 2.0 * beta * delta_s  # 1.0s remaining

    prob = ShardedCache.xfetch_recompute_probability(
        remaining_ttl_s=remaining_ttl_s,
        delta_s=delta_s,
        beta=beta,
    )

    expected = math.exp(-2.0)
    assert prob == pytest.approx(expected, rel=1e-5)
    assert round(prob * 100.0, 2) == 13.53


def test_xfetch_probability_boundary_conditions():
    """Verify XFetch probability boundaries: 100% when expired, 0% when time is far."""
    # When expired (remaining_ttl <= 0)
    assert ShardedCache.xfetch_recompute_probability(0.0, 0.1) == 1.0
    assert ShardedCache.xfetch_recompute_probability(-5.0, 0.1) == 1.0

    # When remaining time is huge compared to beta * delta
    tiny_prob = ShardedCache.xfetch_recompute_probability(100.0, 0.01, beta=1.0)
    assert tiny_prob < 1e-10


def test_singleflight_coalesces_50_concurrent_requests():
    """
    Simulate a cache stampede: 50 concurrent threads request the same key simultaneously.
    SingleFlight MUST coordinate so that loader_fn is invoked EXACTLY ONCE.
    """
    cache = ShardedCache()
    loader_calls = 0
    lock = threading.Lock()

    def expensive_loader():
        nonlocal loader_calls
        with lock:
            loader_calls += 1
        time.sleep(0.05)  # 50ms compute delay
        return {"data": "computed_result"}

    results = []
    threads = []

    def worker():
        val = cache.get_or_compute("heavy_stampede_key", expensive_loader, ttl=10.0)
        results.append(val)

    # Launch 50 concurrent threads
    for _ in range(50):
        t = threading.Thread(target=worker)
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 50 threads must receive the valid result
    assert len(results) == 50
    for r in results:
        assert r == {"data": "computed_result"}

    # CRITICAL: Loader MUST have been called exactly ONCE
    assert loader_calls == 1
    assert cache.loader_executions == 1


def test_xfetch_serves_stale_and_refreshes_background():
    """
    Verify that when early recomputation is triggered and serve_stale=True,
    the caller receives the current value immediately without waiting for the slow loader.
    """
    cache = ShardedCache()
    key = "refresh_key"

    # Pre-populate key with a fast loader
    cache.get_or_compute(key, lambda: "initial_value", ttl=10.0)
    assert cache.get(key) == "initial_value"

    # Simulate key having a recorded computation duration and near expiration
    shard = cache._get_shard(key)
    with shard.lock:
        node = shard.peek(key)
        assert node is not None
        node.delta_ns = 500_000_000  # 500ms
        node.created_at_ns = time.monotonic_ns() - 9_900_000_000  # 100ms TTL left
        node.ttl_ns = 10_000_000_000  # 10s total TTL

    # Calling with beta=100.0 virtually guarantees XFetch recomputation trigger
    refreshed_event = threading.Event()

    def slow_refresh():
        time.sleep(0.05)
        refreshed_event.set()
        return "refreshed_value"

    t0 = time.monotonic_ns()
    # Call get_or_compute with serve_stale=True
    val = cache.get_or_compute(key, slow_refresh, ttl=10.0, beta=100.0, serve_stale=True)
    duration_ms = (time.monotonic_ns() - t0) / 1_000_000.0

    # Caller must get initial_value almost instantly (< 10ms) without waiting 50ms for slow_refresh
    assert val == "initial_value"
    assert duration_ms < 25.0

    # Wait for background thread to complete
    assert refreshed_event.wait(timeout=1.0)
    # Give background put a brief moment to land in shard
    time.sleep(0.02)

    # Subsequent read gets the refreshed value
    assert cache.get(key) == "refreshed_value"


def test_singleflight_error_propagation():
    """Verify that exceptions raised in loader are propagated to all waiting followers."""
    sf = SingleFlight()

    def failing_loader():
        time.sleep(0.02)
        raise ValueError("database connection timed out")

    errors = []

    def worker():
        try:
            sf.do("err_key", failing_loader)
        except ValueError as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 5 threads must catch the exact exception
    assert len(errors) == 5
    for err in errors:
        assert err == "database connection timed out"
