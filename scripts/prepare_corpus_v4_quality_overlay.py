"""Prepare a text-only quality overlay from an AI pre-review proposal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    from scripts.audit_corpus_repetition import normalize_exact_text
    from scripts.validate_corpus_v4_batches import _WORD_RANGES, _WORD_RE
except ModuleNotFoundError:
    from audit_corpus_repetition import normalize_exact_text
    from validate_corpus_v4_batches import _WORD_RANGES, _WORD_RE

_SCHEMA_VERSION = 1
_RECORD_FIELDS = {
    "batch_id",
    "record_id",
    "text",
    "language_class",
    "category",
    "scene_context",
    "speech_intent",
    "intended_length_class",
    "template_family_id",
    "semantic_intent_id",
    "key_phrase_id",
}
_PRESERVE_FIELDS = _RECORD_FIELDS - {"text"}
_OVERLAY_FIELDS = {
    "quality_repair_overlay_schema_version",
    "corpus_id",
    "base_records_sha256",
    "frozen_review_form_sha256",
    "corrected_review_form_sha256",
    "ai_prereview_sha256",
    "record_id",
    "preserve",
    "source_text_sha256",
    "replacement_text",
    "replacement_text_sha256",
    "reason",
}
_REVIEW_IDENTITY_FIELDS = (
    "label",
    "category",
    "language_class",
    "intended_length_class",
    "source_sample_sha256",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-records", type=Path, required=True)
    parser.add_argument("--frozen-review-form", type=Path, required=True)
    parser.add_argument("--corrected-review-form", type=Path, required=True)
    parser.add_argument("--ai-prereview", type=Path, required=True)
    parser.add_argument("--exclude-repair-set", type=Path, required=True)
    parser.add_argument("--corpus-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base_bytes = args.base_records.read_bytes()
    frozen_bytes = args.frozen_review_form.read_bytes()
    corrected_bytes = args.corrected_review_form.read_bytes()
    ai_prereview_bytes = args.ai_prereview.read_bytes()
    rows = _prepare_overlay(
        _load_jsonl(base_bytes, "base records"),
        _load_jsonl(frozen_bytes, "frozen review form"),
        _load_jsonl(corrected_bytes, "corrected review form"),
        _load_jsonl(ai_prereview_bytes, "AI pre-review"),
        _load_object(args.exclude_repair_set.read_bytes(), "repair set"),
        corpus_id=args.corpus_id,
        base_records_sha256=hashlib.sha256(base_bytes).hexdigest(),
        frozen_review_form_sha256=hashlib.sha256(frozen_bytes).hexdigest(),
        corrected_review_form_sha256=hashlib.sha256(corrected_bytes).hexdigest(),
        ai_prereview_sha256=hashlib.sha256(ai_prereview_bytes).hexdigest(),
    )
    _write_jsonl(args.output, rows)
    print(
        json.dumps(
            {
                "overlay_record_count": len(rows),
                "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


def _prepare_overlay(
    base_records: list[dict[str, Any]],
    frozen_review: list[dict[str, Any]],
    corrected_review: list[dict[str, Any]],
    ai_prereview: list[dict[str, Any]],
    repair_set: dict[str, Any],
    *,
    corpus_id: str,
    base_records_sha256: str,
    frozen_review_form_sha256: str,
    corrected_review_form_sha256: str,
    ai_prereview_sha256: str,
) -> list[dict[str, object]]:
    base_by_id = _records_by_id(base_records)
    frozen_by_id = _review_by_id(frozen_review, "frozen review form")
    corrected_by_id = _review_by_id(corrected_review, "corrected review form")
    ai_by_id = _review_by_id(ai_prereview, "AI pre-review")
    if set(frozen_by_id) != set(corrected_by_id):
        raise RuntimeError("corrected review labels do not match the frozen form")
    if set(frozen_by_id) != set(ai_by_id):
        raise RuntimeError("AI pre-review labels do not match the frozen form")
    repair_ids = _repair_record_ids(repair_set)
    rows = []
    for record_id in sorted(frozen_by_id):
        frozen = frozen_by_id[record_id]
        corrected = corrected_by_id[record_id]
        _validate_review_identity(frozen, corrected, record_id)
        if corrected["text"] == frozen["text"]:
            continue
        _validate_ai_prereview(frozen, ai_by_id[record_id], record_id)
        if record_id in repair_ids:
            continue
        base = base_by_id.get(record_id)
        if base is None:
            raise RuntimeError(f"review label is absent from base records: {record_id}")
        if base["text"] != frozen["text"]:
            raise RuntimeError(f"{record_id}: base text does not match frozen review")
        if any(base[field] != frozen[field] for field in _REVIEW_IDENTITY_FIELDS[1:4]):
            raise RuntimeError(f"{record_id}: base metadata does not match frozen review")
        replacement = corrected["text"]
        if not isinstance(replacement, str) or not replacement.strip():
            raise RuntimeError(f"{record_id}: corrected text is invalid")
        if normalize_exact_text(replacement) == normalize_exact_text(str(base["text"])):
            raise RuntimeError(f"{record_id}: corrected text does not change base")
        _validate_word_range(base, replacement)
        rows.append(
            {
                "quality_repair_overlay_schema_version": _SCHEMA_VERSION,
                "corpus_id": corpus_id,
                "base_records_sha256": base_records_sha256,
                "frozen_review_form_sha256": frozen_review_form_sha256,
                "corrected_review_form_sha256": corrected_review_form_sha256,
                "ai_prereview_sha256": ai_prereview_sha256,
                "record_id": record_id,
                "preserve": {field: base[field] for field in sorted(_PRESERVE_FIELDS)},
                "source_text_sha256": _text_sha256(str(base["text"])),
                "replacement_text": replacement,
                "replacement_text_sha256": _text_sha256(replacement),
                "reason": "ai_prereview_general_revision",
            }
        )
    _validate_unique_replacements(rows, base_by_id)
    if not rows:
        raise RuntimeError("corrected review has no new quality repairs")
    return rows


def _validate_review_identity(
    frozen: dict[str, Any], corrected: dict[str, Any], record_id: str
) -> None:
    if any(frozen.get(field) != corrected.get(field) for field in _REVIEW_IDENTITY_FIELDS):
        raise RuntimeError(f"{record_id}: corrected review identity drifted")


def _validate_ai_prereview(
    frozen: dict[str, Any], ai_prereview: dict[str, Any], record_id: str
) -> None:
    if any(frozen.get(field) != ai_prereview.get(field) for field in _REVIEW_IDENTITY_FIELDS):
        raise RuntimeError(f"{record_id}: AI pre-review identity drifted")
    if ai_prereview.get("review_status") != "ai_prereview_complete_not_human_gate":
        raise RuntimeError(f"{record_id}: AI pre-review status is invalid")


def _validate_word_range(record: dict[str, Any], text: str) -> None:
    length_class = record.get("intended_length_class")
    word_range = _WORD_RANGES.get(length_class)
    word_count = len(_WORD_RE.findall(text))
    if word_range is None or word_count not in range(word_range[0], word_range[1] + 1):
        raise RuntimeError(f"{record['record_id']}: corrected text length is invalid")


def _validate_unique_replacements(
    rows: list[dict[str, object]], base_by_id: dict[str, dict[str, Any]]
) -> None:
    replacement_ids = {str(row["record_id"]) for row in rows}
    unchanged = {
        normalize_exact_text(str(record["text"])): record_id
        for record_id, record in base_by_id.items()
        if record_id not in replacement_ids
    }
    seen: dict[str, str] = {}
    for row in rows:
        text = normalize_exact_text(str(row["replacement_text"]))
        record_id = str(row["record_id"])
        if text in unchanged:
            raise RuntimeError(
                f"{record_id}: replacement collides with unchanged base "
                f"record {unchanged[text]}"
            )
        if text in seen:
            raise RuntimeError(f"{record_id}: replacement duplicates {seen[text]}")
        seen[text] = record_id


def _records_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        if set(row) != _RECORD_FIELDS:
            raise RuntimeError("base records have an invalid schema")
        record_id = row.get("record_id")
        if not isinstance(record_id, str) or record_id in result:
            raise RuntimeError("base records have duplicate or invalid record IDs")
        result[record_id] = row
    return result


def _review_by_id(rows: list[dict[str, Any]], name: str) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        record_id = row.get("label")
        if not isinstance(record_id, str) or record_id in result:
            raise RuntimeError(f"{name} has duplicate or invalid labels")
        result[record_id] = row
    return result


def _repair_record_ids(repair_set: dict[str, Any]) -> set[str]:
    records = repair_set.get("records")
    if not isinstance(records, list):
        raise RuntimeError("repair set records are invalid")
    result = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("record_id"), str):
            raise RuntimeError("repair set has an invalid record")
        result.add(record["record_id"])
    return result


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


def _load_object(value: bytes, name: str) -> dict[str, Any]:
    result = json.loads(value)
    if not isinstance(result, dict):
        raise RuntimeError(f"{name} is not an object")
    return result


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
