"""Core caching primitives, data structures, and engine for CacheOpti."""

from cacheopti.core.node import CacheNode, DoublyLinkedList
from cacheopti.core.entry import CACHE_MISS, is_cache_miss, CacheEntrySnapshot
from cacheopti.core.policies import BaseCachePolicy, LRUPolicy, FIFOPolicy, LFUPolicy
from cacheopti.core.key_builder import build_cache_key
from cacheopti.core.engine import CacheEngine

__all__ = [
    "CacheNode",
    "DoublyLinkedList",
    "CACHE_MISS",
    "is_cache_miss",
    "CacheEntrySnapshot",
    "BaseCachePolicy",
    "LRUPolicy",
    "FIFOPolicy",
    "LFUPolicy",
    "build_cache_key",
    "CacheEngine",
]
