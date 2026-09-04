"""Benchmark a packaged worker across multiple synthesis requests."""

from __future__ import annotations

import argparse
import hashlib
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
    request_shapes = _load_request_shapes(args.request_shapes_jsonl)

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
            shape = _request_shape_for_index(args, request_shapes, index + 1)
            warmups.append(
                _run_request(
                    harness,
                    request_id=request_id,
                    text=str(shape["text"]),
                    language=str(shape["language"]),
                    speaker=str(shape["speaker"]),
                    instruction=str(shape["instruction"]),
                    voice_id=str(shape["voice_id"]),
                    reference_audio_path=str(shape["reference_audio_path"]),
                    reference_text=str(shape["reference_text"]),
                    x_vector_only=bool(shape["x_vector_only"]),
                )
            )
        results = []
        for index in range(args.requests):
            request_id = args.warmups + index + 1
            shape = _request_shape_for_index(args, request_shapes, request_id)
            result = _run_request(
                harness,
                request_id=request_id,
                text=str(shape["text"]),
                language=str(shape["language"]),
                speaker=str(shape["speaker"]),
                instruction=str(shape["instruction"]),
                voice_id=str(shape["voice_id"]),
                reference_audio_path=str(shape["reference_audio_path"]),
                reference_text=str(shape["reference_text"]),
                x_vector_only=bool(shape["x_vector_only"]),
            )
            result["shape_label"] = shape["label"]
            result["talker_prefill_length"] = shape.get("talker_prefill_length")
            results.append(
                result
            )
        _shutdown(harness)
        worker_metrics = _worker_metrics(harness.stderr_text())
    finally:
        harness.close()

    warmups = [_with_request_metrics(row, worker_metrics) for row in warmups]
    results = [_with_request_metrics(row, worker_metrics) for row in results]

    report = {
        "config": {
            "warmups": args.warmups,
            "requests": args.requests,
            "text": args.text,
            "language": args.language,
            "speaker": args.speaker,
            "instruction": args.instruction,
            "seed": args.seed,
            "seed_mode": args.seed_mode,
            "warmup_seed": args.warmup_seed,
            "warmup_synthesis": args.warmup_synthesis,
            "warmup_synthesis_passes": args.warmup_synthesis_passes,
            "warmup_unbounded_passes": args.warmup_unbounded_passes,
            "warmup_max_output_chunks": args.warmup_max_output_chunks,
            "warmup_voice_id": args.warmup_voice_id,
            "preload_voice_profiles": args.preload_voice_profiles,
            "engine_startup_mode": args.engine_startup_mode,
            "prefill_compile_lengths": args.prefill_compile_lengths,
            "prefill_compile_on_miss": args.prefill_compile_on_miss,
            "prefill_unknown_shape_policy": args.prefill_unknown_shape_policy,
            "request_shapes_jsonl": str(args.request_shapes_jsonl)
            if args.request_shapes_jsonl
            else None,
            "emit_chunk_schedule": args.emit_chunk_schedule,
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
    }
    serialized = json.dumps(report, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
        print(f"report_json={args.output.resolve()}")
    else:
        print(serialized)
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
    parser.add_argument("--emit-chunk-schedule", default="")
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
    parser.add_argument("--profile-prefill", action="store_true")
    parser.add_argument("--profile-nvtx", action="store_true")
    parser.add_argument("--collect-generation-trace", action="store_true")
    parser.add_argument(
        "--prefill-backend",
        choices=(
            "eager",
            "compile_backend_eager",
            "compile_backend_aot_eager",
            "compile_default",
            "compile_inductor_default",
            "compile_reduce_overhead",
        ),
        default="eager",
    )
    parser.add_argument(
        "--prefill-compile-compat-mode",
        choices=("none", "strict_bf16_sdpa_v1"),
        default="none",
    )
    parser.add_argument(
        "--prefill-compile-lengths",
        type=_parse_prefill_compile_lengths,
        default=(),
    )
    parser.add_argument(
        "--no-prefill-compile-on-miss",
        action="store_false",
        dest="prefill_compile_on_miss",
        default=True,
    )
    parser.add_argument(
        "--prefill-unknown-shape-policy",
        choices=("eager", "error"),
        default="eager",
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--seed-mode",
        choices=("request_id", "fixed"),
        default="request_id",
    )
    parser.add_argument("--warmup-seed", type=int, default=None)
    parser.add_argument("--warmup-synthesis", action="store_true")
    parser.add_argument("--warmup-synthesis-passes", type=int, default=1)
    parser.add_argument("--warmup-unbounded-passes", type=int, default=0)
    parser.add_argument("--warmup-max-output-chunks", type=int, default=None)
    parser.add_argument("--warmup-text", default="Warmup.")
    parser.add_argument("--warmup-language", default="auto")
    parser.add_argument("--warmup-speaker", default="")
    parser.add_argument("--warmup-voice-id", default="")
    parser.add_argument("--warmup-instruction", default="")
    parser.add_argument(
        "--engine-startup-mode",
        choices=("auto", "main", "engine_warmup", "engine_load_warmup"),
        default="auto",
    )
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--mock-chunks", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--requests", type=int, default=2)
    parser.add_argument("--text", default="Packaged worker benchmark request.")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--speaker", default="")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--voice-id", default="")
    parser.add_argument("--reference-audio-path", default="")
    parser.add_argument("--reference-text", default="")
    parser.add_argument("--x-vector-only", action="store_true")
    parser.add_argument("--voice-registry-path", default="")
    parser.add_argument("--preload-voice-profiles", action="store_true")
    parser.add_argument(
        "--request-shapes-jsonl",
        type=Path,
        default=None,
        help=(
            "Optional JSONL schedule with label/text/language/speaker/instruction "
            "and Base voice-clone fields."
        ),
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser


def _load_request_shapes(path: Path | None) -> list[dict[str, object]]:
    if path is None:
        return []
    shapes = []
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid request shape JSONL at line {line_number}: {exc}"
            ) from exc
        if not isinstance(item, dict):
            raise ValueError(
                f"request shape JSONL line {line_number} must be an object"
            )
        text = item.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError(
                f"request shape JSONL line {line_number} must contain text"
            )
        label = item.get("label", f"shape_{line_number}")
        if not isinstance(label, str) or not label:
            raise ValueError(
                f"request shape JSONL line {line_number} has invalid label"
            )
        shape = {
            "label": label,
            "text": text,
            "language": item.get("language", "auto"),
            "speaker": item.get("speaker", ""),
            "instruction": item.get("instruction", ""),
            "voice_id": item.get("voice_id", ""),
            "reference_audio_path": item.get("reference_audio_path", ""),
            "reference_text": item.get("reference_text", ""),
            "x_vector_only": item.get("x_vector_only", False),
            "talker_prefill_length": item.get("talker_prefill_length"),
        }
        _validate_request_shape(shape, line_number)
        shapes.append(shape)
    return shapes


def _request_shape_for_index(
    args: argparse.Namespace,
    shapes: list[dict[str, object]],
    request_id: int,
) -> dict[str, object]:
    if shapes:
        return shapes[(request_id - 1) % len(shapes)]
    return {
        "label": "default",
        "text": args.text,
        "language": args.language,
        "speaker": args.speaker,
        "instruction": args.instruction,
        "voice_id": args.voice_id,
        "reference_audio_path": args.reference_audio_path,
        "reference_text": args.reference_text,
        "x_vector_only": args.x_vector_only,
        "talker_prefill_length": None,
    }


def _validate_request_shape(shape: dict[str, object], line_number: int) -> None:
    """Reject malformed clone fields before a real worker is started."""

    for field in (
        "language",
        "speaker",
        "instruction",
        "voice_id",
        "reference_audio_path",
        "reference_text",
    ):
        if not isinstance(shape[field], str):
            raise ValueError(
                f"request shape JSONL line {line_number} has invalid {field}"
            )
    if not isinstance(shape["x_vector_only"], bool):
        raise ValueError(
            f"request shape JSONL line {line_number} has invalid x_vector_only"
        )
    if shape["voice_id"] and (
        shape["reference_audio_path"]
        or shape["reference_text"]
        or shape["x_vector_only"]
    ):
        raise ValueError(
            "request shape JSONL line "
            f"{line_number} mixes voice_id with direct reference-audio fields"
        )


def _parse_prefill_compile_lengths(value: str) -> tuple[int, ...]:
    text = value.strip()
    if not text:
        return ()
    lengths: list[int] = []
    for part in text.split(","):
        item = part.strip()
        if not item:
            raise argparse.ArgumentTypeError(
                "--prefill-compile-lengths must not contain empty items"
            )
        try:
            length = int(item)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                "--prefill-compile-lengths must contain integers"
            ) from exc
        if length <= 0:
            raise argparse.ArgumentTypeError(
                "--prefill-compile-lengths must contain positive integers"
            )
        lengths.append(length)
    if len(set(lengths)) != len(lengths):
        raise argparse.ArgumentTypeError(
            "--prefill-compile-lengths must not contain duplicates"
        )
    return tuple(lengths)


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
    voice_id: str,
    reference_audio_path: str,
    reference_text: str,
    x_vector_only: bool,
    seed: int | None = None,
) -> dict[str, object]:
    start = time.perf_counter()
    harness.send_control(
        request_id,
        _synthesize_payload(
            text=text,
            language=language,
            speaker=speaker,
            instruction=instruction,
            voice_id=voice_id,
            reference_audio_path=reference_audio_path,
            reference_text=reference_text,
            x_vector_only=x_vector_only,
            seed=seed,
        ),
    )

    audio_bytes = 0
    audio_chunks = 0
    pcm_digest = hashlib.sha256()
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
            pcm_digest.update(frame.payload)
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
        "pcm_sha256": pcm_digest.hexdigest(),
        "audio_duration_ms": audio_duration_ms,
        "real_time_factor": real_time_factor,
        "local_rtf": real_time_factor,
        "inverse_rtf": inverse_real_time_factor,
    }


def _with_request_metrics(
    request: dict[str, object],
    worker_metrics: list[dict[str, object]],
) -> dict[str, object]:
    request_id = request.get("request_id")
    if not isinstance(request_id, int):
        return request
    phases = _metrics_by_event(worker_metrics, request_id).get(
        "request_first_chunk_engine_phases",
        {},
    )
    if not isinstance(phases, dict):
        return request
    enriched = dict(request)
    for key in (
        "prefill_ms",
        "ar_decode_ms",
        "talker_prefill_length",
        "prefill_shape_length",
        "prefill_shape_call_ordinal",
        "prefill_compiled_call_3plus_host_ms",
    ):
        value = phases.get(key)
        if isinstance(value, (int, float)):
            enriched[f"first_chunk_{key}"] = float(value)
    for key in (
        "prefill_backend_used",
        "prefill_shape_policy",
        "prefill_compile_cache_kind",
    ):
        value = phases.get(key)
        if isinstance(value, str):
            enriched[f"first_chunk_{key}"] = value
    for key in (
        "prefill_compile_fallback",
        "prefill_shape_allowlist_hit",
        "prefill_compile_on_miss",
    ):
        value = phases.get(key)
        if isinstance(value, bool):
            enriched[f"first_chunk_{key}"] = value
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
    voice_id: str = "",
    reference_audio_path: str = "",
    reference_text: str = "",
    x_vector_only: bool = False,
    seed: int | None = None,
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
    if voice_id:
        payload["voice_id"] = voice_id
    if reference_audio_path:
        payload["reference_audio_path"] = reference_audio_path
    if reference_text:
        payload["reference_text"] = reference_text
    if x_vector_only:
        payload["x_vector_only"] = True
    if seed is not None:
        payload["seed"] = seed
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
