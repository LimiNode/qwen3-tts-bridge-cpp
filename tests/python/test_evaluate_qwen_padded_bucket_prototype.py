from __future__ import annotations

import unittest

from scripts.evaluate_qwen_padded_bucket_prototype import _evaluate


class QwenPaddedBucketResearchAuthorizationTests(unittest.TestCase):
    def test_real_accepted_baseline_authorizes_research_only(self) -> None:
        result = _evaluate(_validation(True), _shapes())

        self.assertTrue(result["research_implementation_authorized"])
        self.assertFalse(result["release_authorized"])
        self.assertEqual(
            "authorized_to_implement_research_prototype",
            result["decision"],
        )

    def test_failed_baseline_cannot_authorize_research(self) -> None:
        result = _evaluate(_validation(False), _shapes())

        self.assertFalse(result["research_implementation_authorized"])
        self.assertIn("baseline_validation", result["failed_checks"])


def _validation(accepted: bool) -> dict[str, object]:
    return {"overall_acceptance_pass": accepted}


def _shapes() -> dict[str, object]:
    return {
        "evidence_source": "real_discovery",
        "generation_acceptance_pass": True,
        "length_histogram": {"16": 25, "22": 25, "28": 25, "32": 25},
    }


if __name__ == "__main__":
    unittest.main()
