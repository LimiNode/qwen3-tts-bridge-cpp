"""Tests for privacy-safe route-aware canary aggregation."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from typing import cast
from unittest.mock import patch

from scripts.summarize_route_coverage import (
    _load_records,
    _summarize,
    _validate_manifest_provenance,
    _validate_record,
    main,
)

_PROFILE = "rtx4090-cv06-bf16-sdpa-strict-v1-9d2a61ef"


class SummarizeRouteCoverageTests(unittest.TestCase):
    def test_coverage_counts_all_route_decisions_across_outcomes(self) -> None:
        records = [
            _record("completed", 32),
            _record("cancelled_after_audio", 31),
            _record("cancelled_before_audio", route_decision_made=False),
            _record("failed", 31),
        ]

        summary = _summary(records)

        self.assertTrue(summary["input_valid"])
        self.assertEqual(3, summary["route_decided_count"])
        self.assertEqual(1, summary["route_not_decided_count"])
        self.assertEqual(
            {
                "cancelled_after_audio": 1,
                "cancelled_before_audio": 1,
                "completed": 1,
                "failed": 1,
            },
            summary["outcome_histogram"],
        )
        self.assertEqual(1, summary["completed_latency_record_count"])

    def test_rejects_route_contract_violations(self) -> None:
        mutations = {
            "backend": {"prefill_backend_used": "eager"},
            "schedule": {"selected_chunk_schedule": [8]},
            "cache": {"prefill_cache_hit": False},
            "attempted": {"prefill_compile_attempted": True},
            "fallback": {"prefill_compile_fallback": True},
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                record = _record("completed", 32)
                record.update(mutation)

                summary = _summary([record])

                self.assertFalse(summary["input_valid"])
                self.assertEqual(1, summary["invalid_route_count"])

    def test_rejects_eager_cache_hit(self) -> None:
        record = _record("failed", 31)
        record["prefill_cache_hit"] = True

        summary = _summary([record])

        self.assertFalse(summary["input_valid"])
        self.assertEqual(
            {"eager_contract_mismatch": 1},
            summary["invalid_route_reasons"],
        )

    def test_rejects_mixed_runtime_profiles(self) -> None:
        records = [_record("completed", 32), _record("failed", 31)]
        records[1]["runtime_profile_id"] = "other-profile-9d2a"

        summary = _summary(records)

        self.assertFalse(summary["input_valid"])
        self.assertEqual(1, summary["profile_mismatch_count"])

    def test_validates_outcome_specific_field_sets(self) -> None:
        completed = _record("completed", 32)
        del completed["inverse_rtf"]
        no_route = _record("cancelled_before_audio", route_decision_made=False)
        no_route["prefill_cache_hit"] = False

        with self.assertRaisesRegex(RuntimeError, "completed requires full latency"):
            _validate_record(completed, 1)
        with self.assertRaisesRegex(RuntimeError, "route fields require"):
            _validate_record(no_route, 2)

    def test_accepts_equal_first_audio_and_completion(self) -> None:
        record = _record("completed", 32)
        record["first_audio_ms"] = 10.0
        record["completed_ms"] = 10.0

        _validate_record(record, 1)

    def test_rejects_malformed_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "telemetry.jsonl"
            path.write_text("{not-json}\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "malformed JSON"):
                _load_records(path)

    def test_evidence_threshold_boundaries(self) -> None:
        exact = [_record("completed", 32) for _ in range(450)]
        unknown = [_record("failed", 31) for _ in range(50)]

        keep = _summary(exact + unknown, min_requests=500)
        self.assertTrue(keep["evidence_gate_pass"])
        self.assertEqual("keep_exact_allowlist", keep["decision"])

        bucket = _summary(
            [_record("completed", 32) for _ in range(449)]
            + [_record("failed", 31) for _ in range(100)],
            min_requests=500,
            min_unknown_requests=100,
            min_samples_per_length=30,
        )
        self.assertTrue(bucket["evidence_gate_pass"])
        self.assertEqual("evaluate_padded_bucket_correctness", bucket["decision"])

        insufficient = _summary(exact + unknown[:-1], min_requests=500)
        self.assertFalse(insufficient["evidence_gate_pass"])
        self.assertEqual("collect_more_anonymous_coverage", insufficient["decision"])

    def test_cli_require_decision_controls_exit_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "canary.jsonl"
            input_path.write_text(
                json.dumps(_record("completed", 32)) + "\n",
                encoding="utf-8",
            )
            profile_path, allowlist_path = _write_manifests(root)
            output_path = root / "summary.json"
            arguments = [
                "summarize_route_coverage.py",
                str(input_path),
                "--runtime-profile-id",
                _PROFILE,
                "--runtime-profile-manifest",
                str(profile_path),
                "--compiled-allowlist-manifest",
                str(allowlist_path),
                "--compiled-length",
                "32",
                "--output",
                str(output_path),
            ]
            with patch.object(sys, "argv", arguments):
                self.assertEqual(0, main())
            required_arguments = arguments + [
                "--require-decision",
                "evaluate_padded_bucket_correctness",
            ]
            with patch.object(sys, "argv", required_arguments):
                self.assertEqual(1, main())

    def test_rejects_incomplete_profile_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path, allowlist_path = _write_manifests(root)
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            del profile["torch_version"]
            profile_path.write_text(json.dumps(profile), encoding="utf-8")

            arguments = _manifest_args(profile_path, allowlist_path)

            with self.assertRaisesRegex(RuntimeError, "missing: torch_version"):
                _validate_manifest_provenance(arguments)


def _summary(
    records: list[dict[str, object]],
    **overrides: object,
) -> dict[str, object]:
    defaults: dict[str, object] = {
        "runtime_profile_id": _PROFILE,
        "compiled_lengths": {32},
        "min_requests": 1,
        "min_unknown_requests": 1,
        "min_samples_per_length": 1,
        "min_eligible_unknown_coverage_percent": 80.0,
        "min_exact_coverage_percent": 90.0,
    }
    defaults.update(overrides)
    return _summarize(
        records,
        runtime_profile_id=cast(str, defaults["runtime_profile_id"]),
        compiled_lengths=cast(set[int], defaults["compiled_lengths"]),
        min_requests=cast(int, defaults["min_requests"]),
        min_unknown_requests=cast(int, defaults["min_unknown_requests"]),
        min_samples_per_length=cast(int, defaults["min_samples_per_length"]),
        min_eligible_unknown_coverage_percent=cast(
            float,
            defaults["min_eligible_unknown_coverage_percent"]
        ),
        min_exact_coverage_percent=cast(
            float, defaults["min_exact_coverage_percent"]
        ),
    )


def _record(
    outcome: str,
    prefill_length: int | None = None,
    *,
    route_decision_made: bool = True,
) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": 3,
        "runtime_profile_id": _PROFILE,
        "request_outcome": outcome,
        "route_decision_made": route_decision_made,
    }
    if route_decision_made:
        if prefill_length is None:
            raise ValueError("route decisions require a prefill length")
        compiled = prefill_length == 32
        result.update(
            {
                "talker_prefill_length": prefill_length,
                "prefill_shape_policy": (
                    "compiled_allowlist" if compiled else "eager_unknown"
                ),
                "prefill_backend_used": (
                    "compile_reduce_overhead" if compiled else "eager"
                ),
                "selected_chunk_schedule": [8, 8, 12] if compiled else [8],
                "prefill_cache_hit": compiled,
                "prefill_compile_attempted": False,
                "prefill_compile_fallback": False,
            }
        )
    if outcome == "completed":
        result.update(
            {
                "first_audio_ms": 10.0,
                "completed_ms": 20.0,
                "inverse_rtf": 2.0,
            }
        )
    return result


def _write_manifests(root: Path) -> tuple[Path, Path]:
    allowlist_path = root / "allowlist.json"
    allowlist = {
        "manifest_schema_version": 1,
        "runtime_profile_id": _PROFILE,
        "compiled_lengths": [32],
        "compiled_route": "compiled_allowlist",
        "compiled_backend": "compile_reduce_overhead",
        "compiled_schedule": [8, 8, 12],
        "eager_route": "eager_unknown",
        "eager_backend": "eager",
        "eager_schedule": [8],
    }
    allowlist_path.write_text(json.dumps(allowlist), encoding="utf-8")
    profile_path = root / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "manifest_schema_version": 1,
                "runtime_profile_id": _PROFILE,
                "bridge_commit": "58fc4df8d78ef96e3838476e5fbf5a65e00f7827",
                "faster_wheel_sha256": (
                    "3b8fb11282072ac79323f696ed1b621bc1a7c676b3d7844c6bd47b4f10297113"
                ),
                "qwen_commit": "58b0637",
                "model_revision": "Qwen3-TTS-12Hz-0.6B-CustomVoice",
                "torch_version": "2.11.0+cu126",
                "cuda_version": "12.6",
                "compiled_allowlist_manifest_sha256": sha256(
                    allowlist_path.read_bytes()
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return profile_path, allowlist_path


def _manifest_args(profile_path: Path, allowlist_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        runtime_profile_id=_PROFILE,
        runtime_profile_manifest=profile_path,
        compiled_allowlist_manifest=allowlist_path,
        compiled_length=[32],
    )


if __name__ == "__main__":
    unittest.main()
