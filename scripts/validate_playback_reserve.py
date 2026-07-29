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
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    report = validate_playback_reserve(
        artifact,
        reserve_ms=args.reserve_ms,
        min_completed_requests=args.min_completed_requests,
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
) -> dict[str, object]:
    failures: list[str] = []
    if not math.isfinite(reserve_ms) or reserve_ms < 0.0:
        return {
            "acceptance_pass": False,
            "failures": ["reserve_ms must be finite and non-negative"],
        }
    requests = artifact.get("requests")
    if not isinstance(requests, list):
        return {"acceptance_pass": False, "failures": ["artifact lacks requests"]}

    completed = [
        request
        for request in requests
        if isinstance(request, dict) and request.get("success") is True
    ]
    if len(completed) < min_completed_requests:
        failures.append(
            f"expected at least {min_completed_requests} completed requests, "
            f"got {len(completed)}"
        )

    all_post_chunk_reserves: list[float] = []
    all_pre_arrival_buffers: list[float] = []
    underruns = 0
    reports: list[dict[str, object]] = []
    for request in completed:
        request_id = request.get("request_id")
        chunks = request.get("chunks")
        if not isinstance(request_id, int) or not isinstance(chunks, list):
            failures.append("completed request lacks chunk observations")
            continue
        report = _analyze_request(request_id, chunks, reserve_ms)
        reports.append(report)
        request_failures = report["failures"]
        if isinstance(request_failures, list):
            failures.extend(str(value) for value in request_failures)
        underruns += int(report["underruns"])
        all_post_chunk_reserves.extend(report["post_chunk_reserve_ms"])
        all_pre_arrival_buffers.extend(report["pre_arrival_buffer_ms"])

    if underruns != 0:
        failures.append(f"observed {underruns} playback underruns")
    minimum_reserve = min(all_post_chunk_reserves, default=None)
    if minimum_reserve is None:
        failures.append("no completed chunk reserve observations")
    elif minimum_reserve < 0.0:
        failures.append(
            f"minimum playback reserve {minimum_reserve:.3f} ms is negative"
        )

    result: dict[str, object] = {
        "acceptance_pass": not failures,
        "failures": failures,
        "completed_requests": len(completed),
        "underruns": underruns,
        "minimum_post_chunk_reserve_ms": minimum_reserve,
        "p05_post_chunk_reserve_ms": _percentile(all_post_chunk_reserves, 5.0),
        "minimum_pre_arrival_buffer_ms": min(all_pre_arrival_buffers, default=None),
        "requests": reports,
    }
    return result


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
