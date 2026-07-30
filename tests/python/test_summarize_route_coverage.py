"""Tests for anonymous route coverage aggregation."""

from __future__ import annotations

import unittest

from scripts.summarize_route_coverage import _summarize, _validate_record


class SummarizeRouteCoverageTests(unittest.TestCase):
    def test_recommends_padded_bucket_research_only_after_coverage_gate(self) -> None:
        records = [_record(32) for _ in range(3)] + [_record(31) for _ in range(3)]

        summary = _summarize(
            records,
            compiled_lengths={32},
            min_requests=6,
            min_samples_per_length=3,
            min_exact_coverage_percent=75.0,
        )

        self.assertEqual("evaluate_padded_bucket_correctness", summary["decision"])

    def test_rejects_text_or_request_identity_fields(self) -> None:
        record = _record(32)
        record["text"] = "must never appear in telemetry"

        with self.assertRaisesRegex(RuntimeError, "approved anonymous schema"):
            _validate_record(record, 1)


def _record(prefill_length: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "talker_prefill_length": prefill_length,
        "prefill_shape_policy": "compiled_allowlist",
        "prefill_backend_used": "compile_reduce_overhead",
        "selected_chunk_schedule": [8, 8, 12],
    }


if __name__ == "__main__":
    unittest.main()
