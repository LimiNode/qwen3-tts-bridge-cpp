"""Create a structured human-review form from a frozen corpus sample."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

_REVIEW_SCHEMA_VERSION = 1
_REQUIRED_SOURCE_FIELDS = {
    "label",
    "category",
    "language_class",
    "intended_length_class",
    "text",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.input.read_bytes()
    records = _load_source_records(source)
    review_form = [_review_record(record, source) for record in records]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in review_form
        ),
        encoding="utf-8",
    )
    return 0


def _load_source_records(source: bytes) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(source.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"input line {line_number} is not an object")
        if _REQUIRED_SOURCE_FIELDS.difference(value):
            raise RuntimeError(f"input line {line_number} is missing review fields")
        records.append(value)
    if not records:
        raise RuntimeError("input sample contains no records")
    return records


def _review_record(record: dict[str, object], source: bytes) -> dict[str, object]:
    return {
        "review_schema_version": _REVIEW_SCHEMA_VERSION,
        "source_sample_sha256": sha256(source).hexdigest(),
        "label": record["label"],
        "category": record["category"],
        "language_class": record["language_class"],
        "intended_length_class": record["intended_length_class"],
        "text": record["text"],
        "review_status": "pending_human_review",
        "reviewer_id": "",
        "category_fidelity": None,
        "naturalness": None,
        "likely_real_usage": None,
        "code_switch_naturalness": None,
        "semantic_repetition_acceptable": None,
        "appropriate_length": None,
        "grammar": None,
        "generic_experiment_phrasing": None,
        "notes": "",
    }


if __name__ == "__main__":
    raise SystemExit(main())
