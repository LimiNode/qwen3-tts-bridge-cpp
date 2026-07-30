"""Tests for deterministic, provenance-pinned corpus-v4 repair selection."""

from __future__ import annotations

import unittest
from typing import Any

from scripts.audit_corpus_repetition import _record_id_set_sha256
from scripts.build_corpus_v4_repair_set import (
    _bounded_local_improvement,
    _build_repair_set,
    _reverse_prune,
)


class CorpusV4RepairSetTests(unittest.TestCase):
    def test_selects_overflow_repairs_with_honest_policy_name(self) -> None:
        records = _records()
        result = _build(
            records,
            {
                "sentence": {
                    "repeat": ["v4-b01-001", "v4-b01-002", "v4-b01-003"]
                }
            },
        )

        self.assertEqual(2, result["selected_record_count"])
        self.assertEqual(
            "deterministic_greedy_multicover_reverse_delete_bounded_local_search",
            result["selection_policy"],
        )
        self.assertEqual(
            2,
            result["selection_metrics"]["greedy_repetition_selected_count"],
        )

    def test_category_rebalance_uses_policy_and_new_text(self) -> None:
        records = _records()
        quotas = _quotas(game_commentary=0, game_review=2)
        result = _build(records, {}, quotas=quotas)

        entry = result["records"][0]
        self.assertEqual("game_commentary", entry["original_category"])
        self.assertEqual("game_review", entry["target"]["category"])
        self.assertIn("category_quota_rebalance", entry["repair_reasons"])
        self.assertEqual(
            1,
            result["selection_metrics"]["category_rebalance_record_count"],
        )

    def test_audit_from_another_source_is_rejected(self) -> None:
        records = _records()
        audit = _audit({}, records)
        audit["source_records_sha256"] = "b" * 64

        with self.assertRaisesRegex(RuntimeError, "source records SHA"):
            _build_repair_set(
                audit,
                records,
                source_audit_sha256="a" * 64,
                source_records_sha256="a" * 64,
                source_record_id_set_sha256=_record_id_set_sha256(records),
                repair_policy=_policy(records, _quotas()),
                repair_policy_sha256="c" * 64,
                category_quotas=_quotas(),
            )

    def test_policy_that_does_not_match_imbalance_is_rejected(self) -> None:
        records = _records()
        quotas = _quotas(game_commentary=0, game_review=2)
        policy = _policy(records, quotas)
        policy["allowed_category_replacements"] = {}
        policy["selection_priority"] = []

        with self.assertRaisesRegex(RuntimeError, "does not match source category"):
            _build(
                records,
                {},
                quotas=quotas,
                policy=policy,
            )

    def test_reverse_prune_removes_redundant_selection(self) -> None:
        groups = [{"id": "sentence:x", "limit": 1, "occurrences": {"a": 1, "b": 1}}]

        self.assertEqual({"a"}, _reverse_prune({"a", "b"}, {}, groups))

    def test_bounded_local_improvement_replaces_two_with_one(self) -> None:
        groups = [
            {"id": "sentence:first", "limit": 1, "occurrences": {"a": 1, "c": 1}},
            {"id": "sentence:second", "limit": 1, "occurrences": {"b": 1, "c": 1}},
        ]

        selected, metrics = _bounded_local_improvement({"a", "b"}, {}, groups)

        self.assertEqual({"c"}, selected)
        self.assertEqual(1, metrics["bounded_local_improvement_count"])


def _build(
    records: list[dict[str, object]],
    groups: dict[str, Any],
    *,
    quotas: dict[str, int] | None = None,
    policy: dict[str, object] | None = None,
) -> dict[str, Any]:
    effective_quotas = quotas or _quotas()
    return _build_repair_set(
        _audit(groups, records),
        records,
        source_audit_sha256="a" * 64,
        source_records_sha256="a" * 64,
        source_record_id_set_sha256=_record_id_set_sha256(records),
        repair_policy=policy or _policy(records, effective_quotas),
        repair_policy_sha256="c" * 64,
        category_quotas=effective_quotas,
    )


def _audit(groups: dict[str, Any], records: list[dict[str, object]]) -> dict[str, Any]:
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
        "corpus_repetition_audit_schema_version": 4,
        "corpus_id": "test-v4",
        "record_count": len(records),
        "source_records_sha256": "a" * 64,
        "source_record_id_set_sha256": _record_id_set_sha256(records),
        "limits": {
            "exact_text": 1,
            "sentence": 1,
            "closing_block": 1,
            **{str(size): 1 for size in range(4, 9)},
        },
        "frequencies": {},
        "violations": violations,
        "violation_records": occurrences,
        "passed": not groups,
    }


def _records() -> list[dict[str, object]]:
    return [
        _record("v4-b01-001", "game_commentary"),
        _record("v4-b01-002", "live_chat"),
        _record("v4-b01-003", "game_review"),
        _record("v4-b01-004", "live_chat"),
    ]


def _record(record_id: str, category: str) -> dict[str, object]:
    return {
        "batch_id": "v4-b01",
        "record_id": record_id,
        "language_class": "ru",
        "intended_length_class": "micro",
        "category": category,
    }


def _quotas(
    *, game_commentary: int = 1, game_review: int = 1
) -> dict[str, int]:
    return {
        "game_commentary": game_commentary,
        "live_chat": 2,
        "game_review": game_review,
        "conversation": 0,
        "game_dialogue": 0,
        "stream_event": 0,
        "transition": 0,
    }


def _policy(
    records: list[dict[str, object]], quotas: dict[str, int]
) -> dict[str, object]:
    source_counts = {
        category: sum(record["category"] == category for record in records)
        for category in quotas
    }
    extras = {
        category: source_counts[category] - quota
        for category, quota in quotas.items()
        if source_counts[category] > quota
    }
    deficits = {
        category: quota - source_counts[category]
        for category, quota in quotas.items()
        if source_counts[category] < quota
    }
    replacements: dict[str, dict[str, int]] = {}
    for source, count in extras.items():
        target = next(
            category for category, deficit in deficits.items() if deficit == count
        )
        replacements[source] = {target: count}
    return {
        "corpus_v4_repair_policy_schema_version": 1,
        "corpus_id": "test-v4",
        "allowed_category_replacements": replacements,
        "selection_priority": list(replacements),
    }


if __name__ == "__main__":
    unittest.main()
