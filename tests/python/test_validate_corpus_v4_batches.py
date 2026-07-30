"""Tests for corpus-v4 batch identity, schema, and quota validation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_corpus_v4_batches import _validate


class CorpusV4BatchValidationTests(unittest.TestCase):
    def test_valid_batch_reports_remaining_quotas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = _write(Path(directory), _records())
            result = _validate([path], 10)

        self.assertTrue(result["passed"])
        self.assertEqual(1100, result["remaining_quotas"]["language_class"]["ru"])

    def test_unknown_enum_and_duplicate_record_id_fail(self) -> None:
        records = _records()
        records[0]["category"] = "unknown"
        records[1]["record_id"] = records[0]["record_id"]
        with tempfile.TemporaryDirectory() as directory:
            path = _write(Path(directory), records)
            result = _validate([path], 10)

        self.assertFalse(result["passed"])
        self.assertEqual(["1"], result["failures"]["record_contract"])
        self.assertTrue(result["failures"]["duplicate_record_id"])


def _records() -> list[dict[str, object]]:
    return [
        {
            "batch_id": "v4-b01",
            "record_id": f"v4-b01-{index:03d}",
            "text": f"Фраза номер {index}.",
            "language_class": "ru",
            "category": "game_commentary",
            "scene_context": "gameplay_stream",
            "speech_intent": "game_commentary",
            "intended_length_class": "micro",
            "template_family_id": f"family-{index}",
            "semantic_intent_id": f"intent-{index}",
            "key_phrase_id": f"phrase-{index}",
        }
        for index in range(1, 201)
    ]


def _write(directory: Path, records: list[dict[str, object]]) -> Path:
    path = directory / "batch.jsonl"
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
