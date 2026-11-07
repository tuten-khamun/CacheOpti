"""
CacheOpti v2.0 - High-Concurrency, Memory-Bounded Caching Engine.

Engineered with 16-way sharded locking, VLDB XFetch probabilistic early expiration,
per-key single-flight request coalescing, dual-bound LRU eviction, and pre-allocated
NumPy ring buffer telemetry.
"""

from cacheopti.core.engine import ShardedCache, CacheEngine
from cacheopti.core.lru import _Node, DoublyLinkedList
from cacheopti.core.shard import _CacheShard, CacheShard
from cacheopti.core.memory import deep_getsizeof, calculate_entry_size
from cacheopti.core.singleflight import SingleFlight
from cacheopti.core.telemetry import PerformanceTelemetry
from cacheopti.core.entry import CACHE_MISS, is_cache_miss
from cacheopti.instrumentation.decorator import cached

__version__ = "2.0.0"

__all__ = [
    "ShardedCache",
    "CacheEngine",
    "_Node",
    "DoublyLinkedList",
    "_CacheShard",
    "CacheShard",
    "deep_getsizeof",
    "calculate_entry_size",
    "SingleFlight",
    "PerformanceTelemetry",
    "CACHE_MISS",
    "is_cache_miss",
    "cached",
    "__version__",
]
