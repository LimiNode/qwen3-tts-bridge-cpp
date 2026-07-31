"""Build and gate a human-adjudicated corpus-v4 AI-pre-review revision."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from scripts.audit_corpus_repetition import _audit, _record_id_set_sha256
    from scripts.validate_corpus_v4_batches import _validate
except ModuleNotFoundError:
    from audit_corpus_repetition import _audit, _record_id_set_sha256
    from validate_corpus_v4_batches import _validate

_BATCH_IDS = tuple(f"v4-b{index:02d}" for index in range(1, 11))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _add_builder_arguments(parser)
    parser.add_argument("--corpus-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("--output-dir must not already exist")
    args.output_dir.mkdir(parents=True)
    candidate_path = args.output_dir / "candidate.jsonl"
    materialization_report_path = args.output_dir / "materialization-report.json"
    _run_builder(args, candidate_path, materialization_report_path)
    records = _load_records(candidate_path)
    batch_paths = _write_batches(args.output_dir / "candidate-batches", records)
    validation = _validate(batch_paths, len(_BATCH_IDS))
    repetition = _audit(
        records,
        source_records_sha256=_sha256(candidate_path.read_bytes()),
        source_record_id_set_sha256=_record_id_set_sha256(records),
        corpus_id=args.corpus_id,
    )
    _write_object(args.output_dir / "full-batch-validation.json", validation)
    _write_object(args.output_dir / "repetition-audit.json", repetition)
    materialization = _load_object(materialization_report_path)
    acceptance = _acceptance_report(materialization, validation, repetition)
    acceptance["materialization_report_sha256"] = _sha256(
        materialization_report_path.read_bytes()
    )
    acceptance["full_batch_validation_sha256"] = _sha256(
        (args.output_dir / "full-batch-validation.json").read_bytes()
    )
    acceptance["repetition_audit_sha256"] = _sha256(
        (args.output_dir / "repetition-audit.json").read_bytes()
    )
    _write_object(args.output_dir / "acceptance-report.json", acceptance)
    print(json.dumps(acceptance, sort_keys=True))
    return 0 if acceptance["acceptance_pass"] else 1


def _add_builder_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-candidate", type=Path, required=True)
    parser.add_argument("--triage-manifest", type=Path, required=True)
    parser.add_argument("--targeted-review-form", type=Path, required=True)
    parser.add_argument("--targeted-ai-prereview", type=Path, required=True)
    parser.add_argument("--general-review-form", type=Path, required=True)
    parser.add_argument("--general-ai-prereview", type=Path, required=True)
    parser.add_argument("--ai-review-provenance", type=Path, required=True)
    parser.add_argument("--targeted-adjudication", type=Path, required=True)
    parser.add_argument("--general-adjudication", type=Path, required=True)


def _run_builder(
    args: argparse.Namespace, candidate_path: Path, report_path: Path
) -> None:
    builder = Path(__file__).with_name("build_corpus_v4_ai_prereview_revision.py")
    command = [sys.executable, str(builder)]
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
    ):
        command.extend((f"--{name.replace('_', '-')}", str(getattr(args, name))))
    command.extend(("--output", str(candidate_path), "--report", str(report_path)))
    subprocess.run(command, check=True)


def _write_batches(directory: Path, records: list[dict[str, Any]]) -> list[Path]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        batch_id = record.get("batch_id")
        if not isinstance(batch_id, str):
            raise RuntimeError("materialized record has an invalid batch_id")
        grouped[batch_id].append(record)
    if set(grouped) != set(_BATCH_IDS):
        raise RuntimeError("materialized corpus does not contain the expected batches")
    paths = []
    for batch_id in _BATCH_IDS:
        path = directory / f"{batch_id}.jsonl"
        _write_jsonl(path, grouped[batch_id])
        paths.append(path)
    return paths


def _acceptance_report(
    materialization: dict[str, Any],
    validation: dict[str, Any],
    repetition: dict[str, Any],
) -> dict[str, object]:
    materialization_pass = materialization.get("record_count") == 2000
    corpus_validation_pass = validation.get("passed") is True
    repetition_pass = repetition.get("passed") is True
    return {
        "corpus_v4_human_adjudication_acceptance_schema_version": 1,
        "materialization_pass": materialization_pass,
        "corpus_validation_pass": corpus_validation_pass,
        "repetition_pass": repetition_pass,
        "acceptance_pass": (
            materialization_pass and corpus_validation_pass and repetition_pass
        ),
    }


def _load_records(path: Path) -> list[dict[str, Any]]:
    return _load_jsonl(path.read_bytes(), "materialized candidate")


def _load_jsonl(value: bytes, name: str) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(value.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise RuntimeError(f"{name} line {line_number} is not an object")
        rows.append(row)
    if not rows:
        raise RuntimeError(f"{name} contains no records")
    return rows


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} is not an object")
    return value


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded_rows = (
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    path.write_text(
        "".join(encoded_rows),
        encoding="utf-8",
        newline="",
    )


def _write_object(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
