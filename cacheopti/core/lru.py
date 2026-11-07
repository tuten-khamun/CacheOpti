"""
CacheOpti v2.0 - Custom LRU Data Structure.

Implements an explicit Doubly Linked List with sentinel head and tail nodes,
and memory-optimized _Node utilizing __slots__ for zero dictionary overhead per node.
Guarantees strict O(1) time complexity for lookup, insertion, deletion, and LRU updates.
"""

from __future__ import annotations
from typing import Any, Optional


class _Node:
    """
    Memory-optimized cache node using __slots__ to eliminate instance __dict__.
    Tracks object payload, deep byte size, monotonic timestamps (in nanoseconds),
    computation duration (delta_ns), access frequency, and linked list pointers.
    """

    __slots__ = (
        "key",
        "value",
        "size_bytes",
        "created_at_ns",
        "ttl_ns",
        "delta_ns",
        "last_accessed_ns",
        "access_count",
        "prev",
        "next",
    )

    def __init__(
        self,
        key: str,
        value: Any,
        size_bytes: int = 0,
        created_at_ns: int = 0,
        ttl_ns: Optional[int] = None,
        delta_ns: int = 0,
    ) -> None:
        self.key: str = key
        self.value: Any = value
        self.size_bytes: int = size_bytes
        self.created_at_ns: int = created_at_ns
        self.ttl_ns: Optional[int] = ttl_ns
        self.delta_ns: int = delta_ns
        self.last_accessed_ns: int = created_at_ns
        self.access_count: int = 1
        self.prev: Optional[_Node] = None
        self.next: Optional[_Node] = None

    def is_expired(self, now_ns: int) -> bool:
        """Check whether entry has exceeded its time-to-live in nanoseconds."""
        if self.ttl_ns is None:
            return False
        return (now_ns - self.created_at_ns) >= self.ttl_ns

    def remaining_ttl_s(self, now_ns: int) -> Optional[float]:
        """Return remaining time in seconds before expiration, or None if immortal."""
        if self.ttl_ns is None:
            return None
        rem_ns = self.ttl_ns - (now_ns - self.created_at_ns)
        return max(0.0, rem_ns / 1_000_000_000.0)

    def touch(self, now_ns: int) -> None:
        """Update last accessed timestamp and increment access frequency in O(1)."""
        self.last_accessed_ns = now_ns
        self.access_count += 1

    def __repr__(self) -> str:
        return (
            f"_Node(key={self.key!r}, size={self.size_bytes}B, "
            f"hits={self.access_count}, ttl_ns={self.ttl_ns})"
        )


class DoublyLinkedList:
    """
    Doubly Linked List with dummy sentinel nodes (_head and _tail).
    Maintains elements in strict recency order:
      _head.next is Most Recently Used (MRU)
      _tail.prev is Least Recently Used (LRU, eviction candidate)
    All operations execute in O(1) pointer updates with no edge-case branching.
    """

    def __init__(self) -> None:
        # Dummy sentinels eliminate null checks for head/tail updates
        self._head: _Node = _Node("__HEAD_SENTINEL__", None)
        self._tail: _Node = _Node("__TAIL_SENTINEL__", None)
        self._head.next = self._tail
        self._tail.prev = self._head
        self._size: int = 0

    def __len__(self) -> int:
        return self._size

    def is_empty(self) -> bool:
        return self._head.next is self._tail

    def add_to_head(self, node: _Node) -> None:
        """Insert node immediately after the _head sentinel (MRU position) in O(1)."""
        first = self._head.next
        node.prev = self._head
        node.next = first
        self._head.next = node
        if first:
            first.prev = node
        self._size += 1

    def remove(self, node: _Node) -> None:
        """Unlink node from its current position in O(1)."""
        if node.prev is None or node.next is None:
            return
        node.prev.next = node.next
        node.next.prev = node.prev
        node.prev = None
        node.next = None
        self._size = max(0, self._size - 1)

    def move_to_head(self, node: _Node) -> None:
        """Promote an existing node to the MRU position in O(1)."""
        self.remove(node)
        self.add_to_head(node)

    def pop_tail(self) -> Optional[_Node]:
        """Remove and return the LRU node right before _tail sentinel in O(1)."""
        if self.is_empty():
            return None
        lru_node = self._tail.prev
        if lru_node and lru_node is not self._head:
            self.remove(lru_node)
            return lru_node
        return None

    def to_list(self) -> list[_Node]:
        """Traverse and return all active nodes in MRU-to-LRU order."""
        nodes: list[_Node] = []
        curr = self._head.next
        while curr and curr is not self._tail:
            nodes.append(curr)
            curr = curr.next
        return nodes

    def clear(self) -> None:
        """Reset the list to empty sentinels in O(1)."""
        self._head.next = self._tail
        self._tail.prev = self._head
        self._size = 0
