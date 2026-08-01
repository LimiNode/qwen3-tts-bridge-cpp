"""Tests for descriptive holdout report publication."""

from __future__ import annotations

import unittest
from typing import cast

from scripts.publish_frequency_holdout_report import _publish


class PublishFrequencyHoldoutReportTests(unittest.TestCase):
    def test_marks_holdout_as_descriptive_and_retains_route_breakdown(self) -> None:
        report = _publish(_source(), "a" * 64)

        self.assertEqual(
            "descriptive_only_not_for_allowlist_retuning",
            report["measurement_role"],
        )
        self.assertEqual([18], report["candidate_exact_lengths"])
        by_route = cast(dict[str, dict[str, object]], report["by_route"])
        self.assertEqual(1, by_route["compiled_allowlist"]["count"])


def _source() -> dict[str, object]:
    return {
        "record_count": 2,
        "candidate_exact_lengths": [18],
        "by_route": {"compiled_allowlist": {"count": 1}, "eager_unknown": {"count": 1}},
        "by_prefill_length": {"18": {"count": 1}, "20": {"count": 1}},
        "by_category": {"game_review": {"count": 2}},
        "by_language_class": {"en": {"count": 2}},
        "coverage": {"candidate_compiled_percent": 50.0},
    }


if __name__ == "__main__":
    unittest.main()
