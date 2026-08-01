from __future__ import annotations

import unittest

from scripts.qwen_holdout_route_report import build_report


class QwenHoldoutRouteReportTests(unittest.TestCase):
    def test_separates_routes_and_keeps_legacy_coverage_descriptive(self) -> None:
        report = build_report(
            [
                _row("compiled_allowlist", 18, "game_commentary", "ru", 250.0),
                _row("eager_unknown", 30, "transition", "en", 400.0),
            ],
            {"prefill_compile_lengths": [18]},
            {"prefill_compile_lengths": [30]},
        )

        self.assertEqual(50.0, report["coverage"]["candidate_compiled_percent"])
        self.assertEqual(
            50.0,
            report["coverage"]["legacy_compiled_percent_descriptive_only"],
        )
        self.assertEqual(1, report["by_route"]["compiled_allowlist"]["count"])
        self.assertIn("descriptive only", report["notes"][0])


def _row(
    route: str,
    length: int,
    category: str,
    language: str,
    first_audio_ms: float,
) -> dict[str, object]:
    return {
        "execution_outcome": "completed",
        "generation_outcome": "eos",
        "first_audio_ms": first_audio_ms,
        "completed_ms": first_audio_ms * 4,
        "inverse_rtf": 2.5,
        "category": category,
        "language_class": language,
        "first_chunk_route": {
            "prefill_shape_policy": route,
            "talker_prefill_length": length,
        },
    }


if __name__ == "__main__":
    unittest.main()
