"""Tests for reviewed authoring JSONL validation before overlay generation."""

from __future__ import annotations

import copy
import unittest
from typing import Any

from scripts.build_corpus_v4_repair_overlay import (
    _authoring_by_id,
    _validate_authoring_row,
    _validate_replacement_texts,
)


class CorpusV4RepairOverlayBuilderTests(unittest.TestCase):
    def test_accepts_stale_generated_reasons_when_semantics_match(self) -> None:
        _validate_authoring_row(_authoring(), _record(), _plan())

    def test_rejects_repetition_only_semantic_drift(self) -> None:
        authoring = _authoring()
        authoring["target"]["speech_intent"] = "explanation"

        with self.assertRaisesRegex(RuntimeError, "metadata drifted"):
            _validate_authoring_row(authoring, _record(), _plan())

    def test_rejects_duplicate_authoring_metadata_ids(self) -> None:
        first = _authoring()
        second = copy.deepcopy(first)
        second["record_id"] = "v4-b01-002"
        second["preserve"]["record_id"] = "v4-b01-002"

        with self.assertRaisesRegex(RuntimeError, "duplicate template_family_id"):
            _authoring_by_id([first, second])

    def test_rejects_canonically_unchanged_replacement_text(self) -> None:
        authoring = _authoring()
        authoring["replacement"]["text"] = (
            "  HOLD   THE BRIDGE BEFORE THE GATE OPENS.  "
        )

        with self.assertRaisesRegex(RuntimeError, "does not change source"):
            _validate_authoring_row(authoring, _record(), _plan())

    def test_rejects_replacement_text_collision_with_unchanged_source(self) -> None:
        source = {
            "v4-b01-001": _record(),
            "v4-b01-002": {
                **_record(),
                "record_id": "v4-b01-002",
                "text": "Same final text.",
            },
        }
        authoring = _authoring()
        authoring["replacement"]["text"] = "Ｓａｍｅ   ｆｉｎａｌ text."

        with self.assertRaisesRegex(RuntimeError, "collides with an unchanged"):
            _validate_replacement_texts(
                source, {"v4-b01-001": _plan()}, {"v4-b01-001": authoring}
            )

    def test_rejects_canonical_duplicate_replacement_texts(self) -> None:
        first = _authoring()
        second = copy.deepcopy(first)
        second["record_id"] = "v4-b01-002"
        second["replacement"]["text"] = "KEEP  THE BRIDGE SECURE BEFORE ENTERING."

        with self.assertRaisesRegex(RuntimeError, "duplicates v4-b01-001"):
            _validate_replacement_texts(
                {
                    "v4-b01-001": _record(),
                    "v4-b01-002": {**_record(), "record_id": "v4-b01-002"},
                },
                {"v4-b01-001": _plan(), "v4-b01-002": _plan()},
                {"v4-b01-001": first, "v4-b01-002": second},
            )


def _record() -> dict[str, object]:
    return {
        "batch_id": "v4-b01",
        "record_id": "v4-b01-001",
        "language_class": "en",
        "intended_length_class": "short",
        "category": "game_commentary",
        "scene_context": "gameplay_stream",
        "speech_intent": "game_commentary",
        "text": "Hold the bridge before the gate opens.",
        "template_family_id": "old-family",
        "semantic_intent_id": "old-intent",
        "key_phrase_id": "old-phrase",
    }


def _plan() -> dict[str, Any]:
    record = _record()
    return {
        "preserve": {
            "batch_id": record["batch_id"],
            "record_id": record["record_id"],
            "language_class": record["language_class"],
            "intended_length_class": record["intended_length_class"],
        },
        "target": {
            "category": record["category"],
            "scene_context": record["scene_context"],
            "speech_intent": record["speech_intent"],
        },
        "target_metadata_policy": "preserve_exact",
    }


def _authoring() -> dict[str, Any]:
    record = _record()
    return {
        "authoring_form_schema_version": 1,
        "record_id": record["record_id"],
        "repair_reasons": ["stale-generated-reason"],
        "preserve": _plan()["preserve"],
        "word_range": {"minimum": 4, "maximum": 7},
        "source": {
            field: record[field]
            for field in (
                "text",
                "category",
                "scene_context",
                "speech_intent",
                "template_family_id",
                "semantic_intent_id",
                "key_phrase_id",
            )
        },
        "target": _plan()["target"],
        "replacement": {
            "text": "Keep the bridge secure before entering.",
            "template_family_id": "new-family",
            "semantic_intent_id": "secure-bridge",
            "key_phrase_id": "bridge-security",
        },
    }


if __name__ == "__main__":
    unittest.main()
