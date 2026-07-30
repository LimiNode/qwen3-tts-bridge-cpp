"""Tests for paired route-aware A/B analysis."""

from __future__ import annotations

import unittest

from scripts.analyze_route_aware_ab import _bootstrap, _build_pairs


class AnalyzeRouteAwareAbTests(unittest.TestCase):
    def test_pairs_by_label_and_occurrence(self) -> None:
        fixed = [_request("compiled_32", 100.0), _request("unknown_31", 200.0)]
        route = [_request("unknown_31", 200.0), _request("compiled_32", 80.0)]

        pairs = _build_pairs(fixed, route)

        self.assertEqual("compiled", pairs[0]["category"])
        self.assertEqual(20.0, pairs[0]["fixed8"]["completed_ms"] - pairs[0]["route_aware"]["completed_ms"])
        self.assertEqual("eager", pairs[1]["category"])

    def test_bootstrap_is_deterministic(self) -> None:
        pairs = _build_pairs(
            [_request("compiled_32", 100.0), _request("compiled_32", 120.0)],
            [_request("compiled_32", 80.0), _request("compiled_32", 100.0)],
        )

        self.assertEqual(_bootstrap(pairs, 20, 7), _bootstrap(pairs, 20, 7))

    def test_rejects_different_manifest_contract(self) -> None:
        fixed = [_request("compiled_32", 100.0)]
        route = [_request("compiled_32", 80.0)]
        route[0]["manifest_contract"]["expected"]["prefill_length"] = 31

        with self.assertRaisesRegex(RuntimeError, "manifest contract"):
            _build_pairs(fixed, route)


def _request(label: str, completed_ms: float) -> dict[str, object]:
    return {
        "success": True,
        "cancelled": False,
        "label": label,
        "first_audio_ms": 10.0,
        "completed_ms": completed_ms,
        "inverse_rtf": 2.0,
        "manifest_contract": {
            "valid": True,
            "expected": {
                "prefill_length": 32,
                "route": "compiled_allowlist",
                "backend": "compile_reduce_overhead",
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
