"""Tests for deterministic corpus-v4 runtime partitioning."""

from __future__ import annotations

import unittest

from scripts.split_corpus_v4_runtime import (
    _batch_coverage,
    _select_review_sample,
    _split_records,
    _validate_batch_coverage,
)


class SplitCorpusV4RuntimeTests(unittest.TestCase):
    def test_creates_disjoint_deterministic_1500_500_split(self) -> None:
        records = _records()

        first_discovery, first_holdout = _split_records(records, 123)
        second_discovery, second_holdout = _split_records(records, 123)

        self.assertEqual(first_discovery, second_discovery)
        self.assertEqual(first_holdout, second_holdout)
        self.assertEqual(1500, len(first_discovery))
        self.assertEqual(500, len(first_holdout))
        self.assertFalse(
            {record["record_id"] for record in first_discovery}
            & {record["record_id"] for record in first_holdout}
        )
        self.assertTrue(
            all(record["corpus_split"] == "discovery" for record in first_discovery)
        )
        self.assertTrue(
            all(
                record["corpus_split"] == "runtime_measurement_holdout"
                for record in first_holdout
            )
        )

    def test_review_sample_is_stratified_and_discovery_only(self) -> None:
        discovery, _ = _split_records(_records(), 123)

        review = _select_review_sample(discovery, 123)

        self.assertEqual(100, len(review))
        self.assertTrue(
            {record["record_id"] for record in review}
            .issubset({record["record_id"] for record in discovery})
        )
        self.assertTrue(all(record["corpus_split"] == "discovery" for record in review))
        self.assertEqual(
            [f"v4-b{index:02d}" for index in range(1, 11)],
            _batch_coverage(review),
        )

    def test_batch_coverage_rejects_missing_batch(self) -> None:
        records = _records()[:1800]

        with self.assertRaisesRegex(RuntimeError, "missing=.*v4-b10"):
            _validate_batch_coverage(records, "test")


def _records() -> list[dict[str, object]]:
    categories = ("conversation", "game_commentary", "game_review", "live_chat")
    languages = ("ru", "en", "mixed")
    lengths = ("micro", "short", "medium", "long", "extended")
    return [
        {
            "batch_id": f"v4-b{index // 200 + 1:02d}",
            "record_id": f"v4-b{index // 200 + 1:02d}-{index % 200 + 1:03d}",
            "text": f"Record {index}.",
            "language_class": languages[index % len(languages)],
            "category": categories[index % len(categories)],
            "scene_context": "offline_conversation",
            "speech_intent": "casual_discussion",
            "intended_length_class": lengths[index % len(lengths)],
            "template_family_id": f"family-{index}",
            "semantic_intent_id": f"intent-{index}",
            "key_phrase_id": f"phrase-{index}",
        }
        for index in range(2000)
    ]


if __name__ == "__main__":
    unittest.main()
