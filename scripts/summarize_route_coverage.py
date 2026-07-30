"""Summarize privacy-safe route coverage telemetry for exact-shape policies."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

_REQUIRED_KEYS = {
    "schema_version",
    "talker_prefill_length",
    "prefill_shape_policy",
    "prefill_backend_used",
    "selected_chunk_schedule",
}
_ALLOWED_KEYS = _REQUIRED_KEYS | {
    "first_audio_ms",
    "completed_ms",
    "inverse_rtf",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--compiled-length", action="append", type=int, required=True)
    parser.add_argument("--min-requests", type=int, default=500)
    parser.add_argument("--min-samples-per-length", type=int, default=30)
    parser.add_argument("--min-exact-coverage-percent", type=float, default=90.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if any(length <= 0 for length in args.compiled_length):
        parser.error("--compiled-length must be positive")
    if len(set(args.compiled_length)) != len(args.compiled_length):
        parser.error("--compiled-length values must be unique")
    if args.min_requests <= 0 or args.min_samples_per_length <= 0:
        parser.error("minimum sample counts must be positive")
    if not 0.0 <= args.min_exact_coverage_percent <= 100.0:
        parser.error("--min-exact-coverage-percent must be within 0..100")

    records = _load_records(args.input)
    summary = _summarize(
        records,
        compiled_lengths=set(args.compiled_length),
        min_requests=args.min_requests,
        min_samples_per_length=args.min_samples_per_length,
        min_exact_coverage_percent=args.min_exact_coverage_percent,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


def _load_records(path: Path) -> list[dict[str, object]]:
    records = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise RuntimeError(f"line {line_number}: record must be an object")
        _validate_record(record, line_number)
        records.append(record)
    if not records:
        raise RuntimeError("telemetry input contains no records")
    return records


def _validate_record(record: dict[str, object], line_number: int) -> None:
    unknown = set(record).difference(_ALLOWED_KEYS)
    missing = _REQUIRED_KEYS.difference(record)
    if unknown or missing:
        raise RuntimeError(
            f"line {line_number}: telemetry keys must be the approved anonymous schema"
        )
    if record["schema_version"] != 1:
        raise RuntimeError(f"line {line_number}: unsupported schema_version")
    if not isinstance(record["talker_prefill_length"], int) or record[
        "talker_prefill_length"
    ] <= 0:
        raise RuntimeError(f"line {line_number}: invalid talker_prefill_length")
    if not isinstance(record["prefill_shape_policy"], str) or not isinstance(
        record["prefill_backend_used"], str
    ):
        raise RuntimeError(f"line {line_number}: invalid route metadata")
    schedule = record["selected_chunk_schedule"]
    if not isinstance(schedule, list) or any(
        not isinstance(step, int) or step <= 0 for step in schedule
    ):
        raise RuntimeError(f"line {line_number}: invalid selected_chunk_schedule")


def _summarize(
    records: list[dict[str, object]],
    *,
    compiled_lengths: set[int],
    min_requests: int,
    min_samples_per_length: int,
    min_exact_coverage_percent: float,
) -> dict[str, object]:
    lengths = Counter(int(record["talker_prefill_length"]) for record in records)
    routes = Counter(str(record["prefill_shape_policy"]) for record in records)
    total = len(records)
    exact_count = sum(
        count for length, count in lengths.items() if length in compiled_lengths
    )
    exact_coverage_percent = exact_count * 100.0 / total
    unknown_lengths = {
        str(length): count
        for length, count in sorted(lengths.items())
        if length not in compiled_lengths
    }
    enough_total = total >= min_requests
    enough_per_length = all(
        count >= min_samples_per_length for count in unknown_lengths.values()
    )
    enough_coverage = exact_coverage_percent >= min_exact_coverage_percent
    decision = "keep_exact_allowlist"
    if not enough_total or not enough_per_length:
        decision = "collect_more_anonymous_coverage"
    elif not enough_coverage and unknown_lengths:
        decision = "evaluate_padded_bucket_correctness"
    return {
        "artifact_schema_version": 1,
        "record_count": total,
        "compiled_lengths": sorted(compiled_lengths),
        "exact_allowlist_count": exact_count,
        "exact_allowlist_coverage_percent": exact_coverage_percent,
        "length_histogram": {
            str(length): count for length, count in sorted(lengths.items())
        },
        "unknown_length_histogram": unknown_lengths,
        "route_histogram": dict(sorted(routes.items())),
        "thresholds": {
            "min_requests": min_requests,
            "min_samples_per_length": min_samples_per_length,
            "min_exact_coverage_percent": min_exact_coverage_percent,
        },
        "decision": decision,
    }


if __name__ == "__main__":
    raise SystemExit(main())
