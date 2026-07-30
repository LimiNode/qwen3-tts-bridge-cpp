"""Tests for worker diagnostics to anonymous canary telemetry export."""

from __future__ import annotations

import json
import unittest

from scripts.export_route_aware_canary_telemetry import _export

_PROFILE = {
    "runtime_profile_id": "profile-v21-9d2a61ef",
    "bridge_commit": "56ecc48123456789",
    "faster_wheel_sha256": "a" * 64,
    "compiled_allowlist_manifest_sha256": "b" * 64,
}


class ExportRouteAwareCanaryTelemetryTests(unittest.TestCase):
    def test_exports_completed_and_cancelled_requests_without_ids(self) -> None:
        result = _export(
            [
                _provenance(),
                _metric("request_received", 1),
                _metric("request_first_chunk_engine_phases", 1, **_route()),
                _metric(
                    "request_finished",
                    1,
                    terminal_state="completed",
                    first_audio_ms=10.0,
                    synthesis_ms=20.0,
                    audio_duration_ms=40.0,
                ),
                _metric("request_received", 2),
                _metric("request_finished", 2, terminal_state="cancelled"),
            ],
            _PROFILE,
            "synthetic_proxy",
            allow_open_requests=False,
        )

        self.assertTrue(result.summary["integrity_valid"])
        self.assertEqual("completed", result.records[0]["request_outcome"])
        self.assertEqual(2.0, result.records[0]["inverse_rtf"])
        self.assertNotIn("request_id", result.records[0])
        self.assertEqual("synthetic_proxy", result.records[0]["evidence_source"])
        self.assertEqual("cancelled_before_audio", result.records[1]["request_outcome"])
        self.assertFalse(result.records[1]["route_decision_made"])

    def test_rejects_open_requests_by_default(self) -> None:
        result = _export(
            [_provenance(), _metric("request_received", 1)],
            _PROFILE,
            "synthetic_proxy",
            allow_open_requests=False,
        )

        self.assertFalse(result.summary["integrity_valid"])
        self.assertEqual(1, result.summary["open_request_count"])

    def test_live_capture_can_explicitly_allow_open_requests(self) -> None:
        result = _export(
            [_provenance(), _metric("request_received", 1)],
            _PROFILE,
            "synthetic_proxy",
            allow_open_requests=True,
        )

        self.assertTrue(result.summary["integrity_valid"])

    def test_rejects_orphan_duplicate_and_invalid_relevant_metrics(self) -> None:
        result = _export(
            [
                _provenance(),
                _metric("request_received", 1),
                _metric("request_first_chunk_engine_phases", 1, **_route()),
                _metric("request_first_chunk_engine_phases", 1, **_route()),
                _metric("request_finished", 2, terminal_state="failed"),
                "qtb_metric " + json.dumps({"event": "request_received"}),
            ],
            _PROFILE,
            "synthetic_proxy",
            allow_open_requests=True,
        )

        self.assertFalse(result.summary["integrity_valid"])
        self.assertEqual(1, result.summary["duplicate_route_count"])
        self.assertEqual(1, result.summary["orphan_request_count"])
        self.assertEqual(1, result.summary["ignored_metric_count"])

    def test_rejects_profile_provenance_mismatch(self) -> None:
        wrong = dict(_PROFILE)
        wrong["bridge_commit"] = "wrong"
        result = _export(
            [_provenance(wrong)],
            _PROFILE,
            "synthetic_proxy",
            allow_open_requests=False,
        )

        self.assertFalse(result.summary["integrity_valid"])
        self.assertFalse(result.summary["worker_provenance_matches_manifest"])


def _provenance(values: dict[str, str] | None = None) -> str:
    payload = {"event": "canary_runtime_provenance", **(values or _PROFILE)}
    return "qtb_metric " + json.dumps(payload)


def _metric(event: str, request_id: int, **fields: object) -> str:
    return "qtb_metric " + json.dumps(
        {"event": event, "request_id": request_id, **fields}
    )


def _route() -> dict[str, object]:
    return {
        "talker_prefill_length": 32,
        "prefill_shape_policy": "compiled_allowlist",
        "prefill_backend_used": "compile_reduce_overhead",
        "selected_chunk_schedule": [8, 8, 12],
        "prefill_compile_cache_hit": True,
        "prefill_compile_attempted": False,
        "prefill_compile_fallback": False,
    }


if __name__ == "__main__":
    unittest.main()
