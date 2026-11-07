"""Core caching primitives, data structures, and engine for CacheOpti v2.0."""

from cacheopti.core.node import CacheNode
from cacheopti.core.lru import _Node, DoublyLinkedList
from cacheopti.core.entry import CACHE_MISS, is_cache_miss, CacheEntrySnapshot, create_snapshot
from cacheopti.core.memory import deep_getsizeof, calculate_entry_size
from cacheopti.core.shard import _CacheShard, CacheShard
from cacheopti.core.singleflight import SingleFlight
from cacheopti.core.telemetry import PerformanceTelemetry
from cacheopti.core.policies import BaseCachePolicy, LRUPolicy, FIFOPolicy, LFUPolicy
from cacheopti.core.key_builder import build_cache_key
from cacheopti.core.engine import CacheEngine, ShardedCache

__all__ = [
    "_Node",
    "CacheNode",
    "DoublyLinkedList",
    "CACHE_MISS",
    "is_cache_miss",
    "CacheEntrySnapshot",
    "create_snapshot",
    "deep_getsizeof",
    "calculate_entry_size",
    "_CacheShard",
    "CacheShard",
    "SingleFlight",
    "PerformanceTelemetry",
    "BaseCachePolicy",
    "LRUPolicy",
    "FIFOPolicy",
    "LFUPolicy",
    "build_cache_key",
    "CacheEngine",
    "ShardedCache",
]
