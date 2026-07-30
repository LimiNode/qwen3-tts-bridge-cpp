"""Tests for worker diagnostics to anonymous canary telemetry export."""

from __future__ import annotations

import json
import unittest

from scripts.export_route_aware_canary_telemetry import _export_records


class ExportRouteAwareCanaryTelemetryTests(unittest.TestCase):
    def test_exports_completed_and_cancelled_requests_without_ids(self) -> None:
        records = _export_records(
            [
                _metric("request_first_chunk_engine_phases", 1, **_route()),
                _metric(
                    "request_finished",
                    1,
                    terminal_state="completed",
                    first_audio_ms=10.0,
                    synthesis_ms=20.0,
                    audio_duration_ms=40.0,
                ),
                _metric("request_finished", 2, terminal_state="cancelled"),
            ],
            "profile-v21-9d2a61ef",
        )

        self.assertEqual("completed", records[0]["request_outcome"])
        self.assertEqual(2.0, records[0]["inverse_rtf"])
        self.assertNotIn("request_id", records[0])
        self.assertEqual("cancelled_before_audio", records[1]["request_outcome"])
        self.assertFalse(records[1]["route_decision_made"])

    def test_rejects_incomplete_route_metrics(self) -> None:
        route = _route()
        del route["prefill_compile_cache_hit"]

        with self.assertRaisesRegex(RuntimeError, "lacks prefill_compile_cache_hit"):
            _export_records(
                [_metric("request_first_chunk_engine_phases", 1, **route)],
                "profile-v21-9d2a61ef",
            )


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
