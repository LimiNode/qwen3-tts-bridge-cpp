"""Create a provenance-pinned pending human-review form for all v4 repairs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 2
_SCORES = (
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
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authoring", type=Path, required=True)
    parser.add_argument("--repair-set", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    authoring = args.authoring.read_bytes()
    repair_set = args.repair_set.read_bytes()
    overlay = args.overlay.read_bytes()
    rows = _prepare_rows(authoring, repair_set, overlay)
    _write_jsonl(args.output, rows)
    print(
        json.dumps(
            {
                "review_record_count": len(rows),
                "review_status": "pending_human_review",
                "review_source_sha256": hashlib.sha256(authoring).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


def _prepare_rows(
    authoring_bytes: bytes, repair_set_bytes: bytes, overlay_bytes: bytes
) -> list[dict[str, object]]:
    authoring = _load_jsonl(authoring_bytes, "authoring")
    repair_set = _load_object(repair_set_bytes, "repair set")
    overlay = _load_object(overlay_bytes, "overlay")
    repair_sha256 = hashlib.sha256(repair_set_bytes).hexdigest()
    overlay_sha256 = hashlib.sha256(overlay_bytes).hexdigest()
    if overlay.get("repair_set_sha256") != repair_sha256:
        raise RuntimeError("overlay does not match the repair set")
    repair_by_id = _by_id(repair_set.get("records"), "repair set")
    overlay_by_id = _by_id(overlay.get("records"), "overlay")
    authoring_by_id = _by_id(authoring, "authoring")
    if not repair_by_id or set(repair_by_id) != set(overlay_by_id) or set(repair_by_id) != set(authoring_by_id):
        raise RuntimeError("repair, overlay, and authoring record IDs must match")
    authoring_sha256 = hashlib.sha256(authoring_bytes).hexdigest()
    return [
        _pending_row(
            authoring_by_id[record_id],
            repair_by_id[record_id],
            overlay_by_id[record_id],
            authoring_sha256,
            repair_sha256,
            overlay_sha256,
        )
        for record_id in sorted(repair_by_id)
    ]


def _pending_row(
    authored: dict[str, Any],
    repair: dict[str, Any],
    overlay: dict[str, Any],
    authoring_sha256: str,
    repair_sha256: str,
    overlay_sha256: str,
) -> dict[str, object]:
    replacement = authored.get("replacement")
    if not isinstance(replacement, dict) or replacement != overlay.get("replacement"):
        raise RuntimeError(f"{authored.get('record_id')}: authoring and overlay differ")
    text = replacement.get("text")
    if not isinstance(text, str):
        raise RuntimeError(f"{authored.get('record_id')}: replacement text is invalid")
    if overlay.get("replacement_text_sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest():
        raise RuntimeError(f"{authored.get('record_id')}: replacement hash is invalid")
    if authored.get("target") != overlay.get("target"):
        raise RuntimeError(f"{authored.get('record_id')}: authoring and overlay target differ")
    repair_reasons = repair.get("repair_reasons")
    if not isinstance(repair_reasons, list) or not all(
        isinstance(reason, str) for reason in repair_reasons
    ):
        raise RuntimeError(f"{authored.get('record_id')}: repair reasons are invalid")
    preserve = authored.get("preserve")
    if not isinstance(preserve, dict):
        raise RuntimeError(f"{authored.get('record_id')}: preserved identity is invalid")
    language = preserve.get("language_class")
    if not isinstance(language, str):
        raise RuntimeError(f"{authored.get('record_id')}: language class is invalid")
    return {
        "targeted_review_schema_version": _SCHEMA_VERSION,
        "review_scope": "all_corpus_v4_replacements",
        "review_status": "pending_human_review",
        "reviewer_id": "",
        "review_source_sha256": authoring_sha256,
        "repair_set_sha256": repair_sha256,
        "overlay_sha256": overlay_sha256,
        "record_id": authored["record_id"],
        "language_class": language,
        "repair_reasons": repair_reasons,
        "source": authored["source"],
        "target": authored["target"],
        "replacement": replacement,
        "replacement_text_sha256": overlay["replacement_text_sha256"],
        **{score: None for score in _SCORES},
        "notes": "",
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


def _load_object(value: bytes, name: str) -> dict[str, Any]:
    result = json.loads(value)
    if not isinstance(result, dict):
        raise RuntimeError(f"{name} is not an object")
    return result


def _by_id(value: object, name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise RuntimeError(f"{name} records are invalid")
    result = {}
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("record_id"), str):
            raise RuntimeError(f"{name} has an invalid record")
        record_id = row["record_id"]
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
