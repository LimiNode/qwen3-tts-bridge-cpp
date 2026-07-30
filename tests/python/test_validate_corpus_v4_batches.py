"""Tests for corpus-v4 batch identity, schema, and quota validation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_corpus_v4_batches import _record_valid, _validate


class CorpusV4BatchValidationTests(unittest.TestCase):
    def test_micro_length_does_not_count_standalone_dash(self) -> None:
        record = _records()[0]
        record["text"] = "Пауза — не сомнение."

        self.assertTrue(_record_valid(record))

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
        self.assertEqual(
            ["unknown_enum:category"],
            result["failures"]["record_contract_details"]["v4-b01-001"],
        )
        self.assertTrue(result["failures"]["duplicate_record_id"])

    def test_missing_text_returns_failure_report_without_traceback(self) -> None:
        records = _records()
        del records[0]["text"]
        with tempfile.TemporaryDirectory() as directory:
            path = _write(Path(directory), records)
            result = _validate([path], 10)

        self.assertFalse(result["passed"])
        self.assertEqual(["1"], result["failures"]["record_contract"])
        self.assertEqual(
            ["missing:text"],
            result["failures"]["record_contract_details"]["v4-b01-001"],
        )
        self.assertEqual({}, result["failures"]["repetition"])
        self.assertEqual({}, result["failures"]["repetition_records"])

    def test_non_contiguous_batch_prefix_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = _write(root / "first", _records("v4-b01"))
            seventh = _write(root / "seventh", _records("v4-b07"))
            result = _validate([first, seventh], 10)

        self.assertFalse(result["passed"])
        self.assertTrue(result["failures"]["contiguous_batch_prefix"])


def _records(batch_id: str = "v4-b01") -> list[dict[str, object]]:
    return [
        {
            "batch_id": batch_id,
            "record_id": f"{batch_id}-{index:03d}",
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
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "batch.jsonl"
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
