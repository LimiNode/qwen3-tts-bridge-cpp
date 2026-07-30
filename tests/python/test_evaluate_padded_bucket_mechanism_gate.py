"""Tests for the fixed one-bucket mechanism gate."""

from __future__ import annotations

import argparse
import unittest

from scripts.evaluate_padded_bucket_mechanism_gate import _evaluate


class PaddedBucketMechanismGateTests(unittest.TestCase):
    def test_only_the_fixed_single_bucket_can_be_authorized(self) -> None:
        result = _evaluate(_route(), {"passed": True}, _args())

        self.assertTrue(result["prototype_authorized"])
        self.assertEqual(
            "prototype_single_padded_bucket_16_32_to_32", result["decision"]
        )
        self.assertEqual(1, result["approved_policy"]["compiled_graph_count"])

    def test_missing_16_to_32_evidence_fails_closed(self) -> None:
        route = _route()
        route["length_histogram"] = {"8": 1500}

        result = _evaluate(route, {"passed": True}, _args())

        self.assertFalse(result["prototype_authorized"])
        self.assertIn("actual_range_represented", result["failed_checks"])


def _route() -> dict[str, object]:
    return {
        "input_valid": True,
        "input_record_count": 1500,
        "evidence_source": "synthetic_proxy",
        "length_histogram": {"16": 20, "24": 50, "32": 15},
    }


def _args() -> argparse.Namespace:
    return argparse.Namespace(minimum_discovery_records=1500)


if __name__ == "__main__":
    unittest.main()
