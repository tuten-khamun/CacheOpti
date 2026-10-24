"""
CacheCraft / CacheOpti - Repeatable Workload Generators.

Provides realistic, deterministic workload distributions to benchmark caching policies:
- Zipfian / Pareto (80/20 skewed distribution representative of real web/DB traffic)
- Uniform Random (uncorrelated access across large key space)
- Cyclic / Round-robin (sequential access loops)
- Thrashing / Churn (workload deliberately overflowing capacity to show LRU thrashing)
- Mixed / Temporal (bursts of popularity with periodic new entries)
"""

from __future__ import annotations
import random
from typing import Sequence, Any


def generate_zipfian_workload(
    keys: Sequence[Any],
    num_requests: int = 100,
    alpha: float = 1.25,
    seed: int = 42,
) -> list[Any]:
    """
    Generate power-law / Zipfian distributed keys where rank 1 is requested most.
    Simulates real-world web/API request popularity.
    """
    rng = random.Random(seed)
    n = len(keys)
    if n == 0:
        return []

    # Calculate Zipf probabilities P(k) ~ 1 / k^alpha
    weights = [1.0 / (i ** alpha) for i in range(1, n + 1)]
    sum_weights = sum(weights)
    probabilities = [w / sum_weights for w in weights]

    # Sample keys according to Zipf distribution
    return rng.choices(keys, weights=probabilities, k=num_requests)


def generate_uniform_workload(
    keys: Sequence[Any],
    num_requests: int = 100,
    seed: int = 42,
) -> list[Any]:
    """Uniformly distributed random requests across available keys."""
    rng = random.Random(seed)
    if not keys:
        return []
    return [rng.choice(keys) for _ in range(num_requests)]


def generate_cyclic_workload(
    keys: Sequence[Any],
    num_cycles: int = 5,
) -> list[Any]:
    """Sequential cyclic iteration over keys for a set number of loops."""
    result: list[Any] = []
    for _ in range(num_cycles):
        result.extend(keys)
    return result


def generate_thrashing_workload(
    capacity: int,
    multiplier: int = 3,
    cycles: int = 3,
) -> list[str]:
    """
    Generates a workload of (capacity * multiplier) unique keys in a loop.
    Under LRU with strict capacity, this causes 100% cache thrashing (compulsory + capacity misses).
    """
    total_keys = max(capacity + 1, capacity * multiplier)
    keys = [f"item_{i}" for i in range(total_keys)]
    return keys * cycles


def generate_bursty_workload(
    keys: Sequence[Any],
    num_requests: int = 100,
    burst_length: int = 5,
    seed: int = 42,
) -> list[Any]:
    """Simulates temporal locality with repeated bursts of identical keys."""
    rng = random.Random(seed)
    result: list[Any] = []
    while len(result) < num_requests:
        chosen = rng.choice(keys)
        burst = min(burst_length, num_requests - len(result))
        result.extend([chosen] * burst)
    return result
