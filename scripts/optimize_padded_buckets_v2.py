"""Build constrained, research-only padded-prefill bucket Pareto candidates."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast


@dataclass(frozen=True, slots=True)
class Bucket:
    start: int
    end: int
    request_count: int
    padding_sum: int


@dataclass(frozen=True, slots=True)
class Plan:
    buckets: tuple[Bucket, ...]
    covered_count: int
    padding_sum: int


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--max-graphs",
        action="append",
        type=int,
        default=None,
    )
    parser.add_argument("--min-bucket-size", type=int, default=30)
    parser.add_argument("--max-padding-frames", type=int, default=16)
    parser.add_argument("--max-padding-ratio", type=float, default=0.4)
    parser.add_argument("--max-bucket-width", type=int, default=16)
    parser.add_argument("--bootstrap-samples", type=int, default=200)
    parser.add_argument("--bootstrap-seed", type=int, default=20260801)
    parser.add_argument("--ceiling-tolerance-frames", type=int, default=2)
    args = parser.parse_args()
    args.max_graphs = args.max_graphs or [4, 5, 6]
    _validate_args(parser, args)
    summary = _load_object(args.input)
    histogram = _histogram(summary)
    candidates, rejected = _candidates(histogram, args)
    artifact = {
        "artifact_schema_version": 2,
        "research_only": True,
        "input_summary_sha256": sha256(args.input.read_bytes()).hexdigest(),
        "runtime_profile_id": summary.get("runtime_profile_id"),
        "input_record_count": sum(histogram.values()),
        "constraints": _constraints(args),
        "candidates": candidates,
        "pareto_frontier_candidate_ids": [
            candidate["candidate_id"] for candidate in candidates
        ],
        "rejected_bucket_constraints": rejected,
        "release_note": "No candidate changes a runtime or release profile.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
    print(json.dumps(artifact, sort_keys=True))
    return 0


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if any(value <= 0 for value in args.max_graphs) or len(set(args.max_graphs)) != len(
        args.max_graphs
    ):
        parser.error("--max-graphs values must be unique and positive")
    if any(
        value <= 0
        for value in (
            args.min_bucket_size,
            args.max_bucket_width,
            args.bootstrap_samples,
        )
    ):
        parser.error("bucket size, width, and bootstrap samples must be positive")
    if args.max_padding_frames < 0 or args.ceiling_tolerance_frames < 0:
        parser.error("padding and ceiling tolerances must be non-negative")
    if not 0.0 <= args.max_padding_ratio <= 1.0:
        parser.error("--max-padding-ratio must be within 0..1")


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("input summary must be a JSON object")
    return value


def _histogram(summary: dict[str, object]) -> dict[int, int]:
    value = summary.get("length_histogram")
    if not isinstance(value, dict) or not value:
        raise RuntimeError("input summary has no length_histogram")
    result: dict[int, int] = {}
    for raw_length, raw_count in value.items():
        try:
            length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("length_histogram has invalid length") from exc
        if (
            not isinstance(raw_count, int)
            or isinstance(raw_count, bool)
            or length <= 0
            or raw_count <= 0
        ):
            raise RuntimeError("length_histogram has invalid count")
        result[length] = raw_count
    return dict(sorted(result.items()))


def _constraints(args: argparse.Namespace) -> dict[str, object]:
    return {
        "max_graphs": args.max_graphs,
        "min_bucket_size": args.min_bucket_size,
        "max_padding_frames": args.max_padding_frames,
        "max_padding_ratio": args.max_padding_ratio,
        "max_bucket_width": args.max_bucket_width,
        "bootstrap_samples": args.bootstrap_samples,
        "bootstrap_seed": args.bootstrap_seed,
        "ceiling_tolerance_frames": args.ceiling_tolerance_frames,
    }


def _candidates(
    histogram: dict[int, int], args: argparse.Namespace
) -> tuple[list[dict[str, object]], dict[str, int]]:
    candidates = []
    rejected = _rejected_constraint_counts(histogram, args)
    for graph_budget in args.max_graphs:
        plan = _best_plan(histogram, graph_budget, args)
        if not plan.buckets:
            continue
        candidates.append(_candidate(histogram, plan, graph_budget, args))
    return _pareto_frontier(candidates), rejected


def _best_plan(
    histogram: dict[int, int], graph_budget: int, args: argparse.Namespace
) -> Plan:
    lengths = list(histogram)
    feasible = _feasible_buckets(histogram, args)
    plans: list[list[Plan | None]] = [
        [None] * (len(lengths) + 1) for _ in range(graph_budget + 1)
    ]
    for index in range(len(lengths) + 1):
        plans[0][index] = Plan((), 0, 0)
    for graph_count in range(1, graph_budget + 1):
        for end in range(1, len(lengths) + 1):
            best = plans[graph_count][end - 1]
            for bucket in feasible.get(end - 1, []):
                previous = plans[graph_count - 1][bucket.start]
                if previous is None:
                    continue
                candidate = Plan(
                    previous.buckets + (bucket,),
                    previous.covered_count + bucket.request_count,
                    previous.padding_sum + bucket.padding_sum,
                )
                best = _better(best, candidate)
            plans[graph_count][end] = best
    result = plans[graph_budget][-1]
    return result if result is not None else Plan((), 0, 0)


def _feasible_buckets(
    histogram: dict[int, int], args: argparse.Namespace
) -> dict[int, list[Bucket]]:
    lengths = list(histogram)
    by_end: dict[int, list[Bucket]] = {}
    for start, minimum in enumerate(lengths):
        request_count = 0
        weighted_sum = 0
        for end in range(start, len(lengths)):
            ceiling = lengths[end]
            request_count += histogram[ceiling]
            weighted_sum += ceiling * histogram[ceiling]
            padding = ceiling * request_count - weighted_sum
            max_padding = ceiling - minimum
            ratio = max_padding / minimum
            if ceiling - minimum > args.max_bucket_width:
                break
            if max_padding > args.max_padding_frames or ratio > args.max_padding_ratio:
                continue
            if request_count >= args.min_bucket_size:
                by_end.setdefault(end, []).append(
                    Bucket(start, end, request_count, padding)
                )
    return by_end


def _better(current: Plan | None, candidate: Plan) -> Plan:
    if current is None:
        return candidate
    current_score = (current.covered_count, -current.padding_sum, -len(current.buckets))
    candidate_score = (
        candidate.covered_count,
        -candidate.padding_sum,
        -len(candidate.buckets),
    )
    return candidate if candidate_score > current_score else current


def _candidate(
    histogram: dict[int, int], plan: Plan, graph_budget: int, args: argparse.Namespace
) -> dict[str, object]:
    total_count = sum(histogram.values())
    lengths = list(histogram)
    buckets = [
        {
            "minimum_actual_length": lengths[bucket.start],
            "ceiling": lengths[bucket.end],
            "request_count": bucket.request_count,
            "width": lengths[bucket.end] - lengths[bucket.start],
        }
        for bucket in plan.buckets
    ]
    padding_values = _padding_values(histogram, plan.buckets)
    candidate = {
        "candidate_id": f"pareto-graphs-{graph_budget}",
        "graph_budget": graph_budget,
        "compiled_graph_count": len(plan.buckets),
        "compiled_bucket_ceilings": [bucket["ceiling"] for bucket in buckets],
        "buckets": buckets,
        "compiled_request_count": plan.covered_count,
        "compiled_coverage_percent": plan.covered_count * 100.0 / total_count,
        "eager_request_count": total_count - plan.covered_count,
        "eager_fallback_percent": (total_count - plan.covered_count)
        * 100.0
        / total_count,
        "internal_eager_gaps": _eager_gaps(histogram, plan.buckets),
        "padding_frames": _padding_summary(padding_values),
        "padding_ratio": _padding_ratio(histogram, plan.buckets),
        "startup_cost_estimate": {
            "compiled_graph_count": len(plan.buckets),
            "measurement_status": "not_measured",
        },
        "runtime_padding_cost": {
            "total_added_frames": plan.padding_sum,
            "measurement_status": "estimated_from_prefill_lengths_only",
        },
    }
    candidate["bootstrap_stability"] = _bootstrap_stability(histogram, candidate, args)
    return candidate


def _padding_values(
    histogram: dict[int, int], buckets: tuple[Bucket, ...]
) -> list[tuple[int, int]]:
    lengths = list(histogram)
    values = []
    for bucket in buckets:
        ceiling = lengths[bucket.end]
        for index in range(bucket.start, bucket.end + 1):
            length = lengths[index]
            values.append((ceiling - length, histogram[length]))
    return values


def _padding_summary(values: list[tuple[int, int]]) -> dict[str, float | int]:
    count = sum(item_count for _, item_count in values)
    total = sum(padding * item_count for padding, item_count in values)
    return {
        "mean": total / count,
        "p95": _weighted_percentile(values, 0.95),
        "max": max(padding for padding, _ in values),
    }


def _weighted_percentile(values: list[tuple[int, int]], quantile: float) -> int:
    target = math.ceil(sum(count for _, count in values) * quantile)
    seen = 0
    for value, count in sorted(values):
        seen += count
        if seen >= target:
            return value
    raise RuntimeError("cannot calculate padding percentile")


def _padding_ratio(
    histogram: dict[int, int], buckets: tuple[Bucket, ...]
) -> dict[str, float]:
    lengths = list(histogram)
    values = [
        (lengths[bucket.end] - lengths[index]) / lengths[index]
        for bucket in buckets
        for index in range(bucket.start, bucket.end + 1)
    ]
    return {"max": max(values), "mean": sum(values) / len(values)}


def _eager_gaps(
    histogram: dict[int, int], buckets: tuple[Bucket, ...]
) -> list[dict[str, int]]:
    lengths = list(histogram)
    compiled = {
        index for bucket in buckets for index in range(bucket.start, bucket.end + 1)
    }
    gaps = []
    start: int | None = None
    count = 0
    for index, length in enumerate(lengths):
        if index not in compiled:
            if start is None:
                start = length
                count = 0
            count += histogram[length]
            continue
        if start is not None:
            gaps.append(
                {
                    "minimum_actual_length": start,
                    "maximum_actual_length": lengths[index - 1],
                    "request_count": count,
                }
            )
            start = None
    if start is not None:
        gaps.append(
            {
                "minimum_actual_length": start,
                "maximum_actual_length": lengths[-1],
                "request_count": count,
            }
        )
    return gaps


def _bootstrap_stability(
    histogram: dict[int, int], candidate: dict[str, object], args: argparse.Namespace
) -> dict[str, float | int]:
    graph_budget = _integer(candidate["graph_budget"])
    original_ceilings = cast(list[int], candidate["compiled_bucket_ceilings"])
    rng = random.Random(args.bootstrap_seed + graph_budget)
    values = [length for length, count in histogram.items() for _ in range(count)]
    matches = 0
    for _ in range(args.bootstrap_samples):
        sampled = dict(sorted(Counter(rng.choice(values) for _ in values).items()))
        plan = _best_plan(sampled, graph_budget, args)
        ceilings = [list(sampled)[bucket.end] for bucket in plan.buckets]
        if len(ceilings) == len(original_ceilings) and all(
            abs(left - right) <= args.ceiling_tolerance_frames
            for left, right in zip(ceilings, original_ceilings, strict=True)
        ):
            matches += 1
    return {
        "samples": args.bootstrap_samples,
        "ceiling_match_count": matches,
        "minimum_ceiling_match_percent": matches * 100.0 / args.bootstrap_samples,
    }


def _rejected_constraint_counts(
    histogram: dict[int, int], args: argparse.Namespace
) -> dict[str, int]:
    lengths = list(histogram)
    counts = {
        "bucket_too_small": 0,
        "padding_frames": 0,
        "padding_ratio": 0,
        "bucket_width": 0,
    }
    for start, minimum in enumerate(lengths):
        request_count = 0
        for end in range(start, len(lengths)):
            ceiling = lengths[end]
            request_count += histogram[ceiling]
            if ceiling - minimum > args.max_bucket_width:
                counts["bucket_width"] += 1
                break
            if ceiling - minimum > args.max_padding_frames:
                counts["padding_frames"] += 1
                continue
            if (ceiling - minimum) / minimum > args.max_padding_ratio:
                counts["padding_ratio"] += 1
                continue
            if request_count < args.min_bucket_size:
                counts["bucket_too_small"] += 1
    return counts


def _pareto_frontier(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    frontier = []
    for candidate in candidates:
        if any(
            _dominates(other, candidate)
            for other in candidates
            if other is not candidate
        ):
            continue
        frontier.append(candidate)
    return frontier


def _dominates(left: dict[str, object], right: dict[str, object]) -> bool:
    left_coverage = _float(left["compiled_coverage_percent"])
    right_coverage = _float(right["compiled_coverage_percent"])
    left_padding = float(_padding(left, "mean"))
    right_padding = float(_padding(right, "mean"))
    return (
        left_coverage >= right_coverage
        and left_padding <= right_padding
        and _integer(left["compiled_graph_count"])
        <= _integer(right["compiled_graph_count"])
        and (
            left_coverage > right_coverage
            or left_padding < right_padding
            or _integer(left["compiled_graph_count"])
            < _integer(right["compiled_graph_count"])
        )
    )


def _padding(candidate: dict[str, object], key: str) -> float:
    padding = candidate["padding_frames"]
    assert isinstance(padding, dict)
    return _float(padding[key])


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError("candidate has invalid integer field")
    return value


def _float(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RuntimeError("candidate has invalid numeric field")
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
