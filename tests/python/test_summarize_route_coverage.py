"""Tests for anonymous route coverage aggregation."""

from __future__ import annotations

import math
import unittest
from typing import cast

from scripts.summarize_route_coverage import _summarize, _validate_record

_PROFILE = "rtx4090-cv06-bf16-sdpa-strict-v1-9d2a61ef"


class SummarizeRouteCoverageTests(unittest.TestCase):
    def test_counts_exact_coverage_only_for_verified_compiled_route(self) -> None:
        records = [_record(32), _record(32, route="eager_unknown")]

        summary = _summary(records)

        self.assertFalse(summary["acceptance_pass"])
        self.assertEqual(1, summary["exact_allowlist_count"])
        self.assertEqual(1, summary["invalid_route_count"])
        self.assertEqual("reject_invalid_canary", summary["decision"])

    def test_rejects_mixed_runtime_profiles(self) -> None:
        records = [_record(32), _record(31, runtime_profile_id="other-profile-9d2a")]

        summary = _summary(records)

        self.assertFalse(summary["acceptance_pass"])
        self.assertEqual(1, summary["profile_mismatch_count"])

    def test_rejects_compiled_cache_policy_violation(self) -> None:
        record = _record(32)
        record["prefill_cache_hit"] = False

        summary = _summary([record])

        self.assertFalse(summary["acceptance_pass"])
        self.assertEqual(
            {"compiled_contract_mismatch": 1},
            summary["invalid_route_reasons"],
        )

    def test_long_tail_does_not_block_eligible_unknown_gate(self) -> None:
        records = [_record(32) for _ in range(10)]
        records.extend(_record(31) for _ in range(10))
        records.extend(_record(length) for length in range(40, 45))

        summary = _summary(
            records,
            min_requests=25,
            min_unknown_requests=10,
            min_samples_per_length=10,
            min_eligible_unknown_coverage_percent=60.0,
            min_exact_coverage_percent=50.0,
        )

        self.assertTrue(summary["acceptance_pass"])
        self.assertEqual("evaluate_padded_bucket_correctness", summary["decision"])
        self.assertEqual({"31": 10}, summary["eligible_unknown_length_histogram"])

    def test_rejects_text_or_request_identity_fields(self) -> None:
        record = _record(32)
        record["text"] = "must never appear in telemetry"

        with self.assertRaisesRegex(RuntimeError, "approved anonymous schema"):
            _validate_record(record, 1)

    def test_rejects_invalid_optional_metrics(self) -> None:
        record = _record(32)
        record["first_audio_ms"] = math.nan

        with self.assertRaisesRegex(RuntimeError, "first_audio_ms must be finite"):
            _validate_record(record, 1)

    def test_rejects_completed_before_first_audio(self) -> None:
        record = _record(32)
        record["first_audio_ms"] = 10.0
        record["completed_ms"] = 9.0

        with self.assertRaisesRegex(RuntimeError, "completed_ms precedes"):
            _validate_record(record, 1)


def _summary(
    records: list[dict[str, object]],
    **overrides: object,
) -> dict[str, object]:
    defaults: dict[str, object] = {
        "runtime_profile_id": _PROFILE,
        "compiled_lengths": {32},
        "min_requests": 1,
        "min_unknown_requests": 1,
        "min_samples_per_length": 1,
        "min_eligible_unknown_coverage_percent": 80.0,
        "min_exact_coverage_percent": 90.0,
    }
    defaults.update(overrides)
    return _summarize(
        records,
        runtime_profile_id=cast(str, defaults["runtime_profile_id"]),
        compiled_lengths=cast(set[int], defaults["compiled_lengths"]),
        min_requests=cast(int, defaults["min_requests"]),
        min_unknown_requests=cast(int, defaults["min_unknown_requests"]),
        min_samples_per_length=cast(int, defaults["min_samples_per_length"]),
        min_eligible_unknown_coverage_percent=cast(
            float, defaults["min_eligible_unknown_coverage_percent"]
        ),
        min_exact_coverage_percent=cast(
            float, defaults["min_exact_coverage_percent"]
        ),
    )


def _record(
    prefill_length: int,
    *,
    runtime_profile_id: str = _PROFILE,
    route: str | None = None,
) -> dict[str, object]:
    compiled = prefill_length == 32
    if route is None:
        route = "compiled_allowlist" if compiled else "eager_unknown"
    return {
        "schema_version": 2,
        "runtime_profile_id": runtime_profile_id,
        "talker_prefill_length": prefill_length,
        "prefill_shape_policy": route,
        "prefill_backend_used": (
            "compile_reduce_overhead" if compiled else "eager"
        ),
        "selected_chunk_schedule": [8, 8, 12] if compiled else [8],
        "prefill_cache_hit": compiled,
        "prefill_compile_attempted": False,
        "prefill_compile_fallback": False,
    }


if __name__ == "__main__":
    unittest.main()
