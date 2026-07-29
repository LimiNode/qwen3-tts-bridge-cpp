"""Exercise a long-lived Qwen worker with mixed completed and cancelled requests."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

try:
    from semantic_trace_contract import validate_generation_trace
except ModuleNotFoundError:  # Imported as scripts.qwen_mixed_soak in tests.
    from scripts.semantic_trace_contract import validate_generation_trace

from benchmark_packaged_worker import (
    _is_request_frame,
    _run_request,
    _shutdown,
    _synthesize_payload,
)
from benchmark_packaged_worker_restart import (
    _hello,
    _load_run_shapes,
    _with_request_pipeline_metrics,
    _worker_metrics,
)
from benchmark_runtime import runtime_fingerprint
from qwen_tts_bridge_worker.protocol import FrameType
from verify_packaged_worker import PackagedWorkerHarness, _control_payload


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.requests <= 0:
        parser.error("--requests must be positive")
    if args.cancel_every < 0:
        parser.error("--cancel-every must be non-negative")
    if args.snapshot_every <= 0:
        parser.error("--snapshot-every must be positive")
    _validate_worker_args(parser, args.worker_arg)
    worker_executable = args.worker_executable.resolve()
    if not worker_executable.is_file():
        parser.error(f"worker executable was not found: {worker_executable}")
    shapes = _load_run_shapes(args.schedule)
    if not shapes:
        parser.error("--schedule must contain at least one JSONL scenario")

    runtime = runtime_fingerprint(
        worker_executable=worker_executable,
        worker_prefix_args=args.worker_arg,
        args=args,
    )
    _validate_wheel(runtime, args.expected_faster_wheel_sha256)
    _progress("runtime provenance verified")
    harness = PackagedWorkerHarness(
        worker_executable=worker_executable,
        args=args.worker_arg,
        timeout_seconds=args.timeout_seconds,
    )
    results: list[dict[str, object]] = []
    snapshots: list[dict[str, object]] = []
    ready: dict[str, object] | None = None
    worker_metrics: list[dict[str, object]] = []
    try:
        _progress("waiting for worker readiness")
        ready = _hello(harness)
        _progress("worker ready")
        snapshots.append(_snapshot(harness.pid, completed_requests=0))
        if args.partial_output:
            _write_report(
                args.partial_output,
                _report(args, runtime, ready, results, snapshots, worker_metrics),
            )
        for request_index in range(1, args.requests + 1):
            shape = dict(shapes[(request_index - 1) % len(shapes)])
            request_id = request_index
            cancelled = (
                args.cancel_every > 0
                and request_index % args.cancel_every == 0
                and request_index < args.requests
            )
            if cancelled:
                _progress(f"request {request_index}: cancelling after first audio")
                result = _run_cancel_after_first_audio(
                    harness,
                    request_id=request_id,
                    shape=shape,
                    cancel_timeout_seconds=args.cancel_timeout_seconds,
                )
            else:
                _progress(f"request {request_index}: completing")
                result = _run_request(
                    harness,
                    request_id=request_id,
                    text=str(shape["text"]),
                    language=str(shape["language"]),
                    speaker=str(shape["speaker"]),
                    instruction=str(shape["instruction"]),
                )
                result["terminal_state"] = "completed"
            result["request_index"] = request_index
            result["shape"] = shape
            result["cancel_after_first_audio"] = cancelled
            results.append(result)
            if (
                request_index % args.snapshot_every == 0
                or request_index == args.requests
            ):
                snapshots.append(
                    _snapshot(harness.pid, completed_requests=request_index)
                )
            if args.partial_output and request_index % args.progress_every == 0:
                _write_report(
                    args.partial_output,
                    _report(args, runtime, ready, results, snapshots, worker_metrics),
                )
            if request_index % args.progress_every == 0:
                _progress(f"request {request_index}: terminal {result['terminal_state']}")
        _shutdown(harness)
        worker_metrics = _worker_metrics(harness.stderr_text())
    finally:
        harness.close()

    results = [
        _with_request_pipeline_metrics(result, worker_metrics) for result in results
    ]
    report = _report(args, runtime, ready, results, snapshots, worker_metrics)
    report["validation"] = _validate_soak(
        results,
        snapshots,
        max_rss_growth_mb=args.max_rss_growth_mb,
        expected_requests=args.requests,
        expected_cancelled=(args.requests - 1) // args.cancel_every
        if args.cancel_every > 0
        else 0,
    )
    report["acceptance_pass"] = not report["validation"]["failures"]
    if args.partial_output:
        _write_report(args.partial_output, report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["acceptance_pass"] else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worker_executable", type=Path)
    parser.add_argument("--worker-arg", action="append", default=[])
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--cancel-every", type=int, default=10)
    parser.add_argument("--snapshot-every", type=int, default=25)
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--partial-output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=1200.0)
    parser.add_argument("--cancel-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-rss-growth-mb", type=float, default=512.0)
    parser.add_argument("--expected-faster-wheel-sha256", required=True)
    return parser


def _validate_worker_args(
    parser: argparse.ArgumentParser,
    worker_args: list[str],
) -> None:
    if "--engine" in worker_args:
        parser.error(
            "--worker-arg expects the worker process arguments, not benchmark "
            "arguments; use '--worker-arg=qwen' instead of "
            "'--worker-arg=--engine --worker-arg=qwen'"
        )
    if not any(argument in {"mock", "qwen"} for argument in worker_args):
        parser.error("--worker-arg must include the worker engine subcommand")


def _run_cancel_after_first_audio(
    harness: PackagedWorkerHarness,
    *,
    request_id: int,
    shape: dict[str, object],
    cancel_timeout_seconds: float,
) -> dict[str, object]:
    started_at = time.perf_counter()
    harness.send_control(
        request_id,
        _synthesize_payload(
            text=str(shape["text"]),
            language=str(shape["language"]),
            speaker=str(shape["speaker"]),
            instruction=str(shape["instruction"]),
        ),
    )
    audio_bytes = 0
    audio_chunks = 0
    first_audio_ms: float | None = None
    cancel_sent_at: float | None = None
    cancel_completed_at: float | None = None
    cancelled_ms: float | None = None
    while cancelled_ms is None:
        timeout_seconds = (
            cancel_timeout_seconds if cancel_sent_at is not None else None
        )
        frame = harness.read_frame(
            lambda item: _is_request_frame(item, request_id),
            timeout_seconds=timeout_seconds,
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        if frame.header.frame_type == FrameType.AUDIO_PCM:
            if first_audio_ms is None:
                first_audio_ms = elapsed_ms
                cancel_sent_at = time.perf_counter()
                harness.send_control(request_id, {"message_type": "cancel"})
            audio_bytes += len(frame.payload)
            audio_chunks += 1
            continue
        if _control_payload(frame).get("message_type") == "cancelled":
            cancelled_ms = elapsed_ms
            cancel_completed_at = time.perf_counter()
    return {
        "request_id": request_id,
        "first_audio_ms": first_audio_ms,
        "cancelled_ms": cancelled_ms,
        "cancel_after_first_audio_ms": (
            (cancelled_ms - first_audio_ms) if first_audio_ms is not None else None
        ),
        "cancel_send_delay_ms": (
            (cancel_completed_at - cancel_sent_at) * 1000.0
            if cancel_sent_at is not None and cancel_completed_at is not None
            else None
        ),
        "audio_bytes": audio_bytes,
        "audio_chunks": audio_chunks,
        "terminal_state": "cancelled",
    }


def _progress(message: str) -> None:
    print(f"mixed soak: {message}", file=sys.stderr, flush=True)


def _snapshot(pid: int, *, completed_requests: int) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "completed_requests": completed_requests,
        "monotonic_s": time.monotonic(),
        "rss_bytes": _rss_bytes(pid),
        "gpu_memory_used_mib": _gpu_memory_used_mib(),
    }
    return snapshot


def _rss_bytes(pid: int) -> int | None:
    try:
        import psutil  # type: ignore[import-not-found]

        return int(psutil.Process(pid).memory_info().rss)
    except Exception:
        return None


def _gpu_memory_used_mib() -> list[int] | None:
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    values: list[int] = []
    for line in output.splitlines():
        try:
            values.append(int(line.strip()))
        except ValueError:
            return None
    return values


def _validate_wheel(runtime: dict[str, object], expected_sha256: str) -> None:
    try:
        actual = str(
            runtime["imports"]["faster_qwen3_tts"]["distribution"]["direct_url"][
                "archive_info"
            ]["hash"]
        ).removeprefix("sha256=")
    except (KeyError, TypeError):
        raise RuntimeError(
            "runtime lacks installed FasterQwen wheel provenance"
        ) from None
    if actual.lower() != expected_sha256.lower():
        raise RuntimeError(
            f"FasterQwen wheel SHA mismatch: {actual} != {expected_sha256}"
        )


def _report(
    args: argparse.Namespace,
    runtime: dict[str, object],
    ready: dict[str, object] | None,
    results: list[dict[str, object]],
    snapshots: list[dict[str, object]],
    worker_metrics: list[dict[str, object]],
) -> dict[str, object]:
    completed = [
        result for result in results if result.get("terminal_state") == "completed"
    ]
    cancelled = [
        result for result in results if result.get("terminal_state") == "cancelled"
    ]
    return {
        "artifact_schema_version": 1,
        "config": {
            "requests": args.requests,
            "cancel_every": args.cancel_every,
            "snapshot_every": args.snapshot_every,
            "schedule": str(args.schedule),
            "worker_args": args.worker_arg,
            "expected_faster_wheel_sha256": args.expected_faster_wheel_sha256,
        },
        "runtime": runtime,
        "ready": ready,
        "summary": {
            "completed_requests": len(completed),
            "cancelled_requests": len(cancelled),
            "first_audio_ms": _summary(completed, "first_audio_ms"),
            "completed_ms": _summary(completed, "completed_ms"),
            "real_time_factor": _summary(completed, "real_time_factor"),
            "cancel_after_first_audio_ms": _summary(
                cancelled,
                "cancel_after_first_audio_ms",
            ),
        },
        "requests": results,
        "memory_snapshots": snapshots,
        "worker_metrics": worker_metrics,
        "validation": {"failures": ["incomplete soak"]},
        "acceptance_pass": False,
    }


def _validate_soak(
    results: list[dict[str, object]],
    snapshots: list[dict[str, object]],
    *,
    max_rss_growth_mb: float,
    expected_requests: int,
    expected_cancelled: int,
) -> dict[str, object]:
    failures: list[str] = []
    cache_entries: set[float] = set()
    cancellation_reset_checks = 0
    for index, result in enumerate(results):
        prefix = f"request {result.get('request_id')}"
        terminal_state = result.get("terminal_state")
        if terminal_state == "completed":
            trace = result.get("generation_trace")
            if not isinstance(trace, dict):
                failures.append(f"{prefix}: missing completed generation trace")
            else:
                try:
                    validate_generation_trace(trace)
                except RuntimeError as exc:
                    failures.append(f"{prefix}: {exc}")
        elif terminal_state != "cancelled":
            failures.append(f"{prefix}: unexpected terminal state {terminal_state!r}")
        _validate_route(prefix, result, failures, cache_entries)
        if terminal_state == "cancelled":
            next_result = results[index + 1] if index + 1 < len(results) else None
            if next_result is None or next_result.get("terminal_state") != "completed":
                failures.append(
                    f"{prefix}: cancellation was not followed by completion"
                )
            else:
                cancellation_reset_checks += 1

    memory = _memory_validation(snapshots, max_rss_growth_mb)
    failures.extend(memory["failures"])
    completed_count = sum(
        1 for result in results if result.get("terminal_state") == "completed"
    )
    cancelled_count = sum(
        1 for result in results if result.get("terminal_state") == "cancelled"
    )
    if len(results) != expected_requests:
        failures.append(f"expected {expected_requests} requests, got {len(results)}")
    if cancelled_count != expected_cancelled:
        failures.append(
            f"expected {expected_cancelled} cancellations, got {cancelled_count}"
        )
    if len(cache_entries) != 1:
        failures.append(
            f"prefill compile cache changed across requests: {sorted(cache_entries)}"
        )
    return {
        "failures": failures,
        "terminal_trace_completed_requests": completed_count,
        "cancelled_requests": cancelled_count,
        "cancellation_reset_checks": cancellation_reset_checks,
        "cache_entries_observed": sorted(cache_entries),
        "memory": memory,
    }


def _validate_route(
    prefix: str,
    result: dict[str, object],
    failures: list[str],
    cache_entries: set[float],
) -> None:
    shape = result.get("shape")
    label = shape.get("label") if isinstance(shape, dict) else ""
    known = isinstance(label, str) and label.startswith("allowlist_")
    expected_backend = "compile_reduce_overhead" if known else "eager"
    for key, expected in (
        ("first_chunk_prefill_backend_used", expected_backend),
        ("first_chunk_prefill_compile_fallback", False),
        ("first_chunk_prefill_compile_attempted", False),
        ("first_chunk_prefill_compile_attempt_count", 0),
        ("first_chunk_prefill_compile_cache_entries_delta", 0),
        ("first_chunk_prefill_compile_cache_evictions_delta", 0),
        ("first_chunk_prefill_dynamo_counter_available", True),
        ("first_chunk_prefill_dynamo_unique_graphs_delta", 0),
    ):
        if result.get(key) != expected:
            failures.append(f"{prefix}: expected {key}={expected!r}")
    entries = result.get("first_chunk_prefill_compile_cache_entries")
    if isinstance(entries, (int, float)):
        cache_entries.add(float(entries))
    else:
        failures.append(f"{prefix}: missing prefill compile cache entry count")
    if known:
        for key, expected in (
            ("first_chunk_prefill_compile_cache_hit", True),
            ("first_chunk_prefill_require_precompiled", True),
        ):
            if result.get(key) != expected:
                failures.append(f"{prefix}: expected {key}={expected!r}")


def _memory_validation(
    snapshots: list[dict[str, object]],
    max_rss_growth_mb: float,
) -> dict[str, object]:
    failures: list[str] = []
    rss_values = [
        int(snapshot["rss_bytes"])
        for snapshot in snapshots
        if isinstance(snapshot.get("rss_bytes"), int)
    ]
    growth_mb = None
    monotonic_non_decreasing = None
    if len(rss_values) >= 2:
        growth_mb = (rss_values[-1] - rss_values[0]) / (1024.0 * 1024.0)
        monotonic_non_decreasing = all(
            previous <= current
            for previous, current in zip(rss_values, rss_values[1:], strict=False)
        )
        if growth_mb > max_rss_growth_mb:
            failures.append(
                f"RSS grew {growth_mb:.3f} MiB, above {max_rss_growth_mb:.3f} MiB"
            )
    return {
        "failures": failures,
        "rss_growth_mib": growth_mb,
        "rss_monotonic_non_decreasing": monotonic_non_decreasing,
        "snapshots": len(snapshots),
    }


def _summary(
    results: list[dict[str, object]],
    key: str,
) -> dict[str, float] | None:
    values = sorted(
        float(result[key])
        for result in results
        if isinstance(result.get(key), (int, float))
    )
    if not values:
        return None
    return {
        "min": values[0],
        "median": statistics.median(values),
        "p95": _percentile(values, 95.0),
        "max": values[-1],
    }


def _percentile(values: list[float], percentile: float) -> float:
    if len(values) == 1:
        return values[0]
    rank = percentile / 100.0 * (len(values) - 1)
    low = int(rank)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (rank - low)


def _write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
