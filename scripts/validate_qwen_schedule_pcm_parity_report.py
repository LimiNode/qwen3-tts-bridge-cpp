"""Revalidate a saved fixed-versus-scheduled PCM quality report."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

try:
    from qwen_schedule_pcm_parity import (
        _compare,
        _load_cases,
        _validate_candidate_contract,
    )
except ModuleNotFoundError:
    from scripts.qwen_schedule_pcm_parity import (
        _compare,
        _load_cases,
        _validate_candidate_contract,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--cases-jsonl", type=Path, required=True)
    parser.add_argument("--language", default="Auto")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--max-duration-delta-ms", type=float, default=0.0)
    parser.add_argument("--max-boundary-jump-s16", type=float, default=12000.0)
    parser.add_argument("--max-p95-boundary-jump-s16", type=float, default=6000.0)
    parser.add_argument("--max-rms-ratio", type=float, default=16.0)
    parser.add_argument("--max-dc-delta-s16", type=float, default=2000.0)
    parser.add_argument("--max-spectral-high-ratio-delta", type=float, default=0.7)
    parser.add_argument("--max-clip-sample-count", type=int, default=0)
    parser.add_argument("--max-boundary-jump-regression-s16", type=float, default=4000.0)
    parser.add_argument(
        "--max-p95-boundary-jump-regression-s16", type=float, default=3000.0
    )
    parser.add_argument("--max-rms-regression-multiplier", type=float, default=2.5)
    parser.add_argument("--max-dc-regression-s16", type=float, default=500.0)
    parser.add_argument(
        "--max-spectral-high-ratio-regression", type=float, default=0.3
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = args.input.read_bytes()
    report = json.loads(raw)
    if not isinstance(report, dict) or not isinstance(report.get("pairs"), list):
        raise RuntimeError("PCM quality report must contain pairs")
    cases = {str(case["label"]): case for case in _load_cases(args.cases_jsonl, args)}
    failures: list[str] = []
    observed_labels: set[str] = set()
    for pair in report["pairs"]:
        if not isinstance(pair, dict):
            failures.append("report contains invalid pair")
            continue
        label = pair.get("label")
        baseline = pair.get("baseline")
        candidate = pair.get("candidate")
        if not isinstance(label, str) or not isinstance(baseline, dict) or not isinstance(candidate, dict):
            failures.append("report pair lacks label or results")
            continue
        observed_labels.add(label)
        case = cases.get(label)
        if case is None:
            failures.append(f"{label}: absent from quality matrix")
            continue
        pair_failures = _compare(
            baseline,
            candidate,
            max_duration_delta_ms=args.max_duration_delta_ms,
            max_boundary_jump_s16=args.max_boundary_jump_s16,
            max_p95_boundary_jump_s16=args.max_p95_boundary_jump_s16,
            max_rms_ratio=args.max_rms_ratio,
            max_dc_delta_s16=args.max_dc_delta_s16,
            max_spectral_high_ratio_delta=args.max_spectral_high_ratio_delta,
            max_clip_sample_count=args.max_clip_sample_count,
            max_boundary_jump_regression_s16=args.max_boundary_jump_regression_s16,
            max_p95_boundary_jump_regression_s16=(
                args.max_p95_boundary_jump_regression_s16
            ),
            max_rms_regression_multiplier=args.max_rms_regression_multiplier,
            max_dc_regression_s16=args.max_dc_regression_s16,
            max_spectral_high_ratio_regression=(
                args.max_spectral_high_ratio_regression
            ),
        )
        pair_failures.extend(_validate_candidate_contract(case, baseline, candidate))
        failures.extend(f"{label}: {failure}" for failure in pair_failures)
    missing = sorted(set(cases).difference(observed_labels))
    if missing:
        failures.append("report is missing quality cases: " + ", ".join(missing))
    output = {
        "artifact_schema_version": 1,
        "input_path": str(args.input),
        "input_sha256": sha256(raw).hexdigest(),
        "cases_path": str(args.cases_jsonl),
        "cases_sha256": sha256(args.cases_jsonl.read_bytes()).hexdigest(),
        "acceptance_pass": not failures,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, sort_keys=True), encoding="utf-8")
    print(json.dumps(output, sort_keys=True))
    return 0 if output["acceptance_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
