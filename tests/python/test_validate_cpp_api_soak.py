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
                    "audio_chunks": 2,
                },
                {
                    "request_id": 2,
                    "success": False,
                    "cancelled": True,
                    "audio_chunks": 1,
                },
            ]
        }
        validation = validate_cpp_api_soak(
            cast(dict[str, object], artifact),
            [_phases(1), _memory(1), _phases(2), _memory(2)],
            expected_requests=2,
            expected_cancelled=1,
            expected_cache_entries=6,
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
                }
            ]
        }
        phases = _phases(1)
        phases["prefill_backend_used"] = "eager"
        validation = validate_cpp_api_soak(
            cast(dict[str, object], artifact),
            [phases, _memory(1)],
            expected_requests=1,
            expected_cancelled=0,
            expected_cache_entries=6,
        )

        self.assertIn(
            "request 1: expected prefill_backend_used='compile_reduce_overhead'",
            cast(list[str], validation["failures"]),
        )


def _phases(request_id: int) -> dict[str, object]:
    return {
        "event": "request_first_chunk_engine_phases",
        "request_id": request_id,
        "prefill_backend_used": "compile_reduce_overhead",
        "prefill_compile_attempted": False,
        "prefill_compile_fallback": False,
        "prefill_compile_cache_hit": True,
        "prefill_require_precompiled": True,
        "prefill_dynamo_unique_graphs_delta": 0,
        "prefill_compile_cache_entries_delta": 0,
        "prefill_compile_cache_entries": 6,
    }


def _memory(request_id: int) -> dict[str, object]:
    return {
        "event": "worker_runtime_memory",
        "request_id": request_id,
        "worker_pid": 42,
        "cuda_memory_allocated_bytes": 1,
        "cuda_memory_reserved_bytes": 1,
        "cuda_memory_max_reserved_bytes": 1,
    }


if __name__ == "__main__":
    unittest.main()
