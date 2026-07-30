"""Materialize a provenance-pinned corpus-v4 JSONL from an immutable overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from scripts.audit_corpus_repetition import _is_sha256, _record_id_set_sha256
    from scripts.build_corpus_v4_repair_set import _record_sha256
except ModuleNotFoundError:
    from audit_corpus_repetition import _is_sha256, _record_id_set_sha256
    from build_corpus_v4_repair_set import _record_sha256

_AUDIT_SCHEMA_VERSION = 4
_POLICY_SCHEMA_VERSION = 1
_REPAIR_SET_SCHEMA_VERSION = 2
_OVERLAY_SCHEMA_VERSION = 2
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
_REPAIR_SET_FIELDS = {
    "corpus_v4_repair_set_schema_version",
    "corpus_id",
    "source_audit_sha256",
    "source_records_sha256",
    "source_record_id_set_sha256",
    "source_record_count",
    "repair_policy_sha256",
    "repair_policy_id",
    "implicated_record_count",
    "selected_record_count",
    "selection_policy",
    "selection_metrics",
    "records",
}
_OVERLAY_FIELDS = {
    "corpus_v4_repair_overlay_schema_version",
    "corpus_id",
    "source_audit_sha256",
    "source_records_sha256",
    "source_record_id_set_sha256",
    "repair_set_sha256",
    "repair_policy_sha256",
    "repair_policy_id",
    "records",
}
_AUDIT_FIELDS = {
    "corpus_repetition_audit_schema_version",
    "corpus_id",
    "record_count",
    "source_records_sha256",
    "source_record_id_set_sha256",
    "limits",
    "frequencies",
    "violations",
    "violation_records",
    "passed",
}
_POLICY_FIELDS = {
    "corpus_v4_repair_policy_schema_version",
    "corpus_id",
    "allowed_category_replacements",
    "selection_priority",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--repair-policy", type=Path, required=True)
    parser.add_argument("--repair-set", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    records_bytes = args.records.read_bytes()
    audit_bytes = args.audit.read_bytes()
    policy_bytes = args.repair_policy.read_bytes()
    repair_set_bytes = args.repair_set.read_bytes()
    overlay_bytes = args.overlay.read_bytes()
    records = _load_records_bytes(records_bytes)
    audit = _load_object_bytes(audit_bytes, "audit")
    policy = _load_object_bytes(policy_bytes, "repair policy")
    repair_set = _load_object_bytes(repair_set_bytes, "repair set")
    overlay = _load_object_bytes(overlay_bytes, "overlay")
    source_records_sha256 = hashlib.sha256(records_bytes).hexdigest()
    source_record_id_set_sha256 = _record_id_set_sha256(records)
    source_audit_sha256 = hashlib.sha256(audit_bytes).hexdigest()
    repair_policy_sha256 = hashlib.sha256(policy_bytes).hexdigest()
    repair_set_sha256 = hashlib.sha256(repair_set_bytes).hexdigest()
    _validate_audit_document(
        audit,
        source_records_sha256,
        source_record_id_set_sha256,
        str(policy["corpus_id"]),
    )
    _validate_policy_document(policy)
    materialized = _materialize(
        records,
        repair_set,
        overlay,
        source_records_sha256=source_records_sha256,
        source_record_id_set_sha256=source_record_id_set_sha256,
        source_record_count=len(records),
        source_audit_sha256=source_audit_sha256,
        repair_policy_sha256=repair_policy_sha256,
        repair_policy_id=str(policy["corpus_id"]),
        repair_set_sha256=repair_set_sha256,
    )
    output = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in materialized
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    report = {
        "corpus_v4_overlay_materialization_schema_version": 2,
        "corpus_id": repair_set["corpus_id"],
        "source_audit_sha256": source_audit_sha256,
        "source_records_sha256": source_records_sha256,
        "source_record_id_set_sha256": source_record_id_set_sha256,
        "repair_policy_sha256": repair_policy_sha256,
        "repair_set_sha256": repair_set_sha256,
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
    *,
    source_records_sha256: str,
    source_record_id_set_sha256: str,
    source_record_count: int,
    source_audit_sha256: str,
    repair_policy_sha256: str,
    repair_policy_id: str,
    repair_set_sha256: str,
) -> list[dict[str, object]]:
    _validate_repair_set_document(
        repair_set,
        source_records_sha256,
        source_record_id_set_sha256,
        source_record_count,
        source_audit_sha256,
        repair_policy_sha256,
        repair_policy_id,
    )
    _validate_overlay_document(
        overlay,
        repair_set,
        source_records_sha256,
        source_record_id_set_sha256,
        source_audit_sha256,
        repair_policy_sha256,
        repair_set_sha256,
    )
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
        result.append(
            {
                **original,
                **replacement["target"],
                **replacement["replacement"],
            }
        )
    if len(result) != len(records):
        raise RuntimeError("materialized record count changed")
    return result


def _validate_audit_document(
    audit: dict[str, Any],
    source_records_sha256: str,
    source_record_id_set_sha256: str,
    corpus_id: str,
) -> None:
    if set(audit) != _AUDIT_FIELDS:
        raise RuntimeError("audit top-level schema is invalid")
    if audit.get("corpus_repetition_audit_schema_version") != _AUDIT_SCHEMA_VERSION:
        raise RuntimeError("audit schema version is unsupported")
    if audit.get("source_records_sha256") != source_records_sha256:
        raise RuntimeError("audit source records SHA does not match")
    if audit.get("source_record_id_set_sha256") != source_record_id_set_sha256:
        raise RuntimeError("audit source record ID set SHA does not match")
    if audit.get("corpus_id") != corpus_id:
        raise RuntimeError("audit corpus_id does not match repair policy")


def _validate_policy_document(policy: dict[str, Any]) -> None:
    if set(policy) != _POLICY_FIELDS:
        raise RuntimeError("repair policy top-level schema is invalid")
    if policy.get("corpus_v4_repair_policy_schema_version") != _POLICY_SCHEMA_VERSION:
        raise RuntimeError("repair policy schema version is unsupported")
    corpus_id = policy.get("corpus_id")
    if not isinstance(corpus_id, str) or not corpus_id:
        raise RuntimeError("repair policy corpus_id is invalid")
    if not isinstance(policy.get("allowed_category_replacements"), dict):
        raise RuntimeError("repair policy replacements are invalid")
    if not isinstance(policy.get("selection_priority"), list):
        raise RuntimeError("repair policy selection_priority is invalid")


def _validate_repair_set_document(
    repair_set: dict[str, Any],
    source_records_sha256: str,
    source_record_id_set_sha256: str,
    source_record_count: int,
    source_audit_sha256: str,
    repair_policy_sha256: str,
    repair_policy_id: str,
) -> None:
    if set(repair_set) != _REPAIR_SET_FIELDS:
        raise RuntimeError("repair set top-level schema is invalid")
    if (
        repair_set.get("corpus_v4_repair_set_schema_version")
        != _REPAIR_SET_SCHEMA_VERSION
    ):
        raise RuntimeError("repair set schema version is unsupported")
    _validate_provenance_value(
        repair_set, "source_records_sha256", source_records_sha256, "repair set"
    )
    _validate_provenance_value(
        repair_set,
        "source_record_id_set_sha256",
        source_record_id_set_sha256,
        "repair set",
    )
    _validate_provenance_value(
        repair_set, "source_audit_sha256", source_audit_sha256, "repair set"
    )
    _validate_provenance_value(
        repair_set, "repair_policy_sha256", repair_policy_sha256, "repair set"
    )
    if repair_set.get("source_record_count") != source_record_count:
        raise RuntimeError("repair set source record count does not match")
    if repair_set.get("corpus_id") != repair_policy_id:
        raise RuntimeError("repair set corpus ID does not match repair policy")
    if repair_set.get("repair_policy_id") != repair_policy_id:
        raise RuntimeError("repair set policy ID does not match repair policy")
    if not isinstance(repair_set.get("records"), list):
        raise RuntimeError("repair set records are invalid")
    if repair_set.get("selected_record_count") != len(repair_set["records"]):
        raise RuntimeError("repair set selected record count does not match")
    if not isinstance(repair_set.get("implicated_record_count"), int):
        raise RuntimeError("repair set implicated record count is invalid")
    if not isinstance(repair_set.get("selection_policy"), str):
        raise RuntimeError("repair set selection policy is invalid")
    if not isinstance(repair_set.get("selection_metrics"), dict):
        raise RuntimeError("repair set selection metrics are invalid")


def _validate_overlay_document(
    overlay: dict[str, Any],
    repair_set: dict[str, Any],
    source_records_sha256: str,
    source_record_id_set_sha256: str,
    source_audit_sha256: str,
    repair_policy_sha256: str,
    repair_set_sha256: str,
) -> None:
    if set(overlay) != _OVERLAY_FIELDS:
        raise RuntimeError("overlay top-level schema is invalid")
    if (
        overlay.get("corpus_v4_repair_overlay_schema_version")
        != _OVERLAY_SCHEMA_VERSION
    ):
        raise RuntimeError("overlay schema version is unsupported")
    if overlay.get("corpus_id") != repair_set.get("corpus_id"):
        raise RuntimeError("overlay corpus ID does not match repair set")
    for field, expected in (
        ("source_records_sha256", source_records_sha256),
        ("source_record_id_set_sha256", source_record_id_set_sha256),
        ("source_audit_sha256", source_audit_sha256),
        ("repair_policy_sha256", repair_policy_sha256),
        ("repair_set_sha256", repair_set_sha256),
    ):
        _validate_provenance_value(overlay, field, expected, "overlay")
    if overlay.get("repair_policy_id") != repair_set.get("repair_policy_id"):
        raise RuntimeError("overlay policy ID does not match repair set")
    if not isinstance(overlay.get("records"), list):
        raise RuntimeError("overlay records are invalid")


def _validate_provenance_value(
    document: dict[str, Any], field: str, expected: str, name: str
) -> None:
    actual = document.get(field)
    if not _is_sha256(actual) or actual != expected:
        raise RuntimeError(f"{name} {field} does not match")


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
