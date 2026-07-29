"""Tests for delivered-PCM playback reserve validation."""

from __future__ import annotations

import unittest

from scripts.validate_playback_reserve import validate_playback_reserve


class PlaybackReserveTests(unittest.TestCase):
    def test_accepts_buffered_chunks(self) -> None:
        report = validate_playback_reserve(
            _artifact([(100.0, 450.0), (300.0, 600.0), (700.0, 900.0)]),
            reserve_ms=50.0,
            min_completed_requests=1,
        )

        self.assertTrue(report["acceptance_pass"])
        self.assertEqual(0, report["underruns"])
        minimum_reserve = report["minimum_post_chunk_reserve_ms"]
        self.assertIsInstance(minimum_reserve, float)
        assert isinstance(minimum_reserve, float)
        self.assertGreater(minimum_reserve, 0.0)
        self.assertNotIn("requests", report)

    def test_includes_request_details_only_on_demand(self) -> None:
        report = validate_playback_reserve(
            _artifact([(100.0, 450.0), (300.0, 600.0)]),
            reserve_ms=50.0,
            min_completed_requests=1,
            include_request_details=True,
        )

        self.assertIn("requests", report)

    def test_rejects_underrun(self) -> None:
        report = validate_playback_reserve(
            _artifact([(100.0, 100.0), (250.0, 100.0)]),
            reserve_ms=50.0,
            min_completed_requests=1,
        )

        self.assertFalse(report["acceptance_pass"])
        self.assertEqual(1, report["underruns"])


def _artifact(chunks: list[tuple[float, float]]) -> dict[str, object]:
    return {
        "requests": [
            {
                "request_id": 1,
                "success": True,
                "chunks": [
                    {
                        "index": index,
                        "arrival_ms": arrival_ms,
                        "audio_duration_ms": duration_ms,
                    }
                    for index, (arrival_ms, duration_ms) in enumerate(chunks)
                ],
            }
        ]
    }


if __name__ == "__main__":
    unittest.main()
