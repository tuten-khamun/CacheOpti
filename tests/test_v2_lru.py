"""
Tests for Component A: Custom LRU Data Structure.
Verifies _Node __slots__, sentinel _head/_tail nodes, O(1) operations, and pointers.
"""

import pytest
from cacheopti.core.lru import _Node, DoublyLinkedList


def test_node_slots_memory_optimization():
    """Verify that _Node uses __slots__ and does not allocate a per-instance __dict__."""
    node = _Node(key="k1", value="v1", size_bytes=100, created_at_ns=1000, ttl_ns=5000)
    assert not hasattr(node, "__dict__"), "_Node must not have an instance __dict__"
    assert hasattr(node, "__slots__")
    
    # Attempting to assign an undeclared attribute must raise AttributeError
    with pytest.raises(AttributeError):
        node.arbitrary_extra_field = "leak"  # type: ignore[attr-defined]


def test_sentinel_head_and_tail_pointers():
    """Verify _head and _tail sentinels are initialized and maintain integrity."""
    dll = DoublyLinkedList()
    assert dll.is_empty()
    assert len(dll) == 0
    assert dll._head.next is dll._tail
    assert dll._tail.prev is dll._head
    assert dll._head.prev is None
    assert dll._tail.next is None


def test_o1_insertion_and_ordering():
    """Verify nodes inserted at head follow strict Most Recently Used (MRU) ordering."""
    dll = DoublyLinkedList()
    node1 = _Node("k1", 1)
    node2 = _Node("k2", 2)
    node3 = _Node("k3", 3)

    dll.add_to_head(node1)
    dll.add_to_head(node2)
    dll.add_to_head(node3)

    assert len(dll) == 3
    nodes = dll.to_list()
    assert [n.key for n in nodes] == ["k3", "k2", "k1"]
    assert dll._head.next is node3
    assert dll._tail.prev is node1


def test_o1_promotion_on_access():
    """Verify promotion of middle and tail nodes to head in O(1)."""
    dll = DoublyLinkedList()
    n1 = _Node("k1", 1)
    n2 = _Node("k2", 2)
    n3 = _Node("k3", 3)

    dll.add_to_head(n1)  # [n1]
    dll.add_to_head(n2)  # [n2, n1]
    dll.add_to_head(n3)  # [n3, n2, n1]

    # Promote middle node n2
    dll.move_to_head(n2)  # [n2, n3, n1]
    assert [n.key for n in dll.to_list()] == ["k2", "k3", "k1"]

    # Promote tail node n1
    dll.move_to_head(n1)  # [n1, n2, n3]
    assert [n.key for n in dll.to_list()] == ["k1", "k2", "k3"]


def test_o1_deletion_and_pop_tail():
    """Verify tail eviction in O(1) down to empty list with sentinels intact."""
    dll = DoublyLinkedList()
    n1 = _Node("k1", 1)
    n2 = _Node("k2", 2)

    dll.add_to_head(n1)
    dll.add_to_head(n2)

    # Pop tail (n1)
    victim1 = dll.pop_tail()
    assert victim1 is n1
    assert len(dll) == 1
    assert [n.key for n in dll.to_list()] == ["k2"]

    # Pop remaining node (n2)
    victim2 = dll.pop_tail()
    assert victim2 is n2
    assert len(dll) == 0
    assert dll.is_empty()
    assert dll._head.next is dll._tail

    # Popping empty list returns None safely
    assert dll.pop_tail() is None


def test_node_ttl_and_touch():
    """Verify TTL remaining calculation and touch access counts."""
    now_ns = 1_000_000_000
    ttl_ns = 2_000_000_000
    node = _Node("k", "v", created_at_ns=now_ns, ttl_ns=ttl_ns)

    assert not node.is_expired(now_ns + 1_000_000_000)
    assert node.remaining_ttl_s(now_ns + 1_000_000_000) == pytest.approx(1.0)
    assert node.is_expired(now_ns + 2_500_000_000)
    assert node.remaining_ttl_s(now_ns + 2_500_000_000) == 0.0

    node.touch(now_ns + 500_000_000)
    assert node.access_count == 2
    assert node.last_accessed_ns == now_ns + 500_000_000
