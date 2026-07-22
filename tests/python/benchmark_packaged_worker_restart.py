"""Benchmark first user request latency across fresh worker processes."""

from __future__ import annotations

import argparse
import json
import statistics
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
    for index in range(args.runs):
        harness = PackagedWorkerHarness(
            worker_executable=worker_executable,
            args=_worker_process_args(args),
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
            run_summaries.append(
                _run_summary(
                    run_index=index + 1,
                    ready=ready,
                    requests=run_requests,
                    worker_metrics=_worker_metrics(harness.stderr_text()),
                    affinity=affinity_result,
                    process_started_gpu=process_started_gpu,
                    after_ready_gpu=after_ready_gpu,
                    after_requests_gpu=after_requests_gpu,
                )
            )
        finally:
            harness.close()

    first_requests = [run["first_request"] for run in run_summaries]
    steady_requests = [
        run["steady_request_median"]
        for run in run_summaries
        if isinstance(run.get("steady_request_median"), dict)
    ]
    paired_deltas = [
        {"paired_delta_first_audio_ms": run["paired_delta_first_audio_ms"]}
        for run in run_summaries
        if isinstance(run.get("paired_delta_first_audio_ms"), (int, float))
    ]

    print(
        json.dumps(
            {
                "config": {
                    "runs": args.runs,
                    "text": args.text,
                    "language": args.language,
                    "speaker": args.speaker,
                    "instruction": args.instruction,
                    "warmup_synthesis": args.warmup_synthesis,
                    "warmup_synthesis_passes": args.warmup_synthesis_passes,
                    "warmup_max_output_chunks": args.warmup_max_output_chunks,
                    "warmup_text": args.warmup_text,
                    "warmup_language": args.warmup_language,
                    "warmup_speaker": args.warmup_speaker,
                    "warmup_instruction": args.warmup_instruction,
                    "seed": args.seed,
                    "requests_per_run": args.requests_per_run,
                    "cpu_affinity": args.cpu_affinity,
                },
                "runtime": runtime_fingerprint(
                    worker_executable=worker_executable,
                    worker_prefix_args=args.worker_prefix_arg,
                    args=args,
                ),
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
                        "real_time_factor": _summary(
                            first_requests,
                            "real_time_factor",
                        ),
                        "inverse_rtf": _summary(first_requests, "inverse_rtf"),
                    },
                    "steady_request_median": {
                        "first_audio_ms": _summary(steady_requests, "first_audio_ms"),
                        "completed_ms": _summary(steady_requests, "completed_ms"),
                        "real_time_factor": _summary(
                            steady_requests,
                            "real_time_factor",
                        ),
                        "inverse_rtf": _summary(steady_requests, "inverse_rtf"),
                    },
                    "paired_delta": {
                        "first_audio_ms": _summary(
                            paired_deltas,
                            "paired_delta_first_audio_ms",
                        ),
                    },
                },
                "runs": run_summaries,
                "requests": results,
            },
            sort_keys=True,
        )
    )
    return 0


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
    parser.add_argument("--warmup-synthesis", action="store_true")
    parser.add_argument("--warmup-synthesis-passes", type=int, default=1)
    parser.add_argument("--warmup-max-output-chunks", type=int, default=None)
    parser.add_argument("--warmup-text", default="Warmup.")
    parser.add_argument("--warmup-language", default="auto")
    parser.add_argument("--warmup-speaker", default="")
    parser.add_argument("--warmup-instruction", default="")
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--mock-chunks", type=int, default=1)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--requests-per-run", type=int, default=1)
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
    first_request = requests[0] if requests else {}
    steady_requests = requests[1:]
    steady_median = _median_request(steady_requests)
    paired_delta: float | None = None
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
        "requests": requests,
    }


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
