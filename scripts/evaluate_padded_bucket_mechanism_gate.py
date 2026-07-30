"""Fail closed on the single approved padded-prefill mechanism prototype."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

_MINIMUM_ACTUAL_LENGTH = 16
_MAXIMUM_ACTUAL_LENGTH = 32
_COMPILED_CEILING = 32


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-summary", type=Path, required=True)
    parser.add_argument("--manual-review-summary", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-discovery-records", type=int, default=1500)
    parser.add_argument("--runtime-profile-id", default="strict_bf16_sdpa_v1")
    args = parser.parse_args()
    if args.minimum_discovery_records <= 0:
        parser.error("--minimum-discovery-records must be positive")
    route_bytes = args.route_summary.read_bytes()
    audit_bytes = args.audit.read_bytes()
    result = _evaluate(
        _load_object_bytes(route_bytes, "route summary"),
        _load_object(args.manual_review_summary, "manual review summary"),
        _load_object_bytes(audit_bytes, "audit"),
        args,
        hashlib.sha256(audit_bytes).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["prototype_authorized"] else 1


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
    audit: dict[str, object],
    args: argparse.Namespace,
    audit_sha256: str,
) -> dict[str, object]:
    histogram = _histogram(route_summary)
    represented = [
        length
        for length in range(_MINIMUM_ACTUAL_LENGTH, _MAXIMUM_ACTUAL_LENGTH + 1)
        if histogram.get(length, 0) > 0
    ]
    controls = _control_groups(histogram)
    checks = {
        "manual_review_passed": manual_review.get("passed") is True,
        "audit_passed": audit.get("automated_preflight_status") == "passed",
        "corpus_id": route_summary.get("corpus_id") == manual_review.get("corpus_id")
        and route_summary.get("corpus_id") == audit.get("corpus_id"),
        "manual_review_audit": manual_review.get("audit_sha256") == audit_sha256,
        "generator_source": manual_review.get("generator_source_sha256")
        == audit.get("generator_source_sha256"),
        "generation_config": manual_review.get("generation_config_sha256")
        == audit.get("generation_config_sha256"),
        "runtime_profile": route_summary.get("runtime_profile_id")
        == args.runtime_profile_id,
        "synthetic_evidence": route_summary.get("evidence_source") == "synthetic_proxy",
        "route_input_valid": route_summary.get("input_valid") is True,
        "minimum_discovery_records": _integer(route_summary.get("input_record_count"))
        >= args.minimum_discovery_records,
        "minimum_range_request_count": sum(
            histogram.get(length, 0) for length in represented
        )
        >= 100,
        "lower_control": controls["lower"] >= 5,
        "middle_control": controls["middle"] >= 5,
        "upper_control": controls["upper"] >= 5,
        "large_padding_control": sum(histogram.get(length, 0) for length in (16, 17))
        >= 5,
        "zero_padding_control": sum(histogram.get(length, 0) for length in (31, 32))
        >= 5,
        "research_only_policy": True,
        "single_fixed_bucket": True,
    }
    failed = [name for name, passed in checks.items() if not passed]
    authorized = not failed
    return {
        "padded_bucket_mechanism_gate_schema_version": 1,
        "checks": checks,
        "failed_checks": failed,
        "prototype_authorized": authorized,
        "approved_policy": {
            "actual_minimum_length": _MINIMUM_ACTUAL_LENGTH,
            "actual_maximum_length": _MAXIMUM_ACTUAL_LENGTH,
            "compiled_ceiling": _COMPILED_CEILING,
            "compiled_graph_count": 1,
        },
        "represented_actual_lengths": represented,
        "control_group_request_counts": controls,
        "input_sha256": {
            "route_summary": _canonical_sha256(route_summary),
            "manual_review": _canonical_sha256(manual_review),
            "audit": audit_sha256,
        },
        "decision": (
            "prototype_single_padded_bucket_16_32_to_32"
            if authorized
            else "do_not_prototype_padded_bucket"
        ),
        "release_authorized": False,
    }


def _histogram(summary: dict[str, object]) -> dict[int, int]:
    value = summary.get("length_histogram")
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, count in value.items():
        try:
            length = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            result[length] = count
    return result


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def _control_groups(histogram: dict[int, int]) -> dict[str, int]:
    return {
        "lower": sum(histogram.get(length, 0) for length in range(16, 22)),
        "middle": sum(histogram.get(length, 0) for length in range(22, 28)),
        "upper": sum(histogram.get(length, 0) for length in range(28, 33)),
    }


def _canonical_sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
