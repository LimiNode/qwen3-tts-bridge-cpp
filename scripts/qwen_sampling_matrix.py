"""Run a reproducible FasterQwen sampling matrix on one loaded engine."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import threading
from pathlib import Path
from time import perf_counter

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine import QwenTtsEngine, SynthesisRequest
from qwen_tts_bridge_worker.engine.types import SamplingOptions

_TEXTS = (
    (
        "short_ru",
        "Я твой робот. Я твой работник.",
        "Russian",
    ),
    (
        "long_ru",
        "После этого поворота проверим карту, сохранимся и пойдём дальше. "
        "Если стражник снова закроет проход, не торопимся с атакой: сначала "
        "найдём другой маршрут.",
        "Russian",
    ),
    (
        "english",
        "The bridge is stable, the route is clear, and we can finish this test "
        "before the next mission starts.",
        "English",
    ),
    (
        "pronunciation_ru",
        "Я положил ключ на за́мок, а потом открыл замо́к.",
        "Russian",
    ),
    (
        "emotional_ru",
        "Немедленно остановитесь. Все системы переходят в ручной режим.",
        "Russian",
    ),
)


def main() -> int:
    """Run the matrix and write a self-contained JSON report."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--speaker", default="serena")
    parser.add_argument("--alternate-speaker", default="ryan")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--alternate-seed", type=int, default=7331)
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--alternate-temperature", type=float, default=0.9)
    parser.add_argument("--max-audio-seconds", type=float, default=30.0)
    args = parser.parse_args()

    if args.seed < 0 or args.alternate_seed < 0:
        parser.error("seeds must be non-negative")
    if args.seed == args.alternate_seed:
        parser.error("--alternate-seed must differ from --seed")
    if not 0.0 < args.temperature <= 2.0:
        parser.error("--temperature must be in (0, 2]")
    if not 0.0 < args.alternate_temperature <= 2.0:
        parser.error("--alternate-temperature must be in (0, 2]")
    if args.max_audio_seconds <= 0.0:
        parser.error("--max-audio-seconds must be positive")

    config = QwenEngineConfig(
        model_path=args.model,
        runtime_backend="faster",
        device="cuda",
        dtype="bfloat16",
        attn_implementation="sdpa",
        max_audio_seconds_per_utterance=args.max_audio_seconds,
        emit_every_frames=8,
        decode_window_frames=80,
        prefill_backend="eager",
        prefill_compile_compat_mode="none",
        prefill_compile_on_miss=False,
        prefill_unknown_shape_policy="eager",
        prefill_compile_policy="diagnostic_dynamic",
        collect_generation_trace=True,
        allow_request_sampling_overrides=True,
        warmup_synthesis_enabled=True,
        warmup_synthesis_passes=1,
        warmup_unbounded_passes=1,
        warmup_text="Проверка готовности завершена.",
        warmup_language="Russian",
        warmup_speaker=args.speaker,
        warmup_instruction="Speak clearly in a neutral, natural tone.",
    )
    engine = QwenTtsEngine(config)
    try:
        engine.load()
        if not engine.capabilities.sampling_overrides:
            raise RuntimeError("loaded engine does not support sampling overrides")
        if not engine.capabilities.deterministic_seed:
            raise RuntimeError("loaded engine does not support deterministic seeds")
        warmup = engine.warmup()
        report = _run_matrix(engine, args)
        report["warmup"] = warmup
    finally:
        engine.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["checks"], indent=2))
    return 0 if report["acceptance_pass"] else 1


def _run_matrix(engine: QwenTtsEngine, args: argparse.Namespace) -> dict[str, object]:
    sampled = SamplingOptions(
        temperature=args.temperature,
        top_k=50,
        top_p=1.0,
        repetition_penalty=1.05,
        do_sample=True,
    )
    hotter = SamplingOptions(
        temperature=args.alternate_temperature,
        top_k=50,
        top_p=1.0,
        repetition_penalty=1.05,
        do_sample=True,
    )
    greedy = SamplingOptions(
        temperature=args.temperature,
        top_k=50,
        top_p=1.0,
        repetition_penalty=1.05,
        do_sample=False,
    )
    requests: list[dict[str, object]] = []
    sampled_baselines: list[dict[str, object]] = []
    hotter_cases: list[dict[str, object]] = []
    alternate_seed_cases: list[dict[str, object]] = []
    checks: dict[str, bool] = {}

    for label, text, language in _TEXTS:
        def run(
            speaker: str,
            seed: int,
            sampling: SamplingOptions,
            *,
            case_label: str = label,
            case_text: str = text,
            case_language: str = language,
        ) -> dict[str, object]:
            return _run_case(
                engine,
                args,
                case_label,
                case_text,
                case_language,
                speaker,
                seed,
                sampling,
            )

        sampled_a = run(args.speaker, args.seed, sampled)
        sampled_b = run(args.speaker, args.seed, sampled)
        hotter_case = run(args.speaker, args.seed, hotter)
        alternate_seed_case = run(args.speaker, args.alternate_seed, sampled)
        greedy_a = run(args.speaker, args.seed, greedy)
        greedy_b = run(args.speaker, args.seed, greedy)
        requests.extend(
            [sampled_a, sampled_b, hotter_case, alternate_seed_case, greedy_a, greedy_b]
        )
        sampled_baselines.append(sampled_a)
        hotter_cases.append(hotter_case)
        alternate_seed_cases.append(alternate_seed_case)
        checks[f"{label}_sampled_repeat_exact"] = _same_output(sampled_a, sampled_b)
        checks[f"{label}_greedy_repeat_exact"] = _same_output(greedy_a, greedy_b)

    _primary_label, primary_text, primary_language = _TEXTS[0]
    greedy_before = _run_case(
        engine,
        args,
        "greedy_before_sampled",
        primary_text,
        primary_language,
        args.speaker,
        args.seed,
        greedy,
    )
    sampled_between = _run_case(
        engine,
        args,
        "sampled_between_greedy",
        primary_text,
        primary_language,
        args.speaker,
        args.seed,
        sampled,
    )
    greedy_after = _run_case(
        engine,
        args,
        "greedy_after_sampled",
        primary_text,
        primary_language,
        args.speaker,
        args.seed,
        greedy,
    )
    requests.extend([greedy_before, sampled_between, greedy_after])
    checks["greedy_sampled_greedy_has_no_state_leakage"] = _same_output(
        greedy_before, greedy_after
    )

    speaker_a_before = _run_case(
        engine,
        args,
        "speaker_a_before",
        primary_text,
        primary_language,
        args.speaker,
        args.seed,
        sampled,
    )
    speaker_b = _run_case(
        engine,
        args,
        "speaker_b",
        primary_text,
        primary_language,
        args.alternate_speaker,
        args.seed,
        sampled,
    )
    speaker_a_after = _run_case(
        engine,
        args,
        "speaker_a_after",
        primary_text,
        primary_language,
        args.speaker,
        args.seed,
        sampled,
    )
    requests.extend([speaker_a_before, speaker_b, speaker_a_after])
    checks["speaker_a_b_a_has_no_state_leakage"] = _same_output(
        speaker_a_before, speaker_a_after
    )

    cancellation = _run_cancellation(
        engine,
        args,
        primary_text,
        primary_language,
        sampled,
    )
    post_cancel = _run_case(
        engine,
        args,
        "post_cancel_control",
        primary_text,
        primary_language,
        args.speaker,
        args.seed,
        sampled,
    )
    requests.append(post_cancel)
    checks["cancellation_stops_after_first_chunk"] = bool(cancellation["cancelled"])
    checks["post_cancel_control_matches_seeded_baseline"] = _same_output(
        speaker_a_before, post_cancel
    )

    checks["temperature_change_changes_at_least_one_sampled_output"] = any(
        not _same_output(left, right)
        for left, right in zip(sampled_baselines, hotter_cases, strict=True)
    )
    checks["seed_change_changes_at_least_one_sampled_output"] = any(
        not _same_output(left, right)
        for left, right in zip(sampled_baselines, alternate_seed_cases, strict=True)
    )

    return {
        "schema_version": 1,
        "experiment": "faster_qwen_sampling_matrix",
        "configuration": {
            "runtime_backend": "faster",
            "device": "cuda",
            "dtype": "bfloat16",
            "prefill_backend": "eager",
            "speaker": args.speaker,
            "alternate_speaker": args.alternate_speaker,
            "seed": args.seed,
            "alternate_seed": args.alternate_seed,
            "temperature": args.temperature,
            "alternate_temperature": args.alternate_temperature,
            "instruction": args.instruction,
            "worker_warmup_synthesis": True,
        },
        "runtime": _runtime_fingerprint(),
        "requests": requests,
        "cancellation": cancellation,
        "checks": checks,
        "acceptance_pass": all(checks.values()),
        "listening_review_required": True,
    }


def _run_case(
    engine: QwenTtsEngine,
    args: argparse.Namespace,
    label: str,
    text: str,
    language: str,
    speaker: str,
    seed: int,
    sampling: SamplingOptions,
) -> dict[str, object]:
    request = SynthesisRequest(
        request_id=len(label),
        text=text,
        language=language,
        speaker=speaker,
        instruction=args.instruction,
        sampling=sampling,
        seed=seed,
    )
    effective = engine.describe_request(request)
    started_at = perf_counter()
    pcm = bytearray()
    stream = engine.synthesize_stream(request, threading.Event())
    try:
        for chunk in stream:
            pcm.extend(chunk)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    trace = engine.pop_last_generation_trace() or {}
    return {
        "label": label,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "speaker": speaker,
        "duration_ms": round((perf_counter() - started_at) * 1000.0, 3),
        "pcm_bytes": len(pcm),
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
        "codec_sha256": trace.get("codec_sha256"),
        "termination_reason": trace.get("termination_reason"),
        **effective,
    }


def _run_cancellation(
    engine: QwenTtsEngine,
    args: argparse.Namespace,
    text: str,
    language: str,
    sampling: SamplingOptions,
) -> dict[str, object]:
    request = SynthesisRequest(
        request_id=9_999,
        text=text,
        language=language,
        speaker=args.speaker,
        instruction=args.instruction,
        sampling=sampling,
        seed=args.seed,
    )
    engine.describe_request(request)
    cancellation = threading.Event()
    audio_chunks = 0
    stream = engine.synthesize_stream(request, cancellation)
    try:
        for _chunk in stream:
            audio_chunks += 1
            cancellation.set()
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    return {
        "cancelled": cancellation.is_set() and audio_chunks == 1,
        "audio_chunks_before_cancel": audio_chunks,
    }


def _same_output(left: dict[str, object], right: dict[str, object]) -> bool:
    return (
        left["pcm_sha256"] == right["pcm_sha256"]
        and left["codec_sha256"] == right["codec_sha256"]
        and left["termination_reason"] == right["termination_reason"]
    )


def _runtime_fingerprint() -> dict[str, object]:
    torch = importlib.import_module("torch")
    faster = importlib.import_module("faster_qwen3_tts")
    source_path = Path(str(faster.__file__)).resolve().parent
    return {
        "torch": str(torch.__version__),
        "cuda_runtime": str(torch.version.cuda),
        "gpu_name": str(torch.cuda.get_device_name(0)),
        "faster_module_path": str(source_path),
        "faster_git_commit": _git_value(source_path, "rev-parse", "HEAD"),
        "faster_git_tree": _git_value(source_path, "rev-parse", "HEAD^{tree}"),
    }


def _git_value(source_path: Path, *arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_path), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


if __name__ == "__main__":
    raise SystemExit(main())
