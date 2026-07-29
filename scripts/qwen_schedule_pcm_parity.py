"""Compare deterministic PCM and codec traces across two Qwen worker schedules."""

from __future__ import annotations

import argparse
from array import array
import cmath
from hashlib import sha256
import json
import math
from pathlib import Path
import sys
import time
import wave

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
    parser.add_argument("--boundary-window-ms", type=float, default=10.0)
    parser.add_argument("--max-boundary-jump-s16", type=float, default=12000.0)
    parser.add_argument("--max-p95-boundary-jump-s16", type=float, default=4000.0)
    parser.add_argument("--max-rms-ratio", type=float, default=8.0)
    parser.add_argument("--max-dc-delta-s16", type=float, default=1200.0)
    parser.add_argument("--max-spectral-high-ratio-delta", type=float, default=0.7)
    parser.add_argument("--max-clip-sample-count", type=int, default=0)
    parser.add_argument("--wav-dir", type=Path)
    parser.add_argument("--cases-jsonl", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=1200.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    executable = args.worker_executable.resolve()
    if not executable.is_file():
        parser.error(f"worker executable was not found: {executable}")
    if args.boundary_window_ms <= 0.0:
        parser.error("--boundary-window-ms must be positive")
    if min(
        args.max_boundary_jump_s16,
        args.max_p95_boundary_jump_s16,
        args.max_rms_ratio,
        args.max_dc_delta_s16,
        args.max_spectral_high_ratio_delta,
        args.max_clip_sample_count,
    ) < 0:
        parser.error("boundary quality limits must not be negative")
    cases = _load_cases(args.cases_jsonl, args)
    baseline_results = _run_cases(
        executable,
        args.baseline_worker_arg,
        args,
        "baseline",
        cases,
    )
    candidate_results = _run_cases(
        executable,
        args.candidate_worker_arg,
        args,
        "candidate",
        cases,
    )
    pairs = []
    failures: list[str] = []
    for case, baseline, candidate in zip(cases, baseline_results, candidate_results):
        _write_pair_wavs(args.wav_dir, str(case["label"]), baseline, candidate)
        pair_failures = _compare(
            baseline,
            candidate,
            max_duration_delta_ms=args.max_duration_delta_ms,
            max_boundary_jump_s16=args.max_boundary_jump_s16,
            max_p95_boundary_jump_s16=args.max_p95_boundary_jump_s16,
            max_rms_ratio=args.max_rms_ratio,
            max_dc_delta_s16=args.max_dc_delta_s16,
            max_spectral_high_ratio_delta=args.max_spectral_high_ratio_delta,
            max_clip_sample_count=args.max_clip_sample_count,
        )
        failures.extend(f"{case['label']}: {failure}" for failure in pair_failures)
        pairs.append(
            {
                "label": case["label"],
                "acceptance_pass": not pair_failures,
                "failures": pair_failures,
                "baseline": baseline,
                "candidate": candidate,
            }
        )
    report: dict[str, object] = {
        "acceptance_pass": not failures,
        "failures": failures,
        "pairs": pairs,
    }
    if len(pairs) == 1:
        report["baseline"] = pairs[0]["baseline"]
        report["candidate"] = pairs[0]["candidate"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if not failures else 1


def _load_cases(path: Path | None, args: argparse.Namespace) -> list[dict[str, object]]:
    if path is None:
        return [
            {
                "label": "default",
                "text": args.text,
                "language": args.language,
                "speaker": args.speaker,
                "instruction": args.instruction,
                "seed": args.seed,
            }
        ]
    cases = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        value = json.loads(raw_line)
        if not isinstance(value, dict):
            raise RuntimeError(f"{path}:{line_number}: case must be an object")
        label = value.get("label")
        text = value.get("text")
        if not isinstance(label, str) or not label:
            raise RuntimeError(f"{path}:{line_number}: case requires label")
        if not isinstance(text, str) or not text:
            raise RuntimeError(f"{path}:{line_number}: case requires text")
        case = {
            "label": label,
            "text": text,
            "language": value.get("language", args.language),
            "speaker": value.get("speaker", args.speaker),
            "instruction": value.get("instruction", args.instruction),
            "seed": value.get("seed", args.seed),
        }
        if not isinstance(case["language"], str) or not isinstance(case["speaker"], str):
            raise RuntimeError(f"{path}:{line_number}: language and speaker must be strings")
        if not isinstance(case["instruction"], str) or not isinstance(case["seed"], int):
            raise RuntimeError(f"{path}:{line_number}: instruction and seed are invalid")
        cases.append(case)
    if not cases:
        raise RuntimeError(f"{path}: no cases")
    if len({str(case["label"]) for case in cases}) != len(cases):
        raise RuntimeError(f"{path}: case labels must be unique")
    return cases


def _run_cases(
    executable: Path,
    worker_args: list[str],
    args: argparse.Namespace,
    label: str,
    cases: list[dict[str, object]],
) -> list[dict[str, object]]:
    harness = PackagedWorkerHarness(executable, worker_args, args.timeout_seconds)
    try:
        ready = _hello(harness)
        results = []
        for request_id, case in enumerate(cases, 1):
            seed = case["seed"]
            assert isinstance(seed, int)
            result = _run_request_with_pcm(
                harness,
                request_id=request_id,
                text=str(case["text"]),
                language=str(case["language"]),
                speaker=str(case["speaker"]),
                instruction=str(case["instruction"]),
                seed=seed,
                boundary_window_ms=args.boundary_window_ms,
            )
            result["label"] = str(case["label"])
            result["ready"] = ready
            results.append(result)
        _shutdown(harness)
        metrics = _worker_metrics(harness.stderr_text())
    finally:
        harness.close()
    for request_id, result in enumerate(results, 1):
        result["generation_trace"] = _generation_trace(metrics, request_id=request_id)
        result["worker_label"] = label
    return results


def _run_request_with_pcm(
    harness: PackagedWorkerHarness,
    *,
    request_id: int,
    text: str,
    language: str,
    speaker: str,
    instruction: str,
    seed: int,
    boundary_window_ms: float,
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
        "request_id": request_id,
        "pcm_sha256": sha256(pcm).hexdigest(),
        "audio_bytes": len(pcm),
        "audio_chunks": len(chunks),
        "chunk_samples": [len(chunk) // 2 for chunk in chunks],
        "audio_duration_ms": len(pcm) * 1000.0 / (24000 * 2),
        "first_audio_ms": first_audio_ms,
        "completed_ms": completed_ms,
        "boundary_quality": _boundary_quality(
            chunks,
            sample_rate=24000,
            window_ms=boundary_window_ms,
        ),
        "_pcm": pcm,
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


def _boundary_quality(
    chunks: list[bytes],
    *,
    sample_rate: int,
    window_ms: float,
) -> dict[str, object]:
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
    window_samples = max(1, int(round(sample_rate * window_ms / 1000.0)))
    boundary_windows = [
        _boundary_window_metrics(samples, offset, window_samples)
        for offset in offsets[1:]
        if offset > 0 and offset < len(samples)
    ]
    return {
        "boundary_count": len(boundary_jumps),
        "max_boundary_jump_s16": max(boundary_jumps, default=0),
        "p95_boundary_jump_s16": _percentile(boundary_jumps, 95.0),
        "max_dc_delta_s16": max(
            (float(item["dc_delta_s16"]) for item in boundary_windows),
            default=0.0,
        ),
        "max_rms_ratio": max(
            (float(item["rms_ratio"]) for item in boundary_windows),
            default=1.0,
        ),
        "max_spectral_high_ratio_delta": max(
            (float(item["spectral_high_ratio_delta"]) for item in boundary_windows),
            default=0.0,
        ),
        "clip_sample_count": sum(1 for value in samples if abs(value) >= 32760),
    }


def _boundary_window_metrics(
    samples: array,
    offset: int,
    window_samples: int,
) -> dict[str, float]:
    left = [float(value) for value in samples[max(0, offset - window_samples) : offset]]
    right = [float(value) for value in samples[offset : offset + window_samples]]
    left_rms = _rms(left)
    right_rms = _rms(right)
    low_rms = max(min(left_rms, right_rms), 1.0)
    return {
        "dc_delta_s16": abs(_mean(left) - _mean(right)),
        "rms_ratio": max(left_rms, right_rms) / low_rms,
        "spectral_high_ratio_delta": abs(
            _spectral_high_ratio(left) - _spectral_high_ratio(right)
        ),
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values)) if values else 0.0


def _spectral_high_ratio(values: list[float]) -> float:
    if len(values) < 8:
        return 0.0
    centered = [value - _mean(values) for value in values]
    total_energy = 0.0
    high_energy = 0.0
    count = len(centered)
    for bin_index in range(1, count // 2 + 1):
        component = sum(
            value * cmath.exp(-2j * math.pi * bin_index * sample_index / count)
            for sample_index, value in enumerate(centered)
        )
        energy = component.real * component.real + component.imag * component.imag
        total_energy += energy
        if bin_index >= count // 4:
            high_energy += energy
    return high_energy / total_energy if total_energy > 0.0 else 0.0


def _write_pair_wavs(
    wav_dir: Path | None,
    label: str,
    baseline: dict[str, object],
    candidate: dict[str, object],
) -> None:
    if wav_dir is None:
        _strip_pcm(baseline)
        _strip_pcm(candidate)
        return
    wav_dir.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(character if character.isalnum() or character in "-_" else "_" for character in label)
    for side, result in (("fixed8", baseline), ("schedule-6-8-12", candidate)):
        pcm = result.get("_pcm")
        if not isinstance(pcm, bytes):
            raise RuntimeError(f"{side} result lacks PCM")
        path = wav_dir / f"{safe_label}-{side}.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(24000)
            handle.writeframes(pcm)
        result["wav_path"] = str(path)
        _strip_pcm(result)


def _strip_pcm(result: dict[str, object]) -> None:
    result.pop("_pcm", None)


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
    max_boundary_jump_s16: float = 12000.0,
    max_p95_boundary_jump_s16: float = 4000.0,
    max_rms_ratio: float = 8.0,
    max_dc_delta_s16: float = 1200.0,
    max_spectral_high_ratio_delta: float = 0.7,
    max_clip_sample_count: int = 0,
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
    _compare_boundary_quality(
        baseline,
        candidate,
        failures,
        max_boundary_jump_s16=max_boundary_jump_s16,
        max_p95_boundary_jump_s16=max_p95_boundary_jump_s16,
        max_rms_ratio=max_rms_ratio,
        max_dc_delta_s16=max_dc_delta_s16,
        max_spectral_high_ratio_delta=max_spectral_high_ratio_delta,
        max_clip_sample_count=max_clip_sample_count,
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


def _compare_boundary_quality(
    baseline: dict[str, object],
    candidate: dict[str, object],
    failures: list[str],
    *,
    max_boundary_jump_s16: float,
    max_p95_boundary_jump_s16: float,
    max_rms_ratio: float,
    max_dc_delta_s16: float,
    max_spectral_high_ratio_delta: float,
    max_clip_sample_count: int,
) -> None:
    baseline_quality = baseline.get("boundary_quality")
    candidate_quality = candidate.get("boundary_quality")
    if not isinstance(baseline_quality, dict) or not isinstance(candidate_quality, dict):
        failures.append("both workers must report boundary_quality")
        return
    for key, maximum in (
        ("max_boundary_jump_s16", max_boundary_jump_s16),
        ("p95_boundary_jump_s16", max_p95_boundary_jump_s16),
        ("max_rms_ratio", max_rms_ratio),
        ("max_dc_delta_s16", max_dc_delta_s16),
        ("max_spectral_high_ratio_delta", max_spectral_high_ratio_delta),
        ("clip_sample_count", max_clip_sample_count),
    ):
        baseline_value = baseline_quality.get(key)
        candidate_value = candidate_quality.get(key)
        if not isinstance(baseline_value, (int, float)) or not isinstance(
            candidate_value, (int, float)
        ):
            failures.append(f"boundary_quality.{key} is missing")
            continue
        if float(candidate_value) > maximum:
            failures.append(
                f"boundary_quality.{key} exceeds maximum {maximum:.3f}"
            )


if __name__ == "__main__":
    raise SystemExit(main())
