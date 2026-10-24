"""
CacheCraft / CacheOpti - Benchmark Runner and Comparative Profiler.

Executes controlled, reproducible benchmarks comparing uncached baselines
against cached execution with full telemetry: cold-start vs warm-cache,
speedup factors, latency distributions, and parameter sweeps.
"""

from __future__ import annotations
import math
import statistics
import time
from dataclasses import dataclass, asdict
from typing import Any, Callable, Sequence, Optional
from cacheopti.core.engine import CacheEngine
from cacheopti.core.entry import is_cache_miss
from cacheopti.core.policies import BaseCachePolicy, LRUPolicy


@dataclass
class BenchmarkResult:
    """Detailed results from a comparative benchmark run."""

    workload_name: str
    total_requests: int
    uncached_total_ms: float
    uncached_mean_ms: float
    uncached_median_ms: float
    uncached_p95_ms: float
    cached_total_ms: float
    cached_mean_ms: float
    cached_median_ms: float
    cached_p95_ms: float
    hits: int
    misses: int
    hit_rate_pct: float
    evictions: int
    expirations: int
    observed_time_saved_ms: float
    speedup_factor: float
    avg_lookup_overhead_us: float
    cold_requests: int
    cold_misses: int
    warm_hits: int
    samples_uncached: list[float]
    samples_cached: list[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _calc_p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, math.ceil(0.95 * len(s)) - 1)
    return s[idx]


class BenchmarkRunner:
    """Orchestrates comparative benchmarking between uncached and cached execution."""

    @staticmethod
    def run_comparison(
        operation: Callable[[Any], Any],
        workload: Sequence[Any],
        cache_capacity: int = 10,
        cache_ttl_seconds: Optional[float] = 60.0,
        policy: Optional[BaseCachePolicy] = None,
        workload_name: str = "Standard Workload",
    ) -> BenchmarkResult:
        """
        Run side-by-side benchmark:
        1. Measure uncached baseline across workload.
        2. Measure cached execution across identical workload.
        3. Compare latencies, hit rate, and compute speedups.
        """
        # Step 1: Uncached Baseline Execution
        uncached_latencies: list[float] = []
        for item in workload:
            t0 = time.perf_counter_ns()
            _ = operation(item)
            t_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            uncached_latencies.append(t_ms)

        # Step 2: Cached Execution
        cache = CacheEngine(
            capacity=cache_capacity,
            default_ttl_seconds=cache_ttl_seconds,
            policy=policy or LRUPolicy(),
        )

        cached_latencies: list[float] = []
        seen_keys: set[str] = set()
        cold_requests = 0
        cold_misses = 0
        warm_hits = 0

        for item in workload:
            key = f"bench:{item}"
            is_cold = key not in seen_keys
            if is_cold:
                cold_requests += 1
                seen_keys.add(key)

            t0 = time.perf_counter_ns()
            val = cache.get(key)
            if is_cache_miss(val):
                if is_cold:
                    cold_misses += 1
                # Miss: compute and store
                val = operation(item)
                cache.put(key, val)
            else:
                if not is_cold:
                    warm_hits += 1

            t_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            cached_latencies.append(t_ms)

        # Step 3: Statistical Aggregation
        uncached_total = sum(uncached_latencies)
        uncached_mean = statistics.mean(uncached_latencies) if uncached_latencies else 0.0
        uncached_median = statistics.median(uncached_latencies) if uncached_latencies else 0.0
        uncached_p95 = _calc_p95(uncached_latencies)

        cached_total = sum(cached_latencies)
        cached_mean = statistics.mean(cached_latencies) if cached_latencies else 0.0
        cached_median = statistics.median(cached_latencies) if cached_latencies else 0.0
        cached_p95 = _calc_p95(cached_latencies)

        time_saved = max(0.0, uncached_total - cached_total)
        speedup = (uncached_total / cached_total) if cached_total > 0 else 1.0

        return BenchmarkResult(
            workload_name=workload_name,
            total_requests=len(workload),
            uncached_total_ms=round(uncached_total, 2),
            uncached_mean_ms=round(uncached_mean, 3),
            uncached_median_ms=round(uncached_median, 3),
            uncached_p95_ms=round(uncached_p95, 3),
            cached_total_ms=round(cached_total, 2),
            cached_mean_ms=round(cached_mean, 3),
            cached_median_ms=round(cached_median, 3),
            cached_p95_ms=round(cached_p95, 3),
            hits=cache.hits,
            misses=cache.misses,
            hit_rate_pct=round(cache.hit_rate * 100.0, 2),
            evictions=cache.evictions,
            expirations=cache.expirations,
            observed_time_saved_ms=round(time_saved, 2),
            speedup_factor=round(speedup, 2),
            avg_lookup_overhead_us=round(cache.average_lookup_overhead_us, 3),
            cold_requests=cold_requests,
            cold_misses=cold_misses,
            warm_hits=warm_hits,
            samples_uncached=uncached_latencies[:50],  # sample preview for UI plotting
            samples_cached=cached_latencies[:50],
        )

    @staticmethod
    def run_capacity_sweep(
        operation: Callable[[Any], Any],
        workload: Sequence[Any],
        capacities: Sequence[int] = (2, 4, 8, 16, 32),
        default_ttl_seconds: Optional[float] = 60.0,
    ) -> list[dict[str, Any]]:
        """Evaluate how varying cache capacity impacts hit rates and total runtimes."""
        results: list[dict[str, Any]] = []
        for cap in capacities:
            res = BenchmarkRunner.run_comparison(
                operation=operation,
                workload=workload,
                cache_capacity=cap,
                cache_ttl_seconds=default_ttl_seconds,
                workload_name=f"Capacity={cap}",
            )
            results.append({
                "capacity": cap,
                "hit_rate_pct": res.hit_rate_pct,
                "hits": res.hits,
                "misses": res.misses,
                "evictions": res.evictions,
                "total_time_ms": res.cached_total_ms,
                "speedup_factor": res.speedup_factor,
            })
        return results
