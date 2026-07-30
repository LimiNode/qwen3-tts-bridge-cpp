"""Prepare fail-closed repair-authoring forms from corpus-v4 AI pre-review."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

_AI_STATUS = "ai_prereview_complete_not_human_gate"
_AUTHORING_STATUS = "pending_human_authoring"
_TARGETED_ID = "record_id"
_GENERAL_ID = "label"
_TARGETED_EDITABLE_FIELDS = {
    "review_status",
    "reviewer_id",
    "notes",
    "naturalness",
    "likely_real_usage",
    "category_fidelity",
    "scene_context_fidelity",
    "speech_intent_fidelity",
    "code_switch_naturalness",
    "appropriate_length",
    "grammar",
    "generic_ai_phrasing",
    "semantic_repetition_acceptable",
    "metadata_only_replacement",
}
_GENERAL_EDITABLE_FIELDS = {
    "review_status",
    "reviewer_id",
    "notes",
    "category_fidelity",
    "naturalness",
    "likely_real_usage",
    "code_switch_naturalness",
    "semantic_repetition_acceptable",
    "appropriate_length",
    "grammar",
    "generic_experiment_phrasing",
}
_TARGETED_POSITIVE_FIELDS = (
    "naturalness",
    "likely_real_usage",
    "category_fidelity",
    "scene_context_fidelity",
    "speech_intent_fidelity",
    "appropriate_length",
    "grammar",
    "semantic_repetition_acceptable",
)
_GENERAL_POSITIVE_FIELDS = (
    "category_fidelity",
    "naturalness",
    "likely_real_usage",
    "appropriate_length",
    "grammar",
    "semantic_repetition_acceptable",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targeted-form", type=Path, required=True)
    parser.add_argument("--targeted-ai-prereview", type=Path, required=True)
    parser.add_argument("--general-form", type=Path, required=True)
    parser.add_argument("--general-ai-prereview", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--targeted-authoring-output", type=Path, required=True)
    parser.add_argument("--general-authoring-output", type=Path, required=True)
    args = parser.parse_args()

    targeted_form = args.targeted_form.read_bytes()
    targeted_ai = args.targeted_ai_prereview.read_bytes()
    general_form = args.general_form.read_bytes()
    general_ai = args.general_ai_prereview.read_bytes()
    manifest, targeted_authoring, general_authoring = _prepare_triage(
        _load_jsonl(targeted_form, "targeted form"),
        _load_jsonl(targeted_ai, "targeted AI pre-review"),
        _load_jsonl(general_form, "general form"),
        _load_jsonl(general_ai, "general AI pre-review"),
        targeted_form_sha256=_sha256(targeted_form),
        targeted_ai_sha256=_sha256(targeted_ai),
        general_form_sha256=_sha256(general_form),
        general_ai_sha256=_sha256(general_ai),
    )
    _write_object(args.manifest_output, manifest)
    _write_jsonl(args.targeted_authoring_output, targeted_authoring)
    _write_jsonl(args.general_authoring_output, general_authoring)
    print(json.dumps(manifest["summary"], sort_keys=True))
    return 0


def _prepare_triage(
    targeted_form: list[dict[str, Any]],
    targeted_ai: list[dict[str, Any]],
    general_form: list[dict[str, Any]],
    general_ai: list[dict[str, Any]],
    *,
    targeted_form_sha256: str,
    targeted_ai_sha256: str,
    general_form_sha256: str,
    general_ai_sha256: str,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    targeted = _validated_ai_rows(
        targeted_form,
        targeted_ai,
        id_field=_TARGETED_ID,
        editable_fields=_TARGETED_EDITABLE_FIELDS,
        positive_fields=_TARGETED_POSITIVE_FIELDS,
        negative_fields=("generic_ai_phrasing", "metadata_only_replacement"),
    )
    general = _validated_ai_rows(
        general_form,
        general_ai,
        id_field=_GENERAL_ID,
        editable_fields=_GENERAL_EDITABLE_FIELDS,
        positive_fields=_GENERAL_POSITIVE_FIELDS,
        negative_fields=("generic_experiment_phrasing",),
    )
    targeted_authoring = [_targeted_authoring_row(row) for row in targeted if row["issues"]]
    general_authoring = [_general_authoring_row(row) for row in general if row["issues"]]
    if not targeted_authoring or not general_authoring:
        raise RuntimeError("AI pre-review did not identify repair candidates in both scopes")
    manifest: dict[str, object] = {
        "corpus_v4_ai_prereview_triage_schema_version": 1,
        "review_status": "ai_prereview_not_human_gate",
        "inputs": {
            "targeted_form_sha256": targeted_form_sha256,
            "targeted_ai_prereview_sha256": targeted_ai_sha256,
            "general_form_sha256": general_form_sha256,
            "general_ai_prereview_sha256": general_ai_sha256,
        },
        "summary": {
            "targeted_review_record_count": len(targeted),
            "targeted_repair_candidate_count": len(targeted_authoring),
            "general_review_record_count": len(general),
            "general_repair_candidate_count": len(general_authoring),
        },
        "targeted_repair_candidates": [
            _manifest_entry(row, _TARGETED_ID) for row in targeted if row["issues"]
        ],
        "general_repair_candidates": [
            _manifest_entry(row, _GENERAL_ID) for row in general if row["issues"]
        ],
    }
    return manifest, targeted_authoring, general_authoring


def _validated_ai_rows(
    form: list[dict[str, Any]],
    ai: list[dict[str, Any]],
    *,
    id_field: str,
    editable_fields: set[str],
    positive_fields: tuple[str, ...],
    negative_fields: tuple[str, ...],
) -> list[dict[str, object]]:
    if len(form) != len(ai):
        raise RuntimeError("AI pre-review record count does not match its form")
    result = []
    for index, (source, reviewed) in enumerate(zip(form, ai, strict=True), 1):
        record_id = source.get(id_field)
        if not isinstance(record_id, str) or reviewed.get(id_field) != record_id:
            raise RuntimeError(f"review row {index} does not preserve {id_field}")
        if set(source) != set(reviewed):
            raise RuntimeError(f"{record_id}: AI pre-review schema drifted")
        for field, value in source.items():
            if field not in editable_fields and reviewed.get(field) != value:
                raise RuntimeError(f"{record_id}: AI pre-review changed protected {field}")
        _validate_ai_status(reviewed, record_id)
        issues = _issues(reviewed, positive_fields, negative_fields, record_id)
        notes = reviewed.get("notes")
        if not isinstance(notes, str):
            raise RuntimeError(f"{record_id}: AI pre-review notes are invalid")
        if issues and not notes.strip():
            raise RuntimeError(f"{record_id}: AI pre-review issue lacks notes")
        result.append({"row": reviewed, "issues": issues})
    return result


def _validate_ai_status(row: dict[str, Any], record_id: str) -> None:
    if row.get("review_status") != _AI_STATUS:
        raise RuntimeError(f"{record_id}: AI pre-review status is invalid")
    reviewer_id = row.get("reviewer_id")
    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        raise RuntimeError(f"{record_id}: AI pre-review reviewer ID is invalid")
    language = row.get("language_class")
    code_switch = row.get("code_switch_naturalness")
    if language == "mixed":
        if not isinstance(code_switch, bool):
            raise RuntimeError(f"{record_id}: mixed row lacks code-switch review")
    elif code_switch is not None:
        raise RuntimeError(f"{record_id}: non-mixed row has code-switch review")


def _issues(
    row: dict[str, Any],
    positive_fields: tuple[str, ...],
    negative_fields: tuple[str, ...],
    record_id: str,
) -> list[str]:
    result = []
    for field in positive_fields:
        if not isinstance(row.get(field), bool):
            raise RuntimeError(f"{record_id}: AI pre-review {field} is invalid")
        if row[field] is False:
            result.append(field)
    code_switch = row.get("code_switch_naturalness")
    if code_switch is False:
        result.append("code_switch_naturalness")
    for field in negative_fields:
        if not isinstance(row.get(field), bool):
            raise RuntimeError(f"{record_id}: AI pre-review {field} is invalid")
        if row[field] is True:
            result.append(field)
    return result


def _manifest_entry(item: dict[str, object], id_field: str) -> dict[str, object]:
    row = item["row"]
    assert isinstance(row, dict)
    return {
        id_field: row[id_field],
        "issues": item["issues"],
        "notes": row["notes"],
    }


def _targeted_authoring_row(item: dict[str, object]) -> dict[str, object]:
    row = item["row"]
    assert isinstance(row, dict)
    return {
        "ai_prereview_repair_authoring_schema_version": 1,
        "authoring_status": _AUTHORING_STATUS,
        "author_id": "",
        "record_id": row["record_id"],
        "language_class": row["language_class"],
        "issues": item["issues"],
        "ai_prereview_notes": row["notes"],
        "source": row["source"],
        "target": row["target"],
        "current_replacement": row["replacement"],
        "proposed_replacement_text": "",
        "authoring_notes": "",
    }


def _general_authoring_row(item: dict[str, object]) -> dict[str, object]:
    row = item["row"]
    assert isinstance(row, dict)
    return {
        "ai_prereview_repair_authoring_schema_version": 1,
        "authoring_status": _AUTHORING_STATUS,
        "author_id": "",
        "label": row["label"],
        "category": row["category"],
        "language_class": row["language_class"],
        "intended_length_class": row["intended_length_class"],
        "issues": item["issues"],
        "ai_prereview_notes": row["notes"],
        "current_text": row["text"],
        "proposed_replacement_text": "",
        "authoring_notes": "",
    }


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


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
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
