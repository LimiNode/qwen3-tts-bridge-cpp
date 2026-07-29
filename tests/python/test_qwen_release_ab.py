"""Tests for release A/B benchmark comparison."""

from __future__ import annotations

import copy
import unittest
from typing import cast

from scripts.qwen_release_ab import _compare


class ReleaseAbTests(unittest.TestCase):
    def test_compare_accepts_matching_eager_and_allowlist_reports(self) -> None:
        baseline = _report(_request("eager", "eager_unknown", False, False, 0))
        candidate = _report(
            _request("compile_reduce_overhead", "compiled_allowlist", True, True, 4)
        )

        report = cast(
            dict[str, object],
            _compare(baseline, candidate, _candidate_matrix_summary()),
        )
        acceptance = cast(dict[str, object], report["acceptance"])
        comparisons = cast(dict[str, object], report["comparisons"])
        known = cast(dict[str, object], comparisons["known_compiled"])
        candidate_summary = cast(dict[str, object], known["candidate"])

        self.assertTrue(report["acceptance_pass"])
        self.assertTrue(acceptance["workload_match_pass"])
        self.assertEqual(
            1,
            candidate_summary["fresh_processes"],
        )

    def test_compare_rejects_baseline_non_eager_route(self) -> None:
        baseline = _report(
            _request("compile_reduce_overhead", "eager_unknown", False, False, 0)
        )
        candidate = _report(
            _request("compile_reduce_overhead", "compiled_allowlist", True, True, 4)
        )

        report = cast(
            dict[str, object],
            _compare(baseline, candidate, _candidate_matrix_summary()),
        )
        acceptance = cast(dict[str, object], report["acceptance"])

        self.assertFalse(report["acceptance_pass"])
        self.assertFalse(acceptance["baseline_eager_contract_pass"])


def _report(request: dict[str, object]) -> dict[str, object]:
    first_request = copy.deepcopy(request)
    first_request.update(
        {
            "first_audio_ms": 300.0,
            "completed_ms": 1000.0,
            "real_time_factor": 0.4,
            "startup_ms": 20000.0,
        }
    )
    return {
        "runtime": {
            "imports": {
                "faster_qwen3_tts": {
                    "distribution": {
                        "direct_url": {"archive_info": {"hash": "sha256=test"}}
                    }
                }
            }
        },
        "runs": [
            {
                "shape": {
                    "label": "allowlist_32",
                    "scenario_id": "case",
                    "text": "Text.",
                    "language": "English",
                    "speaker": "ryan",
                    "instruction": "",
                    "talker_prefill_length": 32,
                },
                "requests": [first_request],
                "first_request": first_request,
                "paired_delta_first_audio_ms": 2.0,
            }
        ],
    }


def _request(
    backend: str,
    policy: str,
    cache_hit: bool,
    require_precompiled: bool,
    ordinal: int,
) -> dict[str, object]:
    return {
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
        "first_chunk_prefill_backend_used": backend,
        "first_chunk_prefill_shape_policy": policy,
        "first_chunk_prefill_compile_cache_hit": cache_hit,
        "first_chunk_prefill_require_precompiled": require_precompiled,
        "first_chunk_prefill_shape_call_ordinal": ordinal,
        "first_chunk_prefill_compile_fallback": False,
        "first_chunk_prefill_compile_attempted": False,
        "first_chunk_prefill_compile_attempt_count": 0,
        "first_chunk_prefill_compile_cache_entries_delta": 0,
        "first_chunk_prefill_compile_cache_evictions_delta": 0,
        "first_chunk_prefill_dynamo_counter_available": True,
        "first_chunk_prefill_dynamo_unique_graphs_delta": 0,
    }


def _candidate_matrix_summary() -> dict[str, object]:
    return {
        "acceptance": {
            "terminal_trace_acceptance_pass": True,
            "routing_acceptance_pass": True,
            "compiled_latency_acceptance_pass": True,
            "eager_latency_acceptance_pass": True,
        }
    }


if __name__ == "__main__":
    unittest.main()
