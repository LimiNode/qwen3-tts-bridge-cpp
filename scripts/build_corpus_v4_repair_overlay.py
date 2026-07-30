"""Build a provenance-pinned corpus-v4 overlay from reviewed authoring JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts.audit_corpus_repetition import (
        _record_id_set_sha256,
        normalize_exact_text,
    )
    from scripts.materialize_corpus_v4_overlay import (
        _REPAIR_PLAN_ENTRY_FIELDS,
        _entries_by_id,
        _validate_audit_document,
        _validate_policy_document,
        _validate_repair_set_document,
    )
    from scripts.validate_corpus_v4_batches import (
        _COMPATIBILITY,
        _WORD_RANGES,
        _WORD_RE,
    )
except ModuleNotFoundError:
    from audit_corpus_repetition import _record_id_set_sha256, normalize_exact_text
    from materialize_corpus_v4_overlay import (
        _REPAIR_PLAN_ENTRY_FIELDS,
        _entries_by_id,
        _validate_audit_document,
        _validate_policy_document,
        _validate_repair_set_document,
    )
    from validate_corpus_v4_batches import _COMPATIBILITY, _WORD_RANGES, _WORD_RE

_AUTHORING_SCHEMA_VERSION = 1
_AUTHORING_FIELDS = {
    "authoring_form_schema_version",
    "record_id",
    "repair_reasons",
    "preserve",
    "word_range",
    "source",
    "target",
    "replacement",
}
_AUTHORING_SOURCE_FIELDS = {
    "text",
    "category",
    "scene_context",
    "speech_intent",
    "template_family_id",
    "semantic_intent_id",
    "key_phrase_id",
}
_PRESERVE_FIELDS = {
    "batch_id",
    "record_id",
    "language_class",
    "intended_length_class",
}
_TARGET_FIELDS = {"category", "scene_context", "speech_intent"}
_REPLACEMENT_FIELDS = {
    "text",
    "template_family_id",
    "semantic_intent_id",
    "key_phrase_id",
}
_ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--repair-policy", type=Path, required=True)
    parser.add_argument("--repair-set", type=Path, required=True)
    parser.add_argument("--authoring", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    records_bytes = args.records.read_bytes()
    audit_bytes = args.audit.read_bytes()
    policy_bytes = args.repair_policy.read_bytes()
    repair_set_bytes = args.repair_set.read_bytes()
    records = _load_records(records_bytes)
    audit = _load_object(audit_bytes, "audit")
    policy = _load_object(policy_bytes, "repair policy")
    repair_set = _load_object(repair_set_bytes, "repair set")
    overlay = _build_overlay(
        records,
        audit,
        policy,
        repair_set,
        _load_authoring(args.authoring),
        source_audit_sha256=hashlib.sha256(audit_bytes).hexdigest(),
        source_records_sha256=hashlib.sha256(records_bytes).hexdigest(),
        repair_policy_sha256=hashlib.sha256(policy_bytes).hexdigest(),
        repair_set_sha256=hashlib.sha256(repair_set_bytes).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(overlay, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "corpus_id": overlay["corpus_id"],
                "replacement_record_count": len(overlay["records"]),
                "overlay_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


def _build_overlay(
    records: list[dict[str, object]],
    audit: dict[str, Any],
    policy: dict[str, Any],
    repair_set: dict[str, Any],
    authoring_rows: list[dict[str, Any]],
    *,
    source_audit_sha256: str,
    source_records_sha256: str,
    repair_policy_sha256: str,
    repair_set_sha256: str,
) -> dict[str, Any]:
    source_id_set_sha256 = _record_id_set_sha256(records)
    policy_id = policy.get("corpus_id")
    if not isinstance(policy_id, str):
        raise RuntimeError("repair policy corpus_id is invalid")
    _validate_audit_document(
        audit, source_records_sha256, source_id_set_sha256, policy_id
    )
    _validate_policy_document(policy)
    _validate_repair_set_document(
        repair_set,
        source_records_sha256,
        source_id_set_sha256,
        len(records),
        source_audit_sha256,
        repair_policy_sha256,
        policy_id,
    )
    plan_by_id = _entries_by_id(repair_set, "repair set", _REPAIR_PLAN_ENTRY_FIELDS)
    authoring_by_id = _authoring_by_id(authoring_rows)
    if set(plan_by_id) != set(authoring_by_id):
        raise RuntimeError("authoring record IDs do not match the repair set")
    source_by_id = _records_by_id(records)
    for record_id in sorted(plan_by_id):
        record = source_by_id.get(record_id)
        if record is None:
            raise RuntimeError(f"repair set references unknown record ID: {record_id}")
        _validate_authoring_row(
            authoring_by_id[record_id], record, plan_by_id[record_id]
        )
    _validate_replacement_texts(source_by_id, plan_by_id, authoring_by_id)
    entries = []
    for record_id in sorted(plan_by_id):
        record = source_by_id.get(record_id)
        plan = plan_by_id[record_id]
        authored = authoring_by_id[record_id]
        text = authored["replacement"]["text"]
        entries.append(
            {
                "record_id": record_id,
                "original_record_sha256": plan["original_record_sha256"],
                "repair_reasons": plan["repair_reasons"],
                "preserve": plan["preserve"],
                "target": authored["target"],
                "replacement": authored["replacement"],
                "replacement_text_sha256": hashlib.sha256(
                    text.encode("utf-8")
                ).hexdigest(),
            }
        )
    return {
        "corpus_v4_repair_overlay_schema_version": 3,
        "corpus_id": repair_set["corpus_id"],
        "source_audit_sha256": source_audit_sha256,
        "source_records_sha256": source_records_sha256,
        "source_record_id_set_sha256": source_id_set_sha256,
        "repair_set_sha256": repair_set_sha256,
        "repair_policy_sha256": repair_policy_sha256,
        "repair_policy_id": repair_set["repair_policy_id"],
        "records": entries,
    }


def _validate_replacement_texts(
    source_by_id: dict[str, dict[str, object]],
    plan_by_id: dict[str, dict[str, Any]],
    authoring_by_id: dict[str, dict[str, Any]],
) -> None:
    unchanged_texts = {
        normalize_exact_text(str(record["text"]))
        for record_id, record in source_by_id.items()
        if record_id not in plan_by_id
    }
    replacement_texts: dict[str, str] = {}
    for record_id in sorted(plan_by_id):
        text = str(authoring_by_id[record_id]["replacement"]["text"])
        normalized_text = normalize_exact_text(text)
        if normalized_text in replacement_texts:
            previous_record_id = replacement_texts[normalized_text]
            raise RuntimeError(
                f"{record_id}: replacement text duplicates {previous_record_id}"
            )
        if normalized_text in unchanged_texts:
            raise RuntimeError(
                f"{record_id}: replacement text collides with an unchanged source "
                "record"
            )
        replacement_texts[normalized_text] = record_id


def _validate_authoring_row(
    row: dict[str, Any], record: dict[str, object], plan: dict[str, Any]
) -> None:
    if set(row) != _AUTHORING_FIELDS:
        raise RuntimeError(f"{record['record_id']}: authoring row schema is invalid")
    if row.get("authoring_form_schema_version") != _AUTHORING_SCHEMA_VERSION:
        raise RuntimeError(f"{record['record_id']}: authoring schema is unsupported")
    if row.get("record_id") != record.get("record_id"):
        raise RuntimeError(f"{record['record_id']}: authoring record ID does not match")
    _validate_exact_mapping(row.get("preserve"), plan["preserve"], "preserve", record)
    source = _mapping(row.get("source"), _AUTHORING_SOURCE_FIELDS, "source", record)
    if source != {field: record.get(field) for field in _AUTHORING_SOURCE_FIELDS}:
        raise RuntimeError(f"{record['record_id']}: authoring source does not match")
    expected_range = _WORD_RANGES.get(record.get("intended_length_class"))
    if row.get("word_range") != {
        "minimum": expected_range[0],
        "maximum": expected_range[1],
    }:
        raise RuntimeError(f"{record['record_id']}: authoring word range does not match")
    target = _mapping(row.get("target"), _TARGET_FIELDS, "target", record)
    if target["category"] != plan["target"]["category"]:
        raise RuntimeError(f"{record['record_id']}: authoring category does not match")
    if plan["target_metadata_policy"] == "preserve_exact":
        if target != plan["target"]:
            raise RuntimeError(f"{record['record_id']}: authoring target metadata drifted")
    elif not _is_compatible_target(target):
        raise RuntimeError(f"{record['record_id']}: authoring target is incompatible")
    replacement = _mapping(
        row.get("replacement"), _REPLACEMENT_FIELDS, "replacement", record
    )
    for field in _REPLACEMENT_FIELDS:
        value = replacement[field]
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"{record['record_id']}: replacement {field} is invalid")
    if not _ID_RE.fullmatch(replacement["template_family_id"]):
        raise RuntimeError(f"{record['record_id']}: template_family_id is invalid")
    if not _ID_RE.fullmatch(replacement["semantic_intent_id"]):
        raise RuntimeError(f"{record['record_id']}: semantic_intent_id is invalid")
    if not _ID_RE.fullmatch(replacement["key_phrase_id"]):
        raise RuntimeError(f"{record['record_id']}: key_phrase_id is invalid")
    if len(_WORD_RE.findall(replacement["text"])) not in range(
        expected_range[0], expected_range[1] + 1
    ):
        raise RuntimeError(f"{record['record_id']}: replacement word count is invalid")
    if normalize_exact_text(replacement["text"]) == normalize_exact_text(
        str(record["text"])
    ):
        raise RuntimeError(
            f"{record['record_id']}: replacement text does not change source"
        )


def _authoring_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    metadata = {
        field: set()
        for field in (
            "template_family_id",
            "semantic_intent_id",
            "key_phrase_id",
        )
    }
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("authoring contains a non-object row")
        record_id = row.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise RuntimeError("authoring row has no record_id")
        if record_id in result:
            raise RuntimeError(f"authoring has duplicate record_id: {record_id}")
        replacement = row.get("replacement")
        if isinstance(replacement, dict):
            for field, seen in metadata.items():
                value = replacement.get(field)
                if value in seen:
                    raise RuntimeError(f"authoring has duplicate {field}: {value}")
                seen.add(value)
        result[record_id] = row
    return result


def _mapping(
    value: object, expected_fields: set[str], name: str, record: dict[str, object]
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise RuntimeError(f"{record['record_id']}: authoring {name} fields are invalid")
    return value


def _validate_exact_mapping(
    value: object, expected: object, name: str, record: dict[str, object]
) -> None:
    if value != expected:
        raise RuntimeError(f"{record['record_id']}: authoring {name} does not match")


def _is_compatible_target(target: dict[str, Any]) -> bool:
    compatibility = _COMPATIBILITY.get(target["category"])
    return (
        compatibility is not None
        and target["scene_context"] in compatibility["contexts"]
        and target["speech_intent"] in compatibility["intents"]
    )


def _records_by_id(records: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    result = {}
    for record in records:
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or not record_id or record_id in result:
            raise RuntimeError("source records contain invalid record IDs")
        result[record_id] = record
    return result


def _load_authoring(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"authoring line {line_number} is not an object")
        rows.append(value)
    return rows


def _load_records(value: bytes) -> list[dict[str, object]]:
    records = []
    for line_number, line in enumerate(value.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"records line {line_number} is not an object")
        records.append(parsed)
    return records


def _load_object(value: bytes, name: str) -> dict[str, Any]:
    parsed = json.loads(value.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
