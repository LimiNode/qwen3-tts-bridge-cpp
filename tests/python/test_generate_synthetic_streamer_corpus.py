"""Tests for the frozen synthetic-proxy workload generator."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.generate_synthetic_streamer_corpus import _audit, _build_records


class GenerateSyntheticStreamerCorpusTests(unittest.TestCase):
    def test_fixed_workload_has_expected_strata_and_repeat_rate(self) -> None:
        records = _build_records(20260730)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.jsonl"
            path.write_text(
                "".join(
                    json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )
            audit = _audit(records, path)

        self.assertEqual(500, audit["record_count"])
        self.assertEqual(350, audit["language_histogram"]["ru"])
        self.assertEqual(100, audit["language_histogram"]["en"])
        self.assertEqual(50, audit["language_histogram"]["mixed"])
        self.assertEqual(160, audit["category_histogram"]["live_chat"])
        self.assertEqual(100, audit["intended_length_histogram"]["short"])
        self.assertGreaterEqual(audit["unique_text_count"], 425)
        self.assertLessEqual(audit["unique_text_count"], 450)
        self.assertEqual(3, audit["word_count_min"])
        self.assertEqual(60, audit["word_count_max"])

    def test_generation_is_deterministic(self) -> None:
        first = _build_records(20260730)
        second = _build_records(20260730)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
