"""Direct QwenTtsEngine latency benchmark.

This measures the Python worker engine adapter without stdio IPC or the C++
bridge. The timing boundary is request object submission to first yielded PCM
bytes and request completion.
"""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
from pathlib import Path
from typing import Any

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine.qwen_engine import QwenTtsEngine
from qwen_tts_bridge_worker.engine.types import AudioFormat, SynthesisRequest


def main() -> int:
    """Run explicit warmup and measured requests against QwenTtsEngine."""

    args = _build_parser().parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    config = QwenEngineConfig(
        model_path=args.model_path,
        runtime_backend=args.runtime_backend,
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
        max_seq_len=args.max_seq_len,
        emit_every_frames=args.emit_every_frames,
        decode_window_frames=args.decode_window_frames,
        overlap_samples=args.overlap_samples,
        enable_streaming_optimizations=args.enable_streaming_optimizations,
        use_compile=not args.no_compile,
        use_cuda_graphs=not args.no_cuda_graphs,
        compile_mode=args.compile_mode,
        use_fast_codebook=args.use_fast_codebook,
        compile_codebook_predictor=not args.no_compile_codebook_predictor,
        compile_talker=not args.no_compile_talker,
        matmul_precision=args.matmul_precision,
        warmup_synthesis_enabled=False,
    )

    engine = QwenTtsEngine(config)
    load_start = time.perf_counter()
    engine.load()
    load_ms = _elapsed_ms(load_start)

    try:
        warmups = [
            _run_request(
                engine,
                request_id=index + 1,
                text=args.text,
                language=args.language,
                speaker=args.speaker,
                instruction=args.instruction,
            )
            for index in range(args.warmups)
        ]
        requests = [
            _run_request(
                engine,
                request_id=args.warmups + index + 1,
                text=args.text,
                language=args.language,
                speaker=args.speaker,
                instruction=args.instruction,
            )
            for index in range(args.requests)
        ]
    finally:
        engine.close()

    result = {
        "config": {
            "model_path": args.model_path,
            "runtime_backend": args.runtime_backend,
            "device": args.device,
            "dtype": args.dtype,
            "attn_implementation": args.attn_implementation,
            "max_seq_len": args.max_seq_len,
            "emit_every_frames": args.emit_every_frames,
            "decode_window_frames": args.decode_window_frames,
            "overlap_samples": args.overlap_samples,
            "text": args.text,
            "language": args.language,
            "speaker": args.speaker,
            "instruction": args.instruction,
            "warmups": args.warmups,
            "requests": args.requests,
        },
        "load_ms": load_ms,
        "summary": {
            "first_audio_ms": _summary(requests, "first_audio_ms"),
            "completed_ms": _summary(requests, "completed_ms"),
            "real_time_factor": _summary(requests, "real_time_factor"),
            "inverse_real_time_factor": _summary(requests, "inverse_rtf"),
        },
        "warmups": warmups,
        "requests": requests,
    }
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
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
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--text", default="This is a faster backend latency benchmark.")
    parser.add_argument("--language", default="English")
    parser.add_argument("--speaker", default="")
    parser.add_argument("--instruction", default="")
    parser.add_argument(
        "--output",
        default="tmp/qwen-engine-latency-benchmark.json",
    )
    return parser


def _run_request(
    engine: QwenTtsEngine,
    *,
    request_id: int,
    text: str,
    language: str,
    speaker: str,
    instruction: str,
) -> dict[str, Any]:
    request = SynthesisRequest(
        request_id=request_id,
        text=text,
        language=language,
        speaker=speaker,
        instruction=instruction,
        output=AudioFormat.default(),
    )
    engine.validate_request(request)

    start = time.perf_counter()
    first_audio_ms: float | None = None
    audio_chunks = 0
    audio_bytes = 0
    cancel_event = threading.Event()

    for chunk in engine.synthesize_stream(request, cancel_event):
        if first_audio_ms is None:
            first_audio_ms = _elapsed_ms(start)
        audio_chunks += 1
        audio_bytes += len(chunk)

    completed_ms = _elapsed_ms(start)
    audio_duration_ms = audio_bytes * 1000.0 / (24000 * 1 * 2)
    real_time_factor = (
        completed_ms / audio_duration_ms
        if audio_duration_ms > 0.0
        else None
    )
    inverse_real_time_factor = (
        audio_duration_ms / completed_ms
        if completed_ms > 0.0
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


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _summary(results: list[dict[str, Any]], key: str) -> dict[str, float] | None:
    values = sorted(
        float(result[key])
        for result in results
        if result.get(key) is not None
    )
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


if __name__ == "__main__":
    raise SystemExit(main())
