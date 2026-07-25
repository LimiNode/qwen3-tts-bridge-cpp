"""Recompute derived benchmark summaries from a saved restart report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_packaged_worker_restart import (
    _paired_steady_residual_summary,
    _paired_steady_residuals,
    _positive_outlier_talker_forward_attribution,
    _talker_forward_explained_outlier_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threshold-ms", type=float, default=20.0)
    args = parser.parse_args()

    report = json.loads(args.input.read_text(encoding="utf-8-sig"))
    runs = report.get("runs")
    if not isinstance(runs, list):
        raise ValueError("input report must contain a runs list")

    enriched_runs = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        item = dict(run)
        first_request = item.get("first_request")
        steady_requests = item.get("steady_requests")
        if isinstance(first_request, dict) and isinstance(steady_requests, list):
            item["paired_steady_residuals"] = _paired_steady_residuals(
                first_request,
                [
                    request
                    for request in steady_requests
                    if isinstance(request, dict)
                ],
            )
        enriched_runs.append(item)

    output = {
        "artifact_schema_version": 1,
        "source_report": str(args.input),
        "threshold_ms": args.threshold_ms,
        "talker_forward_declassification": (
            _talker_forward_explained_outlier_summary(
                enriched_runs,
                threshold_ms=args.threshold_ms,
            )
        ),
        "positive_outlier_talker_forward_attribution": (
            _positive_outlier_talker_forward_attribution(
                enriched_runs,
                threshold_ms=args.threshold_ms,
            )
        ),
        "paired_steady_residuals": _paired_steady_residual_summary(enriched_runs),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(output["talker_forward_declassification"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
