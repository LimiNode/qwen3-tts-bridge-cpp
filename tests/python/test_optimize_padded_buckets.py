"""Tests for the offline padded-prefill candidate optimizer."""

from __future__ import annotations

import unittest
from typing import Any, cast

from scripts.optimize_padded_buckets import _candidate, _load_histogram


class OptimizePaddedBucketsTests(unittest.TestCase):
    def test_candidate_partitions_lengths_without_changing_coverage_claims(
        self,
    ) -> None:
        candidate = _candidate(
            {2: 4, 3: 3, 6: 2, 8: 1},
            requested_bucket_count=2,
            coverage_percent=100.0,
            per_graph_startup_ms=12.5,
        )

        self.assertEqual([3, 8], candidate["compiled_bucket_ceilings"])
        self.assertEqual(2, candidate["compiled_graph_count"])
        self.assertEqual(10, candidate["compiled_request_count"])
        self.assertEqual(0, candidate["eager_request_count"])
        padding = cast(dict[str, Any], candidate["padding_frames"])
        startup = cast(dict[str, Any], candidate["startup_cost_estimate"])
        self.assertEqual(0.8, padding["mean"])
        self.assertEqual(2, padding["max"])
        self.assertEqual(
            25.0,
            startup["estimated_startup_ms"],
        )

    def test_candidate_reports_eager_tail_at_requested_coverage(self) -> None:
        candidate = _candidate(
            {2: 4, 3: 3, 6: 2, 8: 1},
            requested_bucket_count=2,
            coverage_percent=70.0,
            per_graph_startup_ms=None,
        )

        self.assertEqual([2, 3], candidate["compiled_bucket_ceilings"])
        self.assertEqual(7, candidate["compiled_request_count"])
        self.assertEqual(3, candidate["eager_request_count"])
        startup = cast(dict[str, Any], candidate["startup_cost_estimate"])
        self.assertEqual("not_measured", startup["measurement_status"])

    def test_histogram_rejects_invalid_counts(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "invalid count"):
            _load_histogram({"length_histogram": {"32": 0}})


if __name__ == "__main__":
    unittest.main()
