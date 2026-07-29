"""Compare an all-eager release baseline with exact-allowlist product results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from semantic_trace_contract import validate_generation_trace
except ModuleNotFoundError:  # Imported as scripts.qwen_release_ab in tests.
    from scripts.semantic_trace_contract import validate_generation_trace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-matrix-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    baseline = _load_report(args.baseline)
    candidate = _load_report(args.candidate)
    candidate_matrix_summary = _load_report(args.candidate_matrix_summary)
    report = _compare(baseline, candidate, candidate_matrix_summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {"acceptance_pass": report["acceptance_pass"], "output": str(args.output)}
        )
    )
    return 0 if report["acceptance_pass"] else 1


def _load_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON report {path} must be an object")
    return value


def _compare(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    candidate_matrix_summary: dict[str, Any],
) -> dict[str, object]:
    failures: list[str] = []
    baseline_runs = _runs(baseline, "baseline")
    candidate_runs = _runs(candidate, "candidate")
    baseline_contract_failures = _validate_all_eager(baseline_runs)
    candidate_contract_failures = _validate_candidate(candidate_runs)
    workload_failures = _validate_matching_workload(baseline_runs, candidate_runs)
    provenance_failures = _validate_matching_provenance(baseline, candidate)
    candidate_summary_failures = _validate_candidate_matrix_summary(
        candidate_matrix_summary
    )
    failures.extend(baseline_contract_failures)
    failures.extend(candidate_contract_failures)
    failures.extend(workload_failures)
    failures.extend(provenance_failures)
    failures.extend(candidate_summary_failures)

    groups = {
        "known_compiled": lambda run: _is_allowlist_run(run),
        "unknown_eager": lambda run: not _is_allowlist_run(run),
        "weighted_workload": lambda _run: True,
    }
    comparisons = {
        name: _group_comparison(
            [run for run in baseline_runs if predicate(run)],
            [run for run in candidate_runs if predicate(run)],
        )
        for name, predicate in groups.items()
    }
    return {
        "artifact_schema_version": 1,
        "acceptance_pass": not failures,
        "acceptance": {
            "baseline_eager_contract_pass": not baseline_contract_failures,
            "candidate_exact_allowlist_contract_pass": not candidate_contract_failures,
            "workload_match_pass": not workload_failures,
            "provenance_match_pass": not provenance_failures,
            "candidate_matrix_acceptance_pass": not candidate_summary_failures,
        },
        "baseline": _condition_summary(baseline_runs),
        "candidate": _condition_summary(candidate_runs),
        "comparisons": comparisons,
        "failures": failures,
    }


def _runs(report: dict[str, Any], label: str) -> list[dict[str, Any]]:
    runs = report.get("runs")
    if not isinstance(runs, list) or not all(isinstance(run, dict) for run in runs):
        raise ValueError(f"{label} report lacks valid runs")
    return runs


def _validate_all_eager(runs: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for run in runs:
        for request in _requests(run, failures):
            prefix = _run_label(run)
            _validate_trace(prefix, request, failures)
            _expect(
                prefix, request, "first_chunk_prefill_backend_used", "eager", failures
            )
            _expect_no_dynamic_compile(prefix, request, failures)
    return failures


def _validate_candidate(runs: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for run in runs:
        known = _is_allowlist_run(run)
        for request in _requests(run, failures):
            prefix = _run_label(run)
            _validate_trace(prefix, request, failures)
            if known:
                _expect(
                    prefix,
                    request,
                    "first_chunk_prefill_backend_used",
                    "compile_reduce_overhead",
                    failures,
                )
                _expect(
                    prefix,
                    request,
                    "first_chunk_prefill_compile_cache_hit",
                    True,
                    failures,
                )
                _expect(
                    prefix,
                    request,
                    "first_chunk_prefill_require_precompiled",
                    True,
                    failures,
                )
                ordinal = request.get("first_chunk_prefill_shape_call_ordinal")
                if not isinstance(ordinal, (int, float)) or ordinal < 4:
                    failures.append(f"{prefix}: expected prefill ordinal >= 4")
            else:
                _expect(
                    prefix,
                    request,
                    "first_chunk_prefill_backend_used",
                    "eager",
                    failures,
                )
            _expect(
                prefix, request, "first_chunk_prefill_compile_fallback", False, failures
            )
            _expect_no_dynamic_compile(prefix, request, failures)
    return failures


def _requests(run: dict[str, Any], failures: list[str]) -> list[dict[str, Any]]:
    requests = run.get("requests")
    if not isinstance(requests, list) or not all(
        isinstance(request, dict) for request in requests
    ):
        failures.append(f"{_run_label(run)}: invalid requests")
        return []
    return requests


def _validate_trace(
    prefix: str,
    request: dict[str, Any],
    failures: list[str],
) -> None:
    trace = request.get("generation_trace")
    if not isinstance(trace, dict):
        failures.append(f"{prefix}: missing generation trace")
        return
    try:
        validate_generation_trace(trace)
    except RuntimeError as exc:
        failures.append(f"{prefix}: {exc}")


def _expect(
    prefix: str,
    request: dict[str, Any],
    key: str,
    expected: object,
    failures: list[str],
) -> None:
    if request.get(key) != expected:
        failures.append(
            f"{prefix}: expected {key}={expected!r}, got {request.get(key)!r}"
        )


def _expect_no_dynamic_compile(
    prefix: str,
    request: dict[str, Any],
    failures: list[str],
) -> None:
    for key, expected in (
        ("first_chunk_prefill_compile_attempted", False),
        ("first_chunk_prefill_compile_attempt_count", 0),
        ("first_chunk_prefill_compile_cache_entries_delta", 0),
        ("first_chunk_prefill_compile_cache_evictions_delta", 0),
        ("first_chunk_prefill_dynamo_counter_available", True),
        ("first_chunk_prefill_dynamo_unique_graphs_delta", 0),
    ):
        _expect(prefix, request, key, expected, failures)


def _validate_matching_workload(
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> list[str]:
    if len(baseline) != len(candidate):
        return [f"workload run count differs: {len(baseline)} != {len(candidate)}"]
    failures: list[str] = []
    for index, (base_run, candidate_run) in enumerate(
        zip(baseline, candidate, strict=True),
        1,
    ):
        if _shape_signature(base_run) != _shape_signature(candidate_run):
            failures.append(f"run {index}: shape scenario differs")
    return failures


def _validate_matching_provenance(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    baseline_wheel = _wheel_sha256(baseline)
    candidate_wheel = _wheel_sha256(candidate)
    if baseline_wheel != candidate_wheel:
        return [f"wheel SHA differs: {baseline_wheel!r} != {candidate_wheel!r}"]
    return []


def _validate_candidate_matrix_summary(summary: dict[str, Any]) -> list[str]:
    acceptance = summary.get("acceptance")
    if not isinstance(acceptance, dict):
        return ["candidate matrix summary lacks acceptance"]
    required = (
        "terminal_trace_acceptance_pass",
        "routing_acceptance_pass",
        "compiled_latency_acceptance_pass",
        "eager_latency_acceptance_pass",
    )
    return [
        f"candidate matrix summary did not pass {name}"
        for name in required
        if acceptance.get(name) is not True
    ]


def _condition_summary(runs: list[dict[str, Any]]) -> dict[str, object]:
    return {
        "fresh_processes": len(runs),
        "measured_requests": sum(len(_requests_for_summary(run)) for run in runs),
        "startup_ms": _metric_summary(runs, "first_request", "startup_ms"),
        "first_ttfa_ms": _metric_summary(runs, "first_request", "first_audio_ms"),
        "first_completed_ms": _metric_summary(runs, "first_request", "completed_ms"),
        "first_real_time_factor": _metric_summary(
            runs,
            "first_request",
            "real_time_factor",
        ),
        "all_completed_ms": _request_metric_summary(runs, "completed_ms"),
        "all_real_time_factor": _request_metric_summary(runs, "real_time_factor"),
        "first_minus_steady_ms": _run_metric_summary(
            runs,
            "paired_delta_first_audio_ms",
        ),
    }


def _group_comparison(
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> dict[str, object]:
    if len(baseline) != len(candidate):
        return {
            "baseline": _condition_summary(baseline),
            "candidate": _condition_summary(candidate),
        }
    return {
        "baseline": _condition_summary(baseline),
        "candidate": _condition_summary(candidate),
        "candidate_minus_baseline": {
            "startup_ms": _paired_metric_summary(
                baseline,
                candidate,
                "first_request",
                "startup_ms",
            ),
            "first_ttfa_ms": _paired_metric_summary(
                baseline,
                candidate,
                "first_request",
                "first_audio_ms",
            ),
            "first_completed_ms": _paired_metric_summary(
                baseline,
                candidate,
                "first_request",
                "completed_ms",
            ),
            "first_real_time_factor": _paired_metric_summary(
                baseline,
                candidate,
                "first_request",
                "real_time_factor",
            ),
        },
    }


def _metric_summary(
    runs: list[dict[str, Any]],
    request_key: str,
    metric: str,
) -> dict[str, float] | None:
    values = [
        float(request[metric])
        for run in runs
        for request in [run.get(request_key)]
        if isinstance(request, dict) and isinstance(request.get(metric), (int, float))
    ]
    return _summary(values)


def _request_metric_summary(
    runs: list[dict[str, Any]],
    metric: str,
) -> dict[str, float] | None:
    values = [
        float(request[metric])
        for run in runs
        for request in _requests_for_summary(run)
        if isinstance(request.get(metric), (int, float))
    ]
    return _summary(values)


def _run_metric_summary(
    runs: list[dict[str, Any]],
    metric: str,
) -> dict[str, float] | None:
    values = [
        float(run[metric]) for run in runs if isinstance(run.get(metric), (int, float))
    ]
    return _summary(values)


def _paired_metric_summary(
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    request_key: str,
    metric: str,
) -> dict[str, float] | None:
    values: list[float] = []
    for base_run, candidate_run in zip(baseline, candidate, strict=True):
        base_request = base_run.get(request_key)
        candidate_request = candidate_run.get(request_key)
        if not isinstance(base_request, dict) or not isinstance(
            candidate_request, dict
        ):
            continue
        base_value = base_request.get(metric)
        candidate_value = candidate_request.get(metric)
        if isinstance(base_value, (int, float)) and isinstance(
            candidate_value, (int, float)
        ):
            values.append(float(candidate_value) - float(base_value))
    return _summary(values)


def _summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "min": min(values),
        "median": _percentile(values, 50.0),
        "p95": _percentile(values, 95.0),
        "max": max(values),
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = percentile / 100.0 * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _shape_signature(run: dict[str, Any]) -> tuple[object, ...]:
    shape = run.get("shape")
    if not isinstance(shape, dict):
        return ()
    return tuple(
        shape.get(key)
        for key in (
            "label",
            "scenario_id",
            "text",
            "language",
            "speaker",
            "instruction",
            "talker_prefill_length",
        )
    )


def _wheel_sha256(report: dict[str, Any]) -> str | None:
    try:
        return str(
            report["runtime"]["imports"]["faster_qwen3_tts"]["distribution"][
                "direct_url"
            ]["archive_info"]["hash"]
        )
    except (KeyError, TypeError):
        return None


def _is_allowlist_run(run: dict[str, Any]) -> bool:
    shape = run.get("shape")
    return isinstance(shape, dict) and str(shape.get("label", "")).startswith(
        "allowlist_"
    )


def _run_label(run: dict[str, Any]) -> str:
    shape = run.get("shape")
    if not isinstance(shape, dict):
        return "unknown run"
    return str(shape.get("scenario_id") or shape.get("label") or "unknown run")


def _requests_for_summary(run: dict[str, Any]) -> list[dict[str, Any]]:
    requests = run.get("requests")
    if not isinstance(requests, list):
        return []
    return [request for request in requests if isinstance(request, dict)]


if __name__ == "__main__":
    raise SystemExit(main())
