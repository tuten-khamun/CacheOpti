"""
CacheCraft / CacheOpti - Function Instrumentation Decorator.

Provides the @cached decorator to wrap Python functions with automatic
cache lookup, deterministic key hashing, error safety, and latency instrumentation.
"""

from __future__ import annotations
import functools
import time
from typing import Any, Callable, Optional
from cacheopti.core.engine import CacheEngine
from cacheopti.core.entry import is_cache_miss
from cacheopti.core.key_builder import build_cache_key
from cacheopti.instrumentation.tracker import OperationTracker, default_tracker


def cached(
    cache_engine: CacheEngine,
    ttl_seconds: Optional[float] = None,
    prefix: Optional[str] = None,
    tracker: Optional[OperationTracker] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that memoizes a function using CacheEngine and logs execution telemetry.

    Example:
        @cached(cache_engine, ttl_seconds=15.0)
        def expensive_lookup(item_id: int):
            ...
    """
    active_tracker = tracker if tracker is not None else default_tracker

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        op_name = prefix or func.__qualname__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            call_start_ns = time.perf_counter_ns()
            key = build_cache_key(op_name, *args, **kwargs)

            # Measure cache lookup overhead
            lookup_start_ns = time.perf_counter_ns()
            cached_val = cache_engine.get(key)
            lookup_overhead_us = (time.perf_counter_ns() - lookup_start_ns) / 1000.0

            if not is_cache_miss(cached_val):
                # Cache Hit
                total_duration_ms = (time.perf_counter_ns() - call_start_ns) / 1_000_000.0
                active_tracker.record_execution(
                    operation_name=op_name,
                    cache_key=key,
                    was_hit=True,
                    total_duration_ms=total_duration_ms,
                    lookup_overhead_us=lookup_overhead_us,
                    compute_duration_ms=0.0,
                    is_error=False,
                )
                return cached_val

            # Cache Miss: execute the underlying function
            compute_start_ns = time.perf_counter_ns()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                compute_duration_ms = (time.perf_counter_ns() - compute_start_ns) / 1_000_000.0
                total_duration_ms = (time.perf_counter_ns() - call_start_ns) / 1_000_000.0
                active_tracker.record_execution(
                    operation_name=op_name,
                    cache_key=key,
                    was_hit=False,
                    total_duration_ms=total_duration_ms,
                    lookup_overhead_us=lookup_overhead_us,
                    compute_duration_ms=compute_duration_ms,
                    is_error=True,
                    error_message=str(exc),
                )
                raise exc

            compute_duration_ms = (time.perf_counter_ns() - compute_start_ns) / 1_000_000.0
            total_duration_ms = (time.perf_counter_ns() - call_start_ns) / 1_000_000.0

            # Store result in cache
            cache_engine.put(key, result, ttl_seconds=ttl_seconds)

            active_tracker.record_execution(
                operation_name=op_name,
                cache_key=key,
                was_hit=False,
                total_duration_ms=total_duration_ms,
                lookup_overhead_us=lookup_overhead_us,
                compute_duration_ms=compute_duration_ms,
                is_error=False,
            )
            return result

        # Expose cache controls on the wrapper
        wrapper.cache = cache_engine  # type: ignore[attr-defined]
        wrapper.operation_name = op_name  # type: ignore[attr-defined]
        return wrapper

    return decorator
