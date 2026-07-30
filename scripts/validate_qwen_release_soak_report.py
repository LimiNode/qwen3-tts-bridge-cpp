"""Revalidate a completed Qwen release-soak artifact with the current gate."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from qwen_release_soak import _validate_release_soak


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = args.input.read_bytes()
    report = json.loads(raw)
    if not isinstance(report, dict):
        raise RuntimeError("release-soak report must be a JSON object")
    results = _list_field(report, "requests")
    snapshots = _list_field(report, "memory_snapshots")
    worker_metrics = _list_field(report, "worker_metrics")
    config = report.get("config")
    if not isinstance(config, dict):
        raise RuntimeError("release-soak report is missing config")
    expected_requests = _positive_int(config, "requests")
    expected_cache_entries = _positive_int(config, "expected_prefill_cache_entries")
    cancellations_per_category = _positive_int(config, "cancellations_per_category")
    max_rss_growth_mb = _positive_number(config, "max_rss_growth_mb")
    labels = {
        str(result["shape_label"])
        for result in results
        if isinstance(result, dict) and isinstance(result.get("shape_label"), str)
    }
    if not labels:
        raise RuntimeError("release-soak report contains no shape labels")
    expected_cancellations = cancellations_per_category * len(labels)
    validation = _validate_release_soak(
        results,
        snapshots,
        worker_metrics,
        expected_cache_entries=expected_cache_entries,
        expected_requests=expected_requests,
        expected_cancellations=expected_cancellations,
        expected_labels=labels,
        cancellations_per_stage=cancellations_per_category // 3,
        max_rss_growth_mb=max_rss_growth_mb,
    )
    output = {
        "artifact_schema_version": 1,
        "input_path": str(args.input),
        "input_sha256": sha256(raw).hexdigest(),
        "acceptance_pass": not validation["failures"],
        "validation": validation,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, sort_keys=True), encoding="utf-8")
    print(json.dumps(output, sort_keys=True))
    return 0 if output["acceptance_pass"] else 1


def _list_field(report: dict[str, object], key: str) -> list[dict[str, object]]:
    value = report.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError(f"release-soak report has invalid {key}")
    return value


def _positive_int(config: dict[str, object], key: str) -> int:
    value = config.get(key)
    if not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"release-soak config has invalid {key}")
    return value


def _positive_number(config: dict[str, object], key: str) -> float:
    value = config.get(key)
    if not isinstance(value, (int, float)) or value <= 0:
        raise RuntimeError(f"release-soak config has invalid {key}")
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
