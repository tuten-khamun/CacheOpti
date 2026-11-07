"""
Tests for Component E: Performance Telemetry.
Verifies pre-allocated NumPy ring buffer, latency percentiles (p50, p95, p99, p99.9),
counters (hits, misses, loader executions, byte evictions), and concurrent write safety.
"""

import threading
import numpy as np
import pytest
from cacheopti.core.telemetry import PerformanceTelemetry


def test_numpy_ring_buffer_preallocation():
    """Verify that the telemetry buffer pre-allocates a contiguous NumPy array."""
    telemetry = PerformanceTelemetry(capacity=1000)
    assert isinstance(telemetry._latencies_ns, np.ndarray)
    assert telemetry._latencies_ns.dtype == np.int64
    assert len(telemetry._latencies_ns) == 1000


def test_percentile_calculation_accuracy():
    """Verify percentiles p50, p95, p99, p99.9 match known statistical values."""
    telemetry = PerformanceTelemetry(capacity=10_000)

    # Insert 1,000 evenly spaced samples from 1us (1,000ns) to 1000us (1,000,000ns)
    for i in range(1, 1001):
        telemetry.record_lookup(latency_ns=i * 1000, was_hit=(i % 2 == 0))

    percentiles = telemetry.get_percentiles()
    assert percentiles["sample_count"] == 1000
    assert percentiles["p50_us"] == pytest.approx(500.5, abs=5.0)
    assert percentiles["p95_us"] == pytest.approx(950.0, abs=5.0)
    assert percentiles["p99_us"] == pytest.approx(990.0, abs=5.0)
    assert percentiles["p99_9_us"] == pytest.approx(999.0, abs=5.0)


def test_telemetry_counters_and_summary():
    """Verify operational counters for hits, misses, evictions, and byte evictions."""
    telemetry = PerformanceTelemetry(capacity=500)
    telemetry.record_lookup(latency_ns=100, was_hit=True)
    telemetry.record_lookup(latency_ns=200, was_hit=True)
    telemetry.record_lookup(latency_ns=300, was_hit=False)

    telemetry.record_loader_execution(count=5)
    telemetry.record_byte_eviction(bytes_evicted=4096, entry_count=2)

    summary = telemetry.get_summary()
    assert summary["hits"] == 2
    assert summary["misses"] == 1
    assert summary["total_lookups"] == 3
    assert summary["hit_rate_pct"] == pytest.approx(66.67, abs=0.1)
    assert summary["loader_executions"] == 5
    assert summary["byte_evictions"] == 4096
    assert summary["evictions"] == 2


def test_concurrent_telemetry_thread_safety():
    """
    Verify thread safety: 32 concurrent threads hammering the telemetry ring buffer
    simultaneously without data corruption or lost sample counts.
    """
    telemetry = PerformanceTelemetry(capacity=50_000)
    samples_per_thread = 500
    thread_count = 32

    def worker():
        for i in range(samples_per_thread):
            telemetry.record_lookup(latency_ns=1000 + i, was_hit=True)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected_samples = thread_count * samples_per_thread
    assert telemetry.hits == expected_samples
    assert telemetry._total_samples == expected_samples

    # Percentiles must compute without crashing
    percentiles = telemetry.get_percentiles()
    assert percentiles["sample_count"] == expected_samples
    assert percentiles["p50_us"] > 0.0
