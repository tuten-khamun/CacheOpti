"""
CacheCraft / CacheOpti - Core Cache Engine.

Coordinates deterministic in-memory storage, monotonic TTL expiration,
pluggable eviction policies (LRU/FIFO/LFU), and fine-grained telemetry.
"""

from __future__ import annotations
import time
from typing import Any, Optional, Callable
from cacheopti.core.node import CacheNode
from cacheopti.core.entry import CACHE_MISS, CacheEntrySnapshot, create_snapshot
from cacheopti.core.policies import BaseCachePolicy, LRUPolicy


class CacheEngine:
    """
    High-performance in-memory caching engine with:
    - O(1) hash map storage + doubly linked list LRU
    - Monotonic clock TTL calculations
    - Pluggable eviction policy
    - Fine-grained telemetry and event logging
    """

    def __init__(
        self,
        capacity: int = 5,
        default_ttl_seconds: Optional[float] = 30.0,
        policy: Optional[BaseCachePolicy] = None,
        clock_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        if capacity < 1:
            raise ValueError(f"Cache capacity must be at least 1, got {capacity}")

        self.capacity: int = capacity
        self.default_ttl_seconds: Optional[float] = default_ttl_seconds
        self.policy: BaseCachePolicy = policy if policy is not None else LRUPolicy()
        self._clock: Callable[[], float] = clock_fn if clock_fn is not None else time.monotonic

        # Key -> CacheNode mapping for O(1) direct lookup
        self._storage: dict[str, CacheNode] = {}

        # Telemetry metrics
        self.hits: int = 0
        self.misses: int = 0
        self.evictions: int = 0
        self.expirations: int = 0
        self.total_lookup_time_ns: int = 0

        # Ring-buffer of recent operational events for UI telemetry
        self._event_log: list[dict[str, Any]] = []
        self._max_event_log: int = 100

    def _log_event(self, event_type: str, key: str, details: Optional[str] = None) -> None:
        """Append an event to the observable event log."""
        event = {
            "timestamp": time.time(),
            "monotonic": self._clock(),
            "type": event_type,
            "key": key,
            "details": details or "",
            "size": len(self._storage),
            "capacity": self.capacity,
        }
        self._event_log.append(event)
        if len(self._event_log) > self._max_event_log:
            self._event_log.pop(0)

    def get(self, key: str) -> Any:
        """
        Retrieve an item from the cache.
        Returns CACHE_MISS if key does not exist or has expired.
        Falsy values (0, False, None, [], {}) are returned intact as hits.
        """
        start_ns = time.perf_counter_ns()
        now = self._clock()

        node = self._storage.get(key)
        if node is None:
            self.misses += 1
            overhead_ns = time.perf_counter_ns() - start_ns
            self.total_lookup_time_ns += overhead_ns
            self._log_event("MISS", key, "Key not found in cache")
            return CACHE_MISS

        # Check for TTL expiration
        if node.is_expired(now):
            self.expirations += 1
            self.misses += 1
            self._purge_node(node)
            overhead_ns = time.perf_counter_ns() - start_ns
            self.total_lookup_time_ns += overhead_ns
            self._log_event(
                "EXPIRE",
                key,
                f"Entry expired after {node.ttl_seconds}s TTL",
            )
            return CACHE_MISS

        # Valid Cache Hit
        self.hits += 1
        node.touch(now)
        self.policy.on_access(node)

        overhead_ns = time.perf_counter_ns() - start_ns
        self.total_lookup_time_ns += overhead_ns
        self._log_event("HIT", key, f"Hit #{node.access_count} (age: {now - node.created_at:.2f}s)")
        return node.value

    def put(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[float] = None,
    ) -> bool:
        """
        Insert or update a cache entry.
        If cache is at capacity, evicts a candidate according to the active policy.
        """
        now = self._clock()
        effective_ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds

        # Case 1: Overwriting an existing key
        if key in self._storage:
            existing_node = self._storage[key]
            existing_node.value = value
            existing_node.created_at = now
            existing_node.last_accessed_at = now
            existing_node.ttl_seconds = effective_ttl
            existing_node.access_count += 1
            self.policy.on_update(existing_node)
            self._log_event("UPDATE", key, f"Value updated with TTL: {effective_ttl}s")
            return True

        # Case 2: Inserting a new key - check capacity and evict if full
        if len(self._storage) >= self.capacity:
            victim = self.policy.select_victim()
            if victim is not None:
                self._storage.pop(victim.key, None)
                self.evictions += 1
                self._log_event(
                    "EVICT",
                    victim.key,
                    f"Evicted by {self.policy.name} policy to make room for {key}",
                )

        # Create and link new node
        new_node = CacheNode(
            key=key,
            value=value,
            created_at=now,
            ttl_seconds=effective_ttl,
        )
        self._storage[key] = new_node
        self.policy.on_insert(new_node)
        self._log_event("INSERT", key, f"Inserted new entry with TTL: {effective_ttl}s")
        return True

    def delete(self, key: str) -> bool:
        """Explicitly remove an entry by key."""
        node = self._storage.pop(key, None)
        if node is not None:
            self.policy.on_delete(node)
            self._log_event("DELETE", key, "Manually deleted")
            return True
        return False

    def _purge_node(self, node: CacheNode) -> None:
        """Helper to remove an expired node from storage and policy."""
        self._storage.pop(node.key, None)
        self.policy.on_delete(node)

    def purge_expired(self) -> int:
        """Active sweep to clean up all expired entries at once."""
        now = self._clock()
        expired_keys = [
            k for k, node in self._storage.items()
            if node.is_expired(now)
        ]
        for k in expired_keys:
            node = self._storage[k]
            self._purge_node(node)
            self.expirations += 1
            self._log_event("EXPIRE", k, "Purged by active sweep")
        return len(expired_keys)

    def clear(self) -> None:
        """Reset the cache state, policy, and storage."""
        self._storage.clear()
        self.policy.clear()
        self._log_event("CLEAR", "*", "Cache storage and policy cleared")

    def reset_metrics(self) -> None:
        """Reset operational telemetry counters."""
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0
        self.total_lookup_time_ns = 0
        self._event_log.clear()

    @property
    def hit_rate(self) -> float:
        """Calculate hit rate: hits / (hits + misses)."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total

    @property
    def average_lookup_overhead_us(self) -> float:
        """Average cache lookup time in microseconds."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return (self.total_lookup_time_ns / total) / 1000.0

    def get_state(self) -> dict[str, Any]:
        """Return a structured telemetry dictionary of current engine state."""
        now = self._clock()
        # Count currently active vs expired in storage
        active_count = sum(1 for n in self._storage.values() if not n.is_expired(now))
        expired_count = len(self._storage) - active_count

        return {
            "capacity": self.capacity,
            "occupancy": len(self._storage),
            "active_entries": active_count,
            "expired_in_storage": expired_count,
            "default_ttl_seconds": self.default_ttl_seconds,
            "policy": self.policy.name,
            "hits": self.hits,
            "misses": self.misses,
            "total_lookups": self.hits + self.misses,
            "hit_rate_pct": round(self.hit_rate * 100.0, 2),
            "evictions": self.evictions,
            "expirations": self.expirations,
            "avg_lookup_overhead_us": round(self.average_lookup_overhead_us, 3),
        }

    def get_entries(self) -> list[CacheEntrySnapshot]:
        """Return snapshots of all entries ordered by policy priority (MRU to LRU)."""
        ordered_nodes = self.policy.to_ordered_list()
        now = self._clock()
        return [
            create_snapshot(node, position=idx, current_time=now)
            for idx, node in enumerate(ordered_nodes)
        ]

    def get_recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent operational events."""
        return self._event_log[-limit:]
