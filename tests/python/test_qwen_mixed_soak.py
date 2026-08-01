"""Tests for mixed long-lived-worker soak validation."""

from __future__ import annotations

import argparse
import unittest
from typing import cast

from scripts.qwen_mixed_soak import (
    _validate_soak,
    _validate_wheel,
    _validate_worker_args,
)


class MixedSoakTests(unittest.TestCase):
    def test_accepts_source_bundle_provenance_without_a_wheel(self) -> None:
        _validate_wheel(
            {
                "imports": {
                    "faster_qwen3_tts": {
                        "source_bundle_sha256": "a" * 64,
                    }
                }
            },
            "",
            "a" * 64,
        )

    def test_rejects_source_bundle_provenance_mismatch(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "source bundle SHA mismatch"):
            _validate_wheel(
                {
                    "imports": {
                        "faster_qwen3_tts": {
                            "source_bundle_sha256": "a" * 64,
                        }
                    }
                },
                "",
                "b" * 64,
            )

    def test_benchmark_style_engine_flag_is_rejected(self) -> None:
        parser = cast(argparse.ArgumentParser, _RecordingParser())

        with self.assertRaisesRegex(ValueError, "worker process arguments"):
            _validate_worker_args(parser, ["--engine", "qwen"])

    def test_completed_requests_and_cancellation_reset_pass(self) -> None:
        results = [
            _request(1, "allowlist_32", "cancelled"),
            _request(2, "unknown_short", "completed"),
            _request(3, "allowlist_32", "completed"),
        ]

        validation = _validate_soak(
            results,
            [{"rss_bytes": 100}, {"rss_bytes": 110}],
            max_rss_growth_mb=1.0,
            expected_requests=3,
            expected_cancelled=1,
        )

        self.assertEqual([], validation["failures"])
        self.assertEqual(1, validation["cancellation_reset_checks"])
        self.assertEqual([6.0], validation["cache_entries_observed"])

    def test_cache_change_fails(self) -> None:
        results = [
            _request(1, "allowlist_32", "completed"),
            _request(2, "unknown_short", "completed"),
        ]
        results[1]["first_chunk_prefill_compile_cache_entries"] = 7

        validation = _validate_soak(
            results,
            [{"rss_bytes": 100}, {"rss_bytes": 110}],
            max_rss_growth_mb=1.0,
            expected_requests=2,
            expected_cancelled=0,
        )

        failures = cast(list[str], validation["failures"])
        self.assertIn("prefill compile cache changed", "\n".join(failures))


def _request(
    request_id: int,
    label: str,
    terminal_state: str,
) -> dict[str, object]:
    known = label.startswith("allowlist_")
    result: dict[str, object] = {
        "request_id": request_id,
        "terminal_state": terminal_state,
        "shape": {"label": label},
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
    }
    if known:
        result["first_chunk_prefill_compile_cache_hit"] = True
        result["first_chunk_prefill_require_precompiled"] = True
    if terminal_state == "completed":
        result["generation_trace"] = {
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
        }
    return result


class _RecordingParser:
    def error(self, message: str) -> None:
        raise ValueError(message)


if __name__ == "__main__":
    unittest.main()
