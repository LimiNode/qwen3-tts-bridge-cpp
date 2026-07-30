from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import generate_natural_synthetic_corpus as corpus


class NaturalSyntheticCorpusTests(unittest.TestCase):
    def test_records_preserve_actual_seed_and_are_unique(self) -> None:
        templates, template_sha256 = corpus._load_templates(corpus._TEMPLATE_PATH)
        provenance = corpus._provenance(123456, template_sha256)

        records = corpus._build_records(123456, templates, provenance)

        self.assertEqual(2000, len(records))
        self.assertEqual(2000, len({record["text"] for record in records}))
        self.assertEqual({123456}, {record["generation_seed"] for record in records})
        self.assertEqual(
            {provenance["generator_source_sha256"]},
            {record["generator_source_sha256"] for record in records},
        )
        self.assertEqual(
            {provenance["template_data_sha256"]},
            {record["template_data_sha256"] for record in records},
        )

    def test_split_and_audit_enforce_natural_corpus_contract(self) -> None:
        templates, template_sha256 = corpus._load_templates(corpus._TEMPLATE_PATH)
        provenance = corpus._provenance(20260731, template_sha256)
        records = corpus._build_records(20260731, templates, provenance)
        discovery, holdout = corpus._split_records(records, 20260731)
        review = corpus._manual_review_records(records, 20260731)

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

        self.assertEqual("none", audit["filler_strategy"])
        self.assertEqual(100.0, audit["uniqueness_percent"])
        self.assertEqual([], audit["class_validation_failures"])
        self.assertEqual([], audit["language_validation_failures"])
        self.assertEqual(1, audit["max_repeated_token_run"])

    def test_template_data_is_valid_json(self) -> None:
        value = json.loads(corpus._TEMPLATE_PATH.read_text(encoding="utf-8"))

        self.assertEqual({"en", "mixed", "ru"}, set(value))


if __name__ == "__main__":
    unittest.main()
