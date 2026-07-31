from __future__ import annotations

import unittest

from scripts.validate_qwen_padded_bucket_runtime_acceptance import (
    _REQUIRED_SEMANTIC_CHECKS,
    validate,
)


class QwenPaddedBucketRuntimeAcceptanceTests(unittest.TestCase):
    def test_complete_semantic_report_authorizes_holdout_but_not_release(self) -> None:
        result = validate(_authorization(True), {"checks": _all_checks(True)})

        self.assertTrue(result["runtime_acceptance_authorized"])
        self.assertTrue(result["holdout_authorized"])
        self.assertFalse(result["release_authorized"])

    def test_missing_semantic_check_fails_closed(self) -> None:
        checks = _all_checks(True)
        checks["rng_neutrality"] = False
        result = validate(_authorization(True), {"checks": checks})

        self.assertFalse(result["runtime_acceptance_authorized"])
        self.assertIn("rng_neutrality", result["failed_checks"])


def _authorization(authorized: bool) -> dict[str, object]:
    return {
        "research_implementation_authorized": authorized,
        "approved_research_policy": {
            "actual_minimum_length": 16,
            "actual_maximum_length": 32,
            "compiled_ceiling": 32,
            "compiled_graph_count": 1,
        },
    }


def _all_checks(value: bool) -> dict[str, bool]:
    return {name: value for name in _REQUIRED_SEMANTIC_CHECKS}


if __name__ == "__main__":
    unittest.main()
