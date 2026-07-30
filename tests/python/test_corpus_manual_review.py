"""Tests for the structured corpus human-review contract."""

from __future__ import annotations

import argparse
import unittest

from scripts.evaluate_corpus_manual_review import _evaluate, _validate_record
from scripts.prepare_corpus_manual_review import _review_record


class CorpusManualReviewTests(unittest.TestCase):
    def test_review_form_starts_pending_without_scores(self) -> None:
        record = _review_record(
            {
                "label": "v3-0001",
                "category": "live_chat",
                "language_class": "ru",
                "intended_length_class": "micro",
                "text": "Погнали.",
            },
            b"source",
        )

        self.assertEqual("pending_human_review", record["review_status"])
        self.assertIsNone(record["naturalness"])

    def test_completed_review_requires_human_fields_and_applies_thresholds(
        self,
    ) -> None:
        records = [_completed("ru"), _completed("mixed")]
        args = argparse.Namespace(
            minimum_natural_percent=90.0,
            minimum_category_percent=90.0,
            maximum_unacceptable_mixed_percent=5.0,
            maximum_generic_experiment_percent=10.0,
        )
        for index, record in enumerate(records, 1):
            _validate_record(record, index)

        summary = _evaluate(records, args)

        self.assertTrue(summary["passed"])
        self.assertEqual("passed", summary["status"])

    def test_pending_review_cannot_be_evaluated_as_human_review(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "not completed"):
            _validate_record(_review_record(_source(), b"source"), 1)


def _source() -> dict[str, object]:
    return {
        "label": "v3-0001",
        "category": "live_chat",
        "language_class": "ru",
        "intended_length_class": "micro",
        "text": "Погнали.",
    }


def _completed(language: str) -> dict[str, object]:
    result = _review_record({**_source(), "language_class": language}, b"source")
    result.update(
        {
            "review_status": "completed_human_review",
            "reviewer_id": "reviewer",
            "category_fidelity": True,
            "naturalness": True,
            "likely_real_usage": True,
            "code_switch_naturalness": True if language == "mixed" else None,
            "semantic_repetition_acceptable": True,
            "appropriate_length": True,
            "grammar": True,
            "generic_experiment_phrasing": False,
        }
    )
    return result


if __name__ == "__main__":
    unittest.main()
