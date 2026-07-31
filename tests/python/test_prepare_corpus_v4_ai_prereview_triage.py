"""Tests for corpus-v4 AI pre-review triage preparation."""

from __future__ import annotations

import copy
import unittest
from typing import Any, cast

from scripts.prepare_corpus_v4_ai_prereview_triage import _prepare_triage


class PrepareCorpusV4AiPrereviewTriageTests(unittest.TestCase):
    def test_builds_decision_forms_for_flagged_rows(self) -> None:
        targeted_form, targeted_ai = _targeted_inputs()
        general_form, general_ai = _general_inputs()
        targeted_ai[0].update(naturalness=False, notes="The wording is stiff.")
        general_ai[0].update(
            generic_experiment_phrasing=True,
            notes="The line sounds generic.",
        )

        manifest, targeted_authoring, general_authoring = _prepare_triage(
            targeted_form,
            targeted_ai,
            general_form,
            general_ai,
            targeted_form_sha256="a" * 64,
            targeted_ai_sha256="b" * 64,
            general_form_sha256="c" * 64,
            general_ai_sha256="d" * 64,
            base_candidate_sha256="e" * 64,
        )

        summary = cast(dict[str, int], manifest["summary"])
        self.assertEqual(1, summary["targeted_repair_candidate_count"])
        self.assertEqual(1, summary["general_repair_candidate_count"])
        self.assertEqual(0, summary["overlap_count"])
        self.assertEqual(2, summary["unique_candidate_count"])
        self.assertEqual("", targeted_authoring[0]["authoring_decision"])
        self.assertEqual("", targeted_authoring[0]["proposed_replacement_text"])
        self.assertEqual(
            ["generic_experiment_phrasing"], general_authoring[0]["issues"]
        )

    def test_allows_zero_candidates_in_one_scope(self) -> None:
        targeted_form, targeted_ai = _targeted_inputs()
        general_form, general_ai = _general_inputs()
        targeted_ai[0].update(naturalness=False, notes="The wording is stiff.")

        manifest, targeted_authoring, general_authoring = _prepare_triage(
            targeted_form,
            targeted_ai,
            general_form,
            general_ai,
            targeted_form_sha256="a" * 64,
            targeted_ai_sha256="b" * 64,
            general_form_sha256="c" * 64,
            general_ai_sha256="d" * 64,
            base_candidate_sha256="e" * 64,
        )

        summary = cast(dict[str, int], manifest["summary"])
        self.assertEqual(1, len(targeted_authoring))
        self.assertEqual([], general_authoring)
        self.assertEqual(0, summary["general_repair_candidate_count"])

    def test_rejects_protected_text_drift(self) -> None:
        targeted_form, targeted_ai = _targeted_inputs()
        general_form, general_ai = _general_inputs()
        targeted_ai[0]["replacement"] = {"text": "Changed."}

        with self.assertRaisesRegex(RuntimeError, "changed protected replacement"):
            _prepare_triage(
                targeted_form,
                targeted_ai,
                general_form,
                general_ai,
                targeted_form_sha256="a" * 64,
                targeted_ai_sha256="b" * 64,
                general_form_sha256="c" * 64,
                general_ai_sha256="d" * 64,
                base_candidate_sha256="e" * 64,
            )

    def test_rejects_overlapping_repair_scopes(self) -> None:
        targeted_form, targeted_ai = _targeted_inputs()
        general_form, general_ai = _general_inputs()
        general_form[0]["label"] = str(targeted_form[0]["record_id"])
        general_ai[0]["label"] = str(targeted_form[0]["record_id"])
        targeted_ai[0].update(naturalness=False, notes="The wording is stiff.")
        general_ai[0].update(
            generic_experiment_phrasing=True,
            notes="The line sounds generic.",
        )

        with self.assertRaisesRegex(RuntimeError, "repair scopes overlap"):
            _prepare_triage(
                targeted_form,
                targeted_ai,
                general_form,
                general_ai,
                targeted_form_sha256="a" * 64,
                targeted_ai_sha256="b" * 64,
                general_form_sha256="c" * 64,
                general_ai_sha256="d" * 64,
                base_candidate_sha256="e" * 64,
            )

    def test_rejects_incomplete_targeted_form(self) -> None:
        targeted_form, targeted_ai = _targeted_inputs()
        general_form, general_ai = _general_inputs()

        with self.assertRaisesRegex(RuntimeError, "exactly 98"):
            _prepare_triage(
                targeted_form[:-1],
                targeted_ai[:-1],
                general_form,
                general_ai,
                targeted_form_sha256="a" * 64,
                targeted_ai_sha256="b" * 64,
                general_form_sha256="c" * 64,
                general_ai_sha256="d" * 64,
                base_candidate_sha256="e" * 64,
            )


def _targeted_inputs() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    form = [_targeted_row(index) for index in range(98)]
    reviewed = copy.deepcopy(form)
    for row in reviewed:
        row.update(
            review_status="ai_prereview_complete_not_human_gate",
            reviewer_id="ai",
            naturalness=True,
            likely_real_usage=True,
            category_fidelity=True,
            scene_context_fidelity=True,
            speech_intent_fidelity=True,
            appropriate_length=True,
            grammar=True,
            generic_ai_phrasing=False,
            semantic_repetition_acceptable=True,
            metadata_only_replacement=False,
        )
    return form, reviewed


def _general_inputs() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    form = [_general_row(index) for index in range(100)]
    reviewed = copy.deepcopy(form)
    for row in reviewed:
        row.update(
            review_status="ai_prereview_complete_not_human_gate",
            reviewer_id="ai",
            category_fidelity=True,
            naturalness=True,
            likely_real_usage=True,
            semantic_repetition_acceptable=True,
            appropriate_length=True,
            grammar=True,
            generic_experiment_phrasing=False,
        )
    return form, reviewed


def _targeted_row(index: int) -> dict[str, object]:
    return {
        "targeted_review_schema_version": 2,
        "review_scope": "all_corpus_v4_replacements",
        "review_status": "pending_human_review",
        "reviewer_id": "",
        "review_source_sha256": "a" * 64,
        "repair_set_sha256": "b" * 64,
        "overlay_sha256": "c" * 64,
        "record_id": f"targeted-{index:03d}",
        "language_class": "en",
        "repair_reasons": ["reason"],
        "source": {"text": "Source."},
        "target": {"category": "game_review"},
        "replacement": {"text": "Current."},
        "replacement_text_sha256": "d" * 64,
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


def _general_row(index: int) -> dict[str, object]:
    return {
        "review_schema_version": 1,
        "source_sample_sha256": "e" * 64,
        "label": f"general-{index:03d}",
        "category": "game_review",
        "language_class": "en",
        "intended_length_class": "short",
        "text": "Current line.",
        "review_status": "pending_human_review",
        "reviewer_id": "",
        "category_fidelity": None,
        "naturalness": None,
        "likely_real_usage": None,
        "code_switch_naturalness": None,
        "semantic_repetition_acceptable": None,
        "appropriate_length": None,
        "grammar": None,
        "generic_experiment_phrasing": None,
        "notes": "",
    }


if __name__ == "__main__":
    unittest.main()
