"""Build a provenance-pinned corpus revision from human AI-pre-review adjudication."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    from scripts.audit_corpus_repetition import (
        _record_id_set_sha256,
        normalize_exact_text,
    )
    from scripts.prepare_corpus_v4_ai_prereview_triage import _prepare_triage
    from scripts.prepare_corpus_v4_quality_overlay import (
        _RECORD_FIELDS,
        _validate_word_range,
    )
except ModuleNotFoundError:
    from audit_corpus_repetition import _record_id_set_sha256, normalize_exact_text
    from prepare_corpus_v4_ai_prereview_triage import _prepare_triage
    from prepare_corpus_v4_quality_overlay import _RECORD_FIELDS, _validate_word_range

_TRIAGE_SCHEMA_VERSION = 2
_AUTHORING_SCHEMA_VERSION = 2
_COMPLETED_STATUS = "completed_human_adjudication"
_REPLACE = "replace"
_KEEP = "keep_after_human_review"
_TARGETED_FIELDS = {
    "ai_prereview_repair_authoring_schema_version",
    "authoring_status",
    "authoring_decision",
    "author_id",
    "decision_notes",
    "base_candidate_sha256",
    "record_id",
    "language_class",
    "issues",
    "ai_prereview_notes",
    "source",
    "target",
    "current_replacement",
    "proposed_replacement_text",
}
_GENERAL_FIELDS = {
    "ai_prereview_repair_authoring_schema_version",
    "authoring_status",
    "authoring_decision",
    "author_id",
    "decision_notes",
    "base_candidate_sha256",
    "label",
    "category",
    "language_class",
    "intended_length_class",
    "issues",
    "ai_prereview_notes",
    "current_text",
    "proposed_replacement_text",
}
_TARGETED_CANDIDATE_FIELDS = {
    "text",
    "category",
    "scene_context",
    "speech_intent",
    "template_family_id",
    "semantic_intent_id",
    "key_phrase_id",
}
_HUMAN_EDITABLE_FIELDS = {
    "authoring_status",
    "authoring_decision",
    "author_id",
    "decision_notes",
    "proposed_replacement_text",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-candidate", type=Path, required=True)
    parser.add_argument("--triage-manifest", type=Path, required=True)
    parser.add_argument("--targeted-review-form", type=Path, required=True)
    parser.add_argument("--targeted-ai-prereview", type=Path, required=True)
    parser.add_argument("--general-review-form", type=Path, required=True)
    parser.add_argument("--general-ai-prereview", type=Path, required=True)
    parser.add_argument("--ai-review-provenance", type=Path, required=True)
    parser.add_argument("--targeted-adjudication", type=Path, required=True)
    parser.add_argument("--general-adjudication", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    base_bytes = args.base_candidate.read_bytes()
    manifest_bytes = args.triage_manifest.read_bytes()
    targeted_form_bytes = args.targeted_review_form.read_bytes()
    targeted_ai_bytes = args.targeted_ai_prereview.read_bytes()
    general_form_bytes = args.general_review_form.read_bytes()
    general_ai_bytes = args.general_ai_prereview.read_bytes()
    ai_review_provenance_bytes = args.ai_review_provenance.read_bytes()
    targeted_adjudication_bytes = args.targeted_adjudication.read_bytes()
    general_adjudication_bytes = args.general_adjudication.read_bytes()
    expected_manifest, expected_targeted, expected_general = _prepare_triage(
        _load_jsonl(targeted_form_bytes, "targeted review form"),
        _load_jsonl(targeted_ai_bytes, "targeted AI pre-review"),
        _load_jsonl(general_form_bytes, "general review form"),
        _load_jsonl(general_ai_bytes, "general AI pre-review"),
        targeted_form_sha256=_sha256(targeted_form_bytes),
        targeted_ai_sha256=_sha256(targeted_ai_bytes),
        general_form_sha256=_sha256(general_form_bytes),
        general_ai_sha256=_sha256(general_ai_bytes),
        base_candidate_sha256=_sha256(base_bytes),
        ai_review_provenance=_load_object(
            ai_review_provenance_bytes, "AI review provenance"
        ),
        ai_review_provenance_sha256=_sha256(ai_review_provenance_bytes),
    )
    manifest = _load_object(manifest_bytes, "triage manifest")
    if manifest != expected_manifest:
        raise RuntimeError("triage manifest does not match pinned review inputs")
    materialized, report = _build_revision(
        _load_jsonl(base_bytes, "base candidate"),
        manifest,
        _load_jsonl(
            targeted_adjudication_bytes,
            "targeted adjudication",
            allow_empty=not expected_targeted,
        ),
        _load_jsonl(
            general_adjudication_bytes,
            "general adjudication",
            allow_empty=not expected_general,
        ),
        expected_targeted,
        expected_general,
        base_candidate_sha256=_sha256(base_bytes),
        triage_manifest_sha256=_sha256(manifest_bytes),
        targeted_review_form_sha256=_sha256(targeted_form_bytes),
        targeted_ai_prereview_sha256=_sha256(targeted_ai_bytes),
        general_review_form_sha256=_sha256(general_form_bytes),
        general_ai_prereview_sha256=_sha256(general_ai_bytes),
        ai_review_provenance_sha256=_sha256(ai_review_provenance_bytes),
        targeted_adjudication_sha256=_sha256(targeted_adjudication_bytes),
        general_adjudication_sha256=_sha256(general_adjudication_bytes),
    )
    output_bytes = _jsonl_bytes(materialized)
    _write_bytes(args.output, output_bytes)
    report["output_sha256"] = _sha256(output_bytes)
    _write_object(args.report, report)
    print(json.dumps(report, sort_keys=True))
    return 0


def _build_revision(
    base_records: list[dict[str, Any]],
    manifest: dict[str, Any],
    targeted_rows: list[dict[str, Any]],
    general_rows: list[dict[str, Any]],
    expected_targeted_rows: list[dict[str, object]],
    expected_general_rows: list[dict[str, object]],
    **provenance: str,
) -> tuple[list[dict[str, Any]], dict[str, object]]:
    base_by_id = _records_by_id(base_records)
    _validate_manifest(manifest, provenance)
    _validate_adjudication_templates(
        targeted_rows,
        expected_targeted_rows,
        "record_id",
        "targeted adjudication",
    )
    _validate_adjudication_templates(
        general_rows,
        expected_general_rows,
        "label",
        "general adjudication",
    )
    targeted_by_id = _adjudications_by_id(
        targeted_rows, "record_id", _TARGETED_FIELDS, "targeted adjudication"
    )
    general_by_id = _adjudications_by_id(
        general_rows, "label", _GENERAL_FIELDS, "general adjudication"
    )
    _validate_manifest_candidates(manifest, targeted_by_id, general_by_id)
    overlap = sorted(set(targeted_by_id).intersection(general_by_id))
    if overlap:
        raise RuntimeError(f"adjudication scopes overlap: {overlap}")
    replacements: dict[str, str] = {}
    targeted_counts = _validate_targeted_rows(
        targeted_by_id,
        base_by_id,
        replacements,
        provenance["base_candidate_sha256"],
    )
    general_counts = _validate_general_rows(
        general_by_id,
        base_by_id,
        replacements,
        provenance["base_candidate_sha256"],
    )
    _validate_final_texts(base_by_id, replacements)
    materialized = [
        {**record, "text": replacements.get(str(record["record_id"]), record["text"])}
        for record in base_records
    ]
    report: dict[str, object] = {
        "corpus_v4_human_adjudication_revision_schema_version": 1,
        "base_candidate_sha256": provenance["base_candidate_sha256"],
        "base_candidate_record_id_set_sha256": _record_id_set_sha256(base_records),
        "triage_manifest_sha256": provenance["triage_manifest_sha256"],
        "targeted_review_form_sha256": provenance["targeted_review_form_sha256"],
        "targeted_ai_prereview_sha256": provenance["targeted_ai_prereview_sha256"],
        "general_review_form_sha256": provenance["general_review_form_sha256"],
        "general_ai_prereview_sha256": provenance["general_ai_prereview_sha256"],
        "targeted_adjudication_sha256": provenance["targeted_adjudication_sha256"],
        "general_adjudication_sha256": provenance["general_adjudication_sha256"],
        "ai_review_provenance": manifest["ai_review_provenance"],
        "targeted_flagged": len(targeted_by_id),
        "targeted_replaced": targeted_counts[_REPLACE],
        "targeted_kept": targeted_counts[_KEEP],
        "general_flagged": len(general_by_id),
        "general_replaced": general_counts[_REPLACE],
        "general_kept": general_counts[_KEEP],
        "overlap_count": len(overlap),
        "unique_candidate_count": len(set(targeted_by_id).union(general_by_id)),
        "unique_revised_count": len(replacements),
        "record_count": len(materialized),
    }
    return materialized, report


def _validate_manifest(manifest: dict[str, Any], provenance: dict[str, str]) -> None:
    expected_fields = {
        "corpus_v4_ai_prereview_triage_schema_version",
        "review_status",
        "inputs",
        "ai_review_provenance",
        "summary",
        "targeted_repair_candidates",
        "general_repair_candidates",
    }
    if set(manifest) != expected_fields:
        raise RuntimeError("triage manifest schema is invalid")
    if (
        manifest.get("corpus_v4_ai_prereview_triage_schema_version")
        != _TRIAGE_SCHEMA_VERSION
    ):
        raise RuntimeError("triage manifest schema is unsupported")
    if manifest.get("review_status") != "ai_prereview_not_human_gate":
        raise RuntimeError("triage manifest review status is invalid")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise RuntimeError("triage manifest inputs are invalid")
    expected_inputs = {
        "targeted_form_sha256": provenance["targeted_review_form_sha256"],
        "targeted_ai_prereview_sha256": provenance["targeted_ai_prereview_sha256"],
        "general_form_sha256": provenance["general_review_form_sha256"],
        "general_ai_prereview_sha256": provenance["general_ai_prereview_sha256"],
        "base_candidate_sha256": provenance["base_candidate_sha256"],
        "ai_review_provenance_sha256": provenance["ai_review_provenance_sha256"],
    }
    if set(inputs) != set(expected_inputs):
        raise RuntimeError("triage manifest input schema is invalid")
    for field, expected in expected_inputs.items():
        if inputs.get(field) != expected:
            raise RuntimeError(f"triage manifest {field} does not match")
    if not _is_sha256(inputs.get("ai_review_provenance_sha256")):
        raise RuntimeError("triage manifest AI provenance SHA is invalid")
    if not isinstance(manifest.get("ai_review_provenance"), dict):
        raise RuntimeError("triage manifest AI provenance is invalid")


def _validate_manifest_candidates(
    manifest: dict[str, Any],
    targeted_by_id: dict[str, dict[str, Any]],
    general_by_id: dict[str, dict[str, Any]],
) -> None:
    targeted_ids = _candidate_ids(
        manifest.get("targeted_repair_candidates"), "record_id", "targeted"
    )
    general_ids = _candidate_ids(
        manifest.get("general_repair_candidates"), "label", "general"
    )
    if set(targeted_by_id) != targeted_ids:
        raise RuntimeError("targeted adjudication IDs do not match triage manifest")
    if set(general_by_id) != general_ids:
        raise RuntimeError("general adjudication IDs do not match triage manifest")
    summary = manifest.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError("triage manifest summary is invalid")
    expected = {
        "targeted_review_record_count": 98,
        "targeted_repair_candidate_count": len(targeted_ids),
        "general_review_record_count": 100,
        "general_repair_candidate_count": len(general_ids),
        "overlap_count": 0,
        "unique_candidate_count": len(targeted_ids.union(general_ids)),
    }
    for field, value in expected.items():
        if summary.get(field) != value:
            raise RuntimeError(f"triage manifest summary {field} is invalid")


def _validate_adjudication_templates(
    actual_rows: list[dict[str, Any]],
    expected_rows: list[dict[str, object]],
    id_field: str,
    name: str,
) -> None:
    actual_by_id = _rows_by_id(actual_rows, id_field, name)
    expected_by_id = _rows_by_id(expected_rows, id_field, f"expected {name}")
    if set(actual_by_id) != set(expected_by_id):
        raise RuntimeError(f"{name} IDs do not match pinned review context")
    for record_id, actual in actual_by_id.items():
        expected = expected_by_id[record_id]
        if set(actual) != set(expected):
            raise RuntimeError(f"{record_id}: {name} schema drifted")
        for field, expected_value in expected.items():
            if (
                field not in _HUMAN_EDITABLE_FIELDS
                and actual.get(field) != expected_value
            ):
                raise RuntimeError(
                    f"{record_id}: {name} protected context drifted: {field}"
                )


def _rows_by_id(
    rows: list[dict[str, object]], id_field: str, name: str
) -> dict[str, dict[str, object]]:
    result = {}
    for row in rows:
        record_id = row.get(id_field)
        if not isinstance(record_id, str) or not record_id or record_id in result:
            raise RuntimeError(f"{name} has duplicate or invalid {id_field}")
        result[record_id] = row
    return result


def _candidate_ids(value: object, field: str, name: str) -> set[str]:
    if not isinstance(value, list):
        raise RuntimeError(f"triage manifest {name} candidates are invalid")
    result: set[str] = set()
    for row in value:
        if not isinstance(row, dict):
            raise RuntimeError(f"triage manifest {name} candidate is invalid")
        record_id = row.get(field)
        if not isinstance(record_id, str) or not record_id or record_id in result:
            raise RuntimeError(f"triage manifest {name} candidate ID is invalid")
        result.add(record_id)
    return result


def _adjudications_by_id(
    rows: list[dict[str, Any]],
    id_field: str,
    expected_fields: set[str],
    name: str,
) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        if set(row) != expected_fields:
            raise RuntimeError(f"{name} row schema is invalid")
        if (
            row.get("ai_prereview_repair_authoring_schema_version")
            != _AUTHORING_SCHEMA_VERSION
        ):
            raise RuntimeError(f"{name} schema is unsupported")
        record_id = row.get(id_field)
        if not isinstance(record_id, str) or not record_id or record_id in result:
            raise RuntimeError(f"{name} has duplicate or invalid {id_field}")
        result[record_id] = row
    return result


def _validate_targeted_rows(
    rows: dict[str, dict[str, Any]],
    base_by_id: dict[str, dict[str, Any]],
    replacements: dict[str, str],
    expected_base_sha256: str,
) -> dict[str, int]:
    counts = {_REPLACE: 0, _KEEP: 0}
    for record_id, row in rows.items():
        base = base_by_id.get(record_id)
        if base is None:
            raise RuntimeError(
                f"targeted adjudication references unknown record: {record_id}"
            )
        _validate_human_decision(row, record_id)
        _validate_base_candidate_pin(row, record_id, expected_base_sha256)
        current = row.get("current_replacement")
        target = row.get("target")
        if not isinstance(current, dict) or not isinstance(target, dict):
            raise RuntimeError(f"{record_id}: targeted current record is invalid")
        expected = {
            "text": base["text"],
            "category": base["category"],
            "scene_context": base["scene_context"],
            "speech_intent": base["speech_intent"],
            "template_family_id": base["template_family_id"],
            "semantic_intent_id": base["semantic_intent_id"],
            "key_phrase_id": base["key_phrase_id"],
        }
        actual = {
            "text": current.get("text"),
            "template_family_id": current.get("template_family_id"),
            "semantic_intent_id": current.get("semantic_intent_id"),
            "key_phrase_id": current.get("key_phrase_id"),
            **target,
        }
        if set(actual) != _TARGETED_CANDIDATE_FIELDS or actual != expected:
            raise RuntimeError(
                f"{record_id}: targeted metadata drifted from base candidate"
            )
        if row.get("language_class") != base.get("language_class"):
            raise RuntimeError(f"{record_id}: targeted language class drifted")
        _apply_decision(row, base, record_id, replacements, counts)
    return counts


def _validate_general_rows(
    rows: dict[str, dict[str, Any]],
    base_by_id: dict[str, dict[str, Any]],
    replacements: dict[str, str],
    expected_base_sha256: str,
) -> dict[str, int]:
    counts = {_REPLACE: 0, _KEEP: 0}
    for record_id, row in rows.items():
        base = base_by_id.get(record_id)
        if base is None:
            raise RuntimeError(
                f"general adjudication references unknown record: {record_id}"
            )
        _validate_human_decision(row, record_id)
        _validate_base_candidate_pin(row, record_id, expected_base_sha256)
        for field in ("category", "language_class", "intended_length_class"):
            if row.get(field) != base.get(field):
                raise RuntimeError(
                    f"{record_id}: general {field} drifted from base candidate"
                )
        if row.get("current_text") != base.get("text"):
            raise RuntimeError(
                f"{record_id}: general current text drifted from base candidate"
            )
        _apply_decision(row, base, record_id, replacements, counts)
    return counts


def _validate_human_decision(row: dict[str, Any], record_id: str) -> None:
    if row.get("authoring_status") != _COMPLETED_STATUS:
        raise RuntimeError(f"{record_id}: human adjudication is not completed")
    if not isinstance(row.get("author_id"), str) or not row["author_id"].strip():
        raise RuntimeError(f"{record_id}: human author ID is required")
    if (
        not isinstance(row.get("decision_notes"), str)
        or not row["decision_notes"].strip()
    ):
        raise RuntimeError(f"{record_id}: human decision notes are required")
    if row.get("authoring_decision") not in {_REPLACE, _KEEP}:
        raise RuntimeError(f"{record_id}: human adjudication decision is invalid")


def _validate_base_candidate_pin(
    row: dict[str, Any], record_id: str, expected_sha256: object
) -> None:
    if row.get("base_candidate_sha256") != expected_sha256:
        raise RuntimeError(f"{record_id}: base candidate SHA does not match")


def _apply_decision(
    row: dict[str, Any],
    base: dict[str, Any],
    record_id: str,
    replacements: dict[str, str],
    counts: dict[str, int],
) -> None:
    decision = str(row["authoring_decision"])
    text = row.get("proposed_replacement_text")
    if decision == _KEEP:
        if text != "":
            raise RuntimeError(
                f"{record_id}: kept row must not contain replacement text"
            )
        counts[_KEEP] += 1
        return
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f"{record_id}: replacement text is required")
    if normalize_exact_text(text) == normalize_exact_text(str(base["text"])):
        raise RuntimeError(
            f"{record_id}: replacement text does not change base candidate"
        )
    _validate_word_range(base, text)
    replacements[record_id] = text
    counts[_REPLACE] += 1


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
            raise RuntimeError("base candidate has an invalid record schema")
        record_id = row.get("record_id")
        if not isinstance(record_id, str) or not record_id or record_id in result:
            raise RuntimeError("base candidate has duplicate or invalid record IDs")
        result[record_id] = row
    return result


def _load_jsonl(
    value: bytes, name: str, *, allow_empty: bool = False
) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(value.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise RuntimeError(f"{name} line {line_number} is not an object")
        rows.append(row)
    if not rows and not allow_empty:
        raise RuntimeError(f"{name} contains no records")
    return rows


def _load_object(value: bytes, name: str) -> dict[str, Any]:
    result = json.loads(value.decode("utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError(f"{name} is not an object")
    return result


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    ).encode("utf-8")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
