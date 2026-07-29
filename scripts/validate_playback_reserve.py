"""Validate delivered PCM chunks against a simulated playback reserve."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--reserve-ms", type=float, default=50.0)
    parser.add_argument("--min-completed-requests", type=int, default=1)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--min-completed-per-category", type=int, default=0)
    parser.add_argument("--min-pre-arrival-buffer-ms", type=float, default=0.0)
    parser.add_argument("--min-p05-pre-arrival-buffer-ms", type=float, default=0.0)
    parser.add_argument("--include-request-details", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    expected_categories = _manifest_categories(args.manifest) if args.manifest else None
    report = validate_playback_reserve(
        artifact,
        reserve_ms=args.reserve_ms,
        min_completed_requests=args.min_completed_requests,
        min_pre_arrival_buffer_ms=args.min_pre_arrival_buffer_ms,
        min_p05_pre_arrival_buffer_ms=args.min_p05_pre_arrival_buffer_ms,
        expected_categories=expected_categories,
        min_completed_per_category=args.min_completed_per_category,
        require_contract=args.manifest is not None,
        include_request_details=args.include_request_details,
    )
    report["artifact"] = str(args.artifact)
    if args.output:
        args.output.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["acceptance_pass"] else 1


def validate_playback_reserve(
    artifact: dict[str, object],
    *,
    reserve_ms: float,
    min_completed_requests: int,
    min_pre_arrival_buffer_ms: float = 0.0,
    min_p05_pre_arrival_buffer_ms: float = 0.0,
    expected_categories: dict[str, int] | None = None,
    min_completed_per_category: int = 0,
    require_contract: bool = False,
    include_request_details: bool = False,
) -> dict[str, object]:
    failures: list[str] = []
    if not math.isfinite(reserve_ms) or reserve_ms < 0.0:
        return {
            "acceptance_pass": False,
            "failures": ["reserve_ms must be finite and non-negative"],
        }
    if not math.isfinite(min_pre_arrival_buffer_ms) or min_pre_arrival_buffer_ms < 0.0:
        return {
            "acceptance_pass": False,
            "failures": ["min_pre_arrival_buffer_ms must be finite and non-negative"],
        }
    if (
        not math.isfinite(min_p05_pre_arrival_buffer_ms)
        or min_p05_pre_arrival_buffer_ms < 0.0
    ):
        return {
            "acceptance_pass": False,
            "failures": [
                "min_p05_pre_arrival_buffer_ms must be finite and non-negative"
            ],
        }
    if min_completed_per_category < 0:
        return {
            "acceptance_pass": False,
            "failures": ["min_completed_per_category must be non-negative"],
        }
    requests = artifact.get("requests")
    if not isinstance(requests, list):
        return {"acceptance_pass": False, "failures": ["artifact lacks requests"]}

    completed: list[dict[str, object]] = []
    for request in requests:
        if not isinstance(request, dict) or request.get("success") is not True:
            continue
        contract = request.get("manifest_contract")
        if require_contract and (
            not isinstance(contract, dict) or contract.get("checked") is not True
            or contract.get("valid") is not True
        ):
            failures.append(
                f"request {request.get('request_id')}: manifest contract is not valid"
            )
            continue
        completed.append(request)
    if len(completed) < min_completed_requests:
        failures.append(
            f"expected at least {min_completed_requests} completed requests, "
            f"got {len(completed)}"
        )

    all_post_chunk_reserves: list[float] = []
    all_pre_arrival_buffers: list[float] = []
    underruns = 0
    reports: list[dict[str, object]] = []
    reports_by_category: dict[str, list[dict[str, object]]] = {}
    for request in completed:
        request_id = request.get("request_id")
        chunks = request.get("chunks")
        if not isinstance(request_id, int) or not isinstance(chunks, list):
            failures.append("completed request lacks chunk observations")
            continue
        report = _analyze_request(request_id, chunks, reserve_ms)
        label = request.get("label")
        if expected_categories is not None:
            if not isinstance(label, str) or label not in expected_categories:
                failures.append(f"request {request_id}: unexpected manifest category")
                continue
        if isinstance(label, str):
            report["label"] = label
            reports_by_category.setdefault(label, []).append(report)
        reports.append(report)
        request_failures = report["failures"]
        if isinstance(request_failures, list):
            failures.extend(str(value) for value in request_failures)
        request_underruns = report["underruns"]
        if isinstance(request_underruns, int):
            underruns += request_underruns
        post_chunk_reserves = report["post_chunk_reserve_ms"]
        if isinstance(post_chunk_reserves, list):
            all_post_chunk_reserves.extend(
                float(value)
                for value in post_chunk_reserves
                if isinstance(value, (int, float))
            )
        pre_arrival_buffers = report["pre_arrival_buffer_ms"]
        if isinstance(pre_arrival_buffers, list):
            all_pre_arrival_buffers.extend(
                float(value)
                for value in pre_arrival_buffers
                if isinstance(value, (int, float))
            )

    if underruns != 0:
        failures.append(f"observed {underruns} playback underruns")
    minimum_reserve = min(all_post_chunk_reserves, default=None)
    if minimum_reserve is None:
        failures.append("no completed chunk reserve observations")
    elif minimum_reserve < 0.0:
        failures.append(
            f"minimum playback reserve {minimum_reserve:.3f} ms is negative"
        )
    minimum_pre_arrival_buffer = min(all_pre_arrival_buffers, default=None)
    p05_pre_arrival_buffer = _percentile(all_pre_arrival_buffers, 5.0)
    if minimum_pre_arrival_buffer is None:
        failures.append("no pre-arrival buffer observations")
    elif minimum_pre_arrival_buffer < min_pre_arrival_buffer_ms:
        failures.append(
            "minimum pre-arrival buffer "
            f"{minimum_pre_arrival_buffer:.3f} ms is below "
            f"{min_pre_arrival_buffer_ms:.3f} ms"
        )
    if p05_pre_arrival_buffer is None:
        failures.append("no p05 pre-arrival buffer observation")
    elif p05_pre_arrival_buffer < min_p05_pre_arrival_buffer_ms:
        failures.append(
            "p05 pre-arrival buffer "
            f"{p05_pre_arrival_buffer:.3f} ms is below "
            f"{min_p05_pre_arrival_buffer_ms:.3f} ms"
        )

    categories: dict[str, dict[str, object]] = {}
    if expected_categories is not None:
        for label, expected_count in expected_categories.items():
            category_reports = reports_by_category.get(label, [])
            category_pre = [
                float(value)
                for report in category_reports
                for value in report["pre_arrival_buffer_ms"]
                if isinstance(value, (int, float))
            ]
            category_post = [
                float(value)
                for report in category_reports
                for value in report["post_chunk_reserve_ms"]
                if isinstance(value, (int, float))
            ]
            category_underruns = sum(
                int(report["underruns"])
                for report in category_reports
                if isinstance(report.get("underruns"), int)
            )
            actual_count = len(category_reports)
            required_count = max(expected_count, min_completed_per_category)
            if actual_count < required_count:
                failures.append(
                    f"category {label}: expected at least {required_count} completed "
                    f"requests, got {actual_count}"
                )
            category_minimum_pre = min(category_pre, default=None)
            category_p05_pre = _percentile(category_pre, 5.0)
            if category_underruns != 0:
                failures.append(f"category {label}: observed {category_underruns} playback underruns")
            if category_minimum_pre is None:
                failures.append(f"category {label}: no pre-arrival buffer observations")
            elif category_minimum_pre < min_pre_arrival_buffer_ms:
                failures.append(
                    f"category {label}: minimum pre-arrival buffer "
                    f"{category_minimum_pre:.3f} ms is below "
                    f"{min_pre_arrival_buffer_ms:.3f} ms"
                )
            if category_p05_pre is None:
                failures.append(f"category {label}: no p05 pre-arrival buffer observation")
            elif category_p05_pre < min_p05_pre_arrival_buffer_ms:
                failures.append(
                    f"category {label}: p05 pre-arrival buffer "
                    f"{category_p05_pre:.3f} ms is below "
                    f"{min_p05_pre_arrival_buffer_ms:.3f} ms"
                )
            categories[label] = {
                "completed_requests": actual_count,
                "minimum_post_chunk_reserve_ms": min(category_post, default=None),
                "p05_post_chunk_reserve_ms": _percentile(category_post, 5.0),
                "minimum_pre_arrival_buffer_ms": category_minimum_pre,
                "p05_pre_arrival_buffer_ms": category_p05_pre,
                "underruns": category_underruns,
            }

    result: dict[str, object] = {
        "acceptance_pass": not failures,
        "failures": failures,
        "completed_requests": len(completed),
        "underruns": underruns,
        "minimum_post_chunk_reserve_ms": minimum_reserve,
        "p05_post_chunk_reserve_ms": _percentile(all_post_chunk_reserves, 5.0),
        "minimum_pre_arrival_buffer_ms": minimum_pre_arrival_buffer,
        "p05_pre_arrival_buffer_ms": p05_pre_arrival_buffer,
        "categories": categories,
    }
    if include_request_details:
        result["requests"] = reports
    return result


def _manifest_categories(path: Path) -> dict[str, int]:
    categories: dict[str, int] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        label = value.get("label") if isinstance(value, dict) else None
        if not isinstance(label, str) or not label:
            raise ValueError(f"manifest line {line_number} lacks label")
        categories[label] = categories.get(label, 0) + 1
    if not categories:
        raise ValueError("manifest contains no categories")
    return categories


def _analyze_request(
    request_id: int,
    chunks: list[object],
    reserve_ms: float,
) -> dict[str, object]:
    failures: list[str] = []
    buffer_ms = 0.0
    previous_arrival_ms: float | None = None
    underruns = 0
    post_chunk_reserves: list[float] = []
    pre_arrival_buffers: list[float] = []
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            failures.append(f"request {request_id}: chunk {index} is not an object")
            continue
        arrival_ms = chunk.get("arrival_ms")
        duration_ms = chunk.get("audio_duration_ms")
        if (
            not isinstance(arrival_ms, (int, float))
            or not isinstance(duration_ms, (int, float))
            or arrival_ms <= 0.0
            or duration_ms <= 0.0
        ):
            failures.append(f"request {request_id}: chunk {index} lacks timing")
            continue
        if previous_arrival_ms is not None:
            elapsed_ms = float(arrival_ms) - previous_arrival_ms
            if elapsed_ms < 0.0:
                failures.append(f"request {request_id}: chunk timestamps regress")
                continue
            buffer_ms -= elapsed_ms
            pre_arrival_buffers.append(buffer_ms)
            if buffer_ms < 0.0:
                underruns += 1
                buffer_ms = 0.0
        buffer_ms += float(duration_ms)
        post_chunk_reserves.append(buffer_ms - reserve_ms)
        previous_arrival_ms = float(arrival_ms)
    return {
        "request_id": request_id,
        "failures": failures,
        "underruns": underruns,
        "post_chunk_reserve_ms": post_chunk_reserves,
        "pre_arrival_buffer_ms": pre_arrival_buffers,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = percentile / 100.0 * (len(ordered) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


if __name__ == "__main__":
    raise SystemExit(main())
