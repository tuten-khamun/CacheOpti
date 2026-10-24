"""
CacheCraft / CacheOpti - Operation Execution Tracker.

Maintains registry of monitored operations, coordinates telemetry collection,
and exports live streams of execution records for UI telemetry panels.
"""

from __future__ import annotations
import threading
import time
from typing import Any, Optional
from cacheopti.instrumentation.metrics import ExecutionRecord, OperationMetrics


class OperationTracker:
    """Central registry and telemetry collector for instrumented calls."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._metrics: dict[str, OperationMetrics] = {}
        self._global_records: list[ExecutionRecord] = []
        self._max_records: int = 200

    def get_or_create_metrics(self, operation_name: str) -> OperationMetrics:
        """Get or initialize metrics for a named operation."""
        with self._lock:
            if operation_name not in self._metrics:
                self._metrics[operation_name] = OperationMetrics(operation_name)
            return self._metrics[operation_name]

    def record_execution(
        self,
        operation_name: str,
        cache_key: str,
        was_hit: bool,
        total_duration_ms: float,
        lookup_overhead_us: float,
        compute_duration_ms: float,
        is_error: bool = False,
        error_message: Optional[str] = None,
    ) -> ExecutionRecord:
        """Record an execution into operation metrics and the global telemetry stream."""
        record = ExecutionRecord(
            timestamp=time.time(),
            operation_name=operation_name,
            cache_key=cache_key,
            was_hit=was_hit,
            total_duration_ms=total_duration_ms,
            lookup_overhead_us=lookup_overhead_us,
            compute_duration_ms=compute_duration_ms,
            is_error=is_error,
            error_message=error_message,
        )

        with self._lock:
            metrics = self.get_or_create_metrics(operation_name)
            metrics.record_execution(record)

            self._global_records.append(record)
            if len(self._global_records) > self._max_records:
                self._global_records.pop(0)

        return record

    def get_all_metrics(self) -> dict[str, dict[str, Any]]:
        """Return summaries for all registered operations."""
        with self._lock:
            return {
                name: m.summary()
                for name, m in self._metrics.items()
            }

    def get_recent_records(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent execution records in JSON-serializable format."""
        with self._lock:
            return [r.to_dict() for r in self._global_records[-limit:]]

    def clear(self) -> None:
        """Reset all metrics and historical records."""
        with self._lock:
            for m in self._metrics.values():
                m.reset()
            self._global_records.clear()


# Default singleton instance
default_tracker = OperationTracker()
