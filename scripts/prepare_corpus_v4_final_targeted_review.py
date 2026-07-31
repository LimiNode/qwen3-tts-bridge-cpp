"""Prepare a final-text human-review form for an accepted corpus-v4 revision."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    from scripts.prepare_corpus_v4_targeted_review import _SCORES
except ModuleNotFoundError:
    from prepare_corpus_v4_targeted_review import _SCORES

_SCHEMA_VERSION = 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targeted-form", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must not already exist")

    rows = _prepare_rows(args.targeted_form.read_bytes(), args.candidate.read_bytes())
    _write_jsonl(args.output, rows)
    print(
        json.dumps(
            {
                "review_record_count": len(rows),
                "review_status": "pending_human_review",
                "candidate_sha256": hashlib.sha256(args.candidate.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


def _prepare_rows(targeted_form_bytes: bytes, candidate_bytes: bytes) -> list[dict[str, object]]:
    targeted_rows = _load_jsonl(targeted_form_bytes, "targeted form")
    candidate_rows = _load_jsonl(candidate_bytes, "candidate")
    candidate_by_id = _by_id(candidate_rows, "candidate")
    targeted_by_id = _by_id(targeted_rows, "targeted form")
    targeted_sha256 = hashlib.sha256(targeted_form_bytes).hexdigest()
    candidate_sha256 = hashlib.sha256(candidate_bytes).hexdigest()

    rows = []
    for record_id in sorted(targeted_by_id):
        targeted = targeted_by_id[record_id]
        candidate = candidate_by_id.get(record_id)
        if candidate is None:
            raise RuntimeError(f"{record_id}: missing from candidate")
        text = candidate.get("text")
        if not isinstance(text, str) or not text:
            raise RuntimeError(f"{record_id}: candidate text is invalid")
        rows.append(
            {
                "final_targeted_review_schema_version": _SCHEMA_VERSION,
                "review_scope": "finalized_corpus_v4_targeted_replacements",
                "review_status": "pending_human_review",
                "reviewer_id": "",
                "targeted_form_sha256": targeted_sha256,
                "candidate_sha256": candidate_sha256,
                "record_id": record_id,
                "language_class": targeted["language_class"],
                "repair_reasons": targeted["repair_reasons"],
                "source": targeted["source"],
                "target": targeted["target"],
                "final_text": text,
                "final_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                **{score: None for score in _SCORES},
                "notes": "",
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
        raise RuntimeError(f"{name} contains no records")
    return rows


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
