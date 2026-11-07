"""
CacheOpti v2.0 - High-Concurrency Sharded Caching Engine & XFetch Stampede Prevention.

Coordinates 16 independent cache shards, dual-bound capacity & byte memory limits,
the VLDB XFetch probabilistic early-recomputation algorithm, per-key single-flight coordination,
and pre-allocated NumPy ring buffer performance telemetry.
"""

from __future__ import annotations
import math
import random
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from cacheopti.core.entry import CACHE_MISS, CacheEntrySnapshot, create_snapshot
from cacheopti.core.lru import _Node
from cacheopti.core.policies import BaseCachePolicy, LRUPolicy
from cacheopti.core.shard import _CacheShard
from cacheopti.core.singleflight import SingleFlight
from cacheopti.core.telemetry import PerformanceTelemetry


class ShardedCache:
    """
    CacheOpti v2.0 flagship 16-way sharded in-process caching engine.

    Architecture & Concurrency:
    - 16 independent Cache Shards (_CacheShard) with per-shard RLock.
    - Deterministic routing via hash(key) & 0x0F.
    - Per-key single-flight request coalescing to eliminate duplicate concurrent loaders.
    - VLDB XFetch probabilistic early expiration preventing cache stampedes.
    - Dual-bound memory and entry eviction (max_entries, max_bytes).
    - Pre-allocated NumPy ring buffer recording lookup latency percentiles (p50, p95, p99, p99.9).
    """

    def __init__(
        self,
        max_entries: Optional[int] = None,
        max_bytes: Optional[int] = None,
        default_ttl_seconds: Optional[float] = 30.0,
        num_shards: int = 16,
        telemetry_capacity: int = 100_000,
    ) -> None:
        if num_shards != 16 and (num_shards < 1 or (num_shards & (num_shards - 1)) != 0):
            raise ValueError(f"num_shards must be a positive power of 2, got {num_shards}")

        self.num_shards: int = num_shards
        self._mask: int = num_shards - 1  # 0x0F for 16 shards
        self.default_ttl_seconds: Optional[float] = default_ttl_seconds
        self.default_ttl_ns: Optional[int] = (
            int(default_ttl_seconds * 1_000_000_000) if default_ttl_seconds is not None else None
        )

        self.max_entries: Optional[int] = max_entries
        self.max_bytes: Optional[int] = max_bytes

        # Partition dual bounds equally across shards
        shard_max_entries = (
            max(1, max_entries // num_shards) if max_entries is not None else None
        )
        shard_max_bytes = (
            max(1, max_bytes // num_shards) if max_bytes is not None else None
        )

        # 16 independent cache shards
        self._shards: List[_CacheShard] = [
            _CacheShard(
                shard_id=i,
                max_entries=shard_max_entries,
                max_bytes=shard_max_bytes,
            )
            for i in range(num_shards)
        ]

        # Single-flight coordination & background refresh executor
        self._singleflight: SingleFlight = SingleFlight(max_background_workers=num_shards)

        # Pre-allocated NumPy ring buffer telemetry
        self._telemetry: PerformanceTelemetry = PerformanceTelemetry(capacity=telemetry_capacity)

    def _get_shard(self, key: str) -> _CacheShard:
        """Route key to one of 16 shards using bitwise mask (hash(key) & 0x0F)."""
        shard_idx = hash(key) & self._mask
        return self._shards[shard_idx]

    @staticmethod
    def xfetch_recompute_probability(
        remaining_ttl_s: float,
        delta_s: float,
        beta: float = 1.0,
    ) -> float:
        """
        Calculate the VLDB XFetch probability of early recomputation:
            P = min(1.0, exp(- remaining_ttl / (beta * delta)))
        Example:
            When remaining_ttl == 2 * beta * delta:
            P = exp(-2) ~= 0.135335 ~= 13.53%
        """
        if remaining_ttl_s <= 0.0:
            return 1.0
        if delta_s <= 0.0 or beta <= 0.0:
            return 0.0
        exponent = -remaining_ttl_s / (beta * delta_s)
        if exponent < -700:
            return 0.0
        return min(1.0, math.exp(exponent))

    def get_or_compute(
        self,
        key: str,
        loader_fn: Callable[[], Any],
        ttl: Optional[float] = None,
        beta: float = 1.0,
        serve_stale: bool = True,
    ) -> Any:
        """
        Retrieve cached value or probabilistically recompute via VLDB XFetch algorithm.

        Parameters:
            key: Cache key.
            loader_fn: Upstream computation/database query callback.
            ttl: Time-to-live in seconds (defaults to self.default_ttl_seconds).
            beta: XFetch aggressiveness multiplier (default 1.0).
            serve_stale: If True, serves existing value immediately while refreshing
                         asynchronously in the background when XFetch triggers.
        """
        start_ns = time.monotonic_ns()
        effective_ttl_s = ttl if ttl is not None else self.default_ttl_seconds
        ttl_ns = int(effective_ttl_s * 1_000_000_000) if effective_ttl_s is not None else None

        shard = self._get_shard(key)
        node = shard.peek(key)
        now_ns = time.monotonic_ns()

        if node is not None:
            is_expired = node.is_expired(now_ns)

            if not is_expired:
                # XFetch probabilistic test
                # Condition: -beta * delta_ns * ln(r) > remaining_ns
                should_recompute = False
                if node.delta_ns > 0 and node.ttl_ns is not None:
                    expiry_ns = node.created_at_ns + node.ttl_ns
                    remaining_ns = expiry_ns - now_ns
                    if remaining_ns > 0:
                        r = max(random.random(), 1e-12)
                        if (-beta * node.delta_ns * math.log(r)) > remaining_ns:
                            should_recompute = True
                    else:
                        should_recompute = True

                if not should_recompute:
                    # Clean cache hit
                    hit_node = shard.get(key, now_ns)
                    val = hit_node.value if hit_node else node.value
                    latency_ns = time.monotonic_ns() - start_ns
                    self._telemetry.record_lookup(latency_ns, was_hit=True)
                    return val

                # Early recomputation triggered by XFetch
                if serve_stale:
                    stale_val = node.value

                    def _async_refresh() -> None:
                        t0 = time.monotonic_ns()
                        fresh_val = loader_fn()
                        d_ns = time.monotonic_ns() - t0
                        shard.put(key, fresh_val, time.monotonic_ns(), ttl_ns=ttl_ns, delta_ns=d_ns)
                        self._telemetry.record_loader_execution(1)

                    # Launch single-flight background refresh without blocking current caller
                    self._singleflight.submit_background(key, _async_refresh)
                    shard.get(key, now_ns)  # promote in LRU
                    latency_ns = time.monotonic_ns() - start_ns
                    self._telemetry.record_lookup(latency_ns, was_hit=True)
                    return stale_val

            elif serve_stale and node.value is not None:
                # Hard-expired entry, but caller permits serving stale during refresh
                stale_val = node.value

                def _async_refresh_expired() -> None:
                    t0 = time.monotonic_ns()
                    fresh_val = loader_fn()
                    d_ns = time.monotonic_ns() - t0
                    shard.put(key, fresh_val, time.monotonic_ns(), ttl_ns=ttl_ns, delta_ns=d_ns)
                    self._telemetry.record_loader_execution(1)

                self._singleflight.submit_background(key, _async_refresh_expired)
                latency_ns = time.monotonic_ns() - start_ns
                self._telemetry.record_lookup(latency_ns, was_hit=True)
                return stale_val

        # Cache Miss or Synchronous Recomputation: Coalesce via SingleFlight
        def _call_loader() -> tuple[Any, int]:
            t0 = time.monotonic_ns()
            computed_val = loader_fn()
            d_ns = time.monotonic_ns() - t0
            return computed_val, d_ns

        result_val, comp_delta_ns, is_leader = self._singleflight.do(key, _call_loader)
        total_latency_ns = time.monotonic_ns() - start_ns

        if is_leader:
            shard.put(
                key=key,
                value=result_val,
                now_ns=time.monotonic_ns(),
                ttl_ns=ttl_ns,
                delta_ns=comp_delta_ns,
            )
            self._telemetry.record_loader_execution(1)

        self._telemetry.record_lookup(total_latency_ns, was_hit=False)
        return result_val

    def get(self, key: str) -> Any:
        """
        Direct O(1) lookup. Returns cached value or CACHE_MISS if missing/expired.
        Preserves valid falsy values (0, False, None, [], {}).
        """
        start_ns = time.monotonic_ns()
        now_ns = start_ns
        shard = self._get_shard(key)
        node = shard.get(key, now_ns)

        overhead_ns = time.monotonic_ns() - start_ns
        if node is None:
            self._telemetry.record_lookup(overhead_ns, was_hit=False)
            return CACHE_MISS

        self._telemetry.record_lookup(overhead_ns, was_hit=True)
        return node.value

    def put(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[float] = None,
        delta_ns: int = 0,
    ) -> None:
        """
        Insert or overwrite an entry, update memory footprint, and evict LRU items if needed.
        """
        effective_ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        ttl_ns = int(effective_ttl * 1_000_000_000) if effective_ttl is not None else None
        now_ns = time.monotonic_ns()

        shard = self._get_shard(key)
        shard.put(key, value, now_ns, ttl_ns=ttl_ns, delta_ns=delta_ns)

    def delete(self, key: str) -> bool:
        """Explicitly remove an entry by key."""
        shard = self._get_shard(key)
        return shard.delete(key)

    def clear(self) -> None:
        """Reset all 16 shards and performance telemetry."""
        for shard in self._shards:
            shard.clear()
        self._telemetry.reset()

    def purge_expired(self) -> int:
        """Active sweep across all shards to evict expired items."""
        now_ns = time.monotonic_ns()
        return sum(shard.purge_expired(now_ns) for shard in self._shards)

    def shutdown(self) -> None:
        """Shut down background worker threads cleanly."""
        self._singleflight.shutdown(wait=False)

    @property
    def total_entries(self) -> int:
        return sum(len(s._dict) for s in self._shards)

    @property
    def total_bytes(self) -> int:
        return sum(s.current_bytes for s in self._shards)

    @property
    def hits(self) -> int:
        return self._telemetry.hits

    @property
    def misses(self) -> int:
        return self._telemetry.misses

    @property
    def evictions(self) -> int:
        return sum(s.evictions for s in self._shards)

    @property
    def byte_evictions(self) -> int:
        return sum(s.byte_evictions for s in self._shards)

    @property
    def loader_executions(self) -> int:
        return self._telemetry.loader_executions

    @property
    def hit_rate(self) -> float:
        return self._telemetry.hit_rate

    def get_telemetry(self) -> Dict[str, Any]:
        """Return NumPy-backed latency percentiles and engine operational metrics."""
        summary = self._telemetry.get_summary()
        summary.update({
            "num_shards": self.num_shards,
            "total_entries": self.total_entries,
            "total_bytes": self.total_bytes,
            "max_entries": self.max_entries,
            "max_bytes": self.max_bytes,
            "evictions": self.evictions,
            "byte_evictions": self.byte_evictions,
        })
        return summary

    def get_state(self) -> Dict[str, Any]:
        """Telemetry snapshot formatted for UI HUD."""
        telemetry = self.get_telemetry()
        return {
            "capacity": self.max_entries or 0,
            "occupancy": self.total_entries,
            "total_bytes": self.total_bytes,
            "num_shards": self.num_shards,
            "hits": self.hits,
            "misses": self.misses,
            "total_lookups": self.hits + self.misses,
            "hit_rate_pct": round(self.hit_rate * 100.0, 2),
            "evictions": self.evictions,
            "byte_evictions": self.byte_evictions,
            "loader_executions": self.loader_executions,
            "percentiles": telemetry["percentiles"],
        }


class CacheEngine:
    """
    Observable Caching Engine for CacheOpti Studio & backward compatibility.
    Maintains support for custom eviction policies (LRU/FIFO/LFU), observable
    event rings, and exposes v2.0 dual-bound memory tracking & XFetch get_or_compute.
    """

    def __init__(
        self,
        capacity: int = 5,
        default_ttl_seconds: Optional[float] = 30.0,
        policy: Optional[BaseCachePolicy] = None,
        clock_fn: Optional[Callable[[], float]] = None,
        max_bytes: Optional[int] = None,
    ) -> None:
        if capacity < 1:
            raise ValueError(f"Cache capacity must be at least 1, got {capacity}")

        self.capacity: int = capacity
        self.max_bytes: Optional[int] = max_bytes
        self.default_ttl_seconds: Optional[float] = default_ttl_seconds
        self.policy: BaseCachePolicy = policy if policy is not None else LRUPolicy()
        self._clock: Callable[[], float] = clock_fn if clock_fn is not None else time.monotonic

        # Key -> node mapping for O(1) lookup
        self._storage: dict[str, Any] = {}

        # Telemetry metrics
        self.hits: int = 0
        self.misses: int = 0
        self.evictions: int = 0
        self.expirations: int = 0
        self.byte_evictions: int = 0
        self.current_bytes: int = 0
        self.total_lookup_time_ns: int = 0

        # Pre-allocated NumPy telemetry & SingleFlight coordination
        self._telemetry = PerformanceTelemetry(capacity=50_000)
        self._singleflight = SingleFlight(max_background_workers=8)

        # Observable event log for UI visualization
        self._event_log: list[dict[str, Any]] = []
        self._max_event_log: int = 100

    def _log_event(self, event_type: str, key: str, details: Optional[str] = None) -> None:
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
        start_ns = time.perf_counter_ns()
        now = self._clock()

        node = self._storage.get(key)
        if node is None:
            self.misses += 1
            overhead_ns = time.perf_counter_ns() - start_ns
            self.total_lookup_time_ns += overhead_ns
            self._telemetry.record_lookup(overhead_ns, was_hit=False)
            self._log_event("MISS", key, "Key not found in cache")
            return CACHE_MISS

        if node.is_expired(now):
            self.expirations += 1
            self.misses += 1
            self._purge_node(node)
            overhead_ns = time.perf_counter_ns() - start_ns
            self.total_lookup_time_ns += overhead_ns
            self._telemetry.record_lookup(overhead_ns, was_hit=False)
            self._log_event("EXPIRE", key, f"Entry expired after {node.ttl_seconds}s TTL")
            return CACHE_MISS

        # Valid Cache Hit
        self.hits += 1
        node.touch(now)
        self.policy.on_access(node)

        overhead_ns = time.perf_counter_ns() - start_ns
        self.total_lookup_time_ns += overhead_ns
        self._telemetry.record_lookup(overhead_ns, was_hit=True)
        self._log_event("HIT", key, f"Hit #{node.access_count} (age: {now - node.created_at:.2f}s)")
        return node.value

    def put(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[float] = None,
    ) -> bool:
        now = self._clock()
        effective_ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds

        # Case 1: Overwrite existing key
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

        # Case 2: New insertion - check capacity and evict
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

        from cacheopti.core.node import CacheNode
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

    def get_or_compute(
        self,
        key: str,
        loader_fn: Callable[[], Any],
        ttl_seconds: Optional[float] = None,
        beta: float = 1.0,
        serve_stale: bool = True,
    ) -> Any:
        """XFetch probabilistic get_or_compute for single-engine instances."""
        now = self._clock()
        effective_ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        node = self._storage.get(key)

        if node is not None and not node.is_expired(now):
            # Check XFetch early recomputation
            rem_s = node.remaining_ttl(now) or 0.0
            delta_s = getattr(node, "delta_s", 0.05)
            r = max(random.random(), 1e-12)

            if (-beta * delta_s * math.log(r)) > rem_s:
                # Early recompute triggered
                if serve_stale:
                    stale_val = node.value
                    def _async():
                        t0 = time.perf_counter()
                        val = loader_fn()
                        d_s = time.perf_counter() - t0
                        self.put(key, val, ttl_seconds=effective_ttl)
                        setattr(self._storage.get(key), "delta_s", d_s)
                    self._singleflight.submit_background(key, _async)
                    return stale_val

            return self.get(key)

        # Cache Miss: SingleFlight
        def _exec():
            t0 = time.perf_counter()
            val = loader_fn()
            d_s = time.perf_counter() - t0
            return val, int(d_s * 1e9)

        val, delta_ns, is_leader = self._singleflight.do(key, _exec)
        if is_leader:
            self.put(key, val, ttl_seconds=effective_ttl)
            if key in self._storage:
                setattr(self._storage[key], "delta_s", delta_ns / 1e9)
        return val

    def delete(self, key: str) -> bool:
        node = self._storage.pop(key, None)
        if node is not None:
            self.policy.on_delete(node)
            self._log_event("DELETE", key, "Manually deleted")
            return True
        return False

    def _purge_node(self, node: Any) -> None:
        self._storage.pop(node.key, None)
        self.policy.on_delete(node)

    def purge_expired(self) -> int:
        now = self._clock()
        expired_keys = [k for k, node in self._storage.items() if node.is_expired(now)]
        for k in expired_keys:
            node = self._storage[k]
            self._purge_node(node)
            self.expirations += 1
            self._log_event("EXPIRE", k, "Purged by active sweep")
        return len(expired_keys)

    def clear(self) -> None:
        self._storage.clear()
        self.policy.clear()
        self._log_event("CLEAR", "*", "Cache storage and policy cleared")

    def reset_metrics(self) -> None:
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0
        self.total_lookup_time_ns = 0
        self._telemetry.reset()
        self._event_log.clear()

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total

    @property
    def average_lookup_overhead_us(self) -> float:
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return (self.total_lookup_time_ns / total) / 1000.0

    def get_state(self) -> dict[str, Any]:
        now = self._clock()
        active_count = sum(1 for n in self._storage.values() if not n.is_expired(now))
        expired_count = len(self._storage) - active_count
        percentiles = self._telemetry.get_percentiles()

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
            "percentiles": percentiles,
        }

    def get_entries(self) -> list[CacheEntrySnapshot]:
        ordered_nodes = self.policy.to_ordered_list()
        now = self._clock()
        return [
            create_snapshot(node, position=idx, current_time=now)
            for idx, node in enumerate(ordered_nodes)
        ]

    def get_recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._event_log[-limit:]
