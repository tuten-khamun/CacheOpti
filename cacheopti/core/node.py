"""
CacheCraft / CacheOpti - Core Data Structures.

Implements an explicit Doubly Linked List and CacheNode for O(1) recency management.
Using explicit pointers provides full observability into how items move from MRU to LRU.
"""

from __future__ import annotations
import time
from typing import Any, Optional


class CacheNode:
    """Represents an individual entry in the cache storage and linked list."""

    __slots__ = (
        "key",
        "value",
        "created_at",
        "last_accessed_at",
        "ttl_seconds",
        "access_count",
        "prev",
        "next",
    )

    def __init__(
        self,
        key: str,
        value: Any,
        created_at: float,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        self.key: str = key
        self.value: Any = value
        self.created_at: float = created_at
        self.last_accessed_at: float = created_at
        self.ttl_seconds: Optional[float] = ttl_seconds
        self.access_count: int = 1
        self.prev: Optional[CacheNode] = None
        self.next: Optional[CacheNode] = None

    def is_expired(self, current_time: Optional[float] = None) -> bool:
        """Check whether this entry has exceeded its time-to-live."""
        if self.ttl_seconds is None:
            return False
        now = current_time if current_time is not None else time.monotonic()
        return (now - self.created_at) >= self.ttl_seconds

    def remaining_ttl(self, current_time: Optional[float] = None) -> Optional[float]:
        """Return remaining seconds before expiration, or None if no TTL set."""
        if self.ttl_seconds is None:
            return None
        now = current_time if current_time is not None else time.monotonic()
        elapsed = now - self.created_at
        remaining = self.ttl_seconds - elapsed
        return max(0.0, remaining)

    def touch(self, current_time: Optional[float] = None) -> None:
        """Update last accessed timestamp and increment access frequency."""
        self.last_accessed_at = current_time if current_time is not None else time.monotonic()
        self.access_count += 1

    def __repr__(self) -> str:
        return (
            f"CacheNode(key={self.key!r}, access_count={self.access_count}, "
            f"ttl={self.ttl_seconds}s)"
        )


class DoublyLinkedList:
    """
    A doubly linked list with dummy head and tail sentinel nodes.
    Maintains items ordered from Most Recently Used (MRU, near head)
    to Least Recently Used (LRU, near tail).
    All insertions, deletions, and promotions run in O(1) time.
    """

    def __init__(self) -> None:
        # Dummy sentinel nodes simplify pointer manipulation
        self.head: CacheNode = CacheNode("__HEAD_SENTINEL__", None, 0.0)
        self.tail: CacheNode = CacheNode("__TAIL_SENTINEL__", None, 0.0)
        self.head.next = self.tail
        self.tail.prev = self.head
        self._size: int = 0

    def __len__(self) -> int:
        return self._size

    def is_empty(self) -> bool:
        return self._size == 0

    def add_to_head(self, node: CacheNode) -> None:
        """Insert node immediately after the head sentinel (MRU position) in O(1)."""
        first = self.head.next
        node.prev = self.head
        node.next = first
        self.head.next = node
        if first:
            first.prev = node
        self._size += 1

    def remove_node(self, node: CacheNode) -> None:
        """Unlink node from its current position in O(1)."""
        if node.prev is None or node.next is None:
            return
        node.prev.next = node.next
        node.next.prev = node.prev
        node.prev = None
        node.next = None
        self._size = max(0, self._size - 1)

    def move_to_head(self, node: CacheNode) -> None:
        """Promote an existing node to the MRU position in O(1)."""
        self.remove_node(node)
        self.add_to_head(node)

    def pop_tail(self) -> Optional[CacheNode]:
        """Remove and return the LRU node right before the tail sentinel in O(1)."""
        if self.is_empty():
            return None
        lru_node = self.tail.prev
        if lru_node and lru_node is not self.head:
            self.remove_node(lru_node)
            return lru_node
        return None

    def to_list(self) -> list[CacheNode]:
        """Traverse and return all active nodes in MRU-to-LRU order."""
        nodes: list[CacheNode] = []
        current = self.head.next
        while current and current is not self.tail:
            nodes.append(current)
            current = current.next
        return nodes

    def clear(self) -> None:
        """Reset the list to empty sentinels."""
        self.head.next = self.tail
        self.tail.prev = self.head
        self._size = 0
