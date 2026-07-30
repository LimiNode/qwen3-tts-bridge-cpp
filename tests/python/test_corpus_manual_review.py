"""Tests for the fail-closed corpus human-review contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import unittest

from scripts.evaluate_corpus_manual_review import (
    _evaluate,
    _validate_contract,
    _validate_record,
)
from scripts.prepare_corpus_manual_review import _review_record


class CorpusManualReviewTests(unittest.TestCase):
    def test_review_form_starts_pending_without_scores(self) -> None:
        record = _review_record(_source("v4-0001"), b"source")

        self.assertEqual("pending_human_review", record["review_status"])
        self.assertIsNone(record["naturalness"])

    def test_completed_review_requires_exact_frozen_sample_and_all_gates(self) -> None:
        frozen = [_source(f"v4-{index:04d}") for index in range(1, 101)]
        frozen_bytes = _jsonl(frozen)
        audit = {
            "corpus_id": "v4",
            "manual_review_sha256": hashlib.sha256(frozen_bytes).hexdigest(),
            "generator_source_sha256": "generator",
            "generation_config_sha256": "config",
        }
        records = [_completed(source, frozen_bytes) for source in frozen]
        for index, record in enumerate(records, 1):
            _validate_record(record, index)

        provenance = _validate_contract(records, frozen, frozen_bytes, audit)
        summary = _evaluate(records, _args(), provenance)

        self.assertTrue(summary["passed"])
        self.assertEqual("passed", summary["status"])
        self.assertEqual("v4", summary["corpus_id"])

    def test_contract_rejects_partial_review(self) -> None:
        frozen = [_source(f"v4-{index:04d}") for index in range(1, 101)]
        frozen_bytes = _jsonl(frozen)
        records = [_completed(frozen[0], frozen_bytes)]
        audit = {
            "corpus_id": "v4",
            "manual_review_sha256": hashlib.sha256(frozen_bytes).hexdigest(),
        }

        with self.assertRaisesRegex(RuntimeError, "exactly 100"):
            _validate_contract(records, frozen, frozen_bytes, audit)

    def test_contract_rejects_changed_source_text(self) -> None:
        frozen = [_source(f"v4-{index:04d}") for index in range(1, 101)]
        frozen_bytes = _jsonl(frozen)
        records = [_completed(source, frozen_bytes) for source in frozen]
        records[0]["text"] = "Changed."
        audit = {
            "corpus_id": "v4",
            "manual_review_sha256": hashlib.sha256(frozen_bytes).hexdigest(),
        }

        with self.assertRaisesRegex(RuntimeError, "does not match frozen content"):
            _validate_contract(records, frozen, frozen_bytes, audit)

    def test_all_published_quality_metrics_block_a_pass(self) -> None:
        frozen = [_source(f"v4-{index:04d}") for index in range(1, 101)]
        frozen_bytes = _jsonl(frozen)
        records = [_completed(source, frozen_bytes) for source in frozen]
        for record in records[:6]:
            record["grammar"] = False
        audit = {
            "corpus_id": "v4",
            "manual_review_sha256": hashlib.sha256(frozen_bytes).hexdigest(),
        }

        self.assertFalse(
            _evaluate(
                records,
                _args(),
                _validate_contract(records, frozen, frozen_bytes, audit),
            )["passed"]
        )


def _source(label: str) -> dict[str, object]:
    return {
        "corpus_id": "v4",
        "label": label,
        "category": "conversation",
        "language_class": "ru",
        "intended_length_class": "micro",
        "text": f"Фраза {label}.",
    }


def _completed(source: dict[str, object], frozen_bytes: bytes) -> dict[str, object]:
    result = _review_record(source, frozen_bytes)
    result.update(
        {
            "review_status": "completed_human_review",
            "reviewer_id": "reviewer",
            "category_fidelity": True,
            "naturalness": True,
            "likely_real_usage": True,
            "semantic_repetition_acceptable": True,
            "appropriate_length": True,
            "grammar": True,
            "generic_experiment_phrasing": False,
        }
    )
    return result


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        minimum_natural_percent=90.0,
        minimum_category_percent=90.0,
        minimum_likely_real_usage_percent=90.0,
        minimum_repetition_percent=90.0,
        minimum_appropriate_length_percent=95.0,
        minimum_grammar_percent=95.0,
        maximum_unacceptable_mixed_percent=5.0,
        maximum_generic_experiment_percent=10.0,
    )


def _jsonl(records: list[dict[str, object]]) -> bytes:
    return b"".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
        for record in records
    )


if __name__ == "__main__":
    unittest.main()
