"""Tests for immutable corpus-v4 overlay materialization."""

from __future__ import annotations

import copy
import hashlib
import unittest

from scripts.build_corpus_v4_repair_set import _record_sha256
from scripts.materialize_corpus_v4_overlay import _materialize


class MaterializeCorpusV4OverlayTests(unittest.TestCase):
    def test_materializes_replacement_without_mutating_source(self) -> None:
        records = [_record()]
        original = copy.deepcopy(records)
        repair_set = {"records": [_plan(records[0])]}
        overlay = {"records": [_overlay(records[0])]}

        first = _materialize(records, repair_set, overlay)
        second = _materialize(records, repair_set, overlay)

        self.assertEqual(records, original)
        self.assertEqual(first, second)
        self.assertEqual("game_review", first[0]["category"])
        self.assertEqual("A focused review checks the sound mix.", first[0]["text"])

    def test_rejects_replacement_with_wrong_source_sha(self) -> None:
        record = _record()
        repair_set = {"records": [_plan(record)]}
        overlay = _overlay(record)
        overlay["original_record_sha256"] = "wrong"

        with self.assertRaisesRegex(RuntimeError, "original record SHA"):
            _materialize([record], repair_set, {"records": [overlay]})

    def test_rejects_repair_set_record_missing_from_source(self) -> None:
        record = _record()
        repair_set = {"records": [_plan(record)]}
        overlay = _overlay(record)
        repair_set["records"][0]["record_id"] = "v4-b01-999"
        overlay["record_id"] = "v4-b01-999"

        with self.assertRaisesRegex(RuntimeError, "unknown record IDs"):
            _materialize([record], repair_set, {"records": [overlay]})

    def test_rejects_overlay_reason_mismatch(self) -> None:
        record = _record()
        repair_set = {"records": [_plan(record)]}
        overlay = _overlay(record)
        overlay["repair_reasons"] = ["different_reason"]

        with self.assertRaisesRegex(RuntimeError, "repair reasons"):
            _materialize([record], repair_set, {"records": [overlay]})


def _record() -> dict[str, object]:
    return {
        "batch_id": "v4-b01",
        "record_id": "v4-b01-001",
        "language_class": "en",
        "intended_length_class": "short",
        "category": "game_commentary",
        "scene_context": "gameplay_stream",
        "speech_intent": "game_commentary",
        "text": "Hold the bridge.",
        "template_family_id": "old-family",
        "semantic_intent_id": "old-intent",
        "key_phrase_id": "old-phrase",
    }


def _plan(record: dict[str, object]) -> dict[str, object]:
    return {
        "record_id": record["record_id"],
        "original_record_sha256": _record_sha256(record),
        "repair_reasons": ["ngram_4:abc"],
        "preserve": {
            "batch_id": "v4-b01",
            "record_id": "v4-b01-001",
            "language_class": "en",
            "intended_length_class": "short",
        },
        "target": {"category": "game_review"},
    }


def _overlay(record: dict[str, object]) -> dict[str, object]:
    text = "A focused review checks the sound mix."
    return {
        "record_id": record["record_id"],
        "original_record_sha256": _record_sha256(record),
        "repair_reasons": ["ngram_4:abc"],
        "preserve": {
            "batch_id": "v4-b01",
            "record_id": "v4-b01-001",
            "language_class": "en",
            "intended_length_class": "short",
        },
        "target": {
            "category": "game_review",
            "scene_context": "technical_stream",
            "speech_intent": "opinion_review",
        },
        "replacement": {
            "text": text,
            "template_family_id": "review-family",
            "semantic_intent_id": "review-intent",
            "key_phrase_id": "review-phrase",
        },
        "replacement_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


if __name__ == "__main__":
    unittest.main()
