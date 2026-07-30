"""Materialize a reproducible corpus-v4 JSONL from immutable records and an overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from scripts.build_corpus_v4_repair_set import _record_sha256
except ModuleNotFoundError:
    from build_corpus_v4_repair_set import _record_sha256

_REPLACEMENT_FIELDS = {
    "text",
    "template_family_id",
    "semantic_intent_id",
    "key_phrase_id",
}
_TARGET_FIELDS = {"category", "scene_context", "speech_intent"}
_PRESERVED_FIELDS = {
    "batch_id",
    "record_id",
    "language_class",
    "intended_length_class",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--repair-set", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    records_bytes = args.records.read_bytes()
    repair_set_bytes = args.repair_set.read_bytes()
    overlay_bytes = args.overlay.read_bytes()
    records = _load_records_bytes(records_bytes)
    repair_set = _load_object_bytes(repair_set_bytes, "repair set")
    overlay = _load_object_bytes(overlay_bytes, "overlay")
    materialized = _materialize(records, repair_set, overlay)
    output = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in materialized
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    report = {
        "corpus_v4_overlay_materialization_schema_version": 1,
        "source_records_sha256": hashlib.sha256(records_bytes).hexdigest(),
        "repair_set_sha256": hashlib.sha256(repair_set_bytes).hexdigest(),
        "overlay_sha256": hashlib.sha256(overlay_bytes).hexdigest(),
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "record_count": len(materialized),
        "replacement_record_count": len(overlay["records"]),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


def _materialize(
    records: list[dict[str, object]],
    repair_set: dict[str, Any],
    overlay: dict[str, Any],
) -> list[dict[str, object]]:
    plan_by_id = _entries_by_id(repair_set, "repair set")
    overlay_by_id = _entries_by_id(overlay, "overlay")
    if set(plan_by_id) != set(overlay_by_id):
        raise RuntimeError("overlay record IDs do not match the repair set")
    source_ids = {
        record_id
        for record in records
        if isinstance(record_id := record.get("record_id"), str)
    }
    unknown_ids = sorted(set(plan_by_id).difference(source_ids))
    if unknown_ids:
        raise RuntimeError(f"repair set references unknown record IDs: {unknown_ids}")
    result = []
    for original in records:
        record_id = original.get("record_id")
        if not isinstance(record_id, str):
            raise RuntimeError("source records must contain record_id")
        plan = plan_by_id.get(record_id)
        if plan is None:
            result.append(dict(original))
            continue
        replacement = overlay_by_id[record_id]
        _validate_replacement(original, plan, replacement)
        target = replacement["target"]
        text = replacement["replacement"]["text"]
        result.append(
            {
                **original,
                **target,
                **replacement["replacement"],
                "text": text,
            }
        )
    if len(result) != len(records):
        raise RuntimeError("materialized record count changed")
    return result


def _entries_by_id(
    document: dict[str, Any], name: str
) -> dict[str, dict[str, Any]]:
    entries = document.get("records")
    if not isinstance(entries, list):
        raise RuntimeError(f"{name} has no records list")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError(f"{name} has a non-object entry")
        record_id = entry.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise RuntimeError(f"{name} entry has no record_id")
        if record_id in result:
            raise RuntimeError(f"{name} has duplicate record_id: {record_id}")
        result[record_id] = entry
    return result


def _validate_replacement(
    original: dict[str, object],
    plan: dict[str, Any],
    replacement: dict[str, Any],
) -> None:
    if replacement.get("original_record_sha256") != _record_sha256(original):
        raise RuntimeError(
            f"{original['record_id']}: original record SHA does not match"
        )
    if replacement.get("original_record_sha256") != plan.get("original_record_sha256"):
        raise RuntimeError(f"{original['record_id']}: repair plan SHA does not match")
    if replacement.get("repair_reasons") != plan.get("repair_reasons"):
        raise RuntimeError(f"{original['record_id']}: repair reasons do not match")
    plan_preserve = _validate_mapping(
        plan.get("preserve"), _PRESERVED_FIELDS, "repair plan preserve"
    )
    for field in _PRESERVED_FIELDS:
        if plan_preserve[field] != original.get(field):
            raise RuntimeError(
                f"{original['record_id']}: repair plan {field} does not match"
            )
    preserve = _validate_mapping(
        replacement.get("preserve"), _PRESERVED_FIELDS, "preserve"
    )
    for field in _PRESERVED_FIELDS:
        if preserve[field] != original.get(field):
            raise RuntimeError(
                f"{original['record_id']}: preserved {field} does not match"
            )
    target = _validate_mapping(replacement.get("target"), _TARGET_FIELDS, "target")
    plan_target = plan.get("target")
    if not isinstance(plan_target, dict):
        raise RuntimeError(f"{original['record_id']}: repair plan target is invalid")
    if target["category"] != plan_target.get("category"):
        raise RuntimeError(
            f"{original['record_id']}: target category does not match plan"
        )
    payload = _validate_mapping(
        replacement.get("replacement"), _REPLACEMENT_FIELDS, "replacement"
    )
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f"{original['record_id']}: replacement text is invalid")
    expected_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if replacement.get("replacement_text_sha256") != expected_sha:
        raise RuntimeError(
            f"{original['record_id']}: replacement text SHA does not match"
        )


def _validate_mapping(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise RuntimeError(f"overlay {name} fields are invalid")
    if any(
        not isinstance(value[field], str) or not value[field].strip()
        for field in fields
    ):
        raise RuntimeError(f"overlay {name} contains an empty field")
    return value


def _load_records_bytes(value: bytes) -> list[dict[str, object]]:
    records = []
    for line_number, line in enumerate(value.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise RuntimeError(f"records line {line_number} is not an object")
        records.append(record)
    return records


def _load_object_bytes(value: bytes, name: str) -> dict[str, Any]:
    document = json.loads(value.decode("utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return document


if __name__ == "__main__":
    raise SystemExit(main())
