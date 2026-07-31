"""Materialize approved final targeted-review repairs into a new corpus candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    from scripts.audit_corpus_repetition import _record_id_set_sha256
    from scripts.prepare_corpus_v4_quality_overlay import _validate_word_range
except ModuleNotFoundError:
    from audit_corpus_repetition import _record_id_set_sha256
    from prepare_corpus_v4_quality_overlay import _validate_word_range

_SCHEMA_VERSION = 1
_FORM_SCHEMA_VERSION = 1
_REQUIRED_FORM_FIELDS = {
    "targeted_final_repair_authoring_schema_version",
    "authoring_status",
    "author_id",
    "authoring_notes",
    "candidate_sha256",
    "final_review_sha256",
    "final_review_summary_sha256",
    "record_id",
    "language_class",
    "target",
    "current_text",
    "current_text_sha256",
    "failure_fields",
    "review_notes",
    "proposed_replacement_text",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-candidate", type=Path, required=True)
    parser.add_argument("--repair-authoring", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.report.exists():
        parser.error("--output and --report must not already exist")

    base_bytes = args.base_candidate.read_bytes()
    authoring_bytes = args.repair_authoring.read_bytes()
    base = _load_jsonl(base_bytes, "base candidate")
    authoring = _load_jsonl(authoring_bytes, "repair authoring")
    records, report = _materialize(base, authoring, base_bytes, authoring_bytes)
    output_bytes = _jsonl_bytes(records)
    report["output_sha256"] = hashlib.sha256(output_bytes).hexdigest()
    report["output_record_id_set_sha256"] = _record_id_set_sha256(records)
    _write_bytes(args.output, output_bytes)
    _write_object(args.report, report)
    print(json.dumps(report, sort_keys=True))
    return 0


def _materialize(
    base: list[dict[str, Any]],
    authoring: list[dict[str, Any]],
    base_bytes: bytes,
    authoring_bytes: bytes,
) -> tuple[list[dict[str, Any]], dict[str, object]]:
    base_by_id = _by_id(base, "base candidate")
    authoring_by_id = _by_id(authoring, "repair authoring")
    if not authoring_by_id:
        raise RuntimeError("repair authoring contains no rows")

    base_sha256 = hashlib.sha256(base_bytes).hexdigest()
    replacements: dict[str, str] = {}
    for record_id, row in authoring_by_id.items():
        _validate_authoring_row(row, base_by_id.get(record_id), base_sha256)
        replacements[record_id] = row["proposed_replacement_text"]

    records = []
    for base_row in base:
        record = dict(base_row)
        replacement = replacements.get(record["record_id"])
        if replacement is not None:
            record["text"] = replacement
        records.append(record)

    return records, {
        "corpus_v4_final_targeted_repair_materialization_schema_version": _SCHEMA_VERSION,
        "base_candidate_sha256": base_sha256,
        "base_candidate_record_id_set_sha256": _record_id_set_sha256(base),
        "repair_authoring_sha256": hashlib.sha256(authoring_bytes).hexdigest(),
        "repair_record_count": len(replacements),
        "record_count": len(records),
    }


def _validate_authoring_row(
    row: dict[str, Any], base: dict[str, Any] | None, base_sha256: str
) -> None:
    if set(row) != _REQUIRED_FORM_FIELDS:
        raise RuntimeError(f"{row.get('record_id')}: repair authoring schema changed")
    record_id = row["record_id"]
    if not isinstance(record_id, str) or base is None:
        raise RuntimeError(f"{record_id}: missing from base candidate")
    if row["targeted_final_repair_authoring_schema_version"] != _FORM_SCHEMA_VERSION:
        raise RuntimeError(f"{record_id}: unsupported repair authoring schema")
    if row["authoring_status"] != "completed_human_authoring":
        raise RuntimeError(f"{record_id}: human authoring is incomplete")
    for field in ("author_id", "authoring_notes", "review_notes", "proposed_replacement_text"):
        if not isinstance(row[field], str) or not row[field].strip():
            raise RuntimeError(f"{record_id}: {field} is required")
    if row["candidate_sha256"] != base_sha256:
        raise RuntimeError(f"{record_id}: base candidate SHA mismatch")
    if row["language_class"] != base.get("language_class"):
        raise RuntimeError(f"{record_id}: language class changed")
    target = {
        field: base.get(field)
        for field in ("category", "scene_context", "speech_intent")
    }
    if row["target"] != target:
        raise RuntimeError(f"{record_id}: target metadata changed")
    if row["current_text"] != base.get("text"):
        raise RuntimeError(f"{record_id}: current text no longer matches base candidate")
    if row["current_text_sha256"] != hashlib.sha256(base["text"].encode("utf-8")).hexdigest():
        raise RuntimeError(f"{record_id}: current text SHA mismatch")
    failures = row["failure_fields"]
    if not isinstance(failures, list) or not failures or not all(isinstance(value, str) for value in failures):
        raise RuntimeError(f"{record_id}: failure fields are invalid")
    _validate_word_range(base, row["proposed_replacement_text"])


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


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    ).encode("utf-8")


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _write_object(path: Path, value: dict[str, object]) -> None:
    _write_bytes(
        path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )


if __name__ == "__main__":
    raise SystemExit(main())
