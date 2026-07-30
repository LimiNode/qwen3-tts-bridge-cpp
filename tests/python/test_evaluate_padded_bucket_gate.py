"""Tests for the separate padded-bucket research gate."""

from __future__ import annotations

import argparse
import unittest
from typing import cast

from scripts.evaluate_padded_bucket_gate import _evaluate


class EvaluatePaddedBucketGateTests(unittest.TestCase):
    def test_pass_authorizes_only_a_correctness_prototype(self) -> None:
        result = _evaluate(_route(), {"passed": True}, _artifact(), _args())

        self.assertTrue(result["prototype_authorized"])
        self.assertFalse(result["release_authorized"])
        self.assertEqual("prototype_padded_bucket_correctness", result["decision"])

    def test_missing_human_review_fails_closed(self) -> None:
        result = _evaluate(_route(), {"passed": False}, _artifact(), _args())

        self.assertFalse(result["prototype_authorized"])
        failed_checks = cast(list[str], result["failed_checks"])
        self.assertIn("manual_review_passed", failed_checks)


def _route() -> dict[str, object]:
    return {
        "input_valid": True,
        "input_record_count": 1500,
        "evidence_source": "synthetic_proxy",
    }


def _artifact() -> dict[str, object]:
    return {
        "research_only": True,
        "candidates": [
            {
                "candidate_id": "actual-16-32-to-32",
                "compiled_coverage_percent": 90.0,
                "compiled_graph_count": 1,
                "padding_frames": {"mean": 3.0, "p95": 8.0, "max": 16.0},
                "padding_ratio": {"max": 0.4},
                "bootstrap_stability": {"minimum_ceiling_match_percent": 90.0},
            }
        ],
    }


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        candidate_id="actual-16-32-to-32",
        minimum_discovery_records=1500,
        minimum_bootstrap_stability_percent=80.0,
        minimum_theoretical_coverage_percent=85.0,
        maximum_mean_padding=6.0,
        maximum_p95_padding=12.0,
        maximum_padding=16.0,
        maximum_padding_ratio=0.4,
        maximum_graphs=6,
    )


if __name__ == "__main__":
    unittest.main()
