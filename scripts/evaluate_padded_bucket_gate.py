"""Fail closed on a research-only padded-prefill correctness prototype gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-summary", type=Path, required=True)
    parser.add_argument("--manual-review-summary", type=Path, required=True)
    parser.add_argument("--candidate-artifact", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-discovery-records", type=int, default=1500)
    parser.add_argument(
        "--minimum-bootstrap-stability-percent", type=float, default=80.0
    )
    parser.add_argument(
        "--minimum-theoretical-coverage-percent", type=float, default=85.0
    )
    parser.add_argument("--maximum-mean-padding", type=float, default=6.0)
    parser.add_argument("--maximum-p95-padding", type=float, default=12.0)
    parser.add_argument("--maximum-padding", type=float, default=16.0)
    parser.add_argument("--maximum-padding-ratio", type=float, default=0.4)
    parser.add_argument("--maximum-graphs", type=int, default=6)
    args = parser.parse_args()
    _validate_args(parser, args)
    result = _evaluate(
        _load_object(args.route_summary, "route summary"),
        _load_object(args.manual_review_summary, "manual review summary"),
        _load_object(args.candidate_artifact, "candidate artifact"),
        args,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["prototype_authorized"] else 1


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.minimum_discovery_records <= 0 or args.maximum_graphs <= 0:
        parser.error("record and graph limits must be positive")
    percentages = (
        args.minimum_bootstrap_stability_percent,
        args.minimum_theoretical_coverage_percent,
        args.maximum_padding_ratio * 100.0,
    )
    if any(not 0.0 <= value <= 100.0 for value in percentages):
        parser.error("percentage thresholds must be within 0..100")
    if any(
        value < 0.0
        for value in (
            args.maximum_mean_padding,
            args.maximum_p95_padding,
            args.maximum_padding,
        )
    ):
        parser.error("padding limits must be non-negative")


def _load_object(path: Path, name: str) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return value


def _evaluate(
    route_summary: dict[str, object],
    manual_review: dict[str, object],
    candidate_artifact: dict[str, object],
    args: argparse.Namespace,
) -> dict[str, object]:
    candidate = _candidate(candidate_artifact, args.candidate_id)
    reasons = []
    checks = {
        "manual_review_passed": manual_review.get("passed") is True,
        "synthetic_evidence": route_summary.get("evidence_source") == "synthetic_proxy",
        "route_input_valid": route_summary.get("input_valid") is True,
        "minimum_discovery_records": _integer(route_summary.get("input_record_count"))
        >= args.minimum_discovery_records,
        "candidate_research_only": candidate_artifact.get("research_only") is True,
        "coverage": _number(candidate.get("compiled_coverage_percent"))
        >= args.minimum_theoretical_coverage_percent,
        "graph_budget": _integer(candidate.get("compiled_graph_count"))
        <= args.maximum_graphs,
        "mean_padding": _padding(candidate, "mean") <= args.maximum_mean_padding,
        "p95_padding": _padding(candidate, "p95") <= args.maximum_p95_padding,
        "max_padding": _padding(candidate, "max") <= args.maximum_padding,
        "max_padding_ratio": _padding_ratio(candidate) <= args.maximum_padding_ratio,
        "bootstrap_stability": _stability(candidate)
        >= args.minimum_bootstrap_stability_percent,
    }
    for name, passed in checks.items():
        if not passed:
            reasons.append(name)
    authorized = not reasons
    return {
        "padded_bucket_gate_schema_version": 1,
        "candidate_id": args.candidate_id,
        "checks": checks,
        "failed_checks": reasons,
        "prototype_authorized": authorized,
        "decision": (
            "prototype_padded_bucket_correctness"
            if authorized
            else "do_not_prototype_padded_bucket"
        ),
        "release_authorized": False,
        "release_note": (
            "Synthetic evidence can authorize only a research correctness "
            "prototype; it cannot authorize a release profile."
        ),
    }


def _candidate(artifact: dict[str, object], candidate_id: str) -> dict[str, object]:
    candidates = artifact.get("candidates")
    if not isinstance(candidates, list):
        raise RuntimeError("candidate artifact has no candidates")
    for candidate in candidates:
        if (
            isinstance(candidate, dict)
            and candidate.get("candidate_id") == candidate_id
        ):
            return candidate
    raise RuntimeError("candidate artifact does not contain --candidate-id")


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def _number(value: object) -> float:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else -1.0
    )


def _padding(candidate: dict[str, object], name: str) -> float:
    padding = candidate.get("padding_frames")
    return _number(padding.get(name) if isinstance(padding, dict) else None)


def _padding_ratio(candidate: dict[str, object]) -> float:
    padding = candidate.get("padding_ratio")
    return _number(padding.get("max") if isinstance(padding, dict) else None)


def _stability(candidate: dict[str, object]) -> float:
    stability = candidate.get("bootstrap_stability")
    return _number(
        stability.get("minimum_ceiling_match_percent")
        if isinstance(stability, dict)
        else None
    )


if __name__ == "__main__":
    raise SystemExit(main())
