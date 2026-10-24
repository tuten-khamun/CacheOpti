"""Benchmarking suite, workloads, and comparative profilers for CacheOpti."""

from cacheopti.benchmark.workloads import (
    generate_zipfian_workload,
    generate_uniform_workload,
    generate_cyclic_workload,
    generate_thrashing_workload,
    generate_bursty_workload,
)
from cacheopti.benchmark.runner import BenchmarkRunner, BenchmarkResult

__all__ = [
    "generate_zipfian_workload",
    "generate_uniform_workload",
    "generate_cyclic_workload",
    "generate_thrashing_workload",
    "generate_bursty_workload",
    "BenchmarkRunner",
    "BenchmarkResult",
]
