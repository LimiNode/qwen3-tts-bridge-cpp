"""Tests for the C++ public API soak validator."""

from __future__ import annotations

import unittest
from typing import cast

from scripts.validate_cpp_api_soak import validate_cpp_api_soak


class ValidateCppApiSoakTests(unittest.TestCase):
    def test_accepts_compiled_completion_and_first_pcm_cancellation(self) -> None:
        artifact = {
            "requests": [
                {
                    "request_id": 1,
                    "success": True,
                    "cancelled": False,
                    "audio_chunks": 3,
                    "chunks": _client_chunks(3),
                },
                {
                    "request_id": 2,
                    "success": False,
                    "cancelled": True,
                    "audio_chunks": 1,
                    "chunks": _client_chunks(1),
                },
            ]
        }
        validation = validate_cpp_api_soak(
            cast(dict[str, object], artifact),
            [
                _phases(1),
                *_chunks(1, completed=True),
                _finished(1, final_chunk_index=2),
                _memory(1),
                _phases(2),
                *_chunks(2, completed=False),
                _memory(2),
            ],
            expected_requests=2,
            expected_cancelled=1,
            expected_cache_entries=6,
            expected_first_chunk_steps=6,
            expected_chunk_schedule=(6, 8, 12),
        )

        self.assertEqual([], cast(list[str], validation["failures"]))

    def test_rejects_route_regression(self) -> None:
        artifact = {
            "requests": [
                {
                    "request_id": 1,
                    "success": True,
                    "cancelled": False,
                    "audio_chunks": 2,
                    "chunks": _client_chunks(2),
                }
            ]
        }
        phases = _phases(1)
        phases["prefill_backend_used"] = "eager"
        validation = validate_cpp_api_soak(
            cast(dict[str, object], artifact),
            [
                phases,
                *_chunks(1, completed=True),
                _finished(1, final_chunk_index=2),
                _memory(1),
            ],
            expected_requests=1,
            expected_cancelled=0,
            expected_cache_entries=6,
        )

        self.assertIn(
            "request 1: expected prefill_backend_used='compile_reduce_overhead'",
            cast(list[str], validation["failures"]),
        )

    def test_rejects_first_chunk_schedule_regression(self) -> None:
        artifact = {
            "requests": [
                {
                    "request_id": 1,
                    "success": True,
                    "cancelled": False,
                    "audio_chunks": 3,
                    "chunks": _client_chunks(3),
                }
            ]
        }
        phases = _phases(1)
        phases["chunk_steps"] = 8
        validation = validate_cpp_api_soak(
            cast(dict[str, object], artifact),
            [
                phases,
                *_chunks(1, completed=True),
                _finished(1, final_chunk_index=2),
                _memory(1),
            ],
            expected_requests=1,
            expected_cancelled=0,
            expected_cache_entries=6,
            expected_first_chunk_steps=6,
            expected_chunk_schedule=(6, 8, 12),
        )

        self.assertIn(
            "request 1: expected chunk_steps=6",
            cast(list[str], validation["failures"]),
        )

    def test_accepts_self_contained_manifest_contract(self) -> None:
        phases = _phases(1)
        phases["talker_prefill_length"] = 32
        artifact = {
            "requests": [
                {
                    "request_id": 1,
                    "label": "compiled_32",
                    "success": True,
                    "cancelled": False,
                    "audio_chunks": 3,
                    "chunks": _client_chunks(3),
                    "manifest_contract": {"checked": True, "valid": True},
                    "worker_telemetry": {
                        "first_chunk_phases": phases,
                        "pcm_chunks": _chunks(1, completed=True),
                        "finished": _finished(1, final_chunk_index=2),
                        "runtime_memory": _memory(1),
                    },
                }
            ]
        }

        validation = validate_cpp_api_soak(
            cast(dict[str, object], artifact),
            [],
            expected_requests=1,
            expected_cancelled=0,
            expected_cache_entries=6,
            expected_contracts={
                "compiled_32": {
                    "prefill_length": 32,
                    "route": "compiled_allowlist",
                    "backend": "compile_reduce_overhead",
                    "chunk_schedule": [6, 8, 12],
                }
            },
        )

        self.assertEqual([], cast(list[str], validation["failures"]))


def _phases(request_id: int) -> dict[str, object]:
    return {
        "event": "request_first_chunk_engine_phases",
        "request_id": request_id,
        "prefill_backend_used": "compile_reduce_overhead",
        "prefill_shape_policy": "compiled_allowlist",
        "prefill_shape_allowlist_hit": True,
        "prefill_compile_attempted": False,
        "prefill_compile_fallback": False,
        "prefill_compile_cache_hit": True,
        "prefill_require_precompiled": True,
        "prefill_dynamo_unique_graphs_delta": 0,
        "prefill_compile_cache_entries_delta": 0,
        "prefill_compile_cache_entries": 6,
        "chunk_steps": 6,
        "chunk_target_steps": 6,
    }


def _chunks(request_id: int, *, completed: bool) -> list[dict[str, object]]:
    sizes = (6, 8, 12) if completed else (6,)
    return [
        {
            "event": "request_pcm_chunk",
            "request_id": request_id,
            "chunk_index": index,
            "chunk_steps": size,
            "chunk_target_steps": size,
            "is_final": completed and index + 1 == len(sizes),
        }
        for index, size in enumerate(sizes)
    ]


def _client_chunks(count: int) -> list[dict[str, object]]:
    return [
        {
            "index": index,
            "arrival_ms": 100.0 + index * 50.0,
            "audio_duration_ms": 400.0,
        }
        for index in range(count)
    ]


def _memory(request_id: int) -> dict[str, object]:
    return {
        "event": "worker_runtime_memory",
        "request_id": request_id,
        "worker_pid": 42,
        "cuda_memory_allocated_bytes": 1,
        "cuda_memory_reserved_bytes": 1,
        "cuda_memory_max_reserved_bytes": 1,
    }


def _finished(request_id: int, *, final_chunk_index: int) -> dict[str, object]:
    return {
        "event": "request_finished",
        "request_id": request_id,
        "terminal_state": "completed",
        "final_pcm_chunk_index": final_chunk_index,
    }


if __name__ == "__main__":
    unittest.main()
