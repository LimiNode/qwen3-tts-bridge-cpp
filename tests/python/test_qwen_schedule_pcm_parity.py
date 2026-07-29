"""Tests for fixed-versus-scheduled PCM parity validation."""

from __future__ import annotations

import unittest

from scripts.qwen_schedule_pcm_parity import _compare


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


def _case() -> dict[str, object]:
    return {
        "pcm_sha256": "a" * 64,
        "audio_bytes": 96000,
        "audio_duration_ms": 2000.0,
        "generation_trace": {
            "codec_sha256": "c" * 64,
            "codec_frame_count": 24,
            "termination_reason": "eos",
            "terminal_token_id": 1,
            "terminal_step_index": 24,
        },
    }
