"""Measure one frozen discovery record across deterministic seeds and lifecycles."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
_PCM_BYTES_PER_SECOND = 24_000 * 2


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.seed_count <= 0:
        parser.error("--seed-count must be positive")
    if args.mode == "single" and args.single_seed is None:
        parser.error("--single requires --single-seed")
    if args.mode != "single" and args.single_seed is not None:
        parser.error("--single-seed requires --single")

    seeds = [args.seed_start + offset for offset in range(args.seed_count)]
    if args.mode == "single":
        result = _single_process_run(args, args.single_seed)
    else:
        result = _matrix_run(args, seeds)
    _write_json(args.output, result)
    print(json.dumps(_printable_summary(result), sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--record-id", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--seed-start", type=int, required=True)
    parser.add_argument("--seed-count", type=int, default=20)
    parser.add_argument(
        "--mode",
        choices=("all", "fresh", "long-lived", "single"),
        default="all",
    )
    parser.add_argument("--single-seed", type=int)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _matrix_run(args: argparse.Namespace, seeds: list[int]) -> dict[str, object]:
    record, request_id = _find_record(args.input, args.record_id)
    modes: dict[str, object] = {}
    if args.mode in {"all", "fresh"}:
        modes["fresh_process"] = _fresh_process_runs(args, seeds)
    if args.mode in {"all", "long-lived"}:
        modes["long_lived"] = _long_lived_runs(args, record, request_id, seeds)
    return {
        "qwen_tail_case_matrix_schema_version": 1,
        "record_id": args.record_id,
        "request_id": request_id,
        "speaker": args.speaker,
        "seed_start": args.seed_start,
        "seed_count": args.seed_count,
        "seed_mode": "explicit_request_seed",
        "profile": _provenance(args.profile),
        "input": _provenance(args.input),
        "modes": modes,
        "diagnostic_scope": (
            "Frozen discovery record only. This matrix does not read the runtime "
            "measurement holdout and does not authorize a runtime configuration change."
        ),
    }


def _fresh_process_runs(args: argparse.Namespace, seeds: list[int]) -> dict[str, object]:
    run_dir = args.output.parent / f"{args.output.stem}-fresh-runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, object]] = []
    for seed in seeds:
        output = run_dir / f"seed-{seed}.json"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--input",
            str(args.input),
            "--record-id",
            args.record_id,
            "--profile",
            str(args.profile),
            "--speaker",
            args.speaker,
            "--seed-start",
            str(args.seed_start),
            "--seed-count",
            "1",
            "--mode",
            "single",
            "--single-seed",
            str(seed),
            "--output",
            str(output),
        ]
        completed = subprocess.run(
            command,
            cwd=_REPO_ROOT,
            capture_output=True,
            check=False,
            text=True,
            env=_child_environment(),
        )
        if not output.exists():
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"fresh seed {seed} failed without output: {message}")
        run = _load_object(output)
        run["subprocess_returncode"] = completed.returncode
        runs.append(run)
    return _mode_summary(runs)


def _long_lived_runs(
    args: argparse.Namespace,
    record: Mapping[str, object],
    request_id: int,
    seeds: list[int],
) -> dict[str, object]:
    engine = _create_engine(_load_object(args.profile), args.speaker)
    try:
        engine.load()
        engine.warmup()
        runs = [
            _run_request(engine, record, request_id, args.speaker, seed)
            for seed in seeds
        ]
    finally:
        engine.close()
    return _mode_summary(runs)


def _single_process_run(args: argparse.Namespace, seed: int) -> dict[str, object]:
    record, request_id = _find_record(args.input, args.record_id)
    engine = _create_engine(_load_object(args.profile), args.speaker)
    try:
        engine.load()
        engine.warmup()
        return _run_request(engine, record, request_id, args.speaker, seed)
    finally:
        engine.close()


def _create_engine(profile: Mapping[str, object], speaker: str) -> Any:
    from qwen_tts_bridge_worker.config import QwenEngineConfig
    from qwen_tts_bridge_worker.engine import QwenTtsEngine

    model_path = _resolve_profile_path(profile, "model_path")
    warmup_manifest = _resolve_profile_path(profile, "prefill_allowlist_warmup_manifest")
    warmup_length = profile.get("prefill_first_chunk_warmup_length")
    return QwenTtsEngine(
        QwenEngineConfig(
            model_path=str(model_path),
            runtime_backend="faster",
            device=str(profile["device"]),
            dtype=str(profile["dtype"]),
            attn_implementation=str(profile["attn_implementation"]),
            max_seq_len=int(profile["max_seq_len"]),
            max_audio_seconds_per_utterance=float(
                profile["max_audio_seconds_per_utterance"]
            ),
            emit_every_frames=int(profile["emit_every_frames"]),
            emit_chunk_schedule=_positive_tuple(profile["emit_chunk_schedule"]),
            compiled_emit_chunk_schedule=_positive_tuple(
                profile["compiled_emit_chunk_schedule"]
            ),
            eager_emit_chunk_schedule=_positive_tuple(profile["eager_emit_chunk_schedule"]),
            decode_window_frames=int(profile["decode_window_frames"]),
            prefill_backend=str(profile["prefill_backend"]),
            prefill_compile_compat_mode=str(profile["prefill_compile_compat_mode"]),
            prefill_compile_lengths=_positive_tuple(profile["prefill_compile_lengths"]),
            prefill_compile_on_miss=bool(profile["prefill_compile_on_miss"]),
            prefill_unknown_shape_policy=str(profile["prefill_unknown_shape_policy"]),
            prefill_compile_policy=str(profile["prefill_compile_policy"]),
            prefill_allowlist_warmup_manifest=str(warmup_manifest),
            prefill_allowlist_warmup_repeats=int(
                profile["prefill_allowlist_warmup_repeats"]
            ),
            prefill_allowlist_max_entries=int(profile["prefill_allowlist_max_entries"]),
            prefill_allowlist_max_abs_threshold=float(
                profile["prefill_allowlist_max_abs_threshold"]
            ),
            prefill_require_precompiled=bool(profile["prefill_require_precompiled"]),
            prefill_first_chunk_warmup_enabled=bool(profile["prefill_first_chunk_warmup"]),
            prefill_first_chunk_warmup_length=(
                int(warmup_length) if warmup_length is not None else None
            ),
            prefill_generation_prime_enabled=bool(
                profile.get("prefill_generation_prime", False)
            ),
            collect_generation_trace=True,
            seed=None,
            warmup_speaker=speaker,
        )
    )


def _run_request(
    engine: Any,
    record: Mapping[str, object],
    request_id: int,
    speaker: str,
    seed: int,
) -> dict[str, object]:
    from qwen_tts_bridge_worker.engine import (
        GenerationSafetyLimitError,
        SynthesisRequest,
    )

    request = SynthesisRequest(
        request_id=request_id,
        text=str(record["text"]),
        language=_language_for_record(str(record.get("language_class", ""))),
        speaker=speaker,
        seed=seed,
    )
    engine.validate_request(request)
    started = time.perf_counter()
    first_audio_ms: float | None = None
    audio_bytes = 0
    audio_chunks = 0
    first_route: dict[str, object] | None = None
    execution_outcome = "completed"
    generation_outcome: str | None = None
    failure: dict[str, object] | None = None
    stream = engine.synthesize_stream(request, threading.Event())
    try:
        for pcm in stream:
            if first_audio_ms is None:
                first_audio_ms = _milliseconds(started)
                metrics = engine.pop_last_chunk_metrics()
                first_route = dict(metrics) if isinstance(metrics, dict) else {}
            audio_chunks += 1
            audio_bytes += len(pcm)
    except GenerationSafetyLimitError as exc:
        execution_outcome = "failed"
        generation_outcome = "safety_duration_limit"
        failure = {
            "code": "safety_duration_limit",
            "max_audio_seconds_per_utterance": exc.limit_seconds,
            "emitted_audio_seconds": exc.emitted_seconds,
        }
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    trace = engine.pop_last_generation_trace()
    if generation_outcome is None:
        generation_outcome = _trace_outcome(trace)
    return {
        "seed": seed,
        "request_id": request_id,
        "execution_outcome": execution_outcome,
        "generation_outcome": generation_outcome,
        "first_audio_ms": round(first_audio_ms, 3) if first_audio_ms is not None else None,
        "completed_ms": round(_milliseconds(started), 3),
        "audio_seconds": round(audio_bytes / _PCM_BYTES_PER_SECOND, 6),
        "audio_chunks": audio_chunks,
        "codec_frame_count": trace.get("codec_frame_count") if isinstance(trace, dict) else None,
        "first_chunk_route": first_route,
        "generation_trace": trace,
        "failure": failure,
    }


def _mode_summary(runs: list[Mapping[str, object]]) -> dict[str, object]:
    return {
        "run_count": len(runs),
        "execution_outcomes": dict(
            sorted(Counter(str(run.get("execution_outcome")) for run in runs).items())
        ),
        "generation_outcomes": dict(
            sorted(Counter(str(run.get("generation_outcome")) for run in runs).items())
        ),
        "audio_seconds": _distribution(runs, "audio_seconds"),
        "first_audio_ms": _distribution(runs, "first_audio_ms"),
        "codec_frame_count": _distribution(runs, "codec_frame_count"),
        "runs": runs,
    }


def _distribution(runs: list[Mapping[str, object]], key: str) -> dict[str, float]:
    values = [
        float(value)
        for run in runs
        if isinstance((value := run.get(key)), (int, float)) and not isinstance(value, bool)
    ]
    if not values:
        return {}
    values.sort()
    return {
        "min": round(values[0], 3),
        "p50": round(_percentile(values, 0.50), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "max": round(values[-1], 3),
        "mean": round(statistics.fmean(values), 3),
    }


def _percentile(values: list[float], fraction: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _find_record(path: Path, record_id: str) -> tuple[dict[str, object], int]:
    for ordinal, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = json.loads(line)
        if isinstance(value, dict) and value.get("record_id") == record_id:
            if value.get("corpus_split") != "discovery":
                raise RuntimeError("tail-case diagnosis accepts discovery records only")
            return value, ordinal
    raise RuntimeError(f"record_id was not found: {record_id}")


def _resolve_profile_path(profile: Mapping[str, object], key: str) -> Path:
    value = Path(str(profile[key]))
    return value if value.is_absolute() else (_REPO_ROOT / value).resolve()


def _positive_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, int) or isinstance(item, bool) or item <= 0 for item in value
    ):
        raise RuntimeError("profile has an invalid positive integer list")
    return tuple(value)


def _trace_outcome(trace: object) -> str:
    if not isinstance(trace, Mapping):
        return "unknown"
    if trace.get("hit_eos") is True or trace.get("termination_reason") == "eos":
        return "eos"
    if trace.get("hit_max_seq_len") is True:
        return "max_seq_len"
    if trace.get("hit_max_new_tokens") is True:
        return "max_new_tokens"
    return "unknown"


def _language_for_record(language_class: str) -> str:
    return {"ru": "Russian", "en": "English", "mixed": "Auto"}.get(
        language_class,
        "Auto",
    )


def _provenance(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _milliseconds(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    paths = [str(_REPO_ROOT / "worker" / "src")]
    previous = environment.get("PYTHONPATH")
    if previous:
        paths.append(previous)
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    return environment


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _printable_summary(value: Mapping[str, object]) -> Mapping[str, object]:
    if "modes" not in value:
        return value
    return {
        "record_id": value["record_id"],
        "seed_count": value["seed_count"],
        "modes": {
            name: {
                "run_count": mode.get("run_count"),
                "execution_outcomes": mode.get("execution_outcomes"),
                "generation_outcomes": mode.get("generation_outcomes"),
            }
            for name, mode in dict(value["modes"]).items()
            if isinstance(mode, Mapping)
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
