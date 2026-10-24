"""
Tests for @cached decorator and OperationTracker telemetry.
"""

import unittest
from cacheopti.core.engine import CacheEngine
from cacheopti.instrumentation.decorator import cached
from cacheopti.instrumentation.tracker import OperationTracker


class TestInstrumentation(unittest.TestCase):

    def setUp(self):
        self.cache = CacheEngine(capacity=5, default_ttl_seconds=60.0)
        self.tracker = OperationTracker()

    def test_cached_decorator_memoizes_and_tracks(self):
        call_count = 0

        @cached(self.cache, tracker=self.tracker, prefix="calc_square")
        def calc_square(n: int) -> int:
            nonlocal call_count
            call_count += 1
            return n * n

        # First call: miss, executes underlying function
        res1 = calc_square(4)
        self.assertEqual(res1, 16)
        self.assertEqual(call_count, 1)

        # Second call: hit, does NOT execute underlying function
        res2 = calc_square(4)
        self.assertEqual(res2, 16)
        self.assertEqual(call_count, 1)  # Still 1!

        # Check telemetry metrics
        metrics = self.tracker.get_or_create_metrics("calc_square")
        self.assertEqual(metrics.total_calls, 2)
        self.assertEqual(metrics.hits, 1)
        self.assertEqual(metrics.misses, 1)
        self.assertEqual(metrics.hit_rate, 0.5)

    def test_cached_decorator_handles_exceptions_safely(self):
        @cached(self.cache, tracker=self.tracker, prefix="faulty_op")
        def faulty_op(should_fail: bool):
            if should_fail:
                raise ValueError("Deliberate error")
            return "success"

        with self.assertRaises(ValueError):
            faulty_op(True)

        metrics = self.tracker.get_or_create_metrics("faulty_op")
        self.assertEqual(metrics.total_calls, 1)
        self.assertEqual(metrics.errors, 1)
        self.assertEqual(metrics.hits, 0)
        # Ensure error wasn't cached
        self.assertEqual(len(self.cache._storage), 0)

        # Successful call afterwards
        res = faulty_op(False)
        self.assertEqual(res, "success")
        self.assertEqual(metrics.total_calls, 2)
        self.assertEqual(metrics.errors, 1)


if __name__ == "__main__":
    unittest.main()
