"""Validate a public-C++-API soak artifact against worker stderr metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--worker-metrics", type=Path, required=True)
    parser.add_argument("--expected-requests", type=int, required=True)
    parser.add_argument("--expected-cancelled", type=int, required=True)
    parser.add_argument("--expected-cache-entries", type=int, default=6)
    parser.add_argument("--expected-first-chunk-steps", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    worker_metrics_text = args.worker_metrics.read_text(encoding="utf-8")
    report = validate_cpp_api_soak(
        artifact,
        _worker_metrics(worker_metrics_text),
        expected_requests=args.expected_requests,
        expected_cancelled=args.expected_cancelled,
        expected_cache_entries=args.expected_cache_entries,
        expected_first_chunk_steps=args.expected_first_chunk_steps,
    )
    report["artifact"] = str(args.artifact)
    report["worker_metrics"] = str(args.worker_metrics)
    report["worker_metrics_sha256"] = hashlib.sha256(
        worker_metrics_text.encode("utf-8")
    ).hexdigest()
    report["acceptance_pass"] = not report["failures"]
    if args.output:
        args.output.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["acceptance_pass"] else 1


def validate_cpp_api_soak(
    artifact: dict[str, object],
    worker_metrics: list[dict[str, object]],
    *,
    expected_requests: int,
    expected_cancelled: int,
    expected_cache_entries: int,
    expected_first_chunk_steps: int | None = None,
) -> dict[str, object]:
    failures: list[str] = []
    requests = artifact.get("requests")
    if not isinstance(requests, list):
        return {"failures": ["artifact lacks requests array"]}
    if len(requests) != expected_requests:
        failures.append(f"expected {expected_requests} requests, got {len(requests)}")

    completed = 0
    cancelled = 0
    request_ids: set[int] = set()
    for request in requests:
        if not isinstance(request, dict):
            failures.append("request entry is not an object")
            continue
        request_id = request.get("request_id")
        if not isinstance(request_id, int):
            failures.append("request lacks numeric request_id")
            continue
        request_ids.add(request_id)
        if request.get("success") is True:
            completed += 1
            if request.get("cancelled") is not False:
                failures.append(f"request {request_id}: completed request is cancelled")
            audio_chunks = request.get("audio_chunks")
            if not isinstance(audio_chunks, int) or audio_chunks < 2:
                failures.append(f"request {request_id}: completion lacks streaming PCM")
        elif request.get("cancelled") is True:
            cancelled += 1
            if request.get("audio_chunks") != 1:
                failures.append(
                    f"request {request_id}: cancellation was not after first PCM"
                )
        else:
            failures.append(f"request {request_id}: unexpected failed terminal state")

    if cancelled != expected_cancelled:
        failures.append(f"expected {expected_cancelled} cancellations, got {cancelled}")
    if completed + cancelled != len(requests):
        failures.append("terminal accounting does not cover all requests")

    metrics_by_request = _metrics_by_request(worker_metrics)
    worker_pids: set[int] = set()
    cache_entries: set[int] = set()
    for request_id in sorted(request_ids):
        metrics = metrics_by_request.get(request_id, {})
        phases = metrics.get("request_first_chunk_engine_phases")
        if not isinstance(phases, dict):
            failures.append(f"request {request_id}: missing first-chunk metrics")
        else:
            _validate_route(
                request_id,
                phases,
                expected_cache_entries,
                expected_first_chunk_steps,
                cache_entries,
                failures,
            )
        memory = metrics.get("worker_runtime_memory")
        if not isinstance(memory, dict):
            failures.append(f"request {request_id}: missing worker memory metric")
            continue
        worker_pid = memory.get("worker_pid")
        if isinstance(worker_pid, int):
            worker_pids.add(worker_pid)
        else:
            failures.append(f"request {request_id}: missing worker PID")
        for field in (
            "cuda_memory_allocated_bytes",
            "cuda_memory_reserved_bytes",
            "cuda_memory_max_reserved_bytes",
        ):
            if not isinstance(memory.get(field), int):
                failures.append(f"request {request_id}: missing {field}")

    if cache_entries != {expected_cache_entries}:
        failures.append(
            f"cache entries {sorted(cache_entries)} != {expected_cache_entries}"
        )
    if len(worker_pids) != 1:
        failures.append(f"expected one worker PID, got {sorted(worker_pids)}")
    return {
        "failures": failures,
        "completed_requests": completed,
        "cancelled_requests": cancelled,
        "cache_entries_observed": sorted(cache_entries),
        "worker_pids": sorted(worker_pids),
    }


def _worker_metrics(stderr_text: str) -> list[dict[str, object]]:
    metrics: list[dict[str, object]] = []
    marker = "qtb_metric "
    search_start = 0
    while True:
        marker_at = stderr_text.find(marker, search_start)
        if marker_at < 0:
            return metrics
        object_start = stderr_text.find("{", marker_at + len(marker))
        if object_start < 0:
            return metrics
        object_end = _json_object_end(stderr_text, object_start)
        if object_end is None:
            search_start = object_start + 1
            continue
        try:
            payload = json.loads(
                stderr_text[object_start:object_end]
                .replace("\r", "")
                .replace("\n", "")
            )
        except json.JSONDecodeError:
            search_start = object_start + 1
            continue
        if isinstance(payload, dict):
            metrics.append(payload)
        search_start = object_end


def _json_object_end(text: str, start: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _metrics_by_request(
    worker_metrics: list[dict[str, object]],
) -> dict[int, dict[str, dict[str, object]]]:
    grouped: dict[int, dict[str, dict[str, object]]] = {}
    for metric in worker_metrics:
        request_id = metric.get("request_id")
        event = metric.get("event")
        if not isinstance(request_id, int) or not isinstance(event, str):
            continue
        grouped.setdefault(request_id, {}).setdefault(event, metric)
    return grouped


def _validate_route(
    request_id: int,
    phases: dict[str, object],
    expected_cache_entries: int,
    expected_first_chunk_steps: int | None,
    cache_entries: set[int],
    failures: list[str],
) -> None:
    expected = {
        "prefill_backend_used": "compile_reduce_overhead",
        "prefill_compile_attempted": False,
        "prefill_compile_fallback": False,
        "prefill_compile_cache_hit": True,
        "prefill_require_precompiled": True,
        "prefill_dynamo_unique_graphs_delta": 0,
        "prefill_compile_cache_entries_delta": 0,
    }
    for key, value in expected.items():
        if phases.get(key) != value:
            failures.append(f"request {request_id}: expected {key}={value!r}")
    entries = phases.get("prefill_compile_cache_entries")
    if isinstance(entries, int):
        cache_entries.add(entries)
    else:
        failures.append(f"request {request_id}: missing cache entry count")
    if expected_first_chunk_steps is not None:
        for key in ("chunk_steps", "chunk_target_steps"):
            if phases.get(key) != expected_first_chunk_steps:
                failures.append(
                    f"request {request_id}: expected {key}="
                    f"{expected_first_chunk_steps!r}"
                )


if __name__ == "__main__":
    raise SystemExit(main())
