"""Tests for the provenance-bound fixed one-bucket mechanism gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import unittest

from scripts.evaluate_padded_bucket_mechanism_gate import _evaluate


class PaddedBucketMechanismGateTests(unittest.TestCase):
    def test_only_well_represented_fixed_bucket_can_be_authorized(self) -> None:
        audit = _audit()
        result = _evaluate(_route(), _manual(audit), audit, _args(), _sha(audit))

        self.assertTrue(result["prototype_authorized"])
        self.assertEqual(
            "prototype_single_padded_bucket_16_32_to_32", result["decision"]
        )

    def test_single_observation_in_range_fails_closed(self) -> None:
        audit = _audit()
        route = _route()
        route["length_histogram"] = {"27": 1}
        result = _evaluate(route, _manual(audit), audit, _args(), _sha(audit))

        self.assertFalse(result["prototype_authorized"])
        self.assertIn("minimum_range_request_count", result["failed_checks"])
        self.assertIn("large_padding_control", result["failed_checks"])
        self.assertIn("zero_padding_control", result["failed_checks"])


def _route() -> dict[str, object]:
    return {
        "corpus_id": "v4",
        "runtime_profile_id": "strict_bf16_sdpa_v1",
        "input_valid": True,
        "input_record_count": 1500,
        "evidence_source": "synthetic_proxy",
        "length_histogram": {
            "16": 5,
            "17": 5,
            "22": 20,
            "25": 20,
            "28": 20,
            "31": 5,
            "32": 25,
        },
    }


def _audit() -> dict[str, object]:
    return {
        "corpus_id": "v4",
        "automated_preflight_status": "passed",
        "generator_source_sha256": "generator",
        "generation_config_sha256": "config",
    }


def _manual(audit: dict[str, object]) -> dict[str, object]:
    return {
        "passed": True,
        "corpus_id": "v4",
        "audit_sha256": _sha(audit),
        "generator_source_sha256": "generator",
        "generation_config_sha256": "config",
    }


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        minimum_discovery_records=1500,
        runtime_profile_id="strict_bf16_sdpa_v1",
    )


def _sha(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
