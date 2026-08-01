"""Run a semantic, cancellation-aware long-lived Qwen release soak."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import random
import sys
import time
from pathlib import Path

try:
    from qwen_mixed_soak import (
        _memory_validation,
        _progress,
        _snapshot,
        _summary,
        _validate_route,
        _validate_wheel,
        _write_report,
    )
    from semantic_trace_contract import validate_generation_trace
except ModuleNotFoundError:  # Imported as scripts.qwen_release_soak in tests.
    from scripts.qwen_mixed_soak import (
        _memory_validation,
        _progress,
        _snapshot,
        _summary,
        _validate_route,
        _validate_wheel,
        _write_report,
    )
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


_CANCEL_STAGES = (
    "before_first_audio",
    "after_first_audio",
    "after_third_audio",
)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(parser, args)
    worker_executable = args.worker_executable.resolve()
    if not worker_executable.is_file():
        parser.error(f"worker executable was not found: {worker_executable}")
    shapes = _shapes_by_label(args.schedule)
    _require_labels(parser, shapes, args.required_label)
    seeds = _load_seed_manifest(args.seed_manifest)
    operations = _build_operations(shapes, args, seeds)

    runtime = runtime_fingerprint(
        worker_executable=worker_executable,
        worker_prefix_args=args.worker_arg,
        args=args,
    )
    _validate_wheel(
        runtime,
        args.expected_faster_wheel_sha256,
        args.expected_faster_source_bundle_sha256,
    )
    harness = PackagedWorkerHarness(
        worker_executable=worker_executable,
        args=args.worker_arg,
        timeout_seconds=args.timeout_seconds,
    )
    results: list[dict[str, object]] = []
    snapshots: list[dict[str, object]] = []
    worker_metrics: list[dict[str, object]] = []
    ready: dict[str, object] | None = None
    try:
        _progress("waiting for worker readiness")
        ready = _hello(harness)
        _progress("worker ready")
        snapshots.append(_snapshot(harness.pid, completed_requests=0))
        for index, operation in enumerate(operations, 1):
            result = _run_operation(harness, index, operation, args)
            result["request_index"] = index
            results.append(result)
            snapshots.append(_snapshot(harness.pid, completed_requests=index))
            if args.partial_output and index % args.progress_every == 0:
                _write_report(
                    args.partial_output,
                    _report(args, runtime, ready, results, snapshots, worker_metrics),
                )
            if index % args.progress_every == 0:
                _progress(f"request {index}: {operation['role']}")
        _shutdown(harness)
        worker_metrics = _worker_metrics(harness.stderr_text())
    finally:
        harness.close()

    results = [
        _with_request_pipeline_metrics(result, worker_metrics) for result in results
    ]
    validation = _validate_release_soak(
        results,
        snapshots,
        worker_metrics,
        expected_cache_entries=args.expected_prefill_cache_entries,
        expected_requests=args.requests,
        expected_cancellations=args.cancellations_per_category * len(shapes),
        expected_labels=set(shapes),
        cancellations_per_stage=(
            args.cancellations_per_category // len(_CANCEL_STAGES)
        ),
        max_rss_growth_mb=args.max_rss_growth_mb,
        max_private_growth_mb=args.max_private_growth_mb,
        max_cuda_allocated_growth_mb=args.max_cuda_allocated_growth_mb,
        max_cuda_reserved_growth_mb=args.max_cuda_reserved_growth_mb,
        max_cuda_reserved_tail_slope_bytes_per_request=(
            args.max_cuda_reserved_tail_slope_bytes_per_request
        ),
        gpu_pid_telemetry_policy=args.gpu_pid_telemetry_policy,
    )
    report = _report(args, runtime, ready, results, snapshots, worker_metrics)
    report["validation"] = validation
    report["acceptance_pass"] = not validation["failures"]
    if args.partial_output:
        _write_report(args.partial_output, report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["acceptance_pass"] else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worker_executable", type=Path)
    parser.add_argument("--worker-arg", action="append", default=[])
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--seed-manifest", type=Path, required=True)
    parser.add_argument("--required-label", action="append", default=[])
    parser.add_argument("--requests", type=int, default=900)
    parser.add_argument("--cancellations-per-category", type=int, default=12)
    parser.add_argument("--semantic-seed", type=int, default=4242)
    parser.add_argument("--operation-seed", type=int, default=20260729)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--partial-output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=1200.0)
    parser.add_argument("--cancel-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-rss-growth-mb", type=float, default=512.0)
    parser.add_argument("--max-private-growth-mb", type=float, default=512.0)
    parser.add_argument("--max-cuda-allocated-growth-mb", type=float, default=128.0)
    parser.add_argument("--max-cuda-reserved-growth-mb", type=float, default=128.0)
    parser.add_argument(
        "--max-cuda-reserved-tail-slope-bytes-per-request",
        type=float,
        default=1048576.0,
    )
    parser.add_argument(
        "--gpu-pid-telemetry-policy",
        choices=("required", "allow_unsupported"),
        default="required",
    )
    parser.add_argument("--expected-prefill-cache-entries", type=int, default=6)
    parser.add_argument("--expected-faster-wheel-sha256", default="")
    parser.add_argument("--expected-faster-source-bundle-sha256", default="")
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.requests <= 0 or args.progress_every <= 0:
        parser.error("--requests and --progress-every must be positive")
    if args.cancellations_per_category <= 0:
        parser.error("--cancellations-per-category must be positive")
    if args.cancellations_per_category % len(_CANCEL_STAGES) != 0:
        parser.error("--cancellations-per-category must divide evenly across stages")
    provenance_count = sum(
        bool(value)
        for value in (
            args.expected_faster_wheel_sha256,
            args.expected_faster_source_bundle_sha256,
        )
    )
    if provenance_count != 1:
        parser.error(
            "provide exactly one FasterQwen provenance: "
            "--expected-faster-wheel-sha256 or "
            "--expected-faster-source-bundle-sha256"
        )
    for key in (
        "expected_prefill_cache_entries",
        "max_rss_growth_mb",
        "max_private_growth_mb",
        "max_cuda_allocated_growth_mb",
        "max_cuda_reserved_growth_mb",
        "max_cuda_reserved_tail_slope_bytes_per_request",
    ):
        if getattr(args, key) <= 0:
            parser.error(f"--{key.replace('_', '-')} must be positive")
    if "--engine" in args.worker_arg or not any(
        item in {"mock", "qwen"} for item in args.worker_arg
    ):
        parser.error("--worker-arg must contain worker process arguments and engine")


def _shapes_by_label(schedule: Path) -> dict[str, dict[str, object]]:
    shapes: dict[str, dict[str, object]] = {}
    for shape in _load_run_shapes(schedule):
        label = shape.get("label")
        if isinstance(label, str) and label and label not in shapes:
            shapes[label] = dict(shape)
    if not shapes:
        raise RuntimeError("schedule contains no labeled scenarios")
    return shapes


def _require_labels(
    parser: argparse.ArgumentParser,
    shapes: dict[str, dict[str, object]],
    required: list[str],
) -> None:
    missing = sorted(set(required).difference(shapes))
    if missing:
        parser.error(f"schedule is missing required labels: {', '.join(missing)}")


def _load_seed_manifest(path: Path) -> list[int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("seeds") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise RuntimeError("seed manifest must be a JSON list or object with seeds")
    seeds = [
        value
        for value in values
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    ]
    if len(seeds) != len(values) or len(set(seeds)) != len(seeds):
        raise RuntimeError("seed manifest must contain unique non-negative integers")
    if len(seeds) < 20:
        raise RuntimeError("seed manifest must contain at least 20 seeds")
    return seeds


def _build_operations(
    shapes: dict[str, dict[str, object]],
    args: argparse.Namespace,
    seeds: list[int],
) -> list[dict[str, object]]:
    labels = sorted(shapes)
    if args.requests % len(labels) != 0:
        raise RuntimeError("--requests must divide evenly across scenario labels")
    per_label = args.requests // len(labels)
    semantic_cost = 1 + args.cancellations_per_category * 2
    if per_label < semantic_cost:
        raise RuntimeError("--requests is too small for semantic cancellation coverage")

    references = [
        _operation("reference", label, shapes[label], args.semantic_seed)
        for label in labels
    ]
    units: list[list[dict[str, object]]] = []
    stage_repeats = args.cancellations_per_category // len(_CANCEL_STAGES)
    for label in labels:
        shape = shapes[label]
        for stage in _CANCEL_STAGES:
            for _ in range(stage_repeats):
                units.append(
                    [
                        _operation("cancel", label, shape, args.semantic_seed, stage),
                        _operation("audit", label, shape, args.semantic_seed),
                    ]
                )
        normal_count = per_label - semantic_cost
        for normal_index in range(normal_count):
            units.append(
                [
                    _operation(
                        "normal",
                        label,
                        shape,
                        seeds[normal_index % len(seeds)],
                    )
                ]
            )
    random.Random(args.operation_seed).shuffle(units)
    return [*references, *(operation for unit in units for operation in unit)]


def _operation(
    role: str,
    label: str,
    shape: dict[str, object],
    seed: int,
    cancel_stage: str | None = None,
) -> dict[str, object]:
    return {
        "role": role,
        "label": label,
        "shape": shape,
        "seed": seed,
        "cancel_stage": cancel_stage,
    }


def _run_operation(
    harness: PackagedWorkerHarness,
    request_id: int,
    operation: dict[str, object],
    args: argparse.Namespace,
) -> dict[str, object]:
    shape = operation["shape"]
    if not isinstance(shape, dict):
        raise RuntimeError("invalid generated soak operation")
    role = str(operation["role"])
    seed = int(operation["seed"])
    if role == "cancel":
        result = _run_cancel(
            harness,
            request_id=request_id,
            shape=shape,
            seed=seed,
            stage=str(operation["cancel_stage"]),
            timeout_seconds=args.cancel_timeout_seconds,
        )
    else:
        result = _run_request(
            harness,
            request_id=request_id,
            text=str(shape["text"]),
            language=str(shape["language"]),
            speaker=str(shape["speaker"]),
            instruction=str(shape["instruction"]),
            seed=seed,
        )
        result["terminal_state"] = "completed"
    result.update(
        {
            "role": role,
            "shape": shape,
            "shape_label": operation["label"],
            "seed": seed,
            "cancel_stage": operation["cancel_stage"],
        }
    )
    return result


def _run_cancel(
    harness: PackagedWorkerHarness,
    *,
    request_id: int,
    shape: dict[str, object],
    seed: int,
    stage: str,
    timeout_seconds: float,
) -> dict[str, object]:
    harness.send_control(
        request_id,
        _synthesize_payload(
            text=str(shape["text"]),
            language=str(shape["language"]),
            speaker=str(shape["speaker"]),
            instruction=str(shape["instruction"]),
            seed=seed,
        ),
    )
    started_at = time.perf_counter()
    audio_chunks = 0
    audio_bytes = 0
    digest = sha256()
    cancel_sent_at: float | None = None
    first_audio_ms: float | None = None
    while True:
        frame = harness.read_frame(
            lambda value: _is_request_frame(value, request_id),
            timeout_seconds=(timeout_seconds if cancel_sent_at is not None else None),
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        if frame.header.frame_type == FrameType.AUDIO_PCM:
            audio_chunks += 1
            audio_bytes += len(frame.payload)
            digest.update(frame.payload)
            if first_audio_ms is None:
                first_audio_ms = elapsed_ms
            if stage == "before_first_audio":
                raise RuntimeError("before_first_audio cancellation received PCM")
            if cancel_sent_at is None and (
                stage == "after_first_audio" or audio_chunks >= 3
            ):
                cancel_sent_at = time.perf_counter()
                harness.send_control(request_id, {"message_type": "cancel"})
            continue

        message_type = _control_payload(frame).get("message_type")
        if message_type == "started" and stage == "before_first_audio":
            cancel_sent_at = time.perf_counter()
            harness.send_control(request_id, {"message_type": "cancel"})
            continue
        if message_type == "cancelled":
            return {
                "request_id": request_id,
                "terminal_state": "cancelled",
                "audio_chunks": audio_chunks,
                "audio_bytes": audio_bytes,
                "pcm_sha256": digest.hexdigest(),
                "first_audio_ms": first_audio_ms,
                "cancelled_ms": elapsed_ms,
                "cancel_latency_ms": (
                    (time.perf_counter() - cancel_sent_at) * 1000.0
                    if cancel_sent_at is not None
                    else None
                ),
            }


def _validate_release_soak(
    results: list[dict[str, object]],
    snapshots: list[dict[str, object]],
    worker_metrics: list[dict[str, object]],
    *,
    expected_cache_entries: int,
    expected_requests: int,
    expected_cancellations: int,
    expected_labels: set[str],
    cancellations_per_stage: int,
    max_rss_growth_mb: float,
    max_private_growth_mb: float = 512.0,
    max_cuda_allocated_growth_mb: float = 128.0,
    max_cuda_reserved_growth_mb: float = 128.0,
    max_cuda_reserved_tail_slope_bytes_per_request: float = 1048576.0,
    gpu_pid_telemetry_policy: str = "allow_unsupported",
) -> dict[str, object]:
    failures: list[str] = []
    references: dict[str, dict[str, object]] = {}
    cancelled_by_label: dict[str, dict[str, int]] = {}
    cache_entries: set[int] = set()
    for result in results:
        request_id = result.get("request_id")
        prefix = f"request {request_id}"
        terminal = result.get("terminal_state")
        label = result.get("shape_label")
        if not isinstance(label, str):
            failures.append(f"{prefix}: missing shape label")
            continue
        if terminal == "completed":
            trace = result.get("generation_trace")
            if not isinstance(trace, dict):
                failures.append(f"{prefix}: missing generation trace")
            else:
                try:
                    validate_generation_trace(trace)
                except RuntimeError as exc:
                    failures.append(f"{prefix}: {exc}")
            _validate_route(prefix, result, failures, cache_entries)
            if result.get("role") == "reference":
                references[label] = _fingerprint(result)
            elif result.get("role") == "audit":
                reference = references.get(label)
                if reference is None:
                    failures.append(f"{prefix}: missing semantic reference for {label}")
                elif reference != _fingerprint(result):
                    failures.append(f"{prefix}: post-cancel semantic fingerprint changed")
        elif terminal == "cancelled":
            stage = result.get("cancel_stage")
            if stage not in _CANCEL_STAGES:
                failures.append(f"{prefix}: invalid cancellation stage {stage!r}")
            else:
                stage_counts = cancelled_by_label.setdefault(label, {})
                stage_counts[str(stage)] = stage_counts.get(str(stage), 0) + 1
        else:
            failures.append(f"{prefix}: unexpected terminal state {terminal!r}")

    if len(results) != expected_requests:
        failures.append(f"expected {expected_requests} requests, got {len(results)}")
    cancelled = sum(1 for result in results if result.get("terminal_state") == "cancelled")
    if cancelled != expected_cancellations:
        failures.append(f"expected {expected_cancellations} cancellations, got {cancelled}")
    for label in sorted(expected_labels):
        stages = cancelled_by_label.get(label, {})
        for stage in _CANCEL_STAGES:
            if stages.get(stage, 0) != cancellations_per_stage:
                failures.append(f"{label}: insufficient {stage} cancellations")
    if cache_entries != {expected_cache_entries}:
        failures.append(
            f"prefill compile cache entries {sorted(cache_entries)} != "
            f"{expected_cache_entries}"
        )
    memory = _memory_validation(
        snapshots,
        max_rss_growth_mb=max_rss_growth_mb,
        max_private_growth_mb=max_private_growth_mb,
        gpu_pid_telemetry_policy=gpu_pid_telemetry_policy,
        require_telemetry=True,
    )
    failures.extend(memory["failures"])
    allocator = _validate_worker_memory_metrics(
        results,
        worker_metrics,
        snapshots,
        failures,
        max_cuda_allocated_growth_mb=max_cuda_allocated_growth_mb,
        max_cuda_reserved_growth_mb=max_cuda_reserved_growth_mb,
        max_cuda_reserved_tail_slope_bytes_per_request=(
            max_cuda_reserved_tail_slope_bytes_per_request
        ),
    )
    return {
        "failures": failures,
        "semantic_references": len(references),
        "cancelled_requests": cancelled,
        "cancelled_by_label": cancelled_by_label,
        "cache_entries_observed": sorted(cache_entries),
        "memory": memory,
        "allocator": allocator,
    }


def _fingerprint(result: dict[str, object]) -> dict[str, object]:
    trace = result.get("generation_trace")
    if not isinstance(trace, dict):
        return {}
    return {
        "pcm_sha256": result.get("pcm_sha256"),
        "audio_chunks": result.get("audio_chunks"),
        "audio_bytes": result.get("audio_bytes"),
        "codec_sha256": trace.get("codec_sha256"),
        "codec_frame_count": trace.get("codec_frame_count"),
        "termination_reason": trace.get("termination_reason"),
        "terminal_token_id": trace.get("terminal_token_id"),
        "terminal_step_index": trace.get("terminal_step_index"),
    }


def _validate_worker_memory_metrics(
    results: list[dict[str, object]],
    worker_metrics: list[dict[str, object]],
    snapshots: list[dict[str, object]],
    failures: list[str],
    *,
    max_cuda_allocated_growth_mb: float,
    max_cuda_reserved_growth_mb: float,
    max_cuda_reserved_tail_slope_bytes_per_request: float,
) -> dict[str, object]:
    memory_by_request = {
        metric.get("request_id"): metric
        for metric in worker_metrics
        if metric.get("event") == "worker_runtime_memory"
    }
    worker_pids: set[int] = set()
    for result in results:
        request_id = result.get("request_id")
        metric = memory_by_request.get(request_id)
        if not isinstance(metric, dict):
            failures.append(f"request {request_id}: missing worker memory metric")
            continue
        worker_pid = metric.get("worker_pid")
        if not isinstance(worker_pid, int):
            failures.append(f"request {request_id}: missing worker model PID")
        else:
            worker_pids.add(worker_pid)
        for key in (
            "cuda_memory_allocated_bytes",
            "cuda_memory_reserved_bytes",
            "cuda_memory_max_reserved_bytes",
        ):
            if not isinstance(metric.get(key), int):
                failures.append(f"request {request_id}: missing {key}")
    if len(worker_pids) != 1:
        failures.append(f"expected one worker model PID, got {sorted(worker_pids)}")
        return {"available": False}
    worker_pid = next(iter(worker_pids))
    for snapshot in snapshots:
        process_ids = {
            process.get("pid")
            for process in snapshot.get("processes", [])
            if isinstance(process, dict)
        }
        if worker_pid not in process_ids:
            completed_requests = snapshot.get("completed_requests")
            failures.append(
                "worker model PID is absent from process tree at "
                f"request {completed_requests}"
            )
    allocated = _metric_series(memory_by_request, "cuda_memory_allocated_bytes")
    reserved = _metric_series(memory_by_request, "cuda_memory_reserved_bytes")
    if allocated is None or reserved is None:
        failures.append("worker allocator telemetry is incomplete")
        return {"available": False}
    allocated_summary = _memory_series_summary(allocated)
    reserved_summary = _memory_series_summary(reserved)
    if allocated_summary["growth_mib"] > max_cuda_allocated_growth_mb:
        failures.append("CUDA allocated memory growth exceeds configured limit")
    if reserved_summary["growth_mib"] > max_cuda_reserved_growth_mb:
        failures.append("CUDA reserved memory growth exceeds configured limit")
    if (
        reserved_summary["tail_slope_bytes_per_request"]
        > max_cuda_reserved_tail_slope_bytes_per_request
    ):
        failures.append("CUDA reserved memory tail slope exceeds configured limit")
    return {
        "available": True,
        "allocated": allocated_summary,
        "reserved": reserved_summary,
    }


def _metric_series(
    metrics: dict[object, dict[str, object]],
    key: str,
) -> list[int] | None:
    values = []
    for request_id in sorted(metrics):
        value = metrics[request_id].get(key)
        if not isinstance(value, int):
            return None
        values.append(value)
    return values


def _memory_series_summary(values: list[int]) -> dict[str, float | int]:
    first = values[0]
    last = values[-1]
    tail = values[len(values) // 2 :]
    return {
        "first_bytes": first,
        "last_bytes": last,
        "max_bytes": max(values),
        "growth_mib": (last - first) / (1024.0 * 1024.0),
        "tail_slope_bytes_per_request": _tail_slope(tail),
    }


def _tail_slope(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean_x = (len(values) - 1) / 2.0
    mean_y = sum(values) / len(values)
    numerator = sum(
        (index - mean_x) * (value - mean_y)
        for index, value in enumerate(values)
    )
    denominator = sum((index - mean_x) ** 2 for index in range(len(values)))
    return numerator / denominator if denominator else 0.0


def _report(
    args: argparse.Namespace,
    runtime: dict[str, object],
    ready: dict[str, object] | None,
    results: list[dict[str, object]],
    snapshots: list[dict[str, object]],
    worker_metrics: list[dict[str, object]],
) -> dict[str, object]:
    completed = [item for item in results if item.get("terminal_state") == "completed"]
    cancelled = [item for item in results if item.get("terminal_state") == "cancelled"]
    return {
        "artifact_schema_version": 2,
        "config": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "runtime": runtime,
        "ready": ready,
        "summary": {
            "completed_requests": len(completed),
            "cancelled_requests": len(cancelled),
            "first_audio_ms": _summary(completed, "first_audio_ms"),
            "completed_ms": _summary(completed, "completed_ms"),
            "real_time_factor": _summary(completed, "real_time_factor"),
            "cancel_latency_ms": _summary(cancelled, "cancel_latency_ms"),
        },
        "requests": results,
        "memory_snapshots": snapshots,
        "worker_metrics": worker_metrics,
        "validation": {"failures": ["incomplete soak"]},
        "acceptance_pass": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
