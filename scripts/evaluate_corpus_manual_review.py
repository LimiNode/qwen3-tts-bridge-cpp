"""Fail closed when evaluating a completed corpus human-review form."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_REVIEW_RECORD_COUNT = 100
_BOOLEAN_FIELDS = {
    "category_fidelity",
    "naturalness",
    "likely_real_usage",
    "semantic_repetition_acceptable",
    "appropriate_length",
    "grammar",
    "generic_experiment_phrasing",
}
_SOURCE_IDENTITY_FIELDS = (
    "label",
    "category",
    "language_class",
    "intended_length_class",
    "text",
)
_REQUIRED_FIELDS = _BOOLEAN_FIELDS | {
    "review_schema_version",
    "source_sample_sha256",
    "review_status",
    "reviewer_id",
    *_SOURCE_IDENTITY_FIELDS,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--frozen-sample", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-natural-percent", type=float, default=90.0)
    parser.add_argument("--minimum-category-percent", type=float, default=90.0)
    parser.add_argument("--minimum-likely-real-usage-percent", type=float, default=90.0)
    parser.add_argument("--minimum-repetition-percent", type=float, default=90.0)
    parser.add_argument(
        "--minimum-appropriate-length-percent", type=float, default=95.0
    )
    parser.add_argument("--minimum-grammar-percent", type=float, default=95.0)
    parser.add_argument("--maximum-unacceptable-mixed-percent", type=float, default=5.0)
    parser.add_argument(
        "--maximum-generic-experiment-percent", type=float, default=10.0
    )
    args = parser.parse_args()
    _validate_thresholds(parser, args)
    review = _load_records(args.input, "review")
    frozen_bytes = args.frozen_sample.read_bytes()
    frozen = _load_records(args.frozen_sample, "frozen sample", validate_review=False)
    audit = _load_object(args.audit, "audit")
    provenance = _validate_contract(review, frozen, frozen_bytes, audit)
    summary = _evaluate(review, args, provenance)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["passed"] else 1


def _validate_thresholds(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    values = (
        args.minimum_natural_percent,
        args.minimum_category_percent,
        args.minimum_likely_real_usage_percent,
        args.minimum_repetition_percent,
        args.minimum_appropriate_length_percent,
        args.minimum_grammar_percent,
        args.maximum_unacceptable_mixed_percent,
        args.maximum_generic_experiment_percent,
    )
    if any(not 0.0 <= value <= 100.0 for value in values):
        parser.error("all review thresholds must be within 0..100")


def _load_records(
    path: Path, name: str, *, validate_review: bool = True
) -> list[dict[str, object]]:
    records = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"{name} line {line_number} is not an object")
        if validate_review:
            _validate_record(value, line_number)
        records.append(value)
    if not records:
        raise RuntimeError(f"{name} contains no records")
    return records


def _load_object(path: Path, name: str) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return value


def _validate_record(record: dict[str, object], line_number: int) -> None:
    missing = _REQUIRED_FIELDS.difference(record)
    if missing:
        raise RuntimeError(f"review line {line_number} is missing required fields")
    if record["review_schema_version"] != 1:
        raise RuntimeError(f"review line {line_number} has unsupported schema")
    if record["review_status"] != "completed_human_review":
        raise RuntimeError(f"review line {line_number} is not completed")
    if not isinstance(record["reviewer_id"], str) or not record["reviewer_id"].strip():
        raise RuntimeError(f"review line {line_number} has no reviewer_id")
    if not isinstance(record["source_sample_sha256"], str):
        raise RuntimeError(f"review line {line_number} has invalid source hash")
    for field in _BOOLEAN_FIELDS:
        if not isinstance(record[field], bool):
            raise RuntimeError(f"review line {line_number} has invalid {field}")
    language = record["language_class"]
    if language == "mixed":
        if not isinstance(record.get("code_switch_naturalness"), bool):
            raise RuntimeError(
                f"review line {line_number} has invalid code-switch score"
            )
    elif record.get("code_switch_naturalness") is not None:
        raise RuntimeError(
            f"review line {line_number} has unexpected code-switch score"
        )


def _validate_contract(
    review: list[dict[str, object]],
    frozen: list[dict[str, object]],
    frozen_bytes: bytes,
    audit: Mapping[str, object],
) -> dict[str, Any]:
    if len(review) != _REVIEW_RECORD_COUNT or len(frozen) != _REVIEW_RECORD_COUNT:
        raise RuntimeError(
            "review and frozen sample must each contain exactly 100 records"
        )
    frozen_hash = hashlib.sha256(frozen_bytes).hexdigest()
    review_labels = _unique_labels(review, "review")
    frozen_labels = _unique_labels(frozen, "frozen sample")
    if review_labels != frozen_labels:
        raise RuntimeError("review labels do not match the frozen sample")
    if {record["source_sample_sha256"] for record in review} != {frozen_hash}:
        raise RuntimeError("review source hash does not match the frozen sample")
    if {record["reviewer_id"] for record in review}.__len__() != 1:
        raise RuntimeError("review must have exactly one reviewer_id")
    frozen_by_label = {str(record["label"]): record for record in frozen}
    for record in review:
        source = frozen_by_label[str(record["label"])]
        if any(record[field] != source.get(field) for field in _SOURCE_IDENTITY_FIELDS):
            raise RuntimeError(
                f"review label {record['label']} does not match frozen content"
            )
    if audit.get("manual_review_sha256") != frozen_hash:
        raise RuntimeError("audit does not pin the frozen sample hash")
    corpus_ids = {record.get("corpus_id") for record in frozen}
    if len(corpus_ids) != 1 or audit.get("corpus_id") not in corpus_ids:
        raise RuntimeError("audit corpus_id does not match the frozen sample")
    return {
        "corpus_id": next(iter(corpus_ids)),
        "frozen_sample_sha256": frozen_hash,
        "audit_sha256": hashlib.sha256(
            json.dumps(audit, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "generator_source_sha256": audit.get("generator_source_sha256"),
        "generation_config_sha256": audit.get("generation_config_sha256"),
        "reviewer_id": review[0]["reviewer_id"],
    }


def _unique_labels(records: list[dict[str, object]], name: str) -> set[str]:
    labels = [record.get("label") for record in records]
    if any(not isinstance(label, str) or not label for label in labels):
        raise RuntimeError(f"{name} has an invalid label")
    result = {str(label) for label in labels}
    if len(result) != len(labels):
        raise RuntimeError(f"{name} has duplicate labels")
    return result


def _evaluate(
    records: list[dict[str, object]],
    args: argparse.Namespace,
    provenance: Mapping[str, object],
) -> dict[str, Any]:
    count = len(records)
    true_counts = Counter(
        field
        for field in _BOOLEAN_FIELDS
        for record in records
        if record[field] is True
    )
    mixed = [record for record in records if record["language_class"] == "mixed"]
    unacceptable_mixed = sum(
        record["code_switch_naturalness"] is False for record in mixed
    )
    percentages = {
        "naturalness": _percent(true_counts["naturalness"], count),
        "category_fidelity": _percent(true_counts["category_fidelity"], count),
        "likely_real_usage": _percent(true_counts["likely_real_usage"], count),
        "semantic_repetition_acceptable": _percent(
            true_counts["semantic_repetition_acceptable"], count
        ),
        "appropriate_length": _percent(true_counts["appropriate_length"], count),
        "grammar": _percent(true_counts["grammar"], count),
        "generic_experiment_phrasing": _percent(
            true_counts["generic_experiment_phrasing"], count
        ),
        "unacceptable_mixed_language": _percent(unacceptable_mixed, len(mixed)),
    }
    checks = {
        "naturalness": percentages["naturalness"] >= args.minimum_natural_percent,
        "category_fidelity": percentages["category_fidelity"]
        >= args.minimum_category_percent,
        "likely_real_usage": percentages["likely_real_usage"]
        >= args.minimum_likely_real_usage_percent,
        "semantic_repetition": percentages["semantic_repetition_acceptable"]
        >= args.minimum_repetition_percent,
        "appropriate_length": percentages["appropriate_length"]
        >= args.minimum_appropriate_length_percent,
        "grammar": percentages["grammar"] >= args.minimum_grammar_percent,
        "mixed_language": percentages["unacceptable_mixed_language"]
        <= args.maximum_unacceptable_mixed_percent,
        "generic_experiment_phrasing": percentages["generic_experiment_phrasing"]
        <= args.maximum_generic_experiment_percent,
    }
    return {
        "manual_review_schema_version": 2,
        "review_record_count": count,
        "mixed_language_record_count": len(mixed),
        "percentages": percentages,
        "checks": checks,
        "thresholds": {
            "minimum_natural_percent": args.minimum_natural_percent,
            "minimum_category_percent": args.minimum_category_percent,
            "minimum_likely_real_usage_percent": args.minimum_likely_real_usage_percent,
            "minimum_repetition_percent": args.minimum_repetition_percent,
            "minimum_appropriate_length_percent": (
                args.minimum_appropriate_length_percent
            ),
            "minimum_grammar_percent": args.minimum_grammar_percent,
            "maximum_unacceptable_mixed_percent": (
                args.maximum_unacceptable_mixed_percent
            ),
            "maximum_generic_experiment_percent": (
                args.maximum_generic_experiment_percent
            ),
        },
        "passed": all(checks.values()),
        "status": "passed" if all(checks.values()) else "failed_needs_revision",
        **provenance,
    }


def _percent(count: int, total: int) -> float:
    return count * 100.0 / total if total else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
