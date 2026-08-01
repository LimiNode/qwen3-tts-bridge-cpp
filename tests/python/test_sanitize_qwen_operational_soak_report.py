"""Tests for operational soak report sanitization."""

from __future__ import annotations

import json
import unittest

from scripts.sanitize_qwen_operational_soak_report import _sanitize_report


class SanitizeQwenOperationalSoakReportTests(unittest.TestCase):
    def test_keeps_aggregate_contract_without_process_or_request_identifiers(
        self,
    ) -> None:
        sanitized = _sanitize_report(_report())
        serialized = json.dumps(sanitized, sort_keys=True)

        self.assertTrue(sanitized["acceptance_pass"])
        self.assertIn("3.12.10", serialized)
        self.assertNotIn("private request", serialized)
        self.assertNotIn("C:/private", serialized)
        self.assertNotIn("session-123", serialized)
        self.assertNotIn("12345", serialized)


def _report() -> dict[str, object]:
    return {
        "acceptance_pass": True,
        "config": {
            "requests": 10,
            "required_label": ["compiled_18_ryan"],
            "partial_output": "C:/private/report.json",
        },
        "summary": {"completed_requests": 9, "cancelled_requests": 1},
        "validation": {"failures": [], "cache_entries_observed": [6]},
        "ready": {
            "session_id": "session-123",
            "warmed_up": True,
            "capabilities": {"streaming": True},
        },
        "runtime": {
            "python": {"version_info": [3, 12, 10], "executable": "C:/private/x"},
            "torch": {"version": "2.10.0+cu128", "cuda_runtime": "12.8"},
            "imports": {
                "faster_qwen3_tts": {
                    "available": True,
                    "source_bundle_sha256": "a" * 64,
                    "origin": "C:/private/faster.py",
                    "source_git": {"commit": "b" * 40, "dirty": False},
                    "distribution": {"version": "0.3.2", "location": "C:/private"},
                },
                "qwen_tts_bridge_worker": {
                    "available": True,
                    "source_bundle_sha256": "c" * 64,
                    "source_git": {"commit": "d" * 40, "dirty": True},
                },
            },
            "process": {"pid": 12345},
        },
        "requests": [{"text": "private request", "request_id": 1}],
        "memory_snapshots": [{"pid": 12345}],
        "worker_metrics": [{"request_id": 1}],
    }


if __name__ == "__main__":
    unittest.main()
