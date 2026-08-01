"""Publish a descriptive-only offline holdout report for a frozen allowlist."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_bytes()
    output = _json_bytes(_publish(_load_object(source), _sha256(source)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    return 0


def _publish(source: dict[str, object], source_sha256: str) -> dict[str, object]:
    required = (
        "by_category",
        "by_language_class",
        "by_prefill_length",
        "by_route",
        "candidate_exact_lengths",
        "coverage",
        "record_count",
    )
    missing = [key for key in required if key not in source]
    if missing:
        raise ValueError(f"source report lacks {missing}")
    return {
        "frequency_offline_holdout_report_schema_version": 1,
        "measurement_role": "descriptive_only_not_for_allowlist_retuning",
        "source_holdout_route_report_sha256": source_sha256,
        "record_count": source["record_count"],
        "candidate_exact_lengths": source["candidate_exact_lengths"],
        "by_route": source["by_route"],
        "by_prefill_length": source["by_prefill_length"],
        "by_category": source["by_category"],
        "by_language_class": source["by_language_class"],
        "coverage": source["coverage"],
        "legacy_exact_lengths_descriptive_only": source.get(
            "legacy_exact_lengths_descriptive_only"
        ),
        "notes": [
            "The holdout was not used to select or retune exact lengths.",
            "Legacy coverage is counterfactual and descriptive only.",
            "Unknown exact lengths remain eager rather than rejected.",
        ],
    }


def _load_object(value: bytes) -> dict[str, object]:
    parsed = json.loads(value.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("source report is not an object")
    return parsed


def _json_bytes(value: dict[str, object]) -> bytes:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
