"""Tests for corpus repetition diagnostics."""

from __future__ import annotations

import unittest

from scripts.audit_corpus_repetition import _audit


class CorpusRepetitionAuditTests(unittest.TestCase):
    def test_unique_sentences_and_ngrams_pass(self) -> None:
        result = _audit(
            [{"text": "Первый маршрут открыт."}, {"text": "Вторая сцена готова."}],
            4,
            5,
        )

        self.assertTrue(result["passed"])

    def test_shared_closing_block_fails(self) -> None:
        result = _audit(
            [
                {"text": "Проверим вход. Дальше идём спокойно."},
                {"text": "Проверим выход. Дальше идём спокойно."},
            ],
            4,
            5,
        )

        self.assertFalse(result["passed"])
        self.assertEqual(2, result["duplicate_closing_blocks"]["дальше идём спокойно"])


if __name__ == "__main__":
    unittest.main()
