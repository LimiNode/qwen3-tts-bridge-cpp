"""Tests for mixed long-lived-worker soak validation."""

from __future__ import annotations

import argparse
import hashlib
import tempfile
import unittest
from pathlib import Path
from typing import cast

from scripts.qwen_mixed_soak import (
    _faster_source_bundle_sha256,
    _validate_faster_provenance,
    _validate_soak,
    _validate_worker_args,
)


class MixedSoakTests(unittest.TestCase):
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

    def test_source_bundle_provenance_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package = Path(temporary_directory) / "faster_qwen3_tts"
            package.mkdir()
            module = package / "__init__.py"
            module.write_text("VERSION = 'test'\n", encoding="utf-8")
            runtime = {"imports": {"faster_qwen3_tts": {"origin": str(module)}}}

            digest = hashlib.sha256()
            digest.update(b"__init__.py\0")
            digest.update(module.read_bytes())
            digest.update(b"\0")
            expected = digest.hexdigest()

            self.assertEqual(expected, _faster_source_bundle_sha256(runtime))
            _validate_faster_provenance(runtime, "", expected)
            with self.assertRaisesRegex(RuntimeError, "SHA mismatch"):
                _validate_faster_provenance(runtime, "", "0" * 64)


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
