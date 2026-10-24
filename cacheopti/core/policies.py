"""
CacheCraft / CacheOpti - Pluggable Eviction Policies.

Defines the BaseCachePolicy interface and implementations for LRU, FIFO, and LFU.
Keeping policy separate from storage ensures extensibility.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
from cacheopti.core.node import CacheNode, DoublyLinkedList


class BaseCachePolicy(ABC):
    """Abstract interface defining cache replacement policies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the eviction policy."""
        pass

    @abstractmethod
    def on_access(self, node: CacheNode) -> None:
        """Triggered when an existing cache entry is read."""
        pass

    @abstractmethod
    def on_insert(self, node: CacheNode) -> None:
        """Triggered when a new entry is added to cache."""
        pass

    @abstractmethod
    def on_update(self, node: CacheNode) -> None:
        """Triggered when an existing key's value is overwritten."""
        pass

    @abstractmethod
    def select_victim(self) -> Optional[CacheNode]:
        """Select and remove the candidate entry for eviction."""
        pass

    @abstractmethod
    def on_delete(self, node: CacheNode) -> None:
        """Triggered when a specific node is removed or purged."""
        pass

    @abstractmethod
    def to_ordered_list(self) -> list[CacheNode]:
        """Return nodes in priority order (highest retention to highest eviction risk)."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Reset internal tracking state."""
        pass


class LRUPolicy(BaseCachePolicy):
    """
    Least Recently Used policy using Doubly Linked List.
    - MRU at the head (index 0).
    - LRU at the tail (eviction candidate).
    - On access, the hit node is promoted to head in O(1).
    """

    def __init__(self) -> None:
        self._list = DoublyLinkedList()

    @property
    def name(self) -> str:
        return "LRU"

    def on_access(self, node: CacheNode) -> None:
        # Successful hit refreshes recency: promote to MRU
        self._list.move_to_head(node)

    def on_insert(self, node: CacheNode) -> None:
        # New entry enters at MRU head
        self._list.add_to_head(node)

    def on_update(self, node: CacheNode) -> None:
        # Updated entry also refreshed to MRU head
        self._list.move_to_head(node)

    def select_victim(self) -> Optional[CacheNode]:
        # Evict least recently accessed node at the tail in O(1)
        return self._list.pop_tail()

    def on_delete(self, node: CacheNode) -> None:
        self._list.remove_node(node)

    def to_ordered_list(self) -> list[CacheNode]:
        return self._list.to_list()

    def clear(self) -> None:
        self._list.clear()


class FIFOPolicy(BaseCachePolicy):
    """
    First In, First Out policy.
    - Entries are evicted strictly in insertion order.
    - Read hits do NOT change eviction order.
    """

    def __init__(self) -> None:
        self._list = DoublyLinkedList()

    @property
    def name(self) -> str:
        return "FIFO"

    def on_access(self, node: CacheNode) -> None:
        # FIFO ignores read hits: access order does not affect eviction
        pass

    def on_insert(self, node: CacheNode) -> None:
        self._list.add_to_head(node)

    def on_update(self, node: CacheNode) -> None:
        # In classic FIFO, an update can either preserve age or reset to head.
        # Here we reset age on overwrite.
        self._list.move_to_head(node)

    def select_victim(self) -> Optional[CacheNode]:
        return self._list.pop_tail()

    def on_delete(self, node: CacheNode) -> None:
        self._list.remove_node(node)

    def to_ordered_list(self) -> list[CacheNode]:
        return self._list.to_list()

    def clear(self) -> None:
        self._list.clear()


class LFUPolicy(BaseCachePolicy):
    """
    Least Frequently Used policy.
    - Evicts the entry with the lowest access_count.
    - Ties broken by least recently accessed (LRU).
    """

    def __init__(self) -> None:
        self._nodes: list[CacheNode] = []

    @property
    def name(self) -> str:
        return "LFU"

    def on_access(self, node: CacheNode) -> None:
        # Node access_count already incremented by CacheEngine
        pass

    def on_insert(self, node: CacheNode) -> None:
        self._nodes.append(node)

    def on_update(self, node: CacheNode) -> None:
        pass

    def select_victim(self) -> Optional[CacheNode]:
        if not self._nodes:
            return None
        # Lowest access_count first; tie-break by oldest last_accessed_at
        victim = min(
            self._nodes,
            key=lambda n: (n.access_count, n.last_accessed_at),
        )
        self._nodes.remove(victim)
        return victim

    def on_delete(self, node: CacheNode) -> None:
        if node in self._nodes:
            self._nodes.remove(node)

    def to_ordered_list(self) -> list[CacheNode]:
        # Return sorted by highest retention priority (most frequent & newest)
        return sorted(
            self._nodes,
            key=lambda n: (n.access_count, n.last_accessed_at),
            reverse=True,
        )

    def clear(self) -> None:
        self._nodes.clear()
