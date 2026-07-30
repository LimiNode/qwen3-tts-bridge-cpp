"""Tests for fail-closed corpus-v4 overlay materialization."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from typing import Any

from scripts.audit_corpus_repetition import _audit, _record_id_set_sha256
from scripts.build_corpus_v4_repair_set import _build_repair_set, _record_sha256
from scripts.materialize_corpus_v4_overlay import _materialize

_AUDIT_SHA = "a" * 64
_SOURCE_SHA = "b" * 64
_POLICY_SHA = "c" * 64
_REPAIR_SET_SHA = "d" * 64


class MaterializeCorpusV4OverlayTests(unittest.TestCase):
    def test_materializes_replacement_without_mutating_source(self) -> None:
        records = [_record()]
        original = copy.deepcopy(records)
        repair_set = _repair_set(records)
        overlay = _overlay(records, repair_set)

        first = _materialize_fixture(records, repair_set, overlay)
        second = _materialize_fixture(records, repair_set, overlay)

        self.assertEqual(records, original)
        self.assertEqual(first, second)
        self.assertEqual("game_review", first[0]["category"])
        self.assertEqual("A focused review checks the sound mix.", first[0]["text"])
        self.assertTrue(_audit(first)["passed"])

    def test_rejects_replacement_with_wrong_source_sha(self) -> None:
        records = [_record()]
        repair_set = _repair_set(records)
        overlay = _overlay(records, repair_set)
        overlay["records"][0]["original_record_sha256"] = "wrong"

        with self.assertRaisesRegex(RuntimeError, "original record SHA"):
            _materialize_fixture(records, repair_set, overlay)

    def test_rejects_repair_set_record_missing_from_source(self) -> None:
        records = [_record()]
        repair_set = _repair_set(records)
        overlay = _overlay(records, repair_set)
        repair_set["records"][0]["record_id"] = "v4-b01-999"
        overlay["records"][0]["record_id"] = "v4-b01-999"

        with self.assertRaisesRegex(RuntimeError, "unknown record IDs"):
            _materialize_fixture(records, repair_set, overlay)

    def test_rejects_overlay_reason_mismatch(self) -> None:
        records = [_record()]
        repair_set = _repair_set(records)
        overlay = _overlay(records, repair_set)
        overlay["records"][0]["repair_reasons"] = ["different_reason"]

        with self.assertRaisesRegex(RuntimeError, "repair reasons"):
            _materialize_fixture(records, repair_set, overlay)

    def test_rejects_mutated_unreplaced_source_provenance(self) -> None:
        records = [_record(), _record("v4-b01-002")]
        repair_set = _repair_set(records)
        overlay = _overlay(records, repair_set)

        with self.assertRaisesRegex(RuntimeError, "source_records_sha256"):
            _materialize_fixture(
                records,
                repair_set,
                overlay,
                source_records_sha256="e" * 64,
            )

    def test_rejects_wrong_overlay_repair_set_sha(self) -> None:
        records = [_record()]
        repair_set = _repair_set(records)
        overlay = _overlay(records, repair_set)
        overlay["repair_set_sha256"] = "e" * 64

        with self.assertRaisesRegex(RuntimeError, "repair_set_sha256"):
            _materialize_fixture(records, repair_set, overlay)

    def test_rejects_unsupported_overlay_schema(self) -> None:
        records = [_record()]
        repair_set = _repair_set(records)
        overlay = _overlay(records, repair_set)
        overlay["corpus_v4_repair_overlay_schema_version"] = 2

        with self.assertRaisesRegex(RuntimeError, "overlay schema version"):
            _materialize_fixture(records, repair_set, overlay)

    def test_rejects_repetition_only_context_drift(self) -> None:
        records = [_record()]
        repair_set = _repair_set(records)
        repair_set["records"][0]["target"] = {
            "category": "game_commentary",
            "scene_context": "gameplay_stream",
            "speech_intent": "game_commentary",
        }
        repair_set["records"][0]["target_metadata_policy"] = "preserve_exact"
        overlay = _overlay(records, repair_set)
        overlay["records"][0]["target"] = {
            "category": "game_commentary",
            "scene_context": "gameplay_stream",
            "speech_intent": "explanation",
        }

        with self.assertRaisesRegex(RuntimeError, "metadata drifted"):
            _materialize_fixture(records, repair_set, overlay)

    def test_rejects_extra_entry_fields(self) -> None:
        records = [_record()]
        repair_set = _repair_set(records)
        overlay = _overlay(records, repair_set)
        overlay["records"][0]["unexpected"] = True

        with self.assertRaisesRegex(RuntimeError, "entry schema"):
            _materialize_fixture(records, repair_set, overlay)

    def test_rejects_missing_entry_fields(self) -> None:
        records = [_record()]
        repair_set = _repair_set(records)
        overlay = _overlay(records, repair_set)
        del overlay["records"][0]["replacement_text_sha256"]

        with self.assertRaisesRegex(RuntimeError, "entry schema"):
            _materialize_fixture(records, repair_set, overlay)

    def test_repair_materialize_audit_round_trip_passes(self) -> None:
        records = [_record(f"v4-b01-00{index}") for index in range(1, 4)]
        for record in records:
            record["text"] = "Shared source sentence."
        source_id_set_sha = _record_id_set_sha256(records)
        audit = _audit(
            records,
            source_records_sha256=_SOURCE_SHA,
            source_record_id_set_sha256=source_id_set_sha,
            corpus_id="test-v4",
        )
        policy = {
            "corpus_v4_repair_policy_schema_version": 1,
            "corpus_id": "test-v4",
            "allowed_category_replacements": {},
            "selection_priority": [],
        }
        repair_set = _build_repair_set(
            audit,
            records,
            source_audit_sha256=_AUDIT_SHA,
            source_records_sha256=_SOURCE_SHA,
            source_record_id_set_sha256=source_id_set_sha,
            repair_policy=policy,
            repair_policy_sha256=_POLICY_SHA,
            category_quotas={"game_commentary": 3},
        )
        repair_set_sha = _document_sha256(repair_set)
        overlay = _round_trip_overlay(records, repair_set, repair_set_sha)

        materialized = _materialize(
            records,
            repair_set,
            overlay,
            source_records_sha256=_SOURCE_SHA,
            source_record_id_set_sha256=source_id_set_sha,
            source_record_count=len(records),
            source_audit_sha256=_AUDIT_SHA,
            repair_policy_sha256=_POLICY_SHA,
            repair_policy_id="test-v4",
            repair_set_sha256=repair_set_sha,
        )

        self.assertTrue(_audit(materialized)["passed"])


def _materialize_fixture(
    records: list[dict[str, object]],
    repair_set: dict[str, Any],
    overlay: dict[str, Any],
    *,
    source_records_sha256: str = _SOURCE_SHA,
) -> list[dict[str, object]]:
    return _materialize(
        records,
        repair_set,
        overlay,
        source_records_sha256=source_records_sha256,
        source_record_id_set_sha256=_record_id_set_sha256(records),
        source_record_count=len(records),
        source_audit_sha256=_AUDIT_SHA,
        repair_policy_sha256=_POLICY_SHA,
        repair_policy_id="test-v4",
        repair_set_sha256=_REPAIR_SET_SHA,
    )


def _record(record_id: str = "v4-b01-001") -> dict[str, object]:
    return {
        "batch_id": "v4-b01",
        "record_id": record_id,
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


def _repair_set(records: list[dict[str, object]]) -> dict[str, Any]:
    record = records[0]
    return {
        "corpus_v4_repair_set_schema_version": 3,
        "corpus_id": "test-v4",
        "source_audit_sha256": _AUDIT_SHA,
        "source_records_sha256": _SOURCE_SHA,
        "source_record_id_set_sha256": _record_id_set_sha256(records),
        "source_record_count": len(records),
        "repair_policy_sha256": _POLICY_SHA,
        "repair_policy_id": "test-v4",
        "implicated_record_count": 1,
        "selected_record_count": 1,
        "selection_policy": (
            "deterministic_greedy_multicover_fixed_slot_swap_reverse_delete_"
            "bounded_local_search"
        ),
        "selection_metrics": {},
        "records": [_plan(record)],
    }


def _plan(record: dict[str, object]) -> dict[str, object]:
    return {
        "record_id": record["record_id"],
        "original_record_sha256": _record_sha256(record),
        "original_category": "game_commentary",
        "repair_reasons": ["ngram_4:abc"],
        "preserve": {
            "batch_id": "v4-b01",
            "record_id": record["record_id"],
            "language_class": "en",
            "intended_length_class": "short",
        },
        "target": {"category": "game_review"},
        "target_metadata_policy": "compatible_author_required",
    }


def _overlay(
    records: list[dict[str, object]], repair_set: dict[str, Any]
) -> dict[str, Any]:
    record = records[0]
    text = "A focused review checks the sound mix."
    return {
        "corpus_v4_repair_overlay_schema_version": 3,
        "corpus_id": "test-v4",
        "source_audit_sha256": _AUDIT_SHA,
        "source_records_sha256": _SOURCE_SHA,
        "source_record_id_set_sha256": _record_id_set_sha256(records),
        "repair_set_sha256": _REPAIR_SET_SHA,
        "repair_policy_sha256": _POLICY_SHA,
        "repair_policy_id": "test-v4",
        "records": [
            {
                "record_id": record["record_id"],
                "original_record_sha256": _record_sha256(record),
                "repair_reasons": ["ngram_4:abc"],
                "preserve": {
                    "batch_id": "v4-b01",
                    "record_id": record["record_id"],
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
                "replacement_text_sha256": hashlib.sha256(
                    text.encode("utf-8")
                ).hexdigest(),
            }
        ],
    }


def _round_trip_overlay(
    records: list[dict[str, object]],
    repair_set: dict[str, Any],
    repair_set_sha: str,
) -> dict[str, Any]:
    records_by_id = {record["record_id"]: record for record in records}
    entries = []
    for index, plan in enumerate(repair_set["records"], 1):
        record = records_by_id[plan["record_id"]]
        text = f"A distinct repaired sentence {index}."
        entries.append(
            {
                "record_id": plan["record_id"],
                "original_record_sha256": plan["original_record_sha256"],
                "repair_reasons": plan["repair_reasons"],
                "preserve": plan["preserve"],
                "target": {
                    "category": plan["target"]["category"],
                    "scene_context": record["scene_context"],
                    "speech_intent": record["speech_intent"],
                },
                "replacement": {
                    "text": text,
                    "template_family_id": f"family-{index}",
                    "semantic_intent_id": f"intent-{index}",
                    "key_phrase_id": f"phrase-{index}",
                },
                "replacement_text_sha256": hashlib.sha256(
                    text.encode("utf-8")
                ).hexdigest(),
            }
        )
    return {
        "corpus_v4_repair_overlay_schema_version": 3,
        "corpus_id": "test-v4",
        "source_audit_sha256": _AUDIT_SHA,
        "source_records_sha256": _SOURCE_SHA,
        "source_record_id_set_sha256": _record_id_set_sha256(records),
        "repair_set_sha256": repair_set_sha,
        "repair_policy_sha256": _POLICY_SHA,
        "repair_policy_id": "test-v4",
        "records": entries,
    }


def _document_sha256(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
