"""Tests for constrained padded-bucket Pareto optimization."""

from __future__ import annotations

import argparse
import unittest
from typing import Any, cast

from scripts.optimize_padded_buckets_v2 import _best_plan, _candidate, _eager_gaps


class OptimizePaddedBucketsV2Tests(unittest.TestCase):
    def test_plan_can_leave_sparse_internal_lengths_eager(self) -> None:
        histogram = {16: 50, 17: 50, 31: 50, 32: 50, 50: 2}
        args = _args()
        plan = _best_plan(histogram, 2, args)
        candidate = _candidate(histogram, plan, 2, args)

        self.assertEqual(200, candidate["compiled_request_count"])
        self.assertEqual(2, candidate["compiled_graph_count"])
        self.assertEqual(
            [
                {
                    "minimum_actual_length": 50,
                    "maximum_actual_length": 50,
                    "request_count": 2,
                }
            ],
            _eager_gaps(histogram, plan.buckets),
        )
        padding_ratio = cast(dict[str, Any], candidate["padding_ratio"])
        self.assertLessEqual(padding_ratio["max"], 0.4)


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        min_bucket_size=10,
        max_padding_frames=16,
        max_padding_ratio=0.4,
        max_bucket_width=16,
        bootstrap_samples=5,
        bootstrap_seed=1,
        ceiling_tolerance_frames=2,
    )


if __name__ == "__main__":
    unittest.main()
