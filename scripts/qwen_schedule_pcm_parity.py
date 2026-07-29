"""Compare deterministic PCM and codec traces across two Qwen worker schedules."""

from __future__ import annotations

import argparse
from array import array
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

from benchmark_packaged_worker import _is_request_frame, _shutdown, _synthesize_payload
from benchmark_packaged_worker_restart import (
    _hello,
    _worker_metrics,
)
from qwen_tts_bridge_worker.protocol import FrameType
from verify_packaged_worker import PackagedWorkerHarness, _control_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worker_executable", type=Path)
    parser.add_argument("--baseline-worker-arg", action="append", required=True)
    parser.add_argument("--candidate-worker-arg", action="append", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--language", default="Auto")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--max-duration-delta-ms", type=float, default=50.0)
    parser.add_argument("--timeout-seconds", type=float, default=1200.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    executable = args.worker_executable.resolve()
    if not executable.is_file():
        parser.error(f"worker executable was not found: {executable}")
    baseline = _run_case(executable, args.baseline_worker_arg, args, "baseline")
    candidate = _run_case(executable, args.candidate_worker_arg, args, "candidate")
    failures = _compare(
        baseline,
        candidate,
        max_duration_delta_ms=args.max_duration_delta_ms,
    )
    report: dict[str, object] = {
        "acceptance_pass": not failures,
        "failures": failures,
        "baseline": baseline,
        "candidate": candidate,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if not failures else 1


def _run_case(
    executable: Path,
    worker_args: list[str],
    args: argparse.Namespace,
    label: str,
) -> dict[str, object]:
    harness = PackagedWorkerHarness(executable, worker_args, args.timeout_seconds)
    try:
        ready = _hello(harness)
        result = _run_request_with_pcm(
            harness,
            request_id=1,
            text=args.text,
            language=args.language,
            speaker=args.speaker,
            instruction=args.instruction,
            seed=args.seed,
        )
        _shutdown(harness)
        metrics = _worker_metrics(harness.stderr_text())
    finally:
        harness.close()
    trace = _generation_trace(metrics, request_id=1)
    return {
        "label": label,
        "ready": ready,
        **result,
        "generation_trace": trace if isinstance(trace, dict) else None,
    }


def _run_request_with_pcm(
    harness: PackagedWorkerHarness,
    *,
    request_id: int,
    text: str,
    language: str,
    speaker: str,
    instruction: str,
    seed: int,
) -> dict[str, object]:
    started_at = time.perf_counter()
    harness.send_control(
        request_id,
        _synthesize_payload(
            text=text,
            language=language,
            speaker=speaker,
            instruction=instruction,
            seed=seed,
        ),
    )
    chunks: list[bytes] = []
    first_audio_ms: float | None = None
    while True:
        frame = harness.read_frame(
            lambda value: _is_request_frame(value, request_id)
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        if frame.header.frame_type == FrameType.AUDIO_PCM:
            if first_audio_ms is None:
                first_audio_ms = elapsed_ms
            chunks.append(frame.payload)
            continue
        if _control_payload(frame).get("message_type") == "completed":
            completed_ms = elapsed_ms
            break
    pcm = b"".join(chunks)
    return {
        "pcm_sha256": sha256(pcm).hexdigest(),
        "audio_bytes": len(pcm),
        "audio_chunks": len(chunks),
        "audio_duration_ms": len(pcm) * 1000.0 / (24000 * 2),
        "first_audio_ms": first_audio_ms,
        "completed_ms": completed_ms,
        "boundary_quality": _boundary_quality(chunks),
    }


def _generation_trace(
    metrics: list[dict[str, object]],
    *,
    request_id: int,
) -> dict[str, object] | None:
    for metric in metrics:
        if (
            metric.get("event") == "request_generation_trace"
            and metric.get("request_id") == request_id
        ):
            return {
                key: value
                for key, value in metric.items()
                if key not in {"event", "request_id"}
            }
    return None


def _boundary_quality(chunks: list[bytes]) -> dict[str, object]:
    samples = array("h")
    offsets: list[int] = []
    for chunk in chunks:
        if len(chunk) % 2 != 0:
            raise RuntimeError("PCM chunk is not S16LE-aligned")
        offsets.append(len(samples))
        values = array("h")
        values.frombytes(chunk)
        if sys.byteorder != "little":
            values.byteswap()
        samples.extend(values)
    boundary_jumps = [
        abs(samples[offset] - samples[offset - 1])
        for offset in offsets[1:]
        if offset < len(samples)
    ]
    return {
        "boundary_count": len(boundary_jumps),
        "max_boundary_jump_s16": max(boundary_jumps, default=0),
        "p95_boundary_jump_s16": _percentile(boundary_jumps, 95.0),
    }


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = percentile / 100.0 * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _compare(
    baseline: dict[str, object],
    candidate: dict[str, object],
    *,
    max_duration_delta_ms: float = 50.0,
) -> list[str]:
    failures: list[str] = []
    baseline_duration = baseline.get("audio_duration_ms")
    candidate_duration = candidate.get("audio_duration_ms")
    if not isinstance(baseline_duration, (int, float)) or not isinstance(
        candidate_duration, (int, float)
    ):
        failures.append("both workers must report audio duration")
    elif abs(float(baseline_duration) - float(candidate_duration)) > max_duration_delta_ms:
        failures.append(
            "audio_duration_ms differs by more than "
            f"{max_duration_delta_ms:.3f} ms"
        )
    baseline_trace = baseline.get("generation_trace")
    candidate_trace = candidate.get("generation_trace")
    if not isinstance(baseline_trace, dict) or not isinstance(candidate_trace, dict):
        failures.append("both workers must emit generation_trace")
        return failures
    for key in (
        "codec_sha256",
        "codec_frame_count",
        "termination_reason",
        "terminal_token_id",
        "terminal_step_index",
    ):
        if baseline_trace.get(key) != candidate_trace.get(key):
            failures.append(f"generation_trace.{key} differs between baseline and candidate")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
