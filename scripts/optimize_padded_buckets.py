"""Produce research-only padded-prefill bucket candidates from a route summary."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path

_SCHEMA_VERSION = 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bucket-count", action="append", type=int)
    parser.add_argument("--coverage-percent", action="append", type=float)
    parser.add_argument("--per-graph-startup-ms", type=float)
    args = parser.parse_args()
    bucket_counts = args.bucket_count or [4, 5, 6]
    coverage_percents = args.coverage_percent or [90.0, 95.0, 99.0, 100.0]
    _validate_args(parser, bucket_counts, coverage_percents, args.per_graph_startup_ms)

    summary = _load_summary(args.input)
    histogram = _load_histogram(summary)
    candidates = [
        _candidate(histogram, bucket_count, coverage, args.per_graph_startup_ms)
        for bucket_count in bucket_counts
        for coverage in coverage_percents
    ]
    artifact = {
        "artifact_schema_version": _SCHEMA_VERSION,
        "research_only": True,
        "input_summary_sha256": _sha256(args.input),
        "runtime_profile_id": summary.get("runtime_profile_id"),
        "input_record_count": sum(histogram.values()),
        "bucket_counts": bucket_counts,
        "coverage_percents": coverage_percents,
        "candidates": candidates,
        "release_note": (
            "This artifact selects no runtime configuration. A single candidate "
            "requires a separate padded-bucket correctness prototype before any "
            "release evaluation."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
    print(json.dumps(artifact, sort_keys=True))
    return 0


def _validate_args(
    parser: argparse.ArgumentParser,
    bucket_counts: list[int],
    coverage_percents: list[float],
    per_graph_startup_ms: float | None,
) -> None:
    if not bucket_counts or any(value <= 0 for value in bucket_counts):
        parser.error("--bucket-count must be positive")
    if len(set(bucket_counts)) != len(bucket_counts):
        parser.error("--bucket-count values must be unique")
    if not coverage_percents or any(
        not 0.0 < value <= 100.0 for value in coverage_percents
    ):
        parser.error("--coverage-percent must be within (0, 100]")
    if len(set(coverage_percents)) != len(coverage_percents):
        parser.error("--coverage-percent values must be unique")
    if per_graph_startup_ms is not None and per_graph_startup_ms <= 0.0:
        parser.error("--per-graph-startup-ms must be positive")


def _load_summary(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("input summary must be a JSON object")
    return value


def _load_histogram(summary: dict[str, object]) -> dict[int, int]:
    raw_histogram = summary.get("length_histogram")
    if not isinstance(raw_histogram, dict) or not raw_histogram:
        raise RuntimeError("input summary has no length_histogram")
    histogram: dict[int, int] = {}
    for raw_length, raw_count in raw_histogram.items():
        try:
            length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("length_histogram has an invalid length") from exc
        if (
            length <= 0
            or not isinstance(raw_count, int)
            or isinstance(raw_count, bool)
            or raw_count <= 0
        ):
            raise RuntimeError("length_histogram has an invalid count")
        histogram[length] = raw_count
    return dict(sorted(histogram.items()))


def _candidate(
    histogram: dict[int, int],
    requested_bucket_count: int,
    coverage_percent: float,
    per_graph_startup_ms: float | None,
) -> dict[str, object]:
    total_count = sum(histogram.values())
    target_count = math.ceil(total_count * coverage_percent / 100.0)
    cutoff = _coverage_cutoff(histogram, target_count)
    covered = {length: count for length, count in histogram.items() if length <= cutoff}
    bucket_count = min(requested_bucket_count, len(covered))
    buckets = _optimal_buckets(covered, bucket_count)
    compiled_count = sum(bucket["request_count"] for bucket in buckets)
    padding = _padding_summary(covered, buckets)
    eager_count = total_count - compiled_count
    graph_count = len(buckets)
    return {
        "candidate_id": (
            f"buckets-{requested_bucket_count}-coverage-{coverage_percent:g}"
        ),
        "requested_bucket_count": requested_bucket_count,
        "compiled_graph_count": graph_count,
        "compiled_bucket_ceilings": [bucket["ceiling"] for bucket in buckets],
        "buckets": buckets,
        "compiled_request_count": compiled_count,
        "compiled_coverage_percent": compiled_count * 100.0 / total_count,
        "eager_request_count": eager_count,
        "eager_fallback_percent": eager_count * 100.0 / total_count,
        "padding_frames": padding,
        "startup_cost_estimate": {
            "compiled_graph_count": graph_count,
            "per_graph_startup_ms": per_graph_startup_ms,
            "estimated_startup_ms": (
                graph_count * per_graph_startup_ms
                if per_graph_startup_ms is not None
                else None
            ),
            "measurement_status": (
                "estimated_from_input"
                if per_graph_startup_ms is not None
                else "not_measured"
            ),
        },
    }


def _coverage_cutoff(histogram: dict[int, int], target_count: int) -> int:
    seen = 0
    for length, count in histogram.items():
        seen += count
        if seen >= target_count:
            return length
    raise RuntimeError("coverage cutoff exceeds histogram")


def _optimal_buckets(
    histogram: dict[int, int], bucket_count: int
) -> list[dict[str, int]]:
    lengths = list(histogram)
    counts = [histogram[length] for length in lengths]
    costs = _segment_costs(lengths, counts)
    item_count = len(lengths)
    infinity = math.inf
    costs_by_bucket = [[infinity] * item_count for _ in range(bucket_count)]
    previous = [[-1] * item_count for _ in range(bucket_count)]
    for end in range(item_count):
        costs_by_bucket[0][end] = costs[0][end]
    for bucket_index in range(1, bucket_count):
        for end in range(bucket_index, item_count):
            for split in range(bucket_index - 1, end):
                candidate = (
                    costs_by_bucket[bucket_index - 1][split] + costs[split + 1][end]
                )
                if candidate < costs_by_bucket[bucket_index][end]:
                    costs_by_bucket[bucket_index][end] = candidate
                    previous[bucket_index][end] = split
    spans: list[tuple[int, int]] = []
    end = item_count - 1
    for bucket_index in range(bucket_count - 1, -1, -1):
        split = previous[bucket_index][end]
        spans.append((split + 1, end))
        end = split
    spans.reverse()
    return [
        {
            "minimum_actual_length": lengths[start],
            "ceiling": lengths[end],
            "request_count": sum(counts[start : end + 1]),
        }
        for start, end in spans
    ]


def _segment_costs(lengths: list[int], counts: list[int]) -> list[list[int]]:
    item_count = len(lengths)
    costs = [[0] * item_count for _ in range(item_count)]
    for start in range(item_count):
        weighted_sum = 0
        count_sum = 0
        for end in range(start, item_count):
            weighted_sum += lengths[end] * counts[end]
            count_sum += counts[end]
            costs[start][end] = lengths[end] * count_sum - weighted_sum
    return costs


def _padding_summary(
    histogram: dict[int, int], buckets: list[dict[str, int]]
) -> dict[str, float | int]:
    differences = []
    for length, count in histogram.items():
        ceiling = next(
            bucket["ceiling"]
            for bucket in buckets
            if bucket["minimum_actual_length"] <= length <= bucket["ceiling"]
        )
        differences.append((ceiling - length, count))
    total_count = sum(count for _, count in differences)
    total_padding = sum(value * count for value, count in differences)
    return {
        "mean": total_padding / total_count,
        "p95": _weighted_percentile(differences, 0.95),
        "max": max(value for value, _ in differences),
    }


def _weighted_percentile(values: Iterable[tuple[int, int]], quantile: float) -> int:
    ordered = sorted(values)
    target = math.ceil(sum(count for _, count in ordered) * quantile)
    seen = 0
    for value, count in ordered:
        seen += count
        if seen >= target:
            return value
    raise RuntimeError("weighted percentile has no values")


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
