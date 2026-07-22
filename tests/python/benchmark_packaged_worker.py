"""Benchmark a packaged worker across multiple synthesis requests."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from benchmark_runtime import runtime_fingerprint
from qwen_tts_bridge_worker.protocol import Frame, FrameType
from verify_packaged_worker import (
    PackagedWorkerHarness,
    _control_payload,
    _is_control_message,
    _worker_process_args,
)


def main() -> int:
    """Run a sequential multi-request benchmark."""

    parser = _build_parser()
    args = parser.parse_args()

    worker_executable = args.worker_executable.resolve()
    if not worker_executable.is_file():
        parser.error(f"worker executable was not found: {worker_executable}")
    if args.engine == "qwen" and not args.model_path:
        parser.error("--model-path is required for --engine qwen")

    harness = PackagedWorkerHarness(
        worker_executable=worker_executable,
        args=_worker_process_args(args),
        timeout_seconds=args.timeout_seconds,
    )
    try:
        _hello(harness)
        warmups = []
        for index in range(args.warmups):
            request_id = index + 1
            warmups.append(
                _run_request(
                    harness,
                    request_id=request_id,
                    text=args.text,
                    language=args.language,
                    speaker=args.speaker,
                    instruction=args.instruction,
                )
            )
        results = []
        for index in range(args.requests):
            request_id = args.warmups + index + 1
            results.append(
                _run_request(
                    harness,
                    request_id=request_id,
                    text=args.text,
                    language=args.language,
                    speaker=args.speaker,
                    instruction=args.instruction,
                )
            )
        _shutdown(harness)
    finally:
        harness.close()

    print(
        json.dumps(
            {
                "config": {
                    "warmups": args.warmups,
                    "requests": args.requests,
                    "text": args.text,
                    "language": args.language,
                    "speaker": args.speaker,
                    "instruction": args.instruction,
                    "seed": args.seed,
                    "warmup_synthesis": args.warmup_synthesis,
                    "warmup_synthesis_passes": args.warmup_synthesis_passes,
                    "warmup_max_output_chunks": args.warmup_max_output_chunks,
                },
                "runtime": runtime_fingerprint(
                    worker_executable=worker_executable,
                    worker_prefix_args=args.worker_prefix_arg,
                    args=args,
                ),
                "summary": {
                    "first_audio_ms": _summary(results, "first_audio_ms"),
                    "completed_ms": _summary(results, "completed_ms"),
                    "real_time_factor": _summary(results, "real_time_factor"),
                    "inverse_rtf": _summary(results, "inverse_rtf"),
                },
                "warmups": warmups,
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
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--requests", type=int, default=2)
    parser.add_argument("--text", default="Packaged worker benchmark request.")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--speaker", default="")
    parser.add_argument("--instruction", default="")
    return parser


def _hello(harness: PackagedWorkerHarness) -> None:
    harness.send_control(
        0,
        {
            "message_type": "hello",
            "client_name": "packaged-worker-benchmark",
            "client_version": "0.2.0",
        },
    )
    harness.read_frame(lambda frame: _is_control_message(frame, "ready", 0))


def _run_request(
    harness: PackagedWorkerHarness,
    *,
    request_id: int,
    text: str,
    language: str,
    speaker: str,
    instruction: str,
) -> dict[str, object]:
    start = time.perf_counter()
    harness.send_control(
        request_id,
        _synthesize_payload(
            text=text,
            language=language,
            speaker=speaker,
            instruction=instruction,
        ),
    )

    audio_bytes = 0
    audio_chunks = 0
    first_audio_ms: float | None = None
    completed_ms: float | None = None
    while completed_ms is None:
        frame = harness.read_frame(
            lambda next_frame: _is_request_frame(next_frame, request_id)
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if frame.header.frame_type == FrameType.AUDIO_PCM:
            if first_audio_ms is None:
                first_audio_ms = elapsed_ms
            audio_bytes += len(frame.payload)
            audio_chunks += 1
            continue
        if _control_payload(frame).get("message_type") == "completed":
            completed_ms = elapsed_ms

    audio_duration_ms = audio_bytes / (24000 * 2) * 1000.0
    real_time_factor = (
        completed_ms / audio_duration_ms
        if audio_duration_ms > 0
        else None
    )
    inverse_real_time_factor = (
        audio_duration_ms / completed_ms
        if completed_ms > 0
        else None
    )
    return {
        "request_id": request_id,
        "first_audio_ms": first_audio_ms,
        "completed_ms": completed_ms,
        "audio_bytes": audio_bytes,
        "audio_chunks": audio_chunks,
        "audio_duration_ms": audio_duration_ms,
        "real_time_factor": real_time_factor,
        "local_rtf": real_time_factor,
        "inverse_rtf": inverse_real_time_factor,
    }


def _summary(
    results: list[dict[str, object]],
    key: str,
) -> dict[str, float] | None:
    values: list[float] = []
    for result in results:
        value = result.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    values.sort()
    if not values:
        return None
    return {
        "min": values[0],
        "median": statistics.median(values),
        "p90": _percentile(values, 90.0),
        "p95": _percentile(values, 95.0),
        "max": values[-1],
    }


def _percentile(values: list[float], percentile: float) -> float:
    if len(values) == 1:
        return values[0]
    rank = percentile / 100.0 * (len(values) - 1)
    low = int(rank)
    high = min(low + 1, len(values) - 1)
    fraction = rank - low
    return values[low] * (1.0 - fraction) + values[high] * fraction


def _synthesize_payload(
    text: str,
    language: str,
    speaker: str,
    instruction: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "message_type": "synthesize",
        "text": text,
        "language": language,
        "output": {
            "sample_format": "s16le",
            "sample_rate": 24000,
            "channels": 1,
        },
    }
    if speaker:
        payload["speaker"] = speaker
    if instruction:
        payload["instruction"] = instruction
    return payload


def _is_request_frame(frame: Frame, request_id: int) -> bool:
    if frame.header.request_id != request_id:
        return False
    if frame.header.frame_type == FrameType.AUDIO_PCM:
        return True
    if frame.header.frame_type != FrameType.CONTROL_JSON:
        return False
    message_type = _control_payload(frame).get("message_type")
    return message_type in {"queued", "started", "completed", "cancelled"}


def _shutdown(harness: PackagedWorkerHarness) -> None:
    harness.send_control(0, {"message_type": "shutdown", "mode": "cancel"})
    harness.read_frame(lambda frame: _is_control_message(frame, "shutdown_ack", 0))
    exit_code = harness.wait()
    if exit_code != 0:
        raise RuntimeError(f"packaged worker exited with code {exit_code}")


if __name__ == "__main__":
    raise SystemExit(main())
