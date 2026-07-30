"""Evaluate a completed structured human review against corpus quality gates."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

_BOOLEAN_FIELDS = {
    "category_fidelity",
    "naturalness",
    "likely_real_usage",
    "semantic_repetition_acceptable",
    "appropriate_length",
    "grammar",
    "generic_experiment_phrasing",
}
_REQUIRED_FIELDS = _BOOLEAN_FIELDS | {
    "review_schema_version",
    "label",
    "language_class",
    "review_status",
    "reviewer_id",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-natural-percent", type=float, default=90.0)
    parser.add_argument("--minimum-category-percent", type=float, default=90.0)
    parser.add_argument("--maximum-unacceptable-mixed-percent", type=float, default=5.0)
    parser.add_argument(
        "--maximum-generic-experiment-percent", type=float, default=10.0
    )
    args = parser.parse_args()
    _validate_thresholds(parser, args)
    records = _load_records(args.input)
    summary = _evaluate(records, args)
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
        args.maximum_unacceptable_mixed_percent,
        args.maximum_generic_experiment_percent,
    )
    if any(not 0.0 <= value <= 100.0 for value in values):
        parser.error("all review thresholds must be within 0..100")


def _load_records(path: Path) -> list[dict[str, object]]:
    records = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"review line {line_number} is not an object")
        _validate_record(value, line_number)
        records.append(value)
    if not records:
        raise RuntimeError("review contains no records")
    return records


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


def _evaluate(
    records: list[dict[str, object]], args: argparse.Namespace
) -> dict[str, object]:
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
        "natural_usable": _percent(true_counts["naturalness"], count),
        "category_correct": _percent(true_counts["category_fidelity"], count),
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
    passed = (
        percentages["natural_usable"] >= args.minimum_natural_percent
        and percentages["category_correct"] >= args.minimum_category_percent
        and percentages["unacceptable_mixed_language"]
        <= args.maximum_unacceptable_mixed_percent
        and percentages["generic_experiment_phrasing"]
        <= args.maximum_generic_experiment_percent
    )
    return {
        "manual_review_schema_version": 1,
        "review_record_count": count,
        "mixed_language_record_count": len(mixed),
        "percentages": percentages,
        "thresholds": {
            "minimum_natural_percent": args.minimum_natural_percent,
            "minimum_category_percent": args.minimum_category_percent,
            "maximum_unacceptable_mixed_percent": (
                args.maximum_unacceptable_mixed_percent
            ),
            "maximum_generic_experiment_percent": (
                args.maximum_generic_experiment_percent
            ),
        },
        "passed": passed,
        "status": "passed" if passed else "failed_needs_revision",
    }


def _percent(count: int, total: int) -> float:
    return count * 100.0 / total if total else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
