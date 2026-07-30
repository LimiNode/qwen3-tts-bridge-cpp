"""Tests for corpus-v4 AI pre-review triage preparation."""

from __future__ import annotations

import copy
import unittest
from typing import cast

from scripts.prepare_corpus_v4_ai_prereview_triage import _prepare_triage


class PrepareCorpusV4AiPrereviewTriageTests(unittest.TestCase):
    def test_builds_separate_authoring_forms_for_flagged_rows(self) -> None:
        targeted_form = [_targeted_row()]
        targeted_ai = [copy.deepcopy(targeted_form[0])]
        targeted_ai[0].update(
            review_status="ai_prereview_complete_not_human_gate",
            reviewer_id="ai",
            likely_real_usage=True,
            category_fidelity=True,
            scene_context_fidelity=True,
            speech_intent_fidelity=True,
            appropriate_length=True,
            grammar=True,
            generic_ai_phrasing=False,
            semantic_repetition_acceptable=True,
            metadata_only_replacement=False,
            naturalness=False,
            notes="The wording is stiff.",
        )
        general_form = [_general_row()]
        general_ai = [copy.deepcopy(general_form[0])]
        general_ai[0].update(
            review_status="ai_prereview_complete_not_human_gate",
            reviewer_id="ai",
            category_fidelity=True,
            naturalness=True,
            likely_real_usage=True,
            semantic_repetition_acceptable=True,
            appropriate_length=True,
            grammar=True,
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
        )

        summary = cast(dict[str, int], manifest["summary"])
        self.assertEqual(1, summary["targeted_repair_candidate_count"])
        self.assertEqual(["naturalness"], targeted_authoring[0]["issues"])
        self.assertEqual("", targeted_authoring[0]["proposed_replacement_text"])
        self.assertEqual(
            ["generic_experiment_phrasing"], general_authoring[0]["issues"]
        )

    def test_rejects_protected_text_drift(self) -> None:
        targeted_form = [_targeted_row()]
        targeted_ai = [copy.deepcopy(targeted_form[0])]
        targeted_ai[0].update(
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
        targeted_ai[0]["replacement"] = {"text": "Changed."}
        general_form = [_general_row()]
        general_ai = [copy.deepcopy(general_form[0])]
        general_ai[0].update(
            review_status="ai_prereview_complete_not_human_gate",
            reviewer_id="ai",
            category_fidelity=True,
            naturalness=True,
            likely_real_usage=True,
            semantic_repetition_acceptable=True,
            appropriate_length=True,
            grammar=True,
            generic_experiment_phrasing=True,
            notes="The line sounds generic.",
        )

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
            )


def _targeted_row() -> dict[str, object]:
    return {
        "targeted_review_schema_version": 2,
        "review_scope": "all_corpus_v4_replacements",
        "review_status": "pending_human_review",
        "reviewer_id": "",
        "review_source_sha256": "source",
        "repair_set_sha256": "repair",
        "overlay_sha256": "overlay",
        "record_id": "v4-b01-001",
        "language_class": "en",
        "repair_reasons": ["reason"],
        "source": {"text": "Source."},
        "target": {"category": "game_review"},
        "replacement": {"text": "Current."},
        "replacement_text_sha256": "replacement",
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


def _general_row() -> dict[str, object]:
    return {
        "review_schema_version": 1,
        "source_sample_sha256": "sample",
        "label": "v4-b01-002",
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
