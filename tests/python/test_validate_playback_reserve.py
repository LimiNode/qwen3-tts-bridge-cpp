"""Tests for delivered-PCM playback reserve validation."""

from __future__ import annotations

import unittest
from typing import cast

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

    def test_checks_each_manifest_category_and_contract(self) -> None:
        artifact: dict[str, object] = {
            "requests": [
                _request(1, "compiled", [(100.0, 500.0), (300.0, 500.0)]),
                _request(2, "eager", [(100.0, 500.0), (300.0, 500.0)]),
            ]
        }

        report = validate_playback_reserve(
            artifact,
            reserve_ms=50.0,
            min_completed_requests=2,
            expected_categories={"compiled": 1, "eager": 1},
            min_completed_per_category=1,
            require_contract=True,
        )

        self.assertTrue(report["acceptance_pass"])
        categories = cast(dict[str, dict[str, object]], report["categories"])
        self.assertEqual(1, categories["compiled"]["completed_requests"])


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


def _request(
    request_id: int,
    label: str,
    chunks: list[tuple[float, float]],
) -> dict[str, object]:
    requests = cast(list[object], _artifact(chunks)["requests"])
    request = cast(dict[str, object], requests[0])
    request["request_id"] = request_id
    request["label"] = label
    request["manifest_contract"] = {"checked": True, "valid": True}
    return request


if __name__ == "__main__":
    unittest.main()
