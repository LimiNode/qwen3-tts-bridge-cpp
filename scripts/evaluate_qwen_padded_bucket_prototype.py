"""Fail closed before adding the 16..32-to-32 padded-prefill runtime prototype."""

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
        # The current FasterQwen route supports exact actual lengths only. A
        # padded route would need an explicit mask/rope semantic-parity contract.
        "runtime_padding_implementation": False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "qwen_padded_bucket_prototype_gate_schema_version": 1,
        "approved_policy_if_implemented": {
            "actual_minimum_length": 16,
            "actual_maximum_length": 32,
            "compiled_ceiling": 32,
            "compiled_graph_count": 1,
        },
        "checks": checks,
        "control_group_request_counts": controls,
        "range_request_count": range_count,
        "failed_checks": failed,
        "prototype_authorized": not failed,
        "release_authorized": False,
        "decision": (
            "prototype_may_be_implemented_with_semantic_parity_gate"
            if not failed
            else "do_not_implement_or_release_padded_prefill_route"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["prototype_authorized"] else 1


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
