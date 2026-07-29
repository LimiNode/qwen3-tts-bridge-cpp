"""Tests for the semantic, cancellation-aware release soak gate."""

from __future__ import annotations

import unittest
from typing import cast

from scripts.qwen_release_soak import _validate_release_soak


class ReleaseSoakTests(unittest.TestCase):
    def test_requires_each_label_and_cancellation_stage(self) -> None:
        results = [
            _completed(1, "allowlist_29", "reference"),
            _cancelled(2, "allowlist_29", "before_first_audio"),
            _completed(3, "allowlist_29", "audit"),
        ]

        validation = _validate_release_soak(
            results,
            _snapshots(),
            _worker_memory_metrics(results),
            expected_cache_entries=6,
            expected_requests=3,
            expected_cancellations=1,
            expected_labels={"allowlist_29", "unknown_short"},
            cancellations_per_stage=1,
            max_rss_growth_mb=1.0,
        )

        failures = cast(list[str], validation["failures"])
        self.assertIn(
            "allowlist_29: insufficient after_first_audio cancellations",
            failures,
        )
        self.assertIn(
            "unknown_short: insufficient before_first_audio cancellations",
            failures,
        )

    def test_semantic_audit_requires_matching_pcm_and_trace(self) -> None:
        reference = _completed(1, "allowlist_29", "reference")
        audit = _completed(2, "allowlist_29", "audit")
        audit["pcm_sha256"] = "b" * 64
        results = [reference, audit]

        validation = _validate_release_soak(
            results,
            _snapshots(),
            _worker_memory_metrics(results),
            expected_cache_entries=6,
            expected_requests=2,
            expected_cancellations=0,
            expected_labels={"allowlist_29"},
            cancellations_per_stage=0,
            max_rss_growth_mb=1.0,
        )

        self.assertIn(
            "request 2: post-cancel semantic fingerprint changed",
            cast(list[str], validation["failures"]),
        )


def _completed(request_id: int, label: str, role: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "terminal_state": "completed",
        "shape_label": label,
        "role": role,
        "pcm_sha256": "a" * 64,
        "audio_chunks": 8,
        "audio_bytes": 128,
        "generation_trace": {
            "codec_frame_count": 8,
            "codec_sha256": "a" * 64,
            "emitted_steps": 8,
            "generated_steps": 8,
            "hit_eos": True,
            "hit_max_new_tokens": False,
            "hit_max_seq_len": False,
            "terminal_step_index": 8,
            "terminal_token_id": 9,
            "termination_reason": "eos",
        },
        **_route(label),
    }


def _cancelled(request_id: int, label: str, stage: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "terminal_state": "cancelled",
        "shape_label": label,
        "role": "cancel",
        "cancel_stage": stage,
    }


def _route(label: str) -> dict[str, object]:
    known = label.startswith("allowlist_")
    return {
        "first_chunk_prefill_backend_used": (
            "compile_reduce_overhead" if known else "eager"
        ),
        "first_chunk_prefill_compile_fallback": False,
        "first_chunk_prefill_compile_attempted": False,
        "first_chunk_prefill_compile_attempt_count": 0,
        "first_chunk_prefill_compile_cache_entries": 6,
        "first_chunk_prefill_compile_cache_entries_delta": 0,
        "first_chunk_prefill_compile_cache_evictions_delta": 0,
        "first_chunk_prefill_dynamo_counter_available": True,
        "first_chunk_prefill_dynamo_unique_graphs_delta": 0,
        "first_chunk_prefill_compile_cache_hit": known,
        "first_chunk_prefill_require_precompiled": known,
    }


def _snapshots() -> list[dict[str, object]]:
    return [
        {
            "rss_tree_bytes": 100,
            "private_tree_bytes": 100,
            "processes": [{"pid": 42}],
            "gpu_process_memory_mib": {"42": None},
        },
        {
            "rss_tree_bytes": 110,
            "private_tree_bytes": 110,
            "processes": [{"pid": 42}],
            "gpu_process_memory_mib": {"42": None},
        },
    ]


def _worker_memory_metrics(results: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "event": "worker_runtime_memory",
            "request_id": result["request_id"],
            "worker_pid": 42,
            "cuda_memory_allocated_bytes": 1,
            "cuda_memory_reserved_bytes": 1,
            "cuda_memory_max_reserved_bytes": 1,
        }
        for result in results
    ]


if __name__ == "__main__":
    unittest.main()
