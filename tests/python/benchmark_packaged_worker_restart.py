"""Benchmark first user request latency across fresh worker processes."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import cast

from benchmark_packaged_worker import _run_request, _shutdown, _summary
from benchmark_runtime import (
    apply_cpu_affinity,
    gpu_snapshot,
    runtime_fingerprint,
)
from verify_packaged_worker import (
    PackagedWorkerHarness,
    _control_payload,
    _is_control_message,
    _worker_process_args,
)

_PHASE_KEYS = (
    "transport_and_dispatch_residual_ms",
    "client_minus_worker_first_pcm_ready_ms",
    "client_minus_worker_frame_enqueued_ms",
    "client_minus_worker_frame_flushed_estimated_ms",
    "first_frame_output_writer_ms",
    "first_chunk_prefill_ms",
    "first_chunk_ar_decode_ms",
    "first_chunk_ar_ms_per_step",
    "first_chunk_codec_wrapper_residual_ms",
    "first_chunk_pcm_convert_ms",
    "first_chunk_next_wall_ms",
)


def main() -> int:
    """Run a restart-based packaged worker benchmark."""

    parser = _build_parser()
    args = parser.parse_args()

    worker_executable = args.worker_executable.resolve()
    if not worker_executable.is_file():
        parser.error(f"worker executable was not found: {worker_executable}")
    if args.engine == "qwen" and not args.model_path:
        parser.error("--model-path is required for --engine qwen")
    if args.runs <= 0:
        parser.error("--runs must be greater than zero")
    if args.requests_per_run <= 0:
        parser.error("--requests-per-run must be greater than zero")

    results = []
    run_summaries = []
    runtime = runtime_fingerprint(
        worker_executable=worker_executable,
        worker_prefix_args=args.worker_prefix_arg,
        args=args,
    )
    started_at = time.perf_counter()
    for index in range(args.runs):
        harness = PackagedWorkerHarness(
            worker_executable=worker_executable,
            args=_worker_process_args_for_run(args, index + 1),
            timeout_seconds=args.timeout_seconds,
        )
        try:
            affinity_result = apply_cpu_affinity(
                harness.pid,
                _parse_cpu_list(args.cpu_affinity),
            )
            process_started_gpu = gpu_snapshot()
            ready = _hello(harness)
            after_ready_gpu = gpu_snapshot()
            run_requests = []
            for request_index in range(args.requests_per_run):
                request_result = _run_request(
                    harness,
                    request_id=request_index + 1,
                    text=args.text,
                    language=args.language,
                    speaker=args.speaker,
                    instruction=args.instruction,
                )
                request_result["run_index"] = index + 1
                request_result["request_index"] = request_index + 1
                request_result["ready_warmed_up"] = ready.get("warmed_up")
                request_result["startup_ms"] = ready.get("startup_ms")
                run_requests.append(request_result)
                results.append(request_result)
            _shutdown(harness)
            after_requests_gpu = gpu_snapshot()
            run_summary = _run_summary(
                run_index=index + 1,
                ready=ready,
                requests=run_requests,
                worker_metrics=_worker_metrics(harness.stderr_text()),
                affinity=affinity_result,
                process_started_gpu=process_started_gpu,
                after_ready_gpu=after_ready_gpu,
                after_requests_gpu=after_requests_gpu,
            )
            run_summaries.append(run_summary)
            if args.partial_output:
                _write_json_file(
                    args.partial_output,
                    _build_report(args, runtime, results, run_summaries),
                )
            if args.progress_every_runs and (index + 1) % args.progress_every_runs == 0:
                progress_line = _progress_line(
                    done=index + 1,
                    total=args.runs,
                    started_at=started_at,
                    run_summary=run_summary,
                )
                if args.progress_output:
                    _append_line(args.progress_output, progress_line)
                else:
                    print(progress_line, file=sys.stderr, flush=True)
        finally:
            harness.close()

    print(
        json.dumps(
            _build_report(args, runtime, results, run_summaries),
            sort_keys=True,
        )
    )
    return 0


def _build_report(
    args: argparse.Namespace,
    runtime: dict[str, object],
    results: list[dict[str, object]],
    run_summaries: list[dict[str, object]],
) -> dict[str, object]:
    first_requests = [
        cast(dict[str, object], run["first_request"])
        for run in run_summaries
        if isinstance(run.get("first_request"), dict)
    ]
    steady_requests = [
        cast(dict[str, object], run["steady_request_median"])
        for run in run_summaries
        if isinstance(run.get("steady_request_median"), dict)
    ]
    pipeline_requests = [
        request
        for run in run_summaries
        for request in cast(list[dict[str, object]], run["requests"])
    ]
    paired_deltas = [
        {"paired_delta_first_audio_ms": run["paired_delta_first_audio_ms"]}
        for run in run_summaries
        if isinstance(run.get("paired_delta_first_audio_ms"), (int, float))
    ]
    paired_phase_deltas = [
        cast(dict[str, object], run["paired_phase_delta"])
        for run in run_summaries
        if isinstance(run.get("paired_phase_delta"), dict)
    ]

    return {
        "config": {
            "runs": args.runs,
            "text": args.text,
            "language": args.language,
            "speaker": args.speaker,
            "instruction": args.instruction,
            "warmup_synthesis": args.warmup_synthesis,
            "warmup_synthesis_passes": args.warmup_synthesis_passes,
            "warmup_unbounded_passes": args.warmup_unbounded_passes,
            "warmup_max_output_chunks": args.warmup_max_output_chunks,
            "warmup_text": args.warmup_text,
            "warmup_language": args.warmup_language,
            "warmup_speaker": args.warmup_speaker,
            "warmup_instruction": args.warmup_instruction,
            "engine_startup_mode": args.engine_startup_mode,
            "seed": args.seed,
            "seed_mode": args.seed_mode,
            "warmup_seed": args.warmup_seed,
            "run_seed_step": args.run_seed_step,
            "run_warmup_seed_step": args.run_warmup_seed_step,
            "requests_per_run": args.requests_per_run,
            "cpu_affinity": args.cpu_affinity,
        },
        "runtime": runtime,
        "summary": {
            "all_requests": {
                "first_audio_ms": _summary(results, "first_audio_ms"),
                "completed_ms": _summary(results, "completed_ms"),
                "real_time_factor": _summary(results, "real_time_factor"),
                "inverse_rtf": _summary(results, "inverse_rtf"),
            },
            "first_request": {
                "first_audio_ms": _summary(first_requests, "first_audio_ms"),
                "completed_ms": _summary(first_requests, "completed_ms"),
                "real_time_factor": _summary(first_requests, "real_time_factor"),
                "inverse_rtf": _summary(first_requests, "inverse_rtf"),
            },
            "steady_request_median": {
                "first_audio_ms": _summary(steady_requests, "first_audio_ms"),
                "completed_ms": _summary(steady_requests, "completed_ms"),
                "real_time_factor": _summary(steady_requests, "real_time_factor"),
                "inverse_rtf": _summary(steady_requests, "inverse_rtf"),
            },
            "paired_delta": {
                "first_audio_ms": _summary(
                    paired_deltas,
                    "paired_delta_first_audio_ms",
                ),
            },
            "pipeline": _phase_summary(pipeline_requests),
            "first_request_pipeline": _phase_summary(first_requests),
            "steady_request_median_pipeline": _phase_summary(
                steady_requests,
            ),
            "paired_phase_delta": _phase_summary(paired_phase_deltas),
        },
        "runs": run_summaries,
        "requests": results,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("worker_executable", type=Path)
    parser.add_argument("--worker-prefix-arg", action="append", default=[])
    parser.add_argument("--engine", choices=("mock", "qwen"), default="mock")
    parser.add_argument("--model-path")
    parser.add_argument(
        "--runtime-backend",
        choices=("upstream", "faster"),
        default="upstream",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--attn-implementation", default="")
    parser.add_argument("--max-seq-len", type=int, default=2048)
    parser.add_argument("--emit-every-frames", type=int, default=8)
    parser.add_argument("--decode-window-frames", type=int, default=80)
    parser.add_argument("--overlap-samples", type=int, default=0)
    parser.add_argument("--enable-streaming-optimizations", action="store_true")
    parser.add_argument("--no-compile", action="store_true")
    parser.add_argument("--no-cuda-graphs", action="store_true")
    parser.add_argument("--compile-mode", default="reduce-overhead")
    parser.add_argument("--use-fast-codebook", action="store_true")
    parser.add_argument("--no-compile-codebook-predictor", action="store_true")
    parser.add_argument("--no-compile-talker", action="store_true")
    parser.add_argument("--matmul-precision", default="")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--seed-mode",
        choices=("request_id", "fixed"),
        default="request_id",
    )
    parser.add_argument("--warmup-seed", type=int, default=None)
    parser.add_argument(
        "--run-seed-step",
        type=int,
        default=0,
        help="Add this offset per fresh-worker run when --seed is set.",
    )
    parser.add_argument(
        "--run-warmup-seed-step",
        type=int,
        default=0,
        help="Add this offset per fresh-worker run when --warmup-seed is set.",
    )
    parser.add_argument("--warmup-synthesis", action="store_true")
    parser.add_argument("--warmup-synthesis-passes", type=int, default=1)
    parser.add_argument("--warmup-unbounded-passes", type=int, default=0)
    parser.add_argument("--warmup-max-output-chunks", type=int, default=None)
    parser.add_argument("--warmup-text", default="Warmup.")
    parser.add_argument("--warmup-language", default="auto")
    parser.add_argument("--warmup-speaker", default="")
    parser.add_argument("--warmup-instruction", default="")
    parser.add_argument(
        "--engine-startup-mode",
        choices=("auto", "main", "engine_warmup", "engine_load_warmup"),
        default="auto",
    )
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--mock-chunks", type=int, default=1)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--requests-per-run", type=int, default=1)
    parser.add_argument(
        "--partial-output",
        type=Path,
        default=None,
        help="Optional JSON file updated after each completed fresh-worker run.",
    )
    parser.add_argument(
        "--progress-every-runs",
        type=int,
        default=0,
        help="Write a compact progress line to stderr every N completed runs.",
    )
    parser.add_argument(
        "--progress-output",
        type=Path,
        default=None,
        help="Optional file for progress lines; avoids PowerShell stderr wrapping.",
    )
    parser.add_argument(
        "--cpu-affinity",
        default="",
        help="Comma-separated CPU indices to apply to each worker process.",
    )
    parser.add_argument("--text", default="Packaged worker restart benchmark request.")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--speaker", default="")
    parser.add_argument("--instruction", default="")
    return parser


def _worker_process_args_for_run(
    args: argparse.Namespace,
    run_index: int,
) -> list[str]:
    if (
        args.seed is None
        and args.warmup_seed is None
    ) or (
        args.run_seed_step == 0
        and args.run_warmup_seed_step == 0
    ):
        return _worker_process_args(args)

    run_args = argparse.Namespace(**vars(args))
    if run_args.seed is not None:
        run_args.seed = int(run_args.seed) + (run_index - 1) * int(
            args.run_seed_step
        )
    if run_args.warmup_seed is not None:
        run_args.warmup_seed = int(run_args.warmup_seed) + (run_index - 1) * int(
            args.run_warmup_seed_step
        )
    return _worker_process_args(run_args)


def _write_json_file(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(
        json.dumps(report, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.write("\n")


def _progress_line(
    *,
    done: int,
    total: int,
    started_at: float,
    run_summary: dict[str, object],
) -> str:
    elapsed_s = time.perf_counter() - started_at
    first = cast(dict[str, object], run_summary.get("first_request", {}))
    steady = run_summary.get("steady_request_median")
    steady_dict = steady if isinstance(steady, dict) else {}
    return (
        "progress "
        f"{done}/{total} "
        f"elapsed_s={elapsed_s:.1f} "
        f"last_first_audio_ms={_format_optional_number(first.get('first_audio_ms'))} "
        "last_steady_first_audio_ms="
        f"{_format_optional_number(steady_dict.get('first_audio_ms'))} "
        "last_delta_first_audio_ms="
        f"{_format_optional_number(run_summary.get('paired_delta_first_audio_ms'))}"
    )


def _format_optional_number(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.1f}"
    return "n/a"


def _hello(harness: PackagedWorkerHarness) -> dict[str, object]:
    start = time.perf_counter()
    harness.send_control(
        0,
        {
            "message_type": "hello",
            "client_name": "packaged-worker-restart-benchmark",
            "client_version": "0.2.0",
        },
    )
    ready = _control_payload(
        harness.read_frame(lambda frame: _is_control_message(frame, "ready", 0))
    )
    ready["startup_ms"] = (time.perf_counter() - start) * 1000.0
    return ready


def _run_summary(
    *,
    run_index: int,
    ready: dict[str, object],
    requests: list[dict[str, object]],
    worker_metrics: list[dict[str, object]],
    affinity: dict[str, object],
    process_started_gpu: dict[str, object],
    after_ready_gpu: dict[str, object],
    after_requests_gpu: dict[str, object],
) -> dict[str, object]:
    enriched_requests = [
        _with_request_pipeline_metrics(request, worker_metrics)
        for request in requests
    ]
    first_request = enriched_requests[0] if enriched_requests else {}
    steady_requests = enriched_requests[1:]
    steady_median = _median_request(steady_requests)
    paired_delta: float | None = None
    paired_phase_delta = _phase_delta(first_request, steady_median)
    first_audio = first_request.get("first_audio_ms")
    if isinstance(first_audio, (int, float)) and steady_median is not None:
        steady_first_audio = steady_median.get("first_audio_ms")
        if isinstance(steady_first_audio, (int, float)):
            paired_delta = float(first_audio) - float(steady_first_audio)
    return {
        "run_index": run_index,
        "ready": ready,
        "affinity": affinity,
        "gpu": {
            "process_started": process_started_gpu,
            "after_ready": after_ready_gpu,
            "after_requests": after_requests_gpu,
        },
        "warmup_passes": [
            metric
            for metric in worker_metrics
            if metric.get("event") == "engine_warmup_pass"
        ],
        "worker_metrics": worker_metrics,
        "first_request": first_request,
        "steady_requests": steady_requests,
        "steady_request_median": steady_median,
        "paired_delta_first_audio_ms": paired_delta,
        "paired_phase_delta": paired_phase_delta,
        "requests": enriched_requests,
    }


def _phase_summary(results: list[dict[str, object]]) -> dict[str, object]:
    return {key: _summary(results, key) for key in _PHASE_KEYS}


def _phase_delta(
    first_request: dict[str, object],
    steady_median: dict[str, object] | None,
) -> dict[str, object]:
    if steady_median is None:
        return {}
    result: dict[str, object] = {}
    for key in _PHASE_KEYS:
        first_value = first_request.get(key)
        steady_value = steady_median.get(key)
        if isinstance(first_value, (int, float)) and isinstance(
            steady_value,
            (int, float),
        ):
            result[key] = float(first_value) - float(steady_value)
    return result


def _with_request_pipeline_metrics(
    request: dict[str, object],
    worker_metrics: list[dict[str, object]],
) -> dict[str, object]:
    request_id = request.get("request_id")
    if not isinstance(request_id, int):
        return dict(request)

    metrics = _metrics_by_event(worker_metrics, request_id)
    enriched = dict(request)
    first_pcm_ready_ms = _metric_number(
        metrics,
        "request_first_pcm_ready",
        "first_pcm_ready_ms",
    )
    first_frame_enqueued_ms = _metric_number(
        metrics,
        "request_first_frame_enqueued",
        "first_frame_enqueue_ms",
    )
    first_frame_output_writer_ms = _metric_number(
        metrics,
        "request_first_frame_flushed",
        "output_writer_ms",
    )
    first_frame_flush_ms = _metric_number(
        metrics,
        "request_first_frame_flushed",
        "flush_ms",
    )
    first_frame_queue_ms = _metric_number(
        metrics,
        "request_first_frame_flushed",
        "output_queue_ms",
    )
    first_chunk_phases = metrics.get("request_first_chunk_engine_phases", {})

    _set_if_number(enriched, "worker_first_pcm_ready_ms", first_pcm_ready_ms)
    _set_if_number(enriched, "worker_first_frame_enqueued_ms", first_frame_enqueued_ms)
    _set_if_number(
        enriched,
        "first_frame_output_writer_ms",
        first_frame_output_writer_ms,
    )
    _set_if_number(enriched, "first_frame_flush_ms", first_frame_flush_ms)
    _set_if_number(enriched, "first_frame_output_queue_ms", first_frame_queue_ms)
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "prefill_ms",
        "first_chunk_prefill_ms",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "ar_decode_ms",
        "first_chunk_ar_decode_ms",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "chunk_steps",
        "first_chunk_steps",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "ar_ms_per_step",
        "first_chunk_ar_ms_per_step",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "codec_wrapper_residual_ms",
        "first_chunk_codec_wrapper_residual_ms",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "pcm_convert_ms",
        "first_chunk_pcm_convert_ms",
    )
    _copy_metric_number(
        enriched,
        first_chunk_phases,
        "next_wall_ms",
        "first_chunk_next_wall_ms",
    )

    if first_frame_enqueued_ms is not None and first_frame_output_writer_ms is not None:
        enriched["worker_first_frame_flushed_estimated_ms"] = (
            first_frame_enqueued_ms + first_frame_output_writer_ms
        )

    client_first_audio_ms = request.get("first_audio_ms")
    if isinstance(client_first_audio_ms, (int, float)):
        if first_pcm_ready_ms is not None:
            residual_ms = (
                float(client_first_audio_ms) - first_pcm_ready_ms
            )
            enriched["transport_and_dispatch_residual_ms"] = residual_ms
            enriched["client_minus_worker_first_pcm_ready_ms"] = residual_ms
        if first_frame_enqueued_ms is not None:
            enriched["client_minus_worker_frame_enqueued_ms"] = (
                float(client_first_audio_ms) - first_frame_enqueued_ms
            )
        flushed_estimate = enriched.get("worker_first_frame_flushed_estimated_ms")
        if isinstance(flushed_estimate, (int, float)):
            enriched["client_minus_worker_frame_flushed_estimated_ms"] = (
                float(client_first_audio_ms) - float(flushed_estimate)
            )

    return enriched


def _metrics_by_event(
    worker_metrics: list[dict[str, object]],
    request_id: int,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for metric in worker_metrics:
        if metric.get("request_id") != request_id:
            continue
        event = metric.get("event")
        if isinstance(event, str) and event not in result:
            result[event] = metric
    return result


def _metric_number(
    metrics: dict[str, dict[str, object]],
    event: str,
    field: str,
) -> float | None:
    value = metrics.get(event, {}).get(field)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _set_if_number(
    target: dict[str, object],
    key: str,
    value: float | None,
) -> None:
    if value is not None:
        target[key] = value


def _copy_metric_number(
    target: dict[str, object],
    source: dict[str, object],
    source_key: str,
    target_key: str,
) -> None:
    value = source.get(source_key)
    if isinstance(value, (int, float)):
        target[target_key] = float(value)


def _median_request(requests: list[dict[str, object]]) -> dict[str, object] | None:
    if not requests:
        return None
    result: dict[str, object] = {"request_count": len(requests)}
    for key in (
        "first_audio_ms",
        "completed_ms",
        "audio_duration_ms",
        "real_time_factor",
        "inverse_rtf",
        "worker_first_pcm_ready_ms",
        "worker_first_frame_enqueued_ms",
        "worker_first_frame_flushed_estimated_ms",
        "first_frame_flush_ms",
        "first_frame_output_queue_ms",
        "first_chunk_steps",
        *_PHASE_KEYS,
    ):
        values = [
            float(cast(int | float, request[key]))
            for request in requests
            if isinstance(request.get(key), (int, float))
        ]
        if values:
            result[key] = statistics.median(values)
    return result


def _worker_metrics(stderr_text: str) -> list[dict[str, object]]:
    metrics = []
    for line in stderr_text.splitlines():
        if not line.startswith("qtb_metric "):
            continue
        try:
            metrics.append(json.loads(line.removeprefix("qtb_metric ")))
        except json.JSONDecodeError:
            continue
    return metrics


def _parse_cpu_list(value: str) -> list[int]:
    if not value.strip():
        return []
    cpus = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        cpus.append(int(item))
    return cpus


if __name__ == "__main__":
    raise SystemExit(main())
