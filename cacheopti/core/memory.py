"""
CacheOpti v2.0 - Deep Memory Accounting.

Provides accurate, recursive memory calculation for arbitrary Python objects,
nested data structures (dicts, lists, sets, tuples), custom slot/dict classes,
NumPy arrays, and Pandas DataFrames.
Protects against infinite recursion from circular object references using pointer sets.
"""

from __future__ import annotations
import collections
import sys
from typing import Any, Optional, Set

# Attempt optional imports for specialized memory introspection
try:
    import pandas as pd  # type: ignore
    _PANDAS_AVAILABLE = True
except ImportError:
    _PANDAS_AVAILABLE = False

try:
    import numpy as np  # type: ignore
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False


def deep_getsizeof(obj: Any, seen: Optional[Set[int]] = None) -> int:
    """
    Recursively calculate the deep memory footprint (in bytes) of any Python object.

    Handles:
    - Primitive types (int, float, str, bytes, bool, None)
    - Collections (dict, list, tuple, set, frozenset, deque)
    - NumPy ndarrays (contiguous buffer + container)
    - Pandas DataFrames & Series (deep memory usage of all series + indices)
    - Custom objects with __dict__ or __slots__
    - Circular references (tracked via memory address id)
    """
    if seen is None:
        seen = set()

    obj_id = id(obj)
    if obj_id in seen:
        return 0

    seen.add(obj_id)

    # 1. Specialized handling for Pandas DataFrames and Series
    if _PANDAS_AVAILABLE:
        if isinstance(obj, pd.DataFrame):
            try:
                # memory_usage(deep=True) accounts for underlying C buffers & python strings
                deep_series = obj.memory_usage(index=True, deep=True)
                return int(deep_series.sum()) + sys.getsizeof(obj)
            except Exception:
                pass
        elif isinstance(obj, pd.Series):
            try:
                return int(obj.memory_usage(index=True, deep=True)) + sys.getsizeof(obj)
            except Exception:
                pass

    # Duck-typing fallback for DataFrame/Series if pandas was reloaded or mocked
    if hasattr(obj, "memory_usage") and callable(getattr(obj, "memory_usage")):
        try:
            mem = obj.memory_usage(index=True, deep=True)
            if hasattr(mem, "sum"):
                return int(mem.sum()) + sys.getsizeof(obj)
            return int(mem) + sys.getsizeof(obj)
        except Exception:
            pass

    # 2. Specialized handling for NumPy ndarrays
    if _NUMPY_AVAILABLE and isinstance(obj, np.ndarray):
        return int(obj.nbytes) + sys.getsizeof(obj)
    if hasattr(obj, "nbytes") and isinstance(getattr(obj, "nbytes"), int):
        return int(obj.nbytes) + sys.getsizeof(obj)

    # Base memory size of container/object itself
    size = sys.getsizeof(obj)

    # 3. Recursive inspection for collections
    if isinstance(obj, dict):
        for k, v in obj.items():
            size += deep_getsizeof(k, seen)
            size += deep_getsizeof(v, seen)
    elif isinstance(obj, (list, tuple, set, frozenset, collections.deque)):
        for item in obj:
            size += deep_getsizeof(item, seen)

    # 4. Custom user objects with __dict__
    elif hasattr(obj, "__dict__"):
        size += deep_getsizeof(getattr(obj, "__dict__"), seen)

    # 5. Custom objects with __slots__
    elif hasattr(type(obj), "__slots__"):
        slots = getattr(type(obj), "__slots__")
        if isinstance(slots, str):
            slots = (slots,)
        for slot in slots:
            if hasattr(obj, slot):
                size += deep_getsizeof(getattr(obj, slot), seen)

    return size


def calculate_entry_size(key: str, value: Any, node_overhead: int = 64) -> int:
    """
    Calculate the total memory consumed by a cache entry:
    key size + value deep size + node structure overhead.
    """
    key_size = deep_getsizeof(key)
    val_size = deep_getsizeof(value)
    return key_size + val_size + node_overhead
