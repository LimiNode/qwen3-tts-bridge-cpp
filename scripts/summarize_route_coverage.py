"""Validate and summarize privacy-safe route-aware canary telemetry."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from collections import Counter
from hashlib import sha256
from pathlib import Path

_SCHEMA_VERSION = 3
_VALIDATOR_SCHEMA_VERSION = 1
_REPO_ROOT = Path(__file__).resolve().parents[1]
_COMPILED_ROUTE = "compiled_allowlist"
_COMPILED_BACKEND = "compile_reduce_overhead"
_COMPILED_SCHEDULE = [8, 8, 12]
_EAGER_ROUTE = "eager_unknown"
_EAGER_BACKEND = "eager"
_EAGER_SCHEDULE = [8]
_PROFILE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{7,127}")
_OUTCOMES = {
    "completed",
    "cancelled_before_audio",
    "cancelled_after_audio",
    "failed",
}
_EVIDENCE_SOURCES = {"synthetic_proxy", "internal_real_traffic"}
_BASE_KEYS = {
    "schema_version",
    "runtime_profile_id",
    "evidence_source",
    "request_outcome",
    "route_decision_made",
}
_ROUTE_KEYS = {
    "talker_prefill_length",
    "prefill_shape_policy",
    "prefill_backend_used",
    "selected_chunk_schedule",
    "prefill_cache_hit",
    "prefill_compile_attempted",
    "prefill_compile_fallback",
}
_LATENCY_KEYS = {"first_audio_ms", "completed_ms", "inverse_rtf"}
_ALLOWED_KEYS = _BASE_KEYS | _ROUTE_KEYS | _LATENCY_KEYS
_PROFILE_MANIFEST_FIELDS = {
    "manifest_schema_version",
    "runtime_profile_id",
    "bridge_commit",
    "faster_wheel_sha256",
    "qwen_commit",
    "model_revision",
    "torch_version",
    "cuda_version",
    "compiled_allowlist_manifest_sha256",
}
_ALLOWLIST_MANIFEST_FIELDS = {
    "manifest_schema_version",
    "runtime_profile_id",
    "compiled_lengths",
    "compiled_route",
    "compiled_backend",
    "compiled_schedule",
    "eager_route",
    "eager_backend",
    "eager_schedule",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--runtime-profile-id", required=True)
    parser.add_argument("--runtime-profile-manifest", type=Path, required=True)
    parser.add_argument("--compiled-allowlist-manifest", type=Path, required=True)
    parser.add_argument("--compiled-length", action="append", type=int, required=True)
    parser.add_argument("--min-requests", type=int, default=500)
    parser.add_argument("--min-unknown-requests", type=int, default=100)
    parser.add_argument("--min-samples-per-length", type=int, default=30)
    parser.add_argument(
        "--min-eligible-unknown-coverage-percent", type=float, default=80.0
    )
    parser.add_argument("--min-exact-coverage-percent", type=float, default=90.0)
    parser.add_argument("--require-decision", choices=_decision_choices())
    parser.add_argument(
        "--require-evidence-source",
        choices=sorted(_EVIDENCE_SOURCES),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _validate_args(parser, args)
    provenance = _validate_manifest_provenance(args)
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
        required_evidence_source=args.require_evidence_source,
    )
    summary.update(
        {
            "input_sha256": _sha256(args.input),
            "validator_schema_version": _VALIDATOR_SCHEMA_VERSION,
            "validator_commit": _validator_commit(),
            "runtime_profile_manifest": provenance["runtime_profile_manifest"],
            "compiled_allowlist_manifest": provenance[
                "compiled_allowlist_manifest"
            ],
        }
    )
    if args.require_decision is not None:
        summary["required_decision"] = args.require_decision
        summary["required_decision_pass"] = (
            summary["decision"] == args.require_decision
        )
    if args.require_evidence_source is not None:
        summary["required_evidence_source"] = args.require_evidence_source
        summary["required_evidence_source_pass"] = (
            summary["evidence_source"] == args.require_evidence_source
            and summary["input_valid"] is True
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0 if _exit_success(summary) else 1


def _decision_choices() -> tuple[str, ...]:
    return (
        "collect_more_anonymous_coverage",
        "keep_exact_allowlist",
        "prototype_padded_bucket_correctness",
        "evaluate_padded_bucket_release_candidate",
    )


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


def _validate_manifest_provenance(args: argparse.Namespace) -> dict[str, object]:
    profile = _load_object(args.runtime_profile_manifest, "runtime profile manifest")
    allowlist = _load_object(
        args.compiled_allowlist_manifest,
        "compiled allowlist manifest",
    )
    _require_manifest_fields(profile, _PROFILE_MANIFEST_FIELDS, "runtime profile")
    _require_manifest_fields(
        allowlist,
        _ALLOWLIST_MANIFEST_FIELDS,
        "compiled allowlist",
    )
    if profile["manifest_schema_version"] != 1:
        raise RuntimeError("runtime profile manifest has an unsupported schema")
    if allowlist["manifest_schema_version"] != 1:
        raise RuntimeError("allowlist manifest has an unsupported schema")
    _validate_profile_identity_fields(profile)
    if profile.get("runtime_profile_id") != args.runtime_profile_id:
        raise RuntimeError(
            "runtime profile manifest does not match --runtime-profile-id"
        )
    if allowlist.get("runtime_profile_id") != args.runtime_profile_id:
        raise RuntimeError("allowlist manifest does not match --runtime-profile-id")
    configured_lengths = allowlist.get("compiled_lengths")
    if configured_lengths != sorted(args.compiled_length):
        raise RuntimeError("allowlist manifest does not match --compiled-length")
    expected_contract = {
        "compiled_route": _COMPILED_ROUTE,
        "compiled_backend": _COMPILED_BACKEND,
        "compiled_schedule": _COMPILED_SCHEDULE,
        "eager_route": _EAGER_ROUTE,
        "eager_backend": _EAGER_BACKEND,
        "eager_schedule": _EAGER_SCHEDULE,
    }
    if any(allowlist.get(key) != value for key, value in expected_contract.items()):
        raise RuntimeError("allowlist manifest does not match the canary contract")
    allowlist_sha = _sha256(args.compiled_allowlist_manifest)
    if profile.get("compiled_allowlist_manifest_sha256") != allowlist_sha:
        raise RuntimeError("runtime profile manifest does not pin the allowlist SHA")
    return {
        "runtime_profile_manifest": _provenance(args.runtime_profile_manifest),
        "compiled_allowlist_manifest": _provenance(args.compiled_allowlist_manifest),
    }


def _require_manifest_fields(
    manifest: dict[str, object],
    required: set[str],
    name: str,
) -> None:
    missing = sorted(required.difference(manifest))
    if missing:
        raise RuntimeError(f"{name} manifest is missing: {', '.join(missing)}")


def _validate_profile_identity_fields(profile: dict[str, object]) -> None:
    for key in _PROFILE_MANIFEST_FIELDS - {
        "manifest_schema_version",
        "runtime_profile_id",
    }:
        value = profile[key]
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"runtime profile manifest has invalid {key}")


def _load_object(path: Path, name: str) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must contain a JSON object")
    return value


def _load_records(path: Path) -> list[dict[str, object]]:
    records = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"line {line_number}: malformed JSON") from exc
        if not isinstance(record, dict):
            raise RuntimeError(f"line {line_number}: record must be an object")
        _validate_record(record, line_number)
        records.append(record)
    if not records:
        raise RuntimeError("telemetry input contains no records")
    return records


def _validate_record(record: dict[str, object], line_number: int) -> None:
    unknown = set(record).difference(_ALLOWED_KEYS)
    missing = _BASE_KEYS.difference(record)
    if unknown or missing:
        raise RuntimeError(
            f"line {line_number}: telemetry keys must be the approved anonymous schema"
        )
    if record["schema_version"] != _SCHEMA_VERSION:
        raise RuntimeError(f"line {line_number}: unsupported schema_version")
    profile_id = record["runtime_profile_id"]
    if not isinstance(profile_id, str) or not _PROFILE_ID_PATTERN.fullmatch(profile_id):
        raise RuntimeError(f"line {line_number}: invalid runtime_profile_id")
    outcome = record["request_outcome"]
    if outcome not in _OUTCOMES:
        raise RuntimeError(f"line {line_number}: invalid request_outcome")
    if record["evidence_source"] not in _EVIDENCE_SOURCES:
        raise RuntimeError(f"line {line_number}: invalid evidence_source")
    route_decision_made = record["route_decision_made"]
    if not isinstance(route_decision_made, bool):
        raise RuntimeError(f"line {line_number}: route_decision_made must be boolean")
    if outcome in {"completed", "cancelled_after_audio"} and not route_decision_made:
        raise RuntimeError(
            f"line {line_number}: {outcome} requires route_decision_made=true"
        )
    _validate_route_fields(record, line_number, route_decision_made)
    _validate_latency_fields(record, line_number, str(outcome))


def _validate_route_fields(
    record: dict[str, object],
    line_number: int,
    route_decision_made: bool,
) -> None:
    present = _ROUTE_KEYS.intersection(record)
    if not route_decision_made:
        if present:
            raise RuntimeError(
                f"line {line_number}: route fields require route_decision_made=true"
            )
        return
    if present != _ROUTE_KEYS:
        raise RuntimeError(f"line {line_number}: incomplete route decision fields")
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


def _validate_latency_fields(
    record: dict[str, object],
    line_number: int,
    outcome: str,
) -> None:
    present = _LATENCY_KEYS.intersection(record)
    if outcome != "completed":
        if present:
            raise RuntimeError(
                f"line {line_number}: latency fields require request_outcome=completed"
            )
        return
    if present != _LATENCY_KEYS:
        raise RuntimeError(
            f"line {line_number}: completed requires full latency fields"
        )
    values = {key: _finite_float(record[key], key, line_number) for key in present}
    if values["first_audio_ms"] < 0.0 or values["completed_ms"] < 0.0:
        raise RuntimeError(f"line {line_number}: latency values must be non-negative")
    if values["completed_ms"] < values["first_audio_ms"]:
        raise RuntimeError(f"line {line_number}: completed_ms precedes first_audio_ms")
    if values["inverse_rtf"] <= 0.0:
        raise RuntimeError(f"line {line_number}: inverse_rtf must be positive")


def _finite_float(value: object, key: str, line_number: int) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise RuntimeError(f"line {line_number}: {key} must be finite")
    return float(value)


def _route_error(record: dict[str, object], compiled_lengths: set[int]) -> str | None:
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
        return None if expected else "compiled_contract_mismatch"
    expected = (
        route == _EAGER_ROUTE
        and backend == _EAGER_BACKEND
        and schedule == _EAGER_SCHEDULE
        and cache_hit is False
        and attempted is False
        and fallback is False
    )
    return None if expected else "eager_contract_mismatch"


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
    required_evidence_source: str | None = None,
) -> dict[str, object]:
    invalid_routes = Counter[str]()
    profile_mismatch_count = 0
    route_decided_records = []
    outcome_counts = Counter[str]()
    evidence_sources = Counter[str]()
    for record in records:
        if record["runtime_profile_id"] != runtime_profile_id:
            profile_mismatch_count += 1
            continue
        outcome = str(record["request_outcome"])
        outcome_counts.update([outcome])
        evidence_sources.update([str(record["evidence_source"])])
        if record["route_decision_made"] is not True:
            continue
        error = _route_error(record, compiled_lengths)
        if error is not None:
            invalid_routes.update([error])
            continue
        route_decided_records.append(record)

    lengths = Counter(_prefill_length(record) for record in route_decided_records)
    routes = Counter(
        str(record["prefill_shape_policy"]) for record in route_decided_records
    )
    route_decided_count = len(route_decided_records)
    exact_count = sum(
        count for length, count in lengths.items() if length in compiled_lengths
    )
    exact_coverage_percent = (
        exact_count * 100.0 / route_decided_count if route_decided_count else 0.0
    )
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
        if count * 100.0 / route_decided_count >= 1.0
    }
    evidence_source = (
        next(iter(evidence_sources)) if len(evidence_sources) == 1 else "mixed"
    )
    source_mismatch_count = (
        sum(evidence_sources.values()) if len(evidence_sources) > 1 else 0
    )
    input_valid = (
        not invalid_routes
        and profile_mismatch_count == 0
        and source_mismatch_count == 0
    )
    evidence_gate_pass = _evidence_gate_pass(
        input_valid=input_valid,
        route_decided_count=route_decided_count,
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
    decision = _decision(
        input_valid=input_valid,
        evidence_gate_pass=evidence_gate_pass,
        exact_coverage_percent=exact_coverage_percent,
        min_exact_coverage_percent=min_exact_coverage_percent,
        evidence_source=evidence_source,
    )
    completed_records = [
        record
        for record in route_decided_records
        if record["request_outcome"] == "completed"
    ]
    return {
        "artifact_schema_version": _SCHEMA_VERSION,
        "input_valid": input_valid,
        "evidence_gate_pass": evidence_gate_pass,
        "runtime_profile_id": runtime_profile_id,
        "evidence_source": evidence_source,
        "evidence_source_histogram": dict(sorted(evidence_sources.items())),
        "required_evidence_source": required_evidence_source,
        "evidence_source_gate_pass": (
            required_evidence_source is None
            or (input_valid and evidence_source == required_evidence_source)
        ),
        "input_record_count": len(records),
        "profile_matched_record_count": sum(outcome_counts.values()),
        "profile_mismatch_count": profile_mismatch_count,
        "evidence_source_mismatch_count": source_mismatch_count,
        "outcome_histogram": dict(sorted(outcome_counts.items())),
        "route_decided_count": route_decided_count,
        "route_not_decided_count": sum(outcome_counts.values()) - route_decided_count,
        "invalid_route_count": sum(invalid_routes.values()),
        "invalid_route_reasons": dict(sorted(invalid_routes.items())),
        "completed_latency_record_count": len(completed_records),
        "completed_latency_by_route": _latency_by_route(completed_records),
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


def _evidence_gate_pass(
    *,
    input_valid: bool,
    route_decided_count: int,
    unknown_count: int,
    exact_coverage_percent: float,
    eligible_unknown_coverage_percent: float,
    min_requests: int,
    min_unknown_requests: int,
    min_exact_coverage_percent: float,
    min_eligible_unknown_coverage_percent: float,
) -> bool:
    if not input_valid or route_decided_count < min_requests:
        return False
    if exact_coverage_percent >= min_exact_coverage_percent:
        return True
    return (
        unknown_count >= min_unknown_requests
        and eligible_unknown_coverage_percent
        >= min_eligible_unknown_coverage_percent
    )


def _decision(
    *,
    input_valid: bool,
    evidence_gate_pass: bool,
    exact_coverage_percent: float,
    min_exact_coverage_percent: float,
    evidence_source: str,
) -> str:
    if not input_valid:
        return "reject_invalid_canary"
    if not evidence_gate_pass:
        return "collect_more_anonymous_coverage"
    if exact_coverage_percent >= min_exact_coverage_percent:
        return "keep_exact_allowlist"
    if evidence_source == "synthetic_proxy":
        return "prototype_padded_bucket_correctness"
    return "evaluate_padded_bucket_release_candidate"


def _histogram(values: dict[int, int] | Counter[int]) -> dict[str, int]:
    return {str(length): count for length, count in sorted(values.items())}


def _latency_by_route(
    completed_records: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for record in completed_records:
        route = str(record["prefill_shape_policy"])
        grouped.setdefault(route, []).append(record)
    summaries: dict[str, dict[str, object]] = {}
    for route, records in sorted(grouped.items()):
        summary: dict[str, object] = {"count": len(records)}
        for metric in ("first_audio_ms", "completed_ms", "inverse_rtf"):
            summary[metric] = _numeric_summary(
                [_completed_metric(record, metric) for record in records]
            )
        summaries[route] = summary
    return summaries


def _completed_metric(record: dict[str, object], metric: str) -> float:
    value = record[metric]
    assert isinstance(value, (int, float))
    assert not isinstance(value, bool)
    return float(value)


def _numeric_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": _percentile(ordered, 0.5),
        "p95": _percentile(ordered, 0.95),
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
    }


def _percentile(values: list[float], quantile: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def _exit_success(summary: dict[str, object]) -> bool:
    if summary.get("input_valid") is not True:
        return False
    required = summary.get("required_decision")
    if required is not None and summary.get("required_decision_pass") is not True:
        return False
    required_source = summary.get("required_evidence_source")
    return (
        required_source is None
        or summary.get("required_evidence_source_pass") is True
    )


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _provenance(path: Path) -> dict[str, str]:
    return {"path": _display_path(path), "sha256": _sha256(path)}


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def _validator_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
