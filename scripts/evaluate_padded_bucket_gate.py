"""Fail closed on a constrained padded-bucket distribution research plan."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-summary", type=Path, required=True)
    parser.add_argument("--manual-review-summary", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
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
    route_bytes = args.route_summary.read_bytes()
    audit_bytes = args.audit.read_bytes()
    result = _evaluate(
        _load_object_bytes(route_bytes, "route summary"),
        _load_object(args.manual_review_summary, "manual review summary"),
        _load_object(args.candidate_artifact, "candidate artifact"),
        _load_object_bytes(audit_bytes, "audit"),
        args,
        hashlib.sha256(route_bytes).hexdigest(),
        hashlib.sha256(audit_bytes).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["distribution_plan_authorized"] else 1


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
    return _load_object_bytes(path.read_bytes(), name)


def _load_object_bytes(value: bytes, name: str) -> dict[str, object]:
    value = json.loads(value.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return value


def _evaluate(
    route_summary: dict[str, object],
    manual_review: dict[str, object],
    candidate_artifact: dict[str, object],
    audit: dict[str, object],
    args: argparse.Namespace,
    route_summary_sha256: str,
    audit_sha256: str,
) -> dict[str, object]:
    candidate = _candidate(candidate_artifact, args.candidate_id)
    reasons = []
    checks = {
        "manual_review_passed": manual_review.get("passed") is True,
        "audit_passed": audit.get("automated_preflight_status") == "passed",
        **_provenance_checks(
            route_summary,
            manual_review,
            candidate_artifact,
            audit,
            route_summary_sha256,
            audit_sha256,
        ),
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
        "padded_bucket_distribution_gate_schema_version": 2,
        "candidate_id": args.candidate_id,
        "checks": checks,
        "failed_checks": reasons,
        "distribution_plan_authorized": authorized,
        "prototype_authorized": False,
        "decision": (
            "distribution_plan_ready_for_mechanism_gate"
            if authorized
            else "do_not_advance_padded_bucket_research"
        ),
        "release_authorized": False,
        "release_note": (
            "A distribution plan cannot authorize a runtime implementation or "
            "release profile. The mechanism gate separately permits only one "
            "16..32-to-32 correctness prototype."
        ),
        "input_sha256": {
            "route_summary": route_summary_sha256,
            "manual_review": _canonical_sha256(manual_review),
            "candidate_artifact": _canonical_sha256(candidate_artifact),
            "audit": audit_sha256,
        },
    }


def _provenance_checks(
    route_summary: dict[str, object],
    manual_review: dict[str, object],
    candidate_artifact: dict[str, object],
    audit: dict[str, object],
    route_summary_sha256: str,
    audit_sha256: str,
) -> dict[str, bool]:
    corpus_id = route_summary.get("corpus_id")
    runtime_profile = route_summary.get("runtime_profile_id")
    return {
        "candidate_input_summary": candidate_artifact.get("input_summary_sha256")
        == route_summary_sha256,
        "corpus_id": isinstance(corpus_id, str)
        and corpus_id == manual_review.get("corpus_id")
        and corpus_id == audit.get("corpus_id"),
        "manual_review_audit": manual_review.get("audit_sha256") == audit_sha256,
        "generator_source": manual_review.get("generator_source_sha256")
        == audit.get("generator_source_sha256"),
        "generation_config": manual_review.get("generation_config_sha256")
        == audit.get("generation_config_sha256"),
        "runtime_profile": isinstance(runtime_profile, str)
        and runtime_profile == candidate_artifact.get("runtime_profile_id"),
    }


def _canonical_sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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
