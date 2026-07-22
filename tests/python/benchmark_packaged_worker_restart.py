"""Benchmark first user request latency across fresh worker processes."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from benchmark_packaged_worker import _run_request, _shutdown, _summary
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

    results = []
    for index in range(args.runs):
        harness = PackagedWorkerHarness(
            worker_executable=worker_executable,
            args=_worker_process_args(args),
            timeout_seconds=args.timeout_seconds,
        )
        try:
            ready = _hello(harness)
            request_result = _run_request(
                harness,
                request_id=1,
                text=args.text,
                language=args.language,
                speaker=args.speaker,
                instruction=args.instruction,
            )
            request_result["run_index"] = index + 1
            request_result["ready_warmed_up"] = ready.get("warmed_up")
            request_result["startup_ms"] = ready.get("startup_ms")
            results.append(request_result)
            _shutdown(harness)
        finally:
            harness.close()

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
                    "warmup_text": args.warmup_text,
                    "warmup_language": args.warmup_language,
                    "warmup_speaker": args.warmup_speaker,
                    "warmup_instruction": args.warmup_instruction,
                },
                "summary": {
                    "first_audio_ms": _summary(results, "first_audio_ms"),
                    "completed_ms": _summary(results, "completed_ms"),
                    "real_time_factor": _summary(results, "real_time_factor"),
                    "inverse_rtf": _summary(results, "inverse_rtf"),
                },
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
    parser.add_argument("--warmup-synthesis", action="store_true")
    parser.add_argument("--warmup-synthesis-passes", type=int, default=1)
    parser.add_argument("--warmup-text", default="Warmup.")
    parser.add_argument("--warmup-language", default="auto")
    parser.add_argument("--warmup-speaker", default="")
    parser.add_argument("--warmup-instruction", default="")
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--mock-chunks", type=int, default=1)
    parser.add_argument("--runs", type=int, default=20)
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


if __name__ == "__main__":
    raise SystemExit(main())
