"""
Tests for BenchmarkRunner and synthetic workload distributions.
"""

import unittest
from cacheopti.benchmark.workloads import (
    generate_zipfian_workload,
    generate_uniform_workload,
    generate_thrashing_workload,
)
from cacheopti.benchmark.runner import BenchmarkRunner


class TestBenchmarkSuite(unittest.TestCase):

    def test_zipfian_skew(self):
        keys = ["A", "B", "C", "D", "E"]
        workload = generate_zipfian_workload(keys, num_requests=200, alpha=1.5, seed=42)
        self.assertEqual(len(workload), 200)
        # Rank 1 ("A") should be the most frequent element
        count_a = workload.count("A")
        count_e = workload.count("E")
        self.assertGreater(count_a, count_e)

    def test_benchmark_runner_executes_and_reports_correctly(self):
        # Deterministic dummy operation
        def dummy_op(x: int) -> int:
            return x * 10

        workload = [1, 2, 1, 2, 1, 3, 1, 2]  # Repeated patterns
        res = BenchmarkRunner.run_comparison(
            operation=dummy_op,
            workload=workload,
            cache_capacity=5,
            cache_ttl_seconds=60.0,
            workload_name="Test Repeat",
        )

        self.assertEqual(res.total_requests, 8)
        self.assertEqual(res.hits + res.misses, 8)
        self.assertGreater(res.hits, 0)
        self.assertGreaterEqual(res.hit_rate_pct, 50.0)
        self.assertGreaterEqual(res.speedup_factor, 0.0)

    def test_capacity_sweep_reports_all_steps(self):
        def dummy_op(x: int) -> int:
            return x + 1

        workload = [1, 2, 3, 4, 1, 2, 3, 4]
        sweep = BenchmarkRunner.run_capacity_sweep(
            operation=dummy_op,
            workload=workload,
            capacities=[2, 4],
        )
        self.assertEqual(len(sweep), 2)
        self.assertEqual(sweep[0]["capacity"], 2)
        self.assertEqual(sweep[1]["capacity"], 4)


if __name__ == "__main__":
    unittest.main()
