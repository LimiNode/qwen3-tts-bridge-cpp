"""Tests for the provenance-bound padded distribution research gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import unittest
from typing import cast

from scripts.evaluate_padded_bucket_gate import _evaluate


class EvaluatePaddedBucketGateTests(unittest.TestCase):
    def test_pass_authorizes_only_a_distribution_research_plan(self) -> None:
        route = _route()
        audit = _audit()
        result = _evaluate(
            route,
            _manual(audit),
            _artifact(_sha(route)),
            audit,
            _args(),
            _sha(route),
            _sha(audit),
        )

        self.assertTrue(result["distribution_plan_authorized"])
        self.assertFalse(result["prototype_authorized"])
        self.assertFalse(result["release_authorized"])

    def test_mismatched_candidate_input_fails_closed(self) -> None:
        route = _route()
        audit = _audit()
        result = _evaluate(
            route,
            _manual(audit),
            _artifact("other-summary"),
            audit,
            _args(),
            _sha(route),
            _sha(audit),
        )

        self.assertFalse(result["distribution_plan_authorized"])
        failed_checks = cast(list[str], result["failed_checks"])
        self.assertIn("candidate_input_summary", failed_checks)


def _route() -> dict[str, object]:
    return {
        "corpus_id": "v4",
        "runtime_profile_id": "strict_bf16_sdpa_v1",
        "input_valid": True,
        "input_record_count": 1500,
        "evidence_source": "synthetic_proxy",
    }


def _audit() -> dict[str, object]:
    return {
        "corpus_id": "v4",
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


def _artifact(route_sha256: str) -> dict[str, object]:
    return {
        "research_only": True,
        "input_summary_sha256": route_sha256,
        "runtime_profile_id": "strict_bf16_sdpa_v1",
        "candidates": [
            {
                "candidate_id": "pareto-graphs-4",
                "compiled_coverage_percent": 90.0,
                "compiled_graph_count": 4,
                "padding_frames": {"mean": 3.0, "p95": 8.0, "max": 16.0},
                "padding_ratio": {"max": 0.4},
                "bootstrap_stability": {"minimum_ceiling_match_percent": 90.0},
            }
        ],
    }


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        candidate_id="pareto-graphs-4",
        minimum_discovery_records=1500,
        minimum_bootstrap_stability_percent=80.0,
        minimum_theoretical_coverage_percent=85.0,
        maximum_mean_padding=6.0,
        maximum_p95_padding=12.0,
        maximum_padding=16.0,
        maximum_padding_ratio=0.4,
        maximum_graphs=6,
    )


def _sha(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
