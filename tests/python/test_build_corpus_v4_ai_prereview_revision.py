"""Tests for corpus-v4 human-adjudication revision building."""

from __future__ import annotations

import unittest

from scripts.build_corpus_v4_ai_prereview_revision import _build_revision


class BuildCorpusV4AiPrereviewRevisionTests(unittest.TestCase):
    def test_materializes_replace_and_keep_decisions(self) -> None:
        base = [_record("targeted-001"), _record("general-001")]
        targeted = [
            _targeted_adjudication(
                base[0], "replace", "This review sounds more natural now."
            )
        ]
        general = [_general_adjudication(base[1], "keep_after_human_review", "")]

        records, report = _build_revision(
            base,
            _manifest({"targeted-001"}, {"general-001"}),
            targeted,
            general,
            **_provenance(),
        )

        self.assertEqual("This review sounds more natural now.", records[0]["text"])
        self.assertEqual(base[1]["text"], records[1]["text"])
        self.assertEqual(1, report["targeted_replaced"])
        self.assertEqual(1, report["general_kept"])
        self.assertEqual(1, report["unique_revised_count"])

    def test_rejects_pending_human_adjudication(self) -> None:
        base = [_record("targeted-001"), _record("general-001")]
        targeted = [
            _targeted_adjudication(
                base[0], "replace", "This review sounds more natural now."
            )
        ]
        targeted[0]["authoring_status"] = "pending_human_adjudication"
        general = [_general_adjudication(base[1], "keep_after_human_review", "")]

        with self.assertRaisesRegex(RuntimeError, "not completed"):
            _build_revision(
                base,
                _manifest({"targeted-001"}, {"general-001"}),
                targeted,
                general,
                **_provenance(),
            )

    def test_rejects_targeted_metadata_drift(self) -> None:
        base = [_record("targeted-001"), _record("general-001")]
        targeted = [
            _targeted_adjudication(
                base[0], "replace", "This review sounds more natural now."
            )
        ]
        cast_target = targeted[0]["target"]
        assert isinstance(cast_target, dict)
        cast_target["category"] = "conversation"
        general = [_general_adjudication(base[1], "keep_after_human_review", "")]

        with self.assertRaisesRegex(RuntimeError, "metadata drifted"):
            _build_revision(
                base,
                _manifest({"targeted-001"}, {"general-001"}),
                targeted,
                general,
                **_provenance(),
            )

    def test_rejects_final_text_collision(self) -> None:
        base = [_record("targeted-001"), _record("general-001")]
        targeted = [_targeted_adjudication(base[0], "keep_after_human_review", "")]
        general = [_general_adjudication(base[1], "replace", str(base[0]["text"]))]

        with self.assertRaisesRegex(RuntimeError, "final text duplicates"):
            _build_revision(
                base,
                _manifest({"targeted-001"}, {"general-001"}),
                targeted,
                general,
                **_provenance(),
            )


def _record(record_id: str) -> dict[str, object]:
    return {
        "batch_id": "v4-b01",
        "record_id": record_id,
        "text": f"The current short text for {record_id}.",
        "language_class": "en",
        "category": "game_review",
        "scene_context": "technical_stream",
        "speech_intent": "opinion_review",
        "intended_length_class": "short",
        "template_family_id": f"family-{record_id}",
        "semantic_intent_id": f"intent-{record_id}",
        "key_phrase_id": f"phrase-{record_id}",
    }


def _targeted_adjudication(
    record: dict[str, object], decision: str, replacement: str
) -> dict[str, object]:
    return {
        "ai_prereview_repair_authoring_schema_version": 2,
        "authoring_status": "completed_human_adjudication",
        "authoring_decision": decision,
        "author_id": "reviewer",
        "decision_notes": "Reviewed in context.",
        "base_candidate_sha256": "0" * 64,
        "record_id": record["record_id"],
        "language_class": record["language_class"],
        "issues": ["naturalness"],
        "ai_prereview_notes": "AI advisory note.",
        "source": {"text": "Original repair source."},
        "target": {
            "category": record["category"],
            "scene_context": record["scene_context"],
            "speech_intent": record["speech_intent"],
        },
        "current_replacement": {
            "text": record["text"],
            "template_family_id": record["template_family_id"],
            "semantic_intent_id": record["semantic_intent_id"],
            "key_phrase_id": record["key_phrase_id"],
        },
        "proposed_replacement_text": replacement,
    }


def _general_adjudication(
    record: dict[str, object], decision: str, replacement: str
) -> dict[str, object]:
    return {
        "ai_prereview_repair_authoring_schema_version": 2,
        "authoring_status": "completed_human_adjudication",
        "authoring_decision": decision,
        "author_id": "reviewer",
        "decision_notes": "Reviewed in context.",
        "base_candidate_sha256": "0" * 64,
        "label": record["record_id"],
        "category": record["category"],
        "language_class": record["language_class"],
        "intended_length_class": record["intended_length_class"],
        "issues": ["naturalness"],
        "ai_prereview_notes": "AI advisory note.",
        "current_text": record["text"],
        "proposed_replacement_text": replacement,
    }


def _manifest(targeted_ids: set[str], general_ids: set[str]) -> dict[str, object]:
    return {
        "corpus_v4_ai_prereview_triage_schema_version": 2,
        "review_status": "ai_prereview_not_human_gate",
        "inputs": {
            "targeted_form_sha256": "a" * 64,
            "targeted_ai_prereview_sha256": "b" * 64,
            "general_form_sha256": "c" * 64,
            "general_ai_prereview_sha256": "d" * 64,
            "base_candidate_sha256": "0" * 64,
            "ai_review_provenance_sha256": None,
        },
        "ai_review_provenance": {"status": "incomplete_not_supplied"},
        "summary": {
            "targeted_repair_candidate_count": len(targeted_ids),
            "general_repair_candidate_count": len(general_ids),
            "overlap_count": 0,
            "unique_candidate_count": len(targeted_ids.union(general_ids)),
        },
        "targeted_repair_candidates": [
            {"record_id": record_id, "issues": ["naturalness"], "notes": "note"}
            for record_id in sorted(targeted_ids)
        ],
        "general_repair_candidates": [
            {"label": record_id, "issues": ["naturalness"], "notes": "note"}
            for record_id in sorted(general_ids)
        ],
    }


def _provenance() -> dict[str, str]:
    return {
        "base_candidate_sha256": "0" * 64,
        "triage_manifest_sha256": "1" * 64,
        "targeted_review_form_sha256": "a" * 64,
        "targeted_ai_prereview_sha256": "b" * 64,
        "general_review_form_sha256": "c" * 64,
        "general_ai_prereview_sha256": "d" * 64,
        "targeted_adjudication_sha256": "2" * 64,
        "general_adjudication_sha256": "3" * 64,
    }


if __name__ == "__main__":
    unittest.main()
