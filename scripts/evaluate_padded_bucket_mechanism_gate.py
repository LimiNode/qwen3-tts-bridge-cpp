"""Fail closed on the single approved padded-prefill mechanism prototype."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_MINIMUM_ACTUAL_LENGTH = 16
_MAXIMUM_ACTUAL_LENGTH = 32
_COMPILED_CEILING = 32


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-summary", type=Path, required=True)
    parser.add_argument("--manual-review-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-discovery-records", type=int, default=1500)
    args = parser.parse_args()
    if args.minimum_discovery_records <= 0:
        parser.error("--minimum-discovery-records must be positive")
    result = _evaluate(
        _load_object(args.route_summary, "route summary"),
        _load_object(args.manual_review_summary, "manual review summary"),
        args,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["prototype_authorized"] else 1


def _load_object(path: Path, name: str) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return value


def _evaluate(
    route_summary: dict[str, object],
    manual_review: dict[str, object],
    args: argparse.Namespace,
) -> dict[str, object]:
    histogram = _histogram(route_summary)
    represented = [
        length
        for length in range(_MINIMUM_ACTUAL_LENGTH, _MAXIMUM_ACTUAL_LENGTH + 1)
        if histogram.get(length, 0) > 0
    ]
    checks = {
        "manual_review_passed": manual_review.get("passed") is True,
        "synthetic_evidence": route_summary.get("evidence_source") == "synthetic_proxy",
        "route_input_valid": route_summary.get("input_valid") is True,
        "minimum_discovery_records": _integer(route_summary.get("input_record_count"))
        >= args.minimum_discovery_records,
        "actual_range_represented": bool(represented),
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


if __name__ == "__main__":
    raise SystemExit(main())
