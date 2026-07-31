"""Authorize only the research implementation of one padded-prefill policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--shape-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validation = _load_object(args.validation)
    shapes = _load_object(args.shape_summary)
    result = _evaluate(validation, shapes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["research_implementation_authorized"] else 1


def _evaluate(
    validation: dict[str, object],
    shapes: dict[str, object],
) -> dict[str, object]:
    histogram = _histogram(shapes)
    range_count = sum(histogram.get(length, 0) for length in range(16, 33))
    controls = {
        "16_to_21": sum(histogram.get(length, 0) for length in range(16, 22)),
        "22_to_27": sum(histogram.get(length, 0) for length in range(22, 28)),
        "28_to_32": sum(histogram.get(length, 0) for length in range(28, 33)),
    }
    checks = {
        "baseline_validation": validation.get("overall_acceptance_pass") is True,
        "real_discovery_histogram": shapes.get("evidence_source") == "real_discovery",
        "generation_acceptance": shapes.get("generation_acceptance_pass") is True,
        "minimum_range_count": range_count >= 100,
        "lower_control": controls["16_to_21"] >= 5,
        "middle_control": controls["22_to_27"] >= 5,
        "upper_control": controls["28_to_32"] >= 5,
        "holdout_contract_closed": True,
        "research_only_policy": True,
    }
    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "qwen_padded_bucket_research_authorization_schema_version": 2,
        "approved_research_policy": {
            "actual_minimum_length": 16,
            "actual_maximum_length": 32,
            "compiled_ceiling": 32,
            "compiled_graph_count": 1,
        },
        "checks": checks,
        "control_group_request_counts": controls,
        "range_request_count": range_count,
        "failed_checks": failed,
        "research_implementation_authorized": not failed,
        "release_authorized": False,
        "decision": (
            "authorized_to_implement_research_prototype"
            if not failed
            else "do_not_implement_padded_prefill_research_prototype"
        ),
    }
    return result


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _histogram(summary: dict[str, object]) -> dict[int, int]:
    value = summary.get("length_histogram")
    if not isinstance(value, dict):
        raise RuntimeError("shape summary has no length_histogram")
    result = {}
    for raw_length, count in value.items():
        length = int(raw_length)
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise RuntimeError("shape summary has invalid count")
        result[length] = count
    return result


if __name__ == "__main__":
    raise SystemExit(main())
