"""Tests for corpus-v4 human-adjudication acceptance gates."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import scripts.accept_corpus_v4_ai_prereview_revision as acceptance
from scripts.audit_corpus_repetition import _audit

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CANDIDATE_ROOT = (
    _REPOSITORY_ROOT
    / "docs"
    / "benchmark-artifacts"
    / "rtx4090-2026-07-30"
    / "representative-v4-r1-candidate"
)


class AcceptCorpusV4AiPrereviewRevisionTests(unittest.TestCase):
    def test_accepts_only_when_all_gates_pass(self) -> None:
        report = acceptance._acceptance_report(
            _materialization_report(),
            {"passed": True, "corpus_v4_batch_validation_schema_version": 1},
            {"passed": True, "corpus_repetition_audit_schema_version": 4},
            _provenance(),
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
        report = acceptance._acceptance_report(
            _materialization_report(),
            {"passed": True, "corpus_v4_batch_validation_schema_version": 1},
            repetition,
            _provenance(),
        )

        self.assertFalse(repetition["passed"])
        self.assertFalse(report["repetition_pass"])
        self.assertFalse(report["acceptance_pass"])

    def test_cli_publishes_only_after_full_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            args = _prepare_arguments(temporary)

            self.assertEqual(0, _run_main(args))

            output_dir = args.output_dir
            self.assertTrue(output_dir.is_dir())
            self.assertFalse(list(temporary.glob("candidate.pending-*")))
            self.assertFalse(list(temporary.glob("candidate.rejected-*")))
            report = _load_object(output_dir / "acceptance-report.json")
            self.assertTrue(report["acceptance_pass"])
            self.assertEqual(
                2,
                report["corpus_v4_human_adjudication_acceptance_schema_version"],
            )
            self.assertEqual(
                _sha256((output_dir / "candidate.jsonl").read_bytes()),
                report["candidate_sha256"],
            )

    def test_rejects_modified_candidate_or_materialization_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            args = _prepare_arguments(temporary)
            self.assertEqual(0, _run_main(args))
            candidate_path = args.output_dir / "candidate.jsonl"
            report_path = args.output_dir / "materialization-report.json"
            candidate_bytes = candidate_path.read_bytes()
            records = acceptance._load_records(candidate_path)
            report = _load_object(report_path)

            report["output_sha256"] = "0" * 64
            with self.assertRaisesRegex(RuntimeError, "output_sha256 does not match"):
                acceptance._verify_materialization_report(
                    report, args, candidate_bytes, records
                )

            report = _load_object(report_path)
            mutated_records = [dict(record) for record in records]
            mutated_records[0]["text"] = f"{mutated_records[0]['text']} again"
            mutated_bytes = _jsonl_bytes(mutated_records)
            with self.assertRaisesRegex(RuntimeError, "output_sha256 does not match"):
                acceptance._verify_materialization_report(
                    report,
                    args,
                    mutated_bytes,
                    mutated_records,
                )

    def test_cli_preserves_rejected_output_when_repetition_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            args = _prepare_arguments(temporary)
            repetition = {
                "corpus_repetition_audit_schema_version": 4,
                "passed": False,
            }

            with patch.object(acceptance, "_audit", return_value=repetition):
                self.assertEqual(1, _run_main(args))

            self.assertFalse(args.output_dir.exists())
            rejected = list(temporary.glob("candidate.rejected-*"))
            self.assertEqual(1, len(rejected))
            report = _load_object(rejected[0] / "acceptance-report.json")
            self.assertFalse(report["repetition_pass"])
            self.assertFalse(report["acceptance_pass"])

    def test_cli_preserves_rejection_when_builder_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            args = _prepare_arguments(temporary)

            with patch.object(
                acceptance,
                "_run_builder",
                side_effect=RuntimeError("test builder failure"),
            ):
                self.assertEqual(1, _run_main(args))

            self.assertFalse(args.output_dir.exists())
            rejected = list(temporary.glob("candidate.rejected-*"))
            self.assertEqual(1, len(rejected))
            report = _load_object(rejected[0] / "rejection-report.json")
            self.assertEqual("RuntimeError", report["error_type"])


def _prepare_arguments(temporary: Path) -> argparse.Namespace:
    authoring_directory = temporary / "authoring"
    authoring_directory.mkdir()
    _write_completed_adjudications(
        _CANDIDATE_ROOT / "ai-prereview" / "targeted-human-adjudication-52.jsonl",
        _CANDIDATE_ROOT
        / "ai-prereview"
        / "targeted-repair-authoring-52.ai-draft.jsonl",
        authoring_directory / "targeted.jsonl",
        "record_id",
    )
    _write_completed_adjudications(
        _CANDIDATE_ROOT / "ai-prereview" / "general-human-adjudication-12.jsonl",
        _CANDIDATE_ROOT / "ai-prereview" / "general-repair-authoring-12.ai-draft.jsonl",
        authoring_directory / "general.jsonl",
        "label",
    )
    return argparse.Namespace(
        base_candidate=_CANDIDATE_ROOT / "candidate.jsonl",
        triage_manifest=_CANDIDATE_ROOT
        / "ai-prereview"
        / "ai-prereview-triage-v2.json",
        targeted_review_form=_CANDIDATE_ROOT / "targeted-review-98.jsonl",
        targeted_ai_prereview=_CANDIDATE_ROOT
        / "ai-prereview"
        / "targeted-review-98.ai-prereview.jsonl",
        general_review_form=_CANDIDATE_ROOT / "manual-review-form-100.jsonl",
        general_ai_prereview=_CANDIDATE_ROOT
        / "ai-prereview"
        / "manual-review-form-100.ai-prereview.jsonl",
        ai_review_provenance=_CANDIDATE_ROOT
        / "ai-prereview"
        / "ai-review-provenance.json",
        targeted_adjudication=authoring_directory / "targeted.jsonl",
        general_adjudication=authoring_directory / "general.jsonl",
        corpus_id="synthetic-integration-test-not-human",
        output_dir=temporary / "candidate",
    )


def _write_completed_adjudications(
    form_path: Path,
    draft_path: Path,
    output_path: Path,
    id_field: str,
) -> None:
    drafts = {
        row[id_field]: row["proposed_replacement_text"]
        for row in _load_jsonl(draft_path)
    }
    rows = _load_jsonl(form_path)
    for row in rows:
        row["authoring_status"] = "completed_human_adjudication"
        row["authoring_decision"] = "replace"
        row["author_id"] = "synthetic-integration-test-not-human"
        row["decision_notes"] = "Synthetic integration test only; not human review."
        row["proposed_replacement_text"] = drafts[row[id_field]]
    output_path.write_bytes(_jsonl_bytes(rows))


def _run_main(args: argparse.Namespace) -> int:
    command = ["accept_corpus_v4_ai_prereview_revision.py"]
    for name in (
        "base_candidate",
        "triage_manifest",
        "targeted_review_form",
        "targeted_ai_prereview",
        "general_review_form",
        "general_ai_prereview",
        "ai_review_provenance",
        "targeted_adjudication",
        "general_adjudication",
        "corpus_id",
        "output_dir",
    ):
        command.extend((f"--{name.replace('_', '-')}", str(getattr(args, name))))
    with patch.object(sys, "argv", command):
        with contextlib.redirect_stdout(io.StringIO()):
            return acceptance.main()


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _jsonl_bytes(rows: list[dict[str, object]]) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _materialization_report() -> dict[str, object]:
    return {"corpus_v4_human_adjudication_revision_schema_version": 1}


def _provenance() -> dict[str, str]:
    return {
        "corpus_id": "test",
        "candidate_sha256": "a" * 64,
        "candidate_record_id_set_sha256": "b" * 64,
        "base_candidate_sha256": "c" * 64,
        "base_candidate_record_id_set_sha256": "d" * 64,
        "triage_manifest_sha256": "e" * 64,
        "targeted_review_form_sha256": "f" * 64,
        "targeted_ai_prereview_sha256": "0" * 64,
        "general_review_form_sha256": "1" * 64,
        "general_ai_prereview_sha256": "2" * 64,
        "ai_review_provenance_sha256": "3" * 64,
        "targeted_adjudication_sha256": "4" * 64,
        "general_adjudication_sha256": "5" * 64,
    }


if __name__ == "__main__":
    unittest.main()
