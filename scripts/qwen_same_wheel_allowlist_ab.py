"""Summarize a same-wheel discovery A/B for two exact allowlists."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-profile", type=Path, required=True)
    parser.add_argument("--candidate-profile", type=Path, required=True)
    parser.add_argument("--baseline-run", type=Path, required=True)
    parser.add_argument("--candidate-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare(
        baseline_profile=_load_object(args.baseline_profile),
        candidate_profile=_load_object(args.candidate_profile),
        baseline_run=args.baseline_run,
        candidate_run=args.candidate_run,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"passed": report["passed"], "output": str(args.output)}))
    return 0 if report["passed"] else 1


def compare(
    *,
    baseline_profile: dict[str, Any],
    candidate_profile: dict[str, Any],
    baseline_run: Path,
    candidate_run: Path,
) -> dict[str, object]:
    baseline_manifest = _load_object(baseline_run / "run-manifest.json")
    candidate_manifest = _load_object(candidate_run / "run-manifest.json")
    baseline_rows = _load_jsonl(baseline_run / "records.jsonl")
    candidate_rows = _load_jsonl(candidate_run / "records.jsonl")
    baseline_by_id = {str(row["record_id"]): row for row in baseline_rows}
    candidate_by_id = {str(row["record_id"]): row for row in candidate_rows}
    baseline_lengths = _positive_int_set(baseline_profile["prefill_compile_lengths"])
    candidate_lengths = _positive_int_set(candidate_profile["prefill_compile_lengths"])
    groups = {
        "newly_compiled": candidate_lengths - baseline_lengths,
        "shared_compiled": candidate_lengths & baseline_lengths,
        "dropped_to_eager": baseline_lengths - candidate_lengths,
    }
    failures = _provenance_failures(
        baseline_manifest,
        candidate_manifest,
        baseline_by_id,
        candidate_by_id,
    )
    group_reports = {
        name: _group_report(
            lengths,
            baseline_by_id,
            candidate_by_id,
            baseline_lengths,
            candidate_lengths,
            failures,
            name,
        )
        for name, lengths in groups.items()
    }
    return {
        "artifact_schema_version": 1,
        "method": "same_wheel_stratified_exact_allowlist_ab",
        "baseline": {
            "profile_lengths": sorted(baseline_lengths),
            "run": _provenance(baseline_run / "run-manifest.json"),
            "records": _provenance(baseline_run / "records.jsonl"),
            "startup": _startup_summary(baseline_manifest),
        },
        "candidate": {
            "profile_lengths": sorted(candidate_lengths),
            "run": _provenance(candidate_run / "run-manifest.json"),
            "records": _provenance(candidate_run / "records.jsonl"),
            "startup": _startup_summary(candidate_manifest),
        },
        "groups": group_reports,
        "failures": failures,
        "passed": not failures,
    }


def _group_report(
    lengths: set[int],
    baseline: dict[str, dict[str, Any]],
    candidate: dict[str, dict[str, Any]],
    baseline_lengths: set[int],
    candidate_lengths: set[int],
    failures: list[str],
    name: str,
) -> dict[str, object]:
    rows = [
        (baseline[record_id], candidate[record_id])
        for record_id in sorted(baseline)
        if _length(baseline[record_id]) in lengths
    ]
    if not rows:
        failures.append(f"{name}: no rows")
        return {"count": 0}
    expected_baseline = (
        "compiled_allowlist" if lengths <= baseline_lengths else "eager_unknown"
    )
    expected_candidate = (
        "compiled_allowlist" if lengths <= candidate_lengths else "eager_unknown"
    )
    for baseline_row, candidate_row in rows:
        _validate_terminal_and_route(
            baseline_row, expected_baseline, failures, f"{name}/baseline"
        )
        _validate_terminal_and_route(
            candidate_row, expected_candidate, failures, f"{name}/candidate"
        )
    return {
        "lengths": sorted(lengths),
        "count": len(rows),
        "baseline_route": expected_baseline,
        "candidate_route": expected_candidate,
        "first_audio_ms": _paired_metric(rows, "first_audio_ms"),
        "completed_ms": _paired_metric(rows, "completed_ms"),
    }


def _paired_metric(
    rows: list[tuple[dict[str, Any], dict[str, Any]]], key: str
) -> dict[str, float]:
    baseline = [float(old[key]) for old, _new in rows]
    candidate = [float(new[key]) for _old, new in rows]
    delta = [new - old for old, new in zip(baseline, candidate, strict=True)]
    return {
        "baseline_mean": round(statistics.mean(baseline), 3),
        "candidate_mean": round(statistics.mean(candidate), 3),
        "candidate_minus_baseline_mean": round(statistics.mean(delta), 3),
        "candidate_minus_baseline_p95": round(_percentile(delta, 0.95), 3),
    }


def _startup_summary(manifest: dict[str, Any]) -> dict[str, object]:
    warmup = manifest.get("engine_warmup")
    fields = warmup if isinstance(warmup, dict) else {}
    return {
        "engine_load_ms": manifest.get("engine_load_ms"),
        "engine_warmup_ms": manifest.get("engine_warmup_ms"),
        "generation_prime": fields.get("prefill_generation_prime", False),
        "generation_prime_duration_ms": fields.get(
            "prefill_generation_prime_duration_ms"
        ),
        "generation_prime_rng_equal": fields.get("prefill_generation_prime_rng_before")
        == fields.get("prefill_generation_prime_rng_after"),
    }


def _provenance_failures(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    baseline_rows: dict[str, dict[str, Any]],
    candidate_rows: dict[str, dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    if baseline_rows.keys() != candidate_rows.keys():
        failures.append("record ID sets differ")
    if baseline.get("input_sha256") != candidate.get("input_sha256"):
        failures.append("fixture SHA differs")
    baseline_runtime = baseline.get("runtime")
    candidate_runtime = candidate.get("runtime")
    if not isinstance(baseline_runtime, dict) or not isinstance(
        candidate_runtime, dict
    ):
        return failures + ["runtime provenance missing"]
    for key in ("torch_version", "faster_qwen3_tts_version", "cuda_device_name"):
        if baseline_runtime.get(key) != candidate_runtime.get(key):
            failures.append(f"runtime differs: {key}")
    return failures


def _validate_terminal_and_route(
    row: dict[str, Any], expected_route: str, failures: list[str], prefix: str
) -> None:
    if (
        row.get("execution_outcome") != "completed"
        or row.get("generation_outcome") != "eos"
    ):
        failures.append(f"{prefix}: non-EOS terminal state")
    route = row.get("first_chunk_route")
    if (
        not isinstance(route, dict)
        or route.get("prefill_shape_policy") != expected_route
    ):
        failures.append(f"{prefix}: route mismatch")
        return
    if route.get("prefill_compile_fallback") is not False:
        failures.append(f"{prefix}: fallback observed")
    if route.get("prefill_dynamo_unique_graphs_delta") != 0:
        failures.append(f"{prefix}: Dynamo graph delta observed")


def _length(row: dict[str, Any]) -> int:
    route = row.get("first_chunk_route")
    if not isinstance(route, dict) or not isinstance(
        route.get("talker_prefill_length"), int
    ):
        raise ValueError("row lacks talker prefill length")
    return int(route["talker_prefill_length"])


def _positive_int_set(value: object) -> set[int]:
    if not isinstance(value, list) or not value:
        raise ValueError("profile lacks exact lengths")
    result = {item for item in value if isinstance(item, int) and item > 0}
    if len(result) != len(value):
        raise ValueError("profile exact lengths are invalid")
    return result


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path}: invalid JSONL")
    return rows


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _provenance(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


if __name__ == "__main__":
    raise SystemExit(main())
