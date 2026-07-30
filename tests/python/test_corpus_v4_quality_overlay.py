"""Tests for the corpus-v4 text-only quality overlay pipeline."""

from __future__ import annotations

import hashlib
import json
import unittest
from typing import Any, cast

from scripts.materialize_corpus_v4_quality_overlay import _materialize
from scripts.prepare_corpus_v4_quality_overlay import _prepare_overlay, _text_sha256


class CorpusV4QualityOverlayTests(unittest.TestCase):
    def test_preparer_excludes_existing_repair_and_keeps_new_revision(self) -> None:
        base = [_record("v4-b01-001"), _record("v4-b01-002")]
        frozen = [_review(record) for record in base]
        corrected = [_review(record) for record in base]
        ai_prereview = [_review(record) for record in base]
        corrected[0]["text"] = "A newer review line."
        corrected[1]["text"] = "A different review line."
        for row in ai_prereview:
            row["review_status"] = "ai_prereview_complete_not_human_gate"
        rows = _prepare_overlay(
            base,
            frozen,
            corrected,
            ai_prereview,
            {"records": [{"record_id": "v4-b01-001"}]},
            corpus_id="candidate",
            base_records_sha256="a" * 64,
            frozen_review_form_sha256="b" * 64,
            corrected_review_form_sha256="c" * 64,
            ai_prereview_sha256="d" * 64,
        )

        self.assertEqual(["v4-b01-002"], [row["record_id"] for row in rows])
        self.assertEqual("A different review line.", rows[0]["replacement_text"])

    def test_materializer_rejects_preserved_metadata_drift(self) -> None:
        base = [_record("v4-b01-001")]
        base_bytes = _jsonl(base)
        row = _overlay_row(base[0], base_bytes)
        preserve = cast(dict[str, object], row["preserve"])
        preserve["category"] = "live_chat"

        with self.assertRaisesRegex(RuntimeError, "preserved metadata drifted"):
            _materialize(base, [row], base_bytes)

    def test_materializer_replaces_only_text(self) -> None:
        base = [_record("v4-b01-001")]
        base_bytes = _jsonl(base)
        row = _overlay_row(base[0], base_bytes)

        output = _materialize(base, [row], base_bytes)

        self.assertEqual("A different review line.", output[0]["text"])
        self.assertEqual(base[0]["category"], output[0]["category"])
        self.assertEqual(base[0]["semantic_intent_id"], output[0]["semantic_intent_id"])

    def test_materializer_rejects_invalid_replacement_length(self) -> None:
        base = [_record("v4-b01-001")]
        base_bytes = _jsonl(base)
        row = _overlay_row(base[0], base_bytes)
        row["replacement_text"] = "Too short."
        row["replacement_text_sha256"] = _text_sha256("Too short.")

        with self.assertRaisesRegex(RuntimeError, "corrected text length is invalid"):
            _materialize(base, [row], base_bytes)


def _record(record_id: str) -> dict[str, Any]:
    return {
        "batch_id": "v4-b01",
        "record_id": record_id,
        "text": "A baseline review line.",
        "language_class": "en",
        "category": "game_review",
        "scene_context": "offline_conversation",
        "speech_intent": "opinion_review",
        "intended_length_class": "short",
        "template_family_id": "review-family",
        "semantic_intent_id": "review-intent",
        "key_phrase_id": "review-key",
    }


def _review(record: dict[str, Any]) -> dict[str, object]:
    return {
        "label": record["record_id"],
        "category": record["category"],
        "language_class": record["language_class"],
        "intended_length_class": record["intended_length_class"],
        "source_sample_sha256": "sample",
        "text": record["text"],
        "review_status": "pending_human_review",
    }


def _overlay_row(record: dict[str, Any], base_bytes: bytes) -> dict[str, object]:
    text = "A different review line."
    return {
        "quality_repair_overlay_schema_version": 1,
        "corpus_id": "candidate",
        "base_records_sha256": hashlib.sha256(base_bytes).hexdigest(),
        "frozen_review_form_sha256": "frozen",
        "corrected_review_form_sha256": "corrected",
        "ai_prereview_sha256": "prereview",
        "record_id": record["record_id"],
        "preserve": {key: value for key, value in record.items() if key != "text"},
        "source_text_sha256": _text_sha256(record["text"]),
        "replacement_text": text,
        "replacement_text_sha256": _text_sha256(text),
        "reason": "ai_prereview_general_revision",
    }


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    return text.encode("utf-8")


if __name__ == "__main__":
    unittest.main()
