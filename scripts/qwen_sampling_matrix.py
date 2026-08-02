"""Run a reproducible FasterQwen sampling matrix on one loaded engine."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
import threading
from collections.abc import Iterable
from importlib import metadata
from pathlib import Path
from time import perf_counter

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine import QwenTtsEngine, SynthesisRequest
from qwen_tts_bridge_worker.engine.types import SamplingOptions

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEXTS = (
    ("short_ru", "Я твой робот. Я твой работник.", "Russian"),
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
    parser.add_argument(
        "--profile",
        type=Path,
        default=_REPO_ROOT
        / "config"
        / "rtx4090-faster-customvoice-style-eager-experiment.json",
    )
    parser.add_argument("--speaker", default="serena")
    parser.add_argument("--alternate-speaker", default="ryan")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--alternate-seed", type=int, default=7331)
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--alternate-temperature", type=float, default=0.9)
    parser.add_argument("--top-k-values", default="1,10,50")
    parser.add_argument("--top-p-values", default="0.7,0.9,1.0")
    parser.add_argument("--repetition-penalty-values", default="1.0,1.05,1.2")
    parser.add_argument("--max-audio-seconds", type=float, default=30.0)
    args = parser.parse_args()

    _validate_arguments(parser, args)
    args.profile = args.profile.resolve()
    args.top_k_values = _parse_csv_values(
        parser, args.top_k_values, int, "--top-k-values"
    )
    args.top_p_values = _parse_csv_values(
        parser, args.top_p_values, float, "--top-p-values"
    )
    args.repetition_penalty_values = _parse_csv_values(
        parser,
        args.repetition_penalty_values,
        float,
        "--repetition-penalty-values",
    )
    if any(value < 1 for value in args.top_k_values):
        parser.error("--top-k-values must contain positive integers")
    if any(not 0.0 < value <= 1.0 for value in args.top_p_values):
        parser.error("--top-p-values must be in (0, 1]")
    if any(value < 1.0 for value in args.repetition_penalty_values):
        parser.error("--repetition-penalty-values must be at least 1.0")

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
        warmup_seed=args.seed,
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


def _validate_arguments(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
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
    if not args.profile.is_file():
        parser.error(f"--profile was not found: {args.profile}")


def _parse_csv_values(
    parser: argparse.ArgumentParser,
    raw: str,
    value_type: type[int] | type[float],
    option: str,
) -> list[int] | list[float]:
    try:
        values = [value_type(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError:
        parser.error(f"{option} must be a comma-separated numeric list")
    if len(values) < 2 or len(set(values)) != len(values):
        parser.error(f"{option} must contain at least two distinct values")
    return values


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

    primary_label, primary_text, primary_language = _TEXTS[0]
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
        greedy_before,
        greedy_after,
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
        speaker_a_before,
        speaker_a_after,
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
        speaker_a_before,
        post_cancel,
    )
    checks["temperature_change_changes_at_least_one_sampled_output"] = any(
        not _same_output(left, right)
        for left, right in zip(sampled_baselines, hotter_cases, strict=True)
    )
    checks["seed_change_changes_at_least_one_sampled_output"] = any(
        not _same_output(left, right)
        for left, right in zip(sampled_baselines, alternate_seed_cases, strict=True)
    )

    sweeps = [
        _run_sampling_sweep(engine, args, "top_k", args.top_k_values, sampled),
        _run_sampling_sweep(engine, args, "top_p", args.top_p_values, sampled),
        _run_sampling_sweep(
            engine,
            args,
            "repetition_penalty",
            args.repetition_penalty_values,
            sampled,
        ),
    ]
    for sweep in sweeps:
        parameter = str(sweep["parameter"])
        checks[f"{parameter}_sweep_effective_settings_match"] = bool(
            sweep["effective_settings_match"]
        )
        checks[f"{parameter}_sweep_changes_at_least_one_output"] = bool(
            sweep["output_variation_observed"]
        )

    return {
        "schema_version": 2,
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
            "top_k_values": args.top_k_values,
            "top_p_values": args.top_p_values,
            "repetition_penalty_values": args.repetition_penalty_values,
            "instruction": args.instruction,
            "worker_warmup_synthesis": True,
            "worker_warmup_seed": args.seed,
        },
        "provenance": _provenance(args),
        "requests": requests,
        "sweeps": sweeps,
        "cancellation": cancellation,
        "checks": checks,
        "acceptance_pass": all(checks.values()),
        "listening_review_required": True,
        "quality_claim": (
            "This report proves control propagation and output variation, "
            "not perceptual quality."
        ),
    }


def _run_sampling_sweep(
    engine: QwenTtsEngine,
    args: argparse.Namespace,
    parameter: str,
    values: Iterable[int] | Iterable[float],
    baseline: SamplingOptions,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    expected_field = f"effective_{parameter}"
    for label, text, language in _TEXTS:
        for value in values:
            sampling = SamplingOptions(
                temperature=baseline.temperature,
                top_k=baseline.top_k,
                top_p=baseline.top_p,
                repetition_penalty=baseline.repetition_penalty,
                do_sample=baseline.do_sample,
            )
            if parameter == "top_k":
                sampling = SamplingOptions(
                    temperature=baseline.temperature,
                    top_k=int(value),
                    top_p=baseline.top_p,
                    repetition_penalty=baseline.repetition_penalty,
                    do_sample=baseline.do_sample,
                )
            elif parameter == "top_p":
                sampling = SamplingOptions(
                    temperature=baseline.temperature,
                    top_k=baseline.top_k,
                    top_p=float(value),
                    repetition_penalty=baseline.repetition_penalty,
                    do_sample=baseline.do_sample,
                )
            else:
                sampling = SamplingOptions(
                    temperature=baseline.temperature,
                    top_k=baseline.top_k,
                    top_p=baseline.top_p,
                    repetition_penalty=float(value),
                    do_sample=baseline.do_sample,
                )
            row = _run_case(
                engine,
                args,
                f"{label}_{parameter}_{value}",
                text,
                language,
                args.speaker,
                args.seed,
                sampling,
            )
            row["sweep_value"] = value
            rows.append(row)

    output_variation_observed = False
    for label, _text, _language in _TEXTS:
        label_rows = [row for row in rows if str(row["label"]).startswith(f"{label}_")]
        output_variation_observed = output_variation_observed or any(
            not _same_output(label_rows[0], row) for row in label_rows[1:]
        )
    return {
        "parameter": parameter,
        "values": list(values),
        "rows": rows,
        "effective_settings_match": all(
            row.get(expected_field) == row.get("sweep_value") for row in rows
        ),
        "output_variation_observed": output_variation_observed,
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


def _provenance(
    args: argparse.Namespace,
    *,
    script_path: Path | None = None,
) -> dict[str, object]:
    torch = importlib.import_module("torch")
    faster = importlib.import_module("faster_qwen3_tts")
    source_path = Path(str(faster.__file__)).resolve().parent
    model_path = Path(args.model).resolve()
    source_script = (script_path or Path(__file__)).resolve()
    return {
        "bridge": _git_fingerprint(_REPO_ROOT),
        "worker_source": _tree_fingerprint(_REPO_ROOT / "worker" / "src"),
        "script": {
            "path": str(source_script),
            "sha256": _sha256_file(source_script),
        },
        "profile": {
            "path": str(args.profile),
            "sha256": _sha256_file(args.profile),
        },
        "model": {
            "path": str(model_path),
            **_tree_fingerprint(model_path),
        },
        "runtime": {
            "python": sys.version.split()[0],
            "python_executable": str(Path(sys.executable).resolve()),
            "torch": str(torch.__version__),
            "cuda_runtime": str(torch.version.cuda),
            "gpu_name": str(torch.cuda.get_device_name(0)),
            "gpu_capability": list(torch.cuda.get_device_capability(0)),
            "gpu_total_memory_bytes": int(
                torch.cuda.get_device_properties(0).total_memory
            ),
            "nvidia_driver_version": _nvidia_driver_version(),
            "triton_distribution": _triton_distribution(),
            "faster_module_path": str(source_path),
            "faster_version": _distribution_version("faster-qwen3-tts"),
            "faster_source": _git_fingerprint(source_path),
        },
    }


def _tree_fingerprint(root: Path) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    total_bytes = 0
    for path in sorted(
        candidate for candidate in root.rglob("*") if candidate.is_file()
    ):
        size = path.stat().st_size
        total_bytes += size
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": size,
                "sha256": _sha256_file(path),
            }
        )
    payload = json.dumps(entries, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "file_count": len(entries),
        "total_bytes": total_bytes,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git_fingerprint(source_path: Path) -> dict[str, object]:
    return {
        "commit": _git_value(source_path, "rev-parse", "HEAD"),
        "tree": _git_value(source_path, "rev-parse", "HEAD^{tree}"),
        "dirty": _git_is_dirty(source_path),
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


def _git_is_dirty(source_path: Path) -> bool | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_path), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(completed.stdout.strip())


def _distribution_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _triton_distribution() -> dict[str, str] | None:
    for distribution in ("triton-windows", "triton"):
        version = _distribution_version(distribution)
        if version is not None:
            return {"name": distribution, "version": version}
    return None


def _nvidia_driver_version() -> str | None:
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.splitlines()[0].strip() if completed.stdout else ""
    return value or None


if __name__ == "__main__":
    raise SystemExit(main())
