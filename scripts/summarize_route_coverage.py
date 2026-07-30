"""Summarize privacy-safe route coverage for an exact-shape canary."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

_SCHEMA_VERSION = 2
_COMPILED_ROUTE = "compiled_allowlist"
_COMPILED_BACKEND = "compile_reduce_overhead"
_COMPILED_SCHEDULE = [8, 8, 12]
_EAGER_ROUTE = "eager_unknown"
_EAGER_BACKEND = "eager"
_EAGER_SCHEDULE = [8]
_PROFILE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{7,127}")

_REQUIRED_KEYS = {
    "schema_version",
    "runtime_profile_id",
    "talker_prefill_length",
    "prefill_shape_policy",
    "prefill_backend_used",
    "selected_chunk_schedule",
    "prefill_cache_hit",
    "prefill_compile_attempted",
    "prefill_compile_fallback",
}
_OPTIONAL_NUMERIC_KEYS = {"first_audio_ms", "completed_ms", "inverse_rtf"}
_ALLOWED_KEYS = _REQUIRED_KEYS | _OPTIONAL_NUMERIC_KEYS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--runtime-profile-id", required=True)
    parser.add_argument("--compiled-length", action="append", type=int, required=True)
    parser.add_argument("--min-requests", type=int, default=500)
    parser.add_argument("--min-unknown-requests", type=int, default=100)
    parser.add_argument("--min-samples-per-length", type=int, default=30)
    parser.add_argument(
        "--min-eligible-unknown-coverage-percent", type=float, default=80.0
    )
    parser.add_argument("--min-exact-coverage-percent", type=float, default=90.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _validate_args(parser, args)

    records = _load_records(args.input)
    summary = _summarize(
        records,
        runtime_profile_id=args.runtime_profile_id,
        compiled_lengths=set(args.compiled_length),
        min_requests=args.min_requests,
        min_unknown_requests=args.min_unknown_requests,
        min_samples_per_length=args.min_samples_per_length,
        min_eligible_unknown_coverage_percent=(
            args.min_eligible_unknown_coverage_percent
        ),
        min_exact_coverage_percent=args.min_exact_coverage_percent,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["acceptance_pass"] else 1


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not _PROFILE_ID_PATTERN.fullmatch(args.runtime_profile_id):
        parser.error("--runtime-profile-id must be a stable anonymous identifier")
    if any(length <= 0 for length in args.compiled_length):
        parser.error("--compiled-length must be positive")
    if len(set(args.compiled_length)) != len(args.compiled_length):
        parser.error("--compiled-length values must be unique")
    counts = (
        args.min_requests,
        args.min_unknown_requests,
        args.min_samples_per_length,
    )
    if any(value <= 0 for value in counts):
        parser.error("minimum sample counts must be positive")
    percentages = (
        args.min_eligible_unknown_coverage_percent,
        args.min_exact_coverage_percent,
    )
    if any(not 0.0 <= value <= 100.0 for value in percentages):
        parser.error("coverage percentages must be within 0..100")


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
    if record["schema_version"] != _SCHEMA_VERSION:
        raise RuntimeError(f"line {line_number}: unsupported schema_version")
    profile_id = record["runtime_profile_id"]
    if not isinstance(profile_id, str) or not _PROFILE_ID_PATTERN.fullmatch(profile_id):
        raise RuntimeError(f"line {line_number}: invalid runtime_profile_id")
    length = record["talker_prefill_length"]
    if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
        raise RuntimeError(f"line {line_number}: invalid talker_prefill_length")
    if not isinstance(record["prefill_shape_policy"], str) or not isinstance(
        record["prefill_backend_used"], str
    ):
        raise RuntimeError(f"line {line_number}: invalid route metadata")
    schedule = record["selected_chunk_schedule"]
    if not isinstance(schedule, list) or any(
        not isinstance(step, int) or isinstance(step, bool) or step <= 0
        for step in schedule
    ):
        raise RuntimeError(f"line {line_number}: invalid selected_chunk_schedule")
    for key in (
        "prefill_cache_hit",
        "prefill_compile_attempted",
        "prefill_compile_fallback",
    ):
        if not isinstance(record[key], bool):
            raise RuntimeError(f"line {line_number}: {key} must be boolean")
    _validate_optional_metrics(record, line_number)


def _validate_optional_metrics(record: dict[str, object], line_number: int) -> None:
    for key in _OPTIONAL_NUMERIC_KEYS:
        if key not in record:
            continue
        value = record[key]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            raise RuntimeError(f"line {line_number}: {key} must be finite")
    first_audio = _optional_float(record, "first_audio_ms")
    completed = _optional_float(record, "completed_ms")
    inverse_rtf = _optional_float(record, "inverse_rtf")
    if first_audio is not None and first_audio < 0.0:
        raise RuntimeError(f"line {line_number}: first_audio_ms must be non-negative")
    if completed is not None and completed < 0.0:
        raise RuntimeError(f"line {line_number}: completed_ms must be non-negative")
    if first_audio is not None and completed is not None and completed < first_audio:
        raise RuntimeError(f"line {line_number}: completed_ms precedes first_audio_ms")
    if inverse_rtf is not None and inverse_rtf <= 0.0:
        raise RuntimeError(f"line {line_number}: inverse_rtf must be positive")


def _optional_float(record: dict[str, object], key: str) -> float | None:
    value = record.get(key)
    if value is None:
        return None
    assert isinstance(value, (int, float))
    assert not isinstance(value, bool)
    return float(value)


def _route_errors(record: dict[str, object], compiled_lengths: set[int]) -> list[str]:
    length = _prefill_length(record)
    route = record["prefill_shape_policy"]
    backend = record["prefill_backend_used"]
    schedule = record["selected_chunk_schedule"]
    cache_hit = record["prefill_cache_hit"]
    attempted = record["prefill_compile_attempted"]
    fallback = record["prefill_compile_fallback"]
    if length in compiled_lengths:
        expected = (
            route == _COMPILED_ROUTE
            and backend == _COMPILED_BACKEND
            and schedule == _COMPILED_SCHEDULE
            and cache_hit is True
            and attempted is False
            and fallback is False
        )
        return [] if expected else ["compiled_contract_mismatch"]
    expected = (
        route == _EAGER_ROUTE
        and backend == _EAGER_BACKEND
        and schedule == _EAGER_SCHEDULE
        and cache_hit is False
        and attempted is False
        and fallback is False
    )
    return [] if expected else ["eager_contract_mismatch"]


def _prefill_length(record: dict[str, object]) -> int:
    length = record["talker_prefill_length"]
    assert isinstance(length, int)
    assert not isinstance(length, bool)
    return length


def _summarize(
    records: list[dict[str, object]],
    *,
    runtime_profile_id: str,
    compiled_lengths: set[int],
    min_requests: int,
    min_unknown_requests: int,
    min_samples_per_length: int,
    min_eligible_unknown_coverage_percent: float,
    min_exact_coverage_percent: float,
) -> dict[str, object]:
    invalid_routes = Counter()
    profile_mismatch_count = 0
    valid_records = []
    for record in records:
        if record["runtime_profile_id"] != runtime_profile_id:
            profile_mismatch_count += 1
            continue
        errors = _route_errors(record, compiled_lengths)
        if errors:
            invalid_routes.update(errors)
            continue
        valid_records.append(record)

    lengths = Counter(
        _prefill_length(record) for record in valid_records
    )
    routes = Counter(str(record["prefill_shape_policy"]) for record in valid_records)
    total = len(valid_records)
    exact_count = sum(
        count for length, count in lengths.items() if length in compiled_lengths
    )
    exact_coverage_percent = exact_count * 100.0 / total if total else 0.0
    unknown_lengths = {
        length: count
        for length, count in lengths.items()
        if length not in compiled_lengths
    }
    unknown_count = sum(unknown_lengths.values())
    eligible_unknown_lengths = {
        length: count
        for length, count in unknown_lengths.items()
        if count >= min_samples_per_length
    }
    eligible_unknown_count = sum(eligible_unknown_lengths.values())
    eligible_unknown_coverage_percent = (
        eligible_unknown_count * 100.0 / unknown_count if unknown_count else 0.0
    )
    material_unknown_lengths = {
        length: count
        for length, count in unknown_lengths.items()
        if count * 100.0 / total >= 1.0
    }
    acceptance_pass = not invalid_routes and profile_mismatch_count == 0 and total > 0
    decision = _decision(
        acceptance_pass=acceptance_pass,
        total=total,
        unknown_count=unknown_count,
        exact_coverage_percent=exact_coverage_percent,
        eligible_unknown_coverage_percent=eligible_unknown_coverage_percent,
        min_requests=min_requests,
        min_unknown_requests=min_unknown_requests,
        min_exact_coverage_percent=min_exact_coverage_percent,
        min_eligible_unknown_coverage_percent=(
            min_eligible_unknown_coverage_percent
        ),
    )
    return {
        "artifact_schema_version": _SCHEMA_VERSION,
        "acceptance_pass": acceptance_pass,
        "runtime_profile_id": runtime_profile_id,
        "input_record_count": len(records),
        "valid_record_count": total,
        "invalid_route_count": sum(invalid_routes.values()),
        "invalid_route_reasons": dict(sorted(invalid_routes.items())),
        "profile_mismatch_count": profile_mismatch_count,
        "compiled_lengths": sorted(compiled_lengths),
        "exact_allowlist_count": exact_count,
        "exact_allowlist_coverage_percent": exact_coverage_percent,
        "unknown_request_count": unknown_count,
        "length_histogram": _histogram(lengths),
        "unknown_length_histogram": _histogram(unknown_lengths),
        "eligible_unknown_length_histogram": _histogram(eligible_unknown_lengths),
        "material_unknown_length_histogram": _histogram(material_unknown_lengths),
        "eligible_unknown_coverage_percent": eligible_unknown_coverage_percent,
        "route_histogram": dict(sorted(routes.items())),
        "thresholds": {
            "min_requests": min_requests,
            "min_unknown_requests": min_unknown_requests,
            "min_samples_per_length": min_samples_per_length,
            "min_eligible_unknown_coverage_percent": (
                min_eligible_unknown_coverage_percent
            ),
            "min_exact_coverage_percent": min_exact_coverage_percent,
        },
        "decision": decision,
    }


def _histogram(values: dict[int, int] | Counter[int]) -> dict[str, int]:
    return {str(length): count for length, count in sorted(values.items())}


def _decision(
    *,
    acceptance_pass: bool,
    total: int,
    unknown_count: int,
    exact_coverage_percent: float,
    eligible_unknown_coverage_percent: float,
    min_requests: int,
    min_unknown_requests: int,
    min_exact_coverage_percent: float,
    min_eligible_unknown_coverage_percent: float,
) -> str:
    if not acceptance_pass:
        return "reject_invalid_canary"
    if total < min_requests:
        return "collect_more_anonymous_coverage"
    if exact_coverage_percent >= min_exact_coverage_percent:
        return "keep_exact_allowlist"
    if unknown_count < min_unknown_requests:
        return "collect_more_anonymous_coverage"
    if eligible_unknown_coverage_percent < min_eligible_unknown_coverage_percent:
        return "collect_more_anonymous_coverage"
    return "evaluate_padded_bucket_correctness"


if __name__ == "__main__":
    raise SystemExit(main())
