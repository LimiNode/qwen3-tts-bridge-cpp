"""Tests for corpus-v4 human-adjudication acceptance gates."""

from __future__ import annotations

import unittest
from typing import Any

from scripts.accept_corpus_v4_ai_prereview_revision import _acceptance_report
from scripts.audit_corpus_repetition import _audit


class AcceptCorpusV4AiPrereviewRevisionTests(unittest.TestCase):
    def test_accepts_only_when_all_gates_pass(self) -> None:
        report = _acceptance_report(
            {"record_count": 2000}, {"passed": True}, {"passed": True}
        )

        self.assertTrue(report["materialization_pass"])
        self.assertTrue(report["corpus_validation_pass"])
        self.assertTrue(report["repetition_pass"])
        self.assertTrue(report["acceptance_pass"])

    def test_rejects_repeated_ngram(self) -> None:
        records: list[dict[str, Any]] = [
            {
                "record_id": f"record-{index}",
                "text": f"one two three four five six seven eight {index}",
            }
            for index in range(7)
        ]
        repetition = _audit(records)
        report = _acceptance_report(
            {"record_count": 2000}, {"passed": True}, repetition
        )

        self.assertFalse(repetition["passed"])
        self.assertFalse(report["repetition_pass"])
        self.assertFalse(report["acceptance_pass"])


if __name__ == "__main__":
    unittest.main()
