"""Derive a real discovery prefill-length histogram from validated records."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--runtime-profile-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validation = _load_object(args.validation)
    if validation.get("route_acceptance_pass") is not True:
        raise RuntimeError("validated records must pass the exact route contract")
    rows = _load_rows(args.records)
    histogram = Counter()
    for row in rows:
        route = row.get("first_chunk_route")
        length = route.get("talker_prefill_length") if isinstance(route, dict) else None
        if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
            raise RuntimeError(f"{row.get('record_id')}: invalid talker_prefill_length")
        histogram[length] += 1
    result = {
        "qwen_discovery_shape_summary_schema_version": 1,
        "evidence_source": "real_discovery",
        "input_valid": validation.get("route_acceptance_pass") is True,
        "generation_acceptance_pass": validation.get("generation_acceptance_pass") is True,
        "corpus_id": validation.get("corpus_id"),
        "runtime_profile_id": args.runtime_profile_id,
        "input_record_count": len(rows),
        "records_sha256": hashlib.sha256(args.records.read_bytes()).hexdigest(),
        "validation_sha256": hashlib.sha256(args.validation.read_bytes()).hexdigest(),
        "length_histogram": {str(length): histogram[length] for length in sorted(histogram)},
        "research_note": (
            "This is an offline shape distribution artifact only. It cannot "
            "authorize a padded runtime route or release configuration."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _load_rows(path: Path) -> list[dict[str, object]]:
    result = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"records line {line_number} must be an object")
        result.append(value)
    if not result:
        raise RuntimeError("records must not be empty")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
