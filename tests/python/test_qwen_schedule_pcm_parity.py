"""Tests for fixed-versus-scheduled PCM parity validation."""

from __future__ import annotations

import unittest

from scripts.qwen_schedule_pcm_parity import _compare, _validate_candidate_contract


class SchedulePcmParityTests(unittest.TestCase):
    def test_accepts_matching_pcm_and_codec_trace(self) -> None:
        baseline = _case()
        self.assertEqual([], _compare(baseline, dict(baseline)))

    def test_rejects_pcm_difference(self) -> None:
        candidate = _case()
        candidate["audio_duration_ms"] = 2100.0
        self.assertIn(
            "audio_duration_ms differs by more than 50.000 ms",
            _compare(_case(), candidate),
        )

    def test_rejects_boundary_quality_above_absolute_limit(self) -> None:
        candidate = _case()
        quality = candidate["boundary_quality"]
        self.assertIsInstance(quality, dict)
        assert isinstance(quality, dict)
        candidate["boundary_quality"] = {
            **quality,
            "max_boundary_jump_s16": 101,
        }

        self.assertIn(
            "boundary_quality.max_boundary_jump_s16 exceeds maximum 100.000",
            _compare(_case(), candidate, max_boundary_jump_s16=100.0),
        )

    def test_rejects_candidate_route_or_schedule_contract_mismatch(self) -> None:
        case = {
            "expected_candidate_route": "compiled_allowlist",
            "expected_candidate_backend": "compile_reduce_overhead",
            "expected_candidate_chunk_schedule": [8, 8, 12],
        }
        candidate = _case()
        candidate["stream_metadata"] = {
            "prefill_shape_policy": "eager_unknown",
            "prefill_backend_used": "eager",
            "selected_chunk_schedule": [8],
        }

        failures = _validate_candidate_contract(case, _case(), candidate)

        self.assertEqual(3, len(failures))

    def test_rejects_relative_boundary_regression(self) -> None:
        candidate = _case()
        candidate["boundary_quality"] = {
            **candidate["boundary_quality"],
            "max_dc_delta_s16": 600.0,
        }

        failures = _compare(
            _case(),
            candidate,
            max_dc_delta_s16=1000.0,
            max_dc_regression_s16=100.0,
        )

        self.assertIn(
            "boundary_quality.max_dc_delta_s16 regressed by more than 100.000",
            failures,
        )

    def test_requires_exact_pcm_for_fixed_eager_control(self) -> None:
        candidate = _case()
        candidate["pcm_sha256"] = "b" * 64

        failures = _validate_candidate_contract(
            {"require_exact_pcm_sha256": True},
            _case(),
            candidate,
        )

        self.assertIn("candidate PCM SHA differs from fixed control", failures)


def _case() -> dict[str, object]:
    return {
        "pcm_sha256": "a" * 64,
        "audio_bytes": 96000,
        "audio_duration_ms": 2000.0,
        "boundary_quality": {
            "max_boundary_jump_s16": 100,
            "p95_boundary_jump_s16": 90.0,
            "max_rms_ratio": 1.1,
            "max_dc_delta_s16": 20.0,
            "max_spectral_high_ratio_delta": 0.1,
            "clip_sample_count": 0,
        },
        "generation_trace": {
            "codec_sha256": "c" * 64,
            "codec_frame_count": 24,
            "termination_reason": "eos",
            "terminal_token_id": 1,
            "terminal_step_index": 24,
        },
    }
