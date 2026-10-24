"""
CacheCraft / CacheOpti - Instrumentation and Performance Metrics.

Tracks operation-level execution stats, latency distributions (mean, median, p95),
cache overhead, and empirical time savings.
"""

from __future__ import annotations
import math
import statistics
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class ExecutionRecord:
    """Detailed record of a single function or API execution."""

    timestamp: float
    operation_name: str
    cache_key: str
    was_hit: bool
    total_duration_ms: float
    lookup_overhead_us: float
    compute_duration_ms: float
    is_error: bool = False
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OperationMetrics:
    """Maintains statistical metrics for an instrumented operation."""

    def __init__(self, operation_name: str) -> None:
        self.operation_name: str = operation_name
        self.total_calls: int = 0
        self.hits: int = 0
        self.misses: int = 0
        self.errors: int = 0

        self.latencies_ms: list[float] = []
        self.lookup_overheads_us: list[float] = []
        self.uncached_latencies_ms: list[float] = []
        self.cached_latencies_ms: list[float] = []

        self.recent_records: list[ExecutionRecord] = []
        self._max_recent: int = 100

    def record_execution(self, record: ExecutionRecord) -> None:
        """Ingest a single execution record and update statistics."""
        self.total_calls += 1
        if record.is_error:
            self.errors += 1

        if record.was_hit:
            self.hits += 1
            self.cached_latencies_ms.append(record.total_duration_ms)
        else:
            self.misses += 1
            self.uncached_latencies_ms.append(record.compute_duration_ms)

        self.latencies_ms.append(record.total_duration_ms)
        self.lookup_overheads_us.append(record.lookup_overhead_us)

        self.recent_records.append(record)
        if len(self.recent_records) > self._max_recent:
            self.recent_records.pop(0)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total > 0 else 0.0

    @property
    def mean_latency_ms(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def median_latency_ms(self) -> float:
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        sorted_latencies = sorted(self.latencies_ms)
        idx = max(0, math.ceil(0.95 * len(sorted_latencies)) - 1)
        return sorted_latencies[idx]

    @property
    def avg_uncached_latency_ms(self) -> float:
        return statistics.mean(self.uncached_latencies_ms) if self.uncached_latencies_ms else 0.0

    @property
    def avg_cached_latency_ms(self) -> float:
        return statistics.mean(self.cached_latencies_ms) if self.cached_latencies_ms else 0.0

    @property
    def avg_lookup_overhead_us(self) -> float:
        return statistics.mean(self.lookup_overheads_us) if self.lookup_overheads_us else 0.0

    @property
    def observed_time_saved_ms(self) -> float:
        """
        Defensible calculation of empirical time saved:
        For every hit, the time saved is the average uncached execution time minus
        the cache retrieval time.
        """
        if not self.uncached_latencies_ms or self.hits == 0:
            return 0.0
        baseline_cost = self.avg_uncached_latency_ms * self.hits
        cached_cost = sum(self.cached_latencies_ms)
        return max(0.0, baseline_cost - cached_cost)

    def summary(self) -> dict[str, Any]:
        """Return a structured overview of operation performance."""
        return {
            "operation": self.operation_name,
            "total_calls": self.total_calls,
            "hits": self.hits,
            "misses": self.misses,
            "errors": self.errors,
            "hit_rate_pct": round(self.hit_rate * 100.0, 2),
            "mean_latency_ms": round(self.mean_latency_ms, 3),
            "median_latency_ms": round(self.median_latency_ms, 3),
            "p95_latency_ms": round(self.p95_latency_ms, 3),
            "avg_uncached_latency_ms": round(self.avg_uncached_latency_ms, 3),
            "avg_cached_latency_ms": round(self.avg_cached_latency_ms, 3),
            "avg_lookup_overhead_us": round(self.avg_lookup_overhead_us, 3),
            "observed_time_saved_ms": round(self.observed_time_saved_ms, 2),
        }

    def reset(self) -> None:
        """Reset metrics counters."""
        self.total_calls = 0
        self.hits = 0
        self.misses = 0
        self.errors = 0
        self.latencies_ms.clear()
        self.lookup_overheads_us.clear()
        self.uncached_latencies_ms.clear()
        self.cached_latencies_ms.clear()
        self.recent_records.clear()
