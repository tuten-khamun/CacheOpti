"""Instrumentation, metrics recording, and function decorators for CacheOpti."""

from cacheopti.instrumentation.metrics import ExecutionRecord, OperationMetrics
from cacheopti.instrumentation.tracker import OperationTracker, default_tracker
from cacheopti.instrumentation.decorator import cached

__all__ = [
    "ExecutionRecord",
    "OperationMetrics",
    "OperationTracker",
    "default_tracker",
    "cached",
]
