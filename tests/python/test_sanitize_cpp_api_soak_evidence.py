"""Tests for C++ API soak evidence sanitization."""

from __future__ import annotations

import unittest
from typing import cast

from scripts.sanitize_cpp_api_soak_evidence import (
    _embedded_worker_metrics,
    _sanitize_artifact,
    _sanitize_worker_metrics,
)


class SanitizeCppApiSoakEvidenceTests(unittest.TestCase):
    def test_extracts_embedded_worker_metrics(self) -> None:
        metrics = _embedded_worker_metrics(_artifact())

        self.assertEqual(
            [
                "request_first_chunk_engine_phases",
                "request_finished",
                "worker_runtime_memory",
                "request_pcm_chunk",
            ],
            [metric["event"] for metric in metrics],
        )

    def test_remaps_request_ids_and_drops_unapproved_metric_fields(self) -> None:
        artifact, request_id_map = _sanitize_artifact(_artifact())
        metrics = _sanitize_worker_metrics(_worker_metrics(), request_id_map)

        requests = cast(list[dict[str, object]], artifact["requests"])
        request = requests[0]
        config = cast(dict[str, object], artifact["config"])
        telemetry = cast(dict[str, object], request["worker_telemetry"])
        first_chunk = cast(dict[str, object], telemetry["first_chunk_phases"])
        self.assertEqual(1, request["request_id"])
        self.assertNotIn("text", config)
        self.assertNotIn(
            "profile_path",
            first_chunk,
        )
        self.assertEqual(1, metrics[0]["request_id"])
        self.assertNotIn("native_thread_id", metrics[0])
        self.assertEqual(1, metrics[1]["worker_pid"])


def _artifact() -> dict[str, object]:
    telemetry = {
        "first_chunk_phases": {
            "event": "request_first_chunk_engine_phases",
            "request_id": 42,
            "talker_prefill_length": 18,
            "prefill_shape_policy": "compiled_allowlist",
            "profile_path": "C:/private/profile.json",
        },
        "pcm_chunks": [
            {
                "event": "request_pcm_chunk",
                "request_id": 42,
                "chunk_index": 0,
                "chunk_steps": 8,
                "chunk_target_steps": 8,
                "is_final": False,
                "text_token_count": 10,
            }
        ],
        "finished": {
            "event": "request_finished",
            "request_id": 42,
            "terminal_state": "completed",
        },
        "runtime_memory": {
            "event": "worker_runtime_memory",
            "request_id": 42,
            "worker_pid": 9876,
            "cuda_memory_allocated_bytes": 1,
            "cuda_memory_reserved_bytes": 2,
            "cuda_memory_max_reserved_bytes": 3,
        },
    }
    return {
        "config": {"text": "private text", "requests": 1, "seed": 3},
        "summary": {"cancelled_requests": 0},
        "requests": [
            {
                "request_id": 42,
                "label": "compiled_18_ryan",
                "success": True,
                "cancelled": False,
                "audio_chunks": 1,
                "chunks": [],
                "worker_telemetry": telemetry,
            }
        ],
    }


def _worker_metrics() -> list[dict[str, object]]:
    return [
        {
            "event": "request_first_chunk_engine_phases",
            "request_id": 42,
            "talker_prefill_length": 18,
            "native_thread_id": 99,
        },
        {
            "event": "worker_runtime_memory",
            "request_id": 42,
            "worker_pid": 9876,
            "cuda_memory_allocated_bytes": 1,
            "cuda_memory_reserved_bytes": 2,
            "cuda_memory_max_reserved_bytes": 3,
        },
    ]


if __name__ == "__main__":
    unittest.main()
