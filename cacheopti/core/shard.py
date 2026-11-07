"""
CacheOpti v2.0 - Independent Cache Shard.

Each _CacheShard manages an isolated segment of the cache key space with:
- An independent Python dict for O(1) key-to-node mapping.
- An independent DoublyLinkedList with _head and _tail sentinels for O(1) LRU updates.
- An independent threading.RLock minimizing lock contention across disjoint keys.
- Dual-bound capacity and byte enforcement (max_entries, max_bytes).
- Precise recursive memory accounting for inserts, updates (overwrites), and evictions.
"""

from __future__ import annotations
import threading
from typing import Any, Dict, List, Optional
from cacheopti.core.lru import _Node, DoublyLinkedList
from cacheopti.core.memory import calculate_entry_size


class _CacheShard:
    """
    Thread-safe cache partition implementing dual-bound LRU eviction and memory tracking.
    """

    def __init__(
        self,
        shard_id: int,
        max_entries: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> None:
        self.shard_id: int = shard_id
        self.max_entries: Optional[int] = max_entries
        self.max_bytes: Optional[int] = max_bytes

        # Internal O(1) storage and recency list
        self._dict: Dict[str, _Node] = {}
        self._list: DoublyLinkedList = DoublyLinkedList()
        self._lock: threading.RLock = threading.RLock()

        # Memory accounting (bytes)
        self.current_bytes: int = 0

        # Shard operational telemetry
        self.hits: int = 0
        self.misses: int = 0
        self.evictions: int = 0
        self.byte_evictions: int = 0

    @property
    def lock(self) -> threading.RLock:
        """Expose shard re-entrant lock."""
        return self._lock

    def get(self, key: str, now_ns: int) -> Optional[_Node]:
        """
        Retrieve node by key in O(1).
        If present and unexpired: updates recency to MRU, increments hits, returns node.
        If missing or expired: increments misses, purges expired entry, returns None.
        """
        with self._lock:
            node = self._dict.get(key)
            if node is None:
                self.misses += 1
                return None

            if node.is_expired(now_ns):
                self.misses += 1
                self._remove_node_internal(node)
                return None

            # Valid Cache Hit
            self.hits += 1
            node.touch(now_ns)
            self._list.move_to_head(node)
            return node

    def peek(self, key: str) -> Optional[_Node]:
        """
        Inspect entry without updating LRU order or incrementing hit count.
        """
        with self._lock:
            return self._dict.get(key)

    def put(
        self,
        key: str,
        value: Any,
        now_ns: int,
        ttl_ns: Optional[int] = None,
        delta_ns: int = 0,
    ) -> _Node:
        """
        Insert or overwrite an entry, update memory footprint, and evict LRU items
        if either max_entries or max_bytes is exceeded.
        """
        entry_bytes = calculate_entry_size(key, value)

        with self._lock:
            # Case 1: Overwrite existing key
            if key in self._dict:
                existing_node = self._dict[key]
                byte_delta = entry_bytes - existing_node.size_bytes
                self.current_bytes += byte_delta

                existing_node.value = value
                existing_node.size_bytes = entry_bytes
                existing_node.created_at_ns = now_ns
                existing_node.last_accessed_ns = now_ns
                existing_node.ttl_ns = ttl_ns
                existing_node.delta_ns = delta_ns
                existing_node.access_count += 1
                self._list.move_to_head(existing_node)
                target_node = existing_node
            else:
                # Case 2: New insertion
                new_node = _Node(
                    key=key,
                    value=value,
                    size_bytes=entry_bytes,
                    created_at_ns=now_ns,
                    ttl_ns=ttl_ns,
                    delta_ns=delta_ns,
                )
                self._dict[key] = new_node
                self._list.add_to_head(new_node)
                self.current_bytes += entry_bytes
                target_node = new_node

            # Dual-bound eviction enforcement
            self._enforce_bounds_internal(target_node)
            return target_node

    def delete(self, key: str) -> bool:
        """Remove entry by key, decrement memory counter, return True if found."""
        with self._lock:
            node = self._dict.pop(key, None)
            if node is not None:
                self._list.remove(node)
                self.current_bytes = max(0, self.current_bytes - node.size_bytes)
                return True
            return False

    def clear(self) -> None:
        """Reset shard storage, linked list, and memory accounting."""
        with self._lock:
            self._dict.clear()
            self._list.clear()
            self.current_bytes = 0

    def purge_expired(self, now_ns: int) -> int:
        """Sweep and purge all expired entries in this shard."""
        with self._lock:
            expired = [n for n in self._dict.values() if n.is_expired(now_ns)]
            for n in expired:
                self._remove_node_internal(n)
            return len(expired)

    def _remove_node_internal(self, node: _Node) -> None:
        """Internal helper to unlink node and decrement memory (must hold self._lock)."""
        self._dict.pop(node.key, None)
        self._list.remove(node)
        self.current_bytes = max(0, self.current_bytes - node.size_bytes)

    def _enforce_bounds_internal(self, target_node: _Node) -> None:
        """
        Evict least recently used entries from tail until both max_entries
        and max_bytes bounds are satisfied (must hold self._lock).
        """
        while (
            (self.max_entries is not None and len(self._dict) > self.max_entries)
            or (self.max_bytes is not None and self.current_bytes > self.max_bytes)
        ):
            victim = self._list.pop_tail()
            if victim is None:
                break

            self._dict.pop(victim.key, None)
            self.current_bytes = max(0, self.current_bytes - victim.size_bytes)
            self.evictions += 1
            self.byte_evictions += victim.size_bytes

            # If the single item itself exceeds max_bytes, it will be popped and loop terminates
            if victim is target_node:
                break

    def get_entries(self) -> List[_Node]:
        """Return a snapshot list of active nodes in MRU-to-LRU order."""
        with self._lock:
            return self._list.to_list()

    def stats(self) -> Dict[str, Any]:
        """Return state snapshot for this shard."""
        with self._lock:
            return {
                "shard_id": self.shard_id,
                "entries": len(self._dict),
                "current_bytes": self.current_bytes,
                "max_entries": self.max_entries,
                "max_bytes": self.max_bytes,
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "byte_evictions": self.byte_evictions,
            }


# Alias for clean public naming
CacheShard = _CacheShard
