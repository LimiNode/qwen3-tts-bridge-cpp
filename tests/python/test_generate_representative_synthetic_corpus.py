"""Tests for the representative streamer/game corpus v3 generator."""

from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, cast

from scripts import generate_representative_synthetic_corpus as corpus


class RepresentativeSyntheticCorpusTests(unittest.TestCase):
    def test_v3_contract_includes_micro_utterances_and_repetition_limits(self) -> None:
        records = corpus._build_records(20260801, corpus._provenance(20260801))

        self.assertEqual(2000, len(records))
        self.assertEqual(2000, len({record["text"] for record in records}))
        self.assertEqual(
            [], [record for record in records if not corpus._length_valid(record)]
        )
        self.assertEqual(
            [], [record for record in records if not corpus._language_valid(record)]
        )
        micro_counts = Counter(
            corpus._word_count(str(record["text"]))
            for record in records
            if record["intended_length_class"] == "micro"
        )
        self.assertEqual(300, sum(micro_counts.values()))
        self.assertTrue(set(micro_counts).issubset({1, 2, 3}))
        self.assertIn(2, micro_counts)

    def test_v3_split_and_audit_preserve_holdout_and_preflight(self) -> None:
        provenance = corpus._provenance(20260801)
        records = corpus._build_records(20260801, provenance)
        discovery, holdout = corpus._split_records(records, 20260801)
        review = corpus._manual_review_records(records, 20260801)

        self.assertEqual(1500, len(discovery))
        self.assertEqual(500, len(holdout))
        self.assertEqual(100, len(review))
        self.assertFalse(
            {record["label"] for record in discovery}
            & {record["label"] for record in holdout}
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            discovery_path = directory / "discovery.jsonl"
            holdout_path = directory / "holdout.jsonl"
            review_path = directory / "review.jsonl"
            corpus._write_jsonl(discovery_path, discovery)
            corpus._write_jsonl(holdout_path, holdout)
            corpus._write_jsonl(review_path, review)
            audit = corpus._audit(
                records,
                discovery,
                holdout,
                review,
                discovery_path,
                holdout_path,
                review_path,
                provenance,
            )

        self.assertEqual("passed", audit["automated_preflight_status"])
        self.assertEqual("pending_human_review", audit["manual_review_status"])
        failures = cast(dict[str, Any], audit["validation_failures"])
        self.assertEqual([], failures["template_family"])
        self.assertEqual([], failures["semantic_intent"])
        self.assertEqual([], failures["key_phrase"])


if __name__ == "__main__":
    unittest.main()
