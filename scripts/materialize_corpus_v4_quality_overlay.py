"""Apply a fail-closed text-only corpus-v4 quality overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    from scripts.audit_corpus_repetition import _record_id_set_sha256, normalize_exact_text
    from scripts.prepare_corpus_v4_quality_overlay import (
        _OVERLAY_FIELDS,
        _PRESERVE_FIELDS,
        _RECORD_FIELDS,
        _SCHEMA_VERSION,
        _text_sha256,
        _validate_word_range,
    )
except ModuleNotFoundError:
    from audit_corpus_repetition import _record_id_set_sha256, normalize_exact_text
    from prepare_corpus_v4_quality_overlay import (
        _OVERLAY_FIELDS,
        _PRESERVE_FIELDS,
        _RECORD_FIELDS,
        _SCHEMA_VERSION,
        _text_sha256,
        _validate_word_range,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-records", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    base_bytes = args.base_records.read_bytes()
    overlay_bytes = args.overlay.read_bytes()
    output = _materialize(_load_records(base_bytes), _load_rows(overlay_bytes), base_bytes)
    _write_jsonl(args.output, output)
    report = {
        "corpus_v4_quality_overlay_materialization_schema_version": 1,
        "base_records_sha256": hashlib.sha256(base_bytes).hexdigest(),
        "base_record_id_set_sha256": _record_id_set_sha256(_load_records(base_bytes)),
        "quality_overlay_sha256": hashlib.sha256(overlay_bytes).hexdigest(),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "record_count": len(output),
        "replacement_record_count": len(_load_rows(overlay_bytes)),
    }
    _write_object(args.report, report)
    print(json.dumps(report, sort_keys=True))
    return 0


def _materialize(
    base_records: list[dict[str, Any]], overlay: list[dict[str, Any]], base_bytes: bytes
) -> list[dict[str, Any]]:
    base_by_id = _records_by_id(base_records)
    base_sha256 = hashlib.sha256(base_bytes).hexdigest()
    overlay_by_id = _overlay_by_id(overlay, base_by_id, base_sha256)
    replacements = {
        record_id: str(row["replacement_text"])
        for record_id, row in overlay_by_id.items()
    }
    _validate_final_texts(base_by_id, replacements)
    return [
        {**record, "text": replacements.get(str(record["record_id"]), record["text"])}
        for record in base_records
    ]


def _overlay_by_id(
    overlay: list[dict[str, Any]],
    base_by_id: dict[str, dict[str, Any]],
    base_sha256: str,
) -> dict[str, dict[str, Any]]:
    result = {}
    for row in overlay:
        if set(row) != _OVERLAY_FIELDS:
            raise RuntimeError("quality overlay row schema is invalid")
        record_id = row.get("record_id")
        if not isinstance(record_id, str) or record_id in result:
            raise RuntimeError("quality overlay has duplicate or invalid record IDs")
        if row.get("quality_repair_overlay_schema_version") != _SCHEMA_VERSION:
            raise RuntimeError(f"{record_id}: quality overlay schema is unsupported")
        if row.get("base_records_sha256") != base_sha256:
            raise RuntimeError(f"{record_id}: base records SHA does not match")
        base = base_by_id.get(record_id)
        if base is None:
            raise RuntimeError(f"quality overlay references unknown record ID: {record_id}")
        if row.get("preserve") != {field: base[field] for field in sorted(_PRESERVE_FIELDS)}:
            raise RuntimeError(f"{record_id}: preserved metadata drifted")
        if row.get("source_text_sha256") != _text_sha256(str(base["text"])):
            raise RuntimeError(f"{record_id}: source text SHA does not match")
        replacement = row.get("replacement_text")
        if not isinstance(replacement, str) or not replacement.strip():
            raise RuntimeError(f"{record_id}: replacement text is invalid")
        if row.get("replacement_text_sha256") != _text_sha256(replacement):
            raise RuntimeError(f"{record_id}: replacement text SHA does not match")
        if normalize_exact_text(replacement) == normalize_exact_text(str(base["text"])):
            raise RuntimeError(f"{record_id}: replacement text does not change base")
        _validate_word_range(base, replacement)
        result[record_id] = row
    if not result:
        raise RuntimeError("quality overlay contains no records")
    _validate_overlay_provenance(overlay)
    return result


def _validate_overlay_provenance(overlay: list[dict[str, Any]]) -> None:
    for field in (
        "corpus_id",
        "base_records_sha256",
        "frozen_review_form_sha256",
        "corrected_review_form_sha256",
        "ai_prereview_sha256",
    ):
        values = {row.get(field) for row in overlay}
        if len(values) != 1 or not isinstance(next(iter(values)), str) or not next(iter(values)):
            raise RuntimeError(f"quality overlay provenance is inconsistent: {field}")


def _validate_final_texts(
    base_by_id: dict[str, dict[str, Any]], replacements: dict[str, str]
) -> None:
    seen: dict[str, str] = {}
    for record_id, record in base_by_id.items():
        text = replacements.get(record_id, str(record["text"]))
        canonical = normalize_exact_text(text)
        if canonical in seen:
            raise RuntimeError(f"{record_id}: final text duplicates {seen[canonical]}")
        seen[canonical] = record_id


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


def _load_records(value: bytes) -> list[dict[str, Any]]:
    return _load_rows(value)


def _load_rows(value: bytes) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(value.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise RuntimeError(f"input line {line_number} is not an object")
        rows.append(row)
    if not rows:
        raise RuntimeError("input contains no records")
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_text(
        path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
    )


def _write_object(path: Path, value: dict[str, object]) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
