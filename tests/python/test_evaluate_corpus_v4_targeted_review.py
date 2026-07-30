"""Tests for the fail-closed corpus-v4 targeted review gate."""

from __future__ import annotations

import unittest
from typing import cast

from scripts.evaluate_corpus_v4_targeted_review import _evaluate


class EvaluateCorpusV4TargetedReviewTests(unittest.TestCase):
    def test_pending_form_does_not_pass(self) -> None:
        template = _template()
        summary = _evaluate([template], [template])

        self.assertFalse(summary["passed"])
        self.assertEqual("failed_needs_human_review", summary["status"])
        checks = cast(dict[str, int], summary["checks"])
        self.assertEqual(1, checks["not_completed_human_review"])

    def test_completed_human_review_requires_all_positive_checks(self) -> None:
        review = _template()
        review.update(
            {
                "review_status": "completed_human_review",
                "reviewer_id": "reviewer-1",
                "naturalness": True,
                "likely_real_usage": True,
                "category_fidelity": True,
                "scene_context_fidelity": True,
                "speech_intent_fidelity": True,
                "appropriate_length": True,
                "grammar": True,
                "generic_ai_phrasing": False,
                "semantic_repetition_acceptable": True,
                "metadata_only_replacement": False,
            }
        )
        summary = _evaluate([review], [_template()])

        self.assertTrue(summary["passed"])
        self.assertEqual("passed", summary["status"])

    def test_content_drift_is_rejected_even_when_scores_pass(self) -> None:
        review = _completed()
        review["replacement"] = {"text": "changed"}

        summary = _evaluate([review], [_template()])

        self.assertFalse(summary["passed"])
        record_failures = cast(dict[str, list[str]], summary["record_failures"])
        self.assertEqual(
            ["provenance_or_content_mismatch"],
            record_failures["v4-b01-001"],
        )


def _completed() -> dict[str, object]:
    row = _template()
    row.update(
        {
            "review_status": "completed_human_review",
            "reviewer_id": "reviewer-1",
            "naturalness": True,
            "likely_real_usage": True,
            "category_fidelity": True,
            "scene_context_fidelity": True,
            "speech_intent_fidelity": True,
            "appropriate_length": True,
            "grammar": True,
            "generic_ai_phrasing": False,
            "semantic_repetition_acceptable": True,
            "metadata_only_replacement": False,
        }
    )
    return row


def _template() -> dict[str, object]:
    return {
        "targeted_review_schema_version": 2,
        "review_scope": "all_corpus_v4_replacements",
        "review_status": "pending_human_review",
        "reviewer_id": "",
        "review_source_sha256": "authoring",
        "repair_set_sha256": "repair-set",
        "overlay_sha256": "overlay",
        "record_id": "v4-b01-001",
        "language_class": "ru",
        "repair_reasons": ["repetition"],
        "source": {"text": "source"},
        "target": {"category": "game_review"},
        "replacement": {"text": "replacement"},
        "replacement_text_sha256": "replacement-hash",
        "naturalness": None,
        "likely_real_usage": None,
        "category_fidelity": None,
        "scene_context_fidelity": None,
        "speech_intent_fidelity": None,
        "code_switch_naturalness": None,
        "appropriate_length": None,
        "grammar": None,
        "generic_ai_phrasing": None,
        "semantic_repetition_acceptable": None,
        "metadata_only_replacement": None,
        "notes": "",
    }


if __name__ == "__main__":
    unittest.main()
