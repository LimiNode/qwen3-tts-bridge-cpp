"""Fail closed when evaluating the completed corpus-v4 targeted review."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from scripts.prepare_corpus_v4_targeted_review import _SCHEMA_VERSION, _prepare_rows
except ModuleNotFoundError:
    from prepare_corpus_v4_targeted_review import _SCHEMA_VERSION, _prepare_rows

_TRUE_FIELDS = (
    "naturalness",
    "likely_real_usage",
    "category_fidelity",
    "scene_context_fidelity",
    "speech_intent_fidelity",
    "appropriate_length",
    "grammar",
    "semantic_repetition_acceptable",
)
_FALSE_FIELDS = ("generic_ai_phrasing", "metadata_only_replacement")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--authoring", type=Path, required=True)
    parser.add_argument("--repair-set", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = _prepare_rows(
        args.authoring.read_bytes(), args.repair_set.read_bytes(), args.overlay.read_bytes()
    )
    review = _load_jsonl(args.input)
    summary = _evaluate(review, expected)
    _write_object(args.output, summary)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["passed"] else 1


def _evaluate(
    review: list[dict[str, Any]], expected: list[dict[str, object]]
) -> dict[str, object]:
    expected_by_id = _by_id(expected, "expected review")
    review_by_id = _by_id(review, "review")
    if set(review_by_id) != set(expected_by_id):
        raise RuntimeError("review record IDs do not match the targeted form")
    reviewers = set()
    failures: dict[str, list[str]] = {}
    for record_id in sorted(expected_by_id):
        row = review_by_id[record_id]
        template = expected_by_id[record_id]
        record_failures = _record_failures(row, template)
        if record_failures:
            failures[record_id] = record_failures
        else:
            reviewers.add(str(row["reviewer_id"]))
    if not failures and len(reviewers) != 1:
        failures["review"] = ["reviewer_id_must_be_one_nonempty_value"]
    checks = Counter(
        reason
        for record_failures in failures.values()
        for reason in record_failures
    )
    return {
        "targeted_repair_review_summary_schema_version": 2,
        "review_scope": "all_corpus_v4_replacements",
        "review_record_count": len(review),
        "reviewer_id": next(iter(reviewers), ""),
        "repair_set_sha256": expected[0]["repair_set_sha256"],
        "overlay_sha256": expected[0]["overlay_sha256"],
        "review_form_sha256": _rows_sha256(review),
        "checks": dict(sorted(checks.items())),
        "record_failures": failures,
        "passed": not failures,
        "status": "passed" if not failures else "failed_needs_human_review",
    }


def _record_failures(
    row: dict[str, Any], template: dict[str, object]
) -> list[str]:
    failures = []
    if set(row) != set(template):
        failures.append("schema")
        return failures
    identity_fields = set(template).difference(
        {
            "review_status",
            "reviewer_id",
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
            "notes",
        }
    )
    if any(row[field] != template[field] for field in identity_fields):
        failures.append("provenance_or_content_mismatch")
    if row["targeted_review_schema_version"] != _SCHEMA_VERSION:
        failures.append("unsupported_schema")
    if row["review_status"] != "completed_human_review":
        failures.append("not_completed_human_review")
    if not isinstance(row["reviewer_id"], str) or not row["reviewer_id"].strip():
        failures.append("missing_reviewer_id")
    for field in _TRUE_FIELDS:
        if row[field] is not True:
            failures.append(field)
    for field in _FALSE_FIELDS:
        if row[field] is not False:
            failures.append(field)
    if row["language_class"] == "mixed":
        if row["code_switch_naturalness"] is not True:
            failures.append("code_switch_naturalness")
    elif row["code_switch_naturalness"] is not None:
        failures.append("unexpected_code_switch_naturalness")
    return failures


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise RuntimeError(f"review line {line_number} is not an object")
        rows.append(row)
    if not rows:
        raise RuntimeError("review contains no records")
    return rows


def _by_id(rows: list[dict[str, Any]] | list[dict[str, object]], name: str) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        record_id = row.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise RuntimeError(f"{name} has an invalid record ID")
        if record_id in result:
            raise RuntimeError(f"{name} has duplicate record ID: {record_id}")
        result[record_id] = row
    return result


def _rows_sha256(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows).encode("utf-8")
    ).hexdigest()


def _write_object(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
