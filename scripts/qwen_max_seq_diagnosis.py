"""Diagnose one discovery record's terminal generation outcome in fresh processes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
_PCM_BYTES_PER_SECOND = 24_000 * 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--record-id", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--request-id",
        type=int,
        default=0,
        help="Use this request ID; zero derives the one-based discovery ordinal.",
    )
    parser.add_argument("--no-sample", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--single", action="store_true")
    parser.add_argument(
        "--fresh-repeat",
        type=int,
        default=1,
        help="Run this many isolated Python processes with the same seed.",
    )
    args = parser.parse_args()
    if args.fresh_repeat <= 0:
        parser.error("--fresh-repeat must be positive")
    if args.single and args.fresh_repeat != 1:
        parser.error("--single requires --fresh-repeat=1")

    if args.single:
        result = _single_run(args)
        _write_json(args.output, result)
        print(json.dumps(result, sort_keys=True))
        return 0

    result = _fresh_repeats(args)
    _write_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0


def _fresh_repeats(args: argparse.Namespace) -> dict[str, object]:
    run_dir = args.output.parent / (args.output.stem + "-runs")
    run_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, object]] = []
    for repeat_index in range(args.fresh_repeat):
        output = run_dir / f"repeat-{repeat_index + 1:02d}.json"
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
            "--seed",
            str(args.seed),
            "--request-id",
            str(args.request_id),
            "--output",
            str(output),
            "--single",
        ]
        if args.no_sample:
            command.append("--no-sample")
        completed = subprocess.run(
            command,
            cwd=_REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=_child_environment(),
        )
        if not output.exists():
            raise RuntimeError(
                f"fresh repeat {repeat_index + 1} failed without an artifact: "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )
        run = _load_object(output)
        run["subprocess_returncode"] = completed.returncode
        runs.append(run)
    outcomes = [str(run.get("generation_outcome")) for run in runs]
    return {
        "qwen_max_seq_diagnosis_schema_version": 1,
        "mode": "fresh_process_repeats",
        "record_id": args.record_id,
        "seed": args.seed,
        "request_id": args.request_id,
        "do_sample": not args.no_sample,
        "repeat_count": args.fresh_repeat,
        "generation_outcomes": outcomes,
        "outcome_stable": len(set(outcomes)) == 1,
        "runs": runs,
        "diagnostic_note": (
            "The safety audio limit is intentionally disabled here. This is a "
            "diagnostic harness, not a product acceptance run."
        ),
    }


def _single_run(args: argparse.Namespace) -> dict[str, object]:
    from qwen_tts_bridge_worker.config import QwenEngineConfig
    from qwen_tts_bridge_worker.engine import (
        GenerationSafetyLimitError,
        QwenTtsEngine,
        SynthesisRequest,
    )

    record, discovery_ordinal = _find_record(args.input, args.record_id)
    request_id = args.request_id or discovery_ordinal
    profile = _load_object(args.profile)
    model_path = _resolve_profile_path(profile, "model_path")
    warmup_manifest = _resolve_profile_path(
        profile,
        "prefill_allowlist_warmup_manifest",
    )
    config = QwenEngineConfig(
        model_path=str(model_path),
        runtime_backend="faster",
        device=str(profile["device"]),
        dtype=str(profile["dtype"]),
        attn_implementation=str(profile["attn_implementation"]),
        max_seq_len=int(profile.get("max_seq_len", 2048)),
        emit_every_frames=int(profile["emit_every_frames"]),
        emit_chunk_schedule=_positive_tuple(profile["emit_chunk_schedule"]),
        compiled_emit_chunk_schedule=_positive_tuple(profile["compiled_emit_chunk_schedule"]),
        eager_emit_chunk_schedule=_positive_tuple(profile["eager_emit_chunk_schedule"]),
        decode_window_frames=int(profile["decode_window_frames"]),
        prefill_backend=str(profile["prefill_backend"]),
        prefill_compile_compat_mode=str(profile["prefill_compile_compat_mode"]),
        prefill_compile_lengths=_positive_tuple(profile["prefill_compile_lengths"]),
        prefill_compile_on_miss=bool(profile["prefill_compile_on_miss"]),
        prefill_unknown_shape_policy=str(profile["prefill_unknown_shape_policy"]),
        prefill_compile_policy=str(profile["prefill_compile_policy"]),
        prefill_allowlist_warmup_manifest=str(warmup_manifest),
        prefill_allowlist_warmup_repeats=int(profile["prefill_allowlist_warmup_repeats"]),
        prefill_allowlist_max_entries=int(profile["prefill_allowlist_max_entries"]),
        prefill_allowlist_max_abs_threshold=float(profile["prefill_allowlist_max_abs_threshold"]),
        prefill_require_precompiled=bool(profile["prefill_require_precompiled"]),
        prefill_first_chunk_warmup_enabled=bool(profile["prefill_first_chunk_warmup"]),
        prefill_first_chunk_warmup_length=int(profile["prefill_first_chunk_warmup_length"]),
        collect_generation_trace=True,
        do_sample=not args.no_sample,
        seed=args.seed,
        seed_mode="request_id",
        warmup_speaker=args.speaker,
    )
    engine = QwenTtsEngine(config)
    started = time.perf_counter()
    audio_bytes = 0
    audio_chunks = 0
    first_route: dict[str, object] | None = None
    execution_outcome = "completed"
    generation_outcome: str | None = None
    failure: dict[str, object] | None = None
    try:
        engine.load()
        engine.warmup()
        request = SynthesisRequest(
            request_id=request_id,
            text=str(record["text"]),
            language=_language_for_record(str(record.get("language_class", ""))),
            speaker=args.speaker,
        )
        engine.validate_request(request)
        try:
            for pcm in engine.synthesize_stream(request, threading.Event()):
                audio_bytes += len(pcm)
                audio_chunks += 1
                if first_route is None:
                    metrics = engine.pop_last_chunk_metrics()
                    first_route = dict(metrics) if isinstance(metrics, dict) else {}
        except GenerationSafetyLimitError as exc:
            execution_outcome = "failed"
            generation_outcome = "safety_duration_limit"
            failure = {"code": "safety_duration_limit", "message": str(exc)}
        trace = engine.pop_last_generation_trace()
        if generation_outcome is None:
            generation_outcome = _trace_outcome(trace)
    finally:
        engine.close()
    return {
        "qwen_max_seq_diagnosis_schema_version": 1,
        "mode": "single_fresh_process",
        "record_id": args.record_id,
        "seed": args.seed,
        "request_id": request_id,
        "do_sample": not args.no_sample,
        "execution_outcome": execution_outcome,
        "generation_outcome": generation_outcome,
        "audio_chunks": audio_chunks,
        "audio_seconds": round(audio_bytes / _PCM_BYTES_PER_SECOND, 6),
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "first_chunk_route": first_route,
        "generation_trace": trace,
        "failure": failure,
        "trace_detail_available": False,
        "trace_detail_note": (
            "The installed FasterQwen trace records terminal state and hashes, "
            "not per-step EOS logits or cycle data."
        ),
    }


def _find_record(path: Path, record_id: str) -> tuple[dict[str, object], int]:
    for ordinal, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = json.loads(line)
        if isinstance(value, dict) and value.get("record_id") == record_id:
            if value.get("corpus_split") != "discovery":
                raise RuntimeError("diagnosis only accepts discovery records")
            return value, ordinal
    raise RuntimeError(f"record_id was not found: {record_id}")


def _resolve_profile_path(profile: dict[str, object], key: str) -> Path:
    value = Path(str(profile[key]))
    return value if value.is_absolute() else (_REPO_ROOT / value).resolve()


def _positive_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or any(not isinstance(item, int) or item <= 0 for item in value):
        raise RuntimeError("profile has an invalid positive integer list")
    return tuple(value)


def _trace_outcome(trace: object) -> str:
    if not isinstance(trace, dict):
        return "unknown"
    if trace.get("hit_eos") is True:
        return "eos"
    if trace.get("hit_max_seq_len") is True:
        return "max_seq_len"
    if trace.get("hit_max_new_tokens") is True:
        return "max_new_tokens"
    return "unknown"


def _language_for_record(language_class: str) -> str:
    return {"ru": "Russian", "en": "English", "mixed": "Auto"}.get(language_class, "Auto")


def _child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(_REPO_ROOT / "worker" / "src")
    return environment


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
