"""Tests for deterministic corpus-v4 repair-set selection."""

from __future__ import annotations

import unittest
from typing import Any

from scripts.build_corpus_v4_repair_set import _build_repair_set


class CorpusV4RepairSetTests(unittest.TestCase):
    def test_keeps_allowed_survivors_and_selects_only_surplus(self) -> None:
        result = _build_repair_set(
            _audit(
                {
                    "sentence": {
                        "repeat": ["v4-b01-001", "v4-b01-002", "v4-b01-003"]
                    }
                }
            ),
            _records(),
            "audit",
            category_quotas=_test_quotas(),
        )

        self.assertEqual(2, result["selected_record_count"])
        self.assertEqual(
            ["v4-b01-001", "v4-b01-002"],
            [entry["record_id"] for entry in result["records"]],
        )

    def test_overlapping_violations_share_one_replacement(self) -> None:
        result = _build_repair_set(
            _audit(
                {
                    "sentence": {"first": ["v4-b01-001", "v4-b01-002"]},
                    "ngrams": {"8": {"second": ["v4-b01-001", "v4-b01-003"]}},
                }
            ),
            _records(),
            "audit",
            category_quotas=_test_quotas(),
        )

        selected = {entry["record_id"]: entry for entry in result["records"]}
        self.assertIn("v4-b01-001", selected)
        self.assertGreaterEqual(len(selected["v4-b01-001"]["repair_reasons"]), 2)

    def test_category_priority_breaks_equal_coverage_ties(self) -> None:
        result = _build_repair_set(
            _audit({"sentence": {"repeat": ["v4-b01-001", "v4-b01-004"]}}),
            _records(),
            "audit",
            category_quotas=_test_quotas(),
        )

        self.assertEqual("v4-b01-001", result["records"][0]["record_id"])

    def test_category_rebalance_selects_new_text_without_mutating_source(self) -> None:
        result = _build_repair_set(
            _audit({}),
            _records(),
            "audit",
            category_quotas={
                "game_commentary": 0,
                "live_chat": 2,
                "game_review": 2,
                "conversation": 0,
                "game_dialogue": 0,
                "stream_event": 0,
                "transition": 0,
            },
        )

        entry = next(
            item for item in result["records"] if item["record_id"] == "v4-b01-001"
        )
        self.assertEqual("game_commentary", entry["original_category"])
        self.assertEqual("game_review", entry["target"]["category"])
        self.assertIn("category_quota_rebalance", entry["repair_reasons"])


def _audit(groups: dict[str, Any]) -> dict[str, Any]:
    violations: dict[str, Any] = {
        "exact_text": {},
        "sentence": {},
        "closing_block": {},
        "ngrams": {str(size): {} for size in range(4, 9)},
    }
    occurrences: dict[str, Any] = {
        "exact_text": {},
        "sentence": {},
        "closing_block": {},
        "ngrams": {str(size): {} for size in range(4, 9)},
    }
    for kind, entries in groups.items():
        if kind == "ngrams":
            for size, values in entries.items():
                violations["ngrams"][size] = {
                    value: len(labels) for value, labels in values.items()
                }
                occurrences["ngrams"][size] = values
        else:
            violations[kind] = {value: len(labels) for value, labels in entries.items()}
            occurrences[kind] = entries
    return {
        "limits": {
            "exact_text": 1,
            "sentence": 1,
            "closing_block": 1,
            **{str(size): 1 for size in range(4, 9)},
        },
        "violations": violations,
        "violation_records": occurrences,
    }


def _records() -> list[dict[str, object]]:
    return [
        {
            "batch_id": "v4-b01",
            "record_id": "v4-b01-001",
            "language_class": "ru",
            "intended_length_class": "micro",
            "category": "game_commentary",
        },
        {
            "batch_id": "v4-b01",
            "record_id": "v4-b01-002",
            "language_class": "ru",
            "intended_length_class": "micro",
            "category": "live_chat",
        },
        {
            "batch_id": "v4-b01",
            "record_id": "v4-b01-003",
            "language_class": "ru",
            "intended_length_class": "micro",
            "category": "game_review",
        },
        {
            "batch_id": "v4-b01",
            "record_id": "v4-b01-004",
            "language_class": "ru",
            "intended_length_class": "micro",
            "category": "live_chat",
        },
    ]


def _test_quotas() -> dict[str, int]:
    return {
        "game_commentary": 1,
        "live_chat": 2,
        "game_review": 1,
        "conversation": 0,
        "game_dialogue": 0,
        "stream_event": 0,
        "transition": 0,
    }


if __name__ == "__main__":
    unittest.main()
