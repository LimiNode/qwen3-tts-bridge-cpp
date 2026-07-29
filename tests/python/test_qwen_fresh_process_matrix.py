"""Tests for fresh-process exact-allowlist matrix validation."""

from __future__ import annotations

import argparse
import copy
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import cast

from scripts.qwen_fresh_process_matrix import _analyze_report, _build_schedule


class FreshProcessMatrixTests(unittest.TestCase):
    def test_route_specific_acceptance_keeps_global_sla_separate(self) -> None:
        report = _report()

        summary = _analyze_report(report, _args())

        acceptance = summary["acceptance"]
        self.assertEqual(2, summary["artifact_schema_version"])
        self.assertTrue(summary["acceptance_pass"])
        self.assertTrue(acceptance["terminal_trace_acceptance_pass"])
        self.assertTrue(acceptance["routing_acceptance_pass"])
        self.assertTrue(acceptance["compiled_latency_acceptance_pass"])
        self.assertTrue(acceptance["eager_latency_acceptance_pass"])
        self.assertFalse(acceptance["global_latency_acceptance_pass"])

    def test_known_compiled_backend_is_fail_closed(self) -> None:
        report = _report()
        runs = cast(list[dict[str, object]], report["runs"])
        requests = cast(list[dict[str, object]], runs[0]["requests"])
        request = requests[0]
        request["first_chunk_prefill_backend_used"] = "eager"

        summary = _analyze_report(report, _args())

        self.assertFalse(summary["acceptance_pass"])
        self.assertFalse(summary["acceptance"]["routing_acceptance_pass"])
        self.assertIn("compile_reduce_overhead", "\n".join(summary["failures"]))

    def test_schedule_count_mismatch_fails_routing_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            schedule = Path(temp) / "schedule.jsonl"
            schedule.write_text('{"label":"allowlist_32"}\n', encoding="utf-8")
            summary = _analyze_report(_report(), _args(schedule))

        self.assertFalse(summary["acceptance_pass"])
        self.assertIn("schedule category counts differ", "\n".join(summary["failures"]))

    def test_scenario_schedule_repeats_and_shuffles_validated_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scenarios.jsonl"
            path.write_text(
                '{"label":"allowlist_32","text":"First.",'
                '"talker_prefill_length":32}\n'
                '{"label":"unknown_short","text":"Second.",'
                '"talker_prefill_length":31}\n',
                encoding="utf-8",
            )
            rows = _build_schedule(
                argparse.Namespace(
                    manifest=None,
                    scenarios_jsonl=path,
                    repeats=3,
                    seed=17,
                )
            )

        self.assertEqual(6, len(rows))
        self.assertEqual(
            Counter({"allowlist_32": 3, "unknown_short": 3}),
            Counter(str(row["label"]) for row in rows),
        )


def _args(schedule: Path | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        schedule=schedule,
        compiled_first_ttfa_p95_max_ms=300.0,
        eager_first_ttfa_p95_max_ms=450.0,
        global_first_ttfa_p95_max_ms=300.0,
        first_minus_steady_p95_max_ms=20.0,
    )


def _report() -> dict[str, object]:
    known = _request(
        length=32,
        backend="compile_reduce_overhead",
        policy="compiled_allowlist",
        allowlist_hit=True,
        cache_hit=True,
        require_precompiled=True,
        ordinal=4,
    )
    unknown = _request(
        length=31,
        backend="eager",
        policy="eager_unknown",
        allowlist_hit=False,
        cache_hit=False,
        require_precompiled=False,
        ordinal=0,
    )
    return {
        "config": {"requests_per_run": 1},
        "runs": [
            _run("allowlist_32", 32, known, 255.0),
            _run("unknown_short", 31, unknown, 390.0),
        ],
    }


def _run(
    label: str,
    length: int,
    request: dict[str, object],
    first_audio_ms: float,
) -> dict[str, object]:
    request = copy.deepcopy(request)
    request["first_audio_ms"] = first_audio_ms
    return {
        "shape": {"label": label, "talker_prefill_length": length},
        "requests": [request],
        "first_request": request,
        "paired_delta_first_audio_ms": 5.0,
    }


def _request(
    *,
    length: int,
    backend: str,
    policy: str,
    allowlist_hit: bool,
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
        "first_chunk_talker_prefill_length": length,
        "first_chunk_prefill_shape_policy": policy,
        "first_chunk_prefill_shape_allowlist_hit": allowlist_hit,
        "first_chunk_prefill_backend_used": backend,
        "first_chunk_prefill_compile_cache_hit": cache_hit,
        "first_chunk_prefill_compile_fallback": False,
        "first_chunk_prefill_require_precompiled": require_precompiled,
        "first_chunk_prefill_shape_call_ordinal": ordinal,
        "first_chunk_prefill_compile_attempted": False,
        "first_chunk_prefill_compile_attempt_count": 0,
        "first_chunk_prefill_compile_cache_entries_delta": 0,
        "first_chunk_prefill_compile_cache_evictions_delta": 0,
        "first_chunk_prefill_dynamo_counter_available": True,
        "first_chunk_prefill_dynamo_unique_graphs_delta": 0,
    }


if __name__ == "__main__":
    unittest.main()
