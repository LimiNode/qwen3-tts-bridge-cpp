"""Tests for frequency-limited corpus repetition diagnostics."""

from __future__ import annotations

import unittest

from scripts.audit_corpus_repetition import _audit


class CorpusRepetitionAuditTests(unittest.TestCase):
    def test_short_natural_phrase_can_repeat_within_limit(self) -> None:
        result = _audit(
            [
                {"text": "Спасибо большое за подписку."},
                {"text": "Спасибо большое за подписку."},
            ]
        )

        self.assertFalse(result["passed"])
        self.assertEqual(
            {"спасибо большое за подписку.": 2},
            result["frequencies"]["duplicate_exact_text"],
        )
        self.assertEqual(
            ["1", "2"],
            result["violation_records"]["exact_text"]
            ["спасибо большое за подписку."],
        )

    def test_sentence_repetition_at_the_limit_is_reported_but_allowed(self) -> None:
        result = _audit(
            [
                {"text": "Спасибо большое за подписку. Первый маршрут открыт."},
                {"text": "Спасибо большое за подписку. Вторая сцена готова."},
            ]
        )

        self.assertTrue(result["passed"])
        self.assertEqual({}, result["violations"]["sentence"])

    def test_exact_text_uses_unicode_and_whitespace_normalization(self) -> None:
        result = _audit(
            [
                {"text": "  \u0420\u0435\u0436\u0438\u043c\u00a0turbo \uff11  "},
                {"text": "\u0440\u0435\u0436\u0438\u043c turbo 1"},
            ]
        )

        self.assertFalse(result["passed"])
        self.assertEqual(
            {"\u0440\u0435\u0436\u0438\u043c turbo 1": 2},
            result["frequencies"]["duplicate_exact_text"],
        )

    def test_shared_closing_block_over_share_fails(self) -> None:
        result = _audit(
            [
                {"text": "Первый маршрут открыт. Дальше идём спокойно."},
                {"text": "Вторая сцена готова. Дальше идём спокойно."},
            ]
        )

        self.assertFalse(result["passed"])
        self.assertEqual(
            2,
            result["violations"]["closing_block"]["дальше идём спокойно"],
        )
    def test_source_provenance_is_included_when_supplied(self) -> None:
        digest = "a" * 64
        result = _audit(
            [{"record_id": "v4-b01-001", "text": "One distinct line."}],
            source_records_sha256=digest,
            source_record_id_set_sha256="b" * 64,
        )

        self.assertEqual(4, result["corpus_repetition_audit_schema_version"])
        self.assertEqual(digest, result["source_records_sha256"])
        self.assertEqual("b" * 64, result["source_record_id_set_sha256"])

    def test_partial_source_provenance_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "source provenance"):
            _audit(
                [{"text": "One distinct line."}],
                source_records_sha256="a" * 64,
            )


if __name__ == "__main__":
    unittest.main()
