"""Prepare a human-authoring form for failed post-repair corpus-v4 review rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--review-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must not already exist")

    rows = _prepare_rows(
        args.candidate.read_bytes(), args.review.read_bytes(), args.review_summary.read_bytes()
    )
    _write_jsonl(args.output, rows)
    print(json.dumps({"repair_record_count": len(rows)}, sort_keys=True))
    return 0


def _prepare_rows(
    candidate_bytes: bytes, review_bytes: bytes, summary_bytes: bytes
) -> list[dict[str, object]]:
    candidate_rows = _load_jsonl(candidate_bytes, "candidate")
    review_rows = _load_jsonl(review_bytes, "review")
    summary = _load_object(summary_bytes, "review summary")
    candidate_by_id = _by_id(candidate_rows, "candidate")
    review_by_id = _by_id(review_rows, "review")
    failures = summary.get("record_failures")
    if not isinstance(failures, dict) or not failures:
        raise RuntimeError("review summary has no record failures")

    candidate_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
    review_sha256 = hashlib.sha256(review_bytes).hexdigest()
    summary_sha256 = hashlib.sha256(summary_bytes).hexdigest()
    rows = []
    for record_id in sorted(failures):
        record = candidate_by_id.get(record_id)
        review = review_by_id.get(record_id)
        failure_fields = failures[record_id]
        if record is None or review is None:
            raise RuntimeError(f"{record_id}: missing from candidate or review")
        if not isinstance(failure_fields, list) or not failure_fields:
            raise RuntimeError(f"{record_id}: failure fields are invalid")
        review_notes = review.get("notes")
        if not isinstance(review_notes, str) or not review_notes.strip():
            raise RuntimeError(f"{record_id}: review notes are missing")
        rows.append(
            {
                "targeted_final_repair_authoring_schema_version": _SCHEMA_VERSION,
                "authoring_status": "pending_human_authoring",
                "author_id": "",
                "authoring_notes": "",
                "candidate_sha256": candidate_sha256,
                "final_review_sha256": review_sha256,
                "final_review_summary_sha256": summary_sha256,
                "record_id": record_id,
                "language_class": record["language_class"],
                "target": {
                    field: record[field]
                    for field in ("category", "scene_context", "speech_intent")
                },
                "current_text": record["text"],
                "current_text_sha256": hashlib.sha256(record["text"].encode("utf-8")).hexdigest(),
                "failure_fields": failure_fields,
                "review_notes": review_notes,
                "proposed_replacement_text": "",
            }
        )
    return rows


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
        raise RuntimeError(f"{name} contains no rows")
    return rows


def _load_object(value: bytes, name: str) -> dict[str, Any]:
    result = json.loads(value.decode("utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError(f"{name} is not an object")
    return result


def _by_id(rows: list[dict[str, Any]], name: str) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        record_id = row.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise RuntimeError(f"{name} has an invalid record ID")
        if record_id in result:
            raise RuntimeError(f"{name} has duplicate record ID: {record_id}")
        result[record_id] = row
    return result


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
