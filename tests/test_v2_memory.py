"""
Tests for Component B: Dual-Bound Eviction and Recursive Memory Accounting.
Verifies memory calculation for nested collections, Pandas DataFrames,
overwrites, and dual-bound eviction (max_entries and max_bytes).
"""

import sys
import pytest
import numpy as np
import pandas as pd
from cacheopti.core.memory import deep_getsizeof, calculate_entry_size
from cacheopti.core.shard import _CacheShard


def test_deep_memory_primitives_and_nested_structures():
    """Verify recursive memory accounting for nested dictionaries and lists."""
    base_int = 42
    assert deep_getsizeof(base_int) == sys.getsizeof(base_int)

    # Nested dictionary with lists and strings
    nested = {
        "user_id": 1001,
        "metadata": {
            "tags": ["finance", "quant", "hft"],
            "scores": [98.5, 99.1, 94.2],
        },
        "payload": "A" * 1024,
    }
    deep_size = deep_getsizeof(nested)
    shallow_size = sys.getsizeof(nested)
    # Deep size must be substantially larger than top-level shallow dict
    assert deep_size > shallow_size
    assert deep_size > 1024


def test_circular_reference_protection():
    """Verify that circular references do not cause infinite recursion."""
    a = []
    b = [a]
    a.append(b)

    # Should compute without RecursionError
    size = deep_getsizeof(a)
    assert size > 0


def test_pandas_dataframe_and_numpy_accounting():
    """Verify accurate memory accounting for Pandas DataFrames and NumPy arrays."""
    arr = np.ones((100, 100), dtype=np.float64)  # 10,000 floats * 8 bytes = 80,000 bytes
    arr_size = deep_getsizeof(arr)
    assert arr_size >= 80_000

    df = pd.DataFrame({
        "int_col": range(1000),
        "str_col": ["test_string_" + str(i) for i in range(1000)],
    })
    df_size = deep_getsizeof(df)
    deep_usage = int(df.memory_usage(index=True, deep=True).sum())
    assert df_size >= deep_usage
    assert df_size > 50_000


def test_dual_bound_max_bytes_eviction():
    """Verify LRU entries are evicted when total memory exceeds max_bytes."""
    # Shard with 100 max_entries but a small max_bytes constraint
    # Each entry of "data": "X"*500 will consume ~600+ bytes
    shard = _CacheShard(shard_id=0, max_entries=100, max_bytes=1500)

    now = 1_000_000_000
    shard.put("k1", "X" * 400, now)
    shard.put("k2", "Y" * 400, now)

    assert shard.current_bytes <= 1500
    assert shard.evictions == 0

    # Adding k3 pushes total memory beyond 1500 bytes -> must evict LRU (k1)
    shard.put("k3", "Z" * 400, now)

    assert shard.current_bytes <= 1500
    assert shard.evictions >= 1
    assert shard.byte_evictions > 0
    # k1 was oldest and should be evicted
    assert shard.get("k1", now) is None
    assert shard.get("k3", now) is not None


def test_memory_accounting_during_overwrites():
    """Verify byte memory accounting tracks correctly when keys are overwritten."""
    shard = _CacheShard(shard_id=0, max_entries=10, max_bytes=100_000)
    now = 1_000_000_000

    # Initial insert with small payload
    shard.put("key_a", "small", now)
    size_small = shard.current_bytes
    assert size_small > 0

    # Overwrite with much larger payload
    shard.put("key_a", "large_" * 500, now)
    size_large = shard.current_bytes
    assert size_large > size_small
    assert len(shard._dict) == 1  # Still 1 key

    # Overwrite back with small payload
    shard.put("key_a", "tiny", now)
    size_tiny = shard.current_bytes
    assert size_tiny < size_large
    assert len(shard._dict) == 1

    # Delete key
    shard.delete("key_a")
    assert shard.current_bytes == 0
