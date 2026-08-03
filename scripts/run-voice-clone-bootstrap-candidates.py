"""Generate reproducible synthetic-reference candidates for Base voice cloning."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any, Iterable

_SCHEMA_VERSION = 4
_LANGUAGE = "Russian"
DEFAULT_TEXT = (
    "Привет! Я твой слуга, я твой работник. Жёлтый луч мягко лёг на шестерёнки; "
    "внизу щёлкнуло реле, сверху загудел вентилятор. Быстро проверь связь, "
    "цифры, шум и каждую новую команду."
)
VOICE_IDS = (
    "kraftwerk_robot_ru_icl_period",
    "kraftwerk_robot_ru_xvector",
)


def main() -> int:
    args = _build_parser().parse_args()
    if not args.voice_id:
        args.voice_id = list(VOICE_IDS)
    if args.candidates_per_voice <= 0:
        raise ValueError("candidates_per_voice must be greater than zero")
    if args.candidate_index_start < 0:
        raise ValueError("candidate_index_start must not be negative")
    if args.max_audio_seconds <= 0:
        raise ValueError("max_audio_seconds must be greater than zero")
    _prepend_paths(args)

    import numpy as np
    import torch
    from faster_qwen3_tts import FasterQwen3TTS

    from qwen_tts_bridge_worker.engine.voice_profiles import VoiceProfileRegistry

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    model_manifest_path = Path(args.model_runtime_manifest).resolve()
    model_manifest = _load_json_object(model_manifest_path)
    _verify_model_runtime_manifest(Path(args.model_path).resolve(), model_manifest)
    python_runtime_manifest_path = Path(args.python_runtime_manifest).resolve()
    python_runtime_manifest = _load_json_object(python_runtime_manifest_path)
    _verify_python_runtime_manifest(python_runtime_manifest)
    experiment_contract = _experiment_contract(
        args=args,
        torch=torch,
        model_manifest=model_manifest,
        python_runtime_manifest=python_runtime_manifest,
    )
    experiment_contract_sha256 = _sha256(_canonical_json_bytes(experiment_contract))
    experiment_locations = _experiment_locations(
        args=args,
        model_manifest_path=model_manifest_path,
        python_runtime_manifest_path=python_runtime_manifest_path,
    )
    registry_path = Path(args.voice_registry).resolve()
    registry = VoiceProfileRegistry.from_json_file(registry_path, len(args.voice_id))
    missing_voice_ids = [voice_id for voice_id in args.voice_id if not registry.has_voice(voice_id)]
    if missing_voice_ids:
        raise ValueError(f"voice registry lacks: {', '.join(missing_voice_ids)}")

    model: Any = FasterQwen3TTS.from_pretrained(
        args.model_path,
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
    )
    model.collect_generation_trace = True
    model.warmup()
    _sync_cuda(torch)

    prompts = {
        voice_id: registry.prompt_for(model, voice_id, policy="shared")
        for voice_id in args.voice_id
    }
    results: list[dict[str, object]] = []
    for voice_id in args.voice_id:
        voice_dir = output_dir / voice_id
        for local_index in range(args.candidates_per_voice):
            candidate_index = args.candidate_index_start + local_index
            seed = args.seed_start + candidate_index
            output_path = voice_dir / f"{candidate_index + 1:03d}-seed-{seed}.wav"
            candidate_contract = _candidate_contract(
                args=args,
                voice_id=voice_id,
                seed=seed,
                profile=registry.profile_for(voice_id),
                experiment_contract_sha256=experiment_contract_sha256,
            )
            if args.resume and output_path.is_file():
                results.append(
                    _read_existing(
                        output_path,
                        candidate_contract,
                        experiment_contract,
                    )
                )
            else:
                result = _generate_one(
                    model=model,
                    np=np,
                    torch=torch,
                    prompt=prompts[voice_id],
                    output_path=output_path,
                    seed=seed,
                    candidate_contract=candidate_contract,
                    experiment_contract=experiment_contract,
                    experiment_locations=experiment_locations,
                    args=args,
                )
                _write_json(_sidecar_path(output_path), result)
                results.append(result)
            print(
                f"[{voice_id}] {candidate_index + 1} "
                f"seed={seed} duration={results[-1]['audio_duration_ms']} ms "
                f"status={results[-1]['status']}"
            )

    summary = {
        "schema_version": _SCHEMA_VERSION,
        "purpose": "synthetic reference bootstrap candidate search",
        "experiment_contract": experiment_contract,
        "experiment_contract_sha256": experiment_contract_sha256,
        "experiment_locations": experiment_locations,
        "inputs": {
            "voice_registry": {
                "path": str(registry_path),
                "sha256": _sha256_file(registry_path),
            },
            "voice_profiles": {
                voice_id: _profile_metadata(registry.profile_for(voice_id))
                for voice_id in args.voice_id
            },
        },
        "selection_policy": {
            "status": "pending_human_listening",
            "do_not_replace_source_reference": True,
            "do_not_use_as_training_data": True,
            "target_prefix_workaround": {
                "enabled": True,
                "reason": "Avoid starting the target with text that overlaps the reference transcript.",
                "requirement": "Use a short prefix absent from the reference transcript and retain it in any selected candidate transcript.",
            },
            "selection_requirements": [
                "target begins with a short prefix absent from the reference transcript",
                "opening phrase resembles the authorized source reference",
                "timbre remains stable across the complete candidate",
                "candidate contains no reference-tail echo or unrelated speech",
            ],
        },
        "source_text": args.text,
        "source_text_sha256": _sha256(args.text.encode("utf-8")),
        "sampling": {
            "seed_start": args.seed_start,
            "candidate_index_start": args.candidate_index_start,
            "candidates_per_voice": args.candidates_per_voice,
            "temperature": args.temperature,
            "top_k": args.top_k,
            "top_p": args.top_p,
            "repetition_penalty": args.repetition_penalty,
            "do_sample": True,
        },
        "results": results,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"generated {len(results)} candidates in {output_dir}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True)
    parser.add_argument(
        "--model-runtime-manifest",
        required=True,
        help="Content manifest produced by scripts/model_runtime_manifest.py.",
    )
    parser.add_argument(
        "--python-runtime-manifest",
        required=True,
        help="Verified manifest produced by scripts/python_runtime_manifest.py.",
    )
    parser.add_argument("--faster-source", required=True)
    parser.add_argument("--voice-registry", required=True)
    parser.add_argument(
        "--output-dir", default="tmp/voice-clone-bootstrap-candidates-15s"
    )
    parser.add_argument(
        "--voice-id",
        action="append",
        default=[],
        help="Voice profile to sample; omit to generate the default ICL and x-vector sets.",
    )
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--candidates-per-voice", type=int, default=100)
    parser.add_argument("--candidate-index-start", type=int, default=0)
    parser.add_argument("--seed-start", type=int, default=10_000)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Keep valid existing WAVs in the selected candidate range.",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--repetition-penalty", type=float, default=1.05)
    parser.add_argument("--chunk-frames", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--max-audio-seconds", type=float, default=30.0)
    return parser


def _generate_one(
    *,
    model: Any,
    np: Any,
    torch: Any,
    prompt: Any,
    output_path: Path,
    seed: int,
    candidate_contract: dict[str, object],
    experiment_contract: dict[str, object],
    experiment_locations: dict[str, object],
    args: argparse.Namespace,
) -> dict[str, object]:
    _seed(seed, np, torch)
    started = time.perf_counter()
    stream: Any = None
    reset: dict[str, object] = {}
    trace: dict[str, object] = {}
    stream_outcome: dict[str, object] = {}
    primary_error: BaseException | None = None
    try:
        stream = model.generate_voice_clone_streaming(
            text=args.text,
            language=_LANGUAGE,
            voice_clone_prompt=prompt,
            chunk_size=args.chunk_frames,
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
            top_k=args.top_k,
            top_p=args.top_p,
            repetition_penalty=args.repetition_penalty,
            do_sample=True,
        )
        pcm, sample_rate, stream_outcome = _consume(
            stream,
            np,
            args.max_audio_seconds,
        )
        _sync_cuda(torch)
        trace = _copy_trace(getattr(model, "last_generation_trace", None))
    except BaseException as exc:
        primary_error = exc

    cleanup_errors: list[BaseException] = []
    close = getattr(stream, "close", None)
    if callable(close):
        try:
            close()
        except BaseException as exc:
            cleanup_errors.append(exc)
    try:
        _sync_cuda(torch)
        reset = _copy_trace(model.reset_after_partial_generation())
    except BaseException as exc:
        cleanup_errors.append(exc)

    if primary_error is not None or cleanup_errors:
        errors = ([primary_error] if primary_error is not None else []) + cleanup_errors
        if len(errors) == 1:
            raise errors[0]
        raise BaseExceptionGroup("candidate generation cleanup failed", errors)

    terminal = _terminal_outcome(stream_outcome, trace, reset)
    if not terminal["passed"]:
        failures = terminal["failures"]
        assert isinstance(failures, list)
        raise RuntimeError(
            "candidate did not reach a clean terminal outcome: "
            + ", ".join(str(failure) for failure in failures)
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_wav(output_path, pcm, sample_rate)
    return {
        "schema_version": _SCHEMA_VERSION,
        "candidate_contract": candidate_contract,
        "experiment_contract": experiment_contract,
        "experiment_locations": experiment_locations,
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "audio_duration_ms": round(len(pcm) / 2 / sample_rate * 1000.0, 3),
        "sample_rate": sample_rate,
        "pcm_sha256": _sha256(pcm),
        "pcm_bytes": len(pcm),
        "wav_sha256": _sha256_file(output_path),
        "output_wav": str(output_path),
        "reset": reset,
        "stream_outcome": stream_outcome,
        "trace": trace,
        "terminal": terminal,
        "status": "completed",
    }


def _read_existing(
    output_path: Path,
    candidate_contract: dict[str, object],
    experiment_contract: dict[str, object],
) -> dict[str, object]:
    sidecar_path = _sidecar_path(output_path)
    if not sidecar_path.is_file():
        raise ValueError(f"resume requires candidate sidecar: {sidecar_path}")
    existing = _load_json_object(sidecar_path)
    if existing.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(f"candidate sidecar has unsupported schema: {sidecar_path}")
    if existing.get("candidate_contract") != candidate_contract:
        raise ValueError(f"candidate sidecar does not match current request: {sidecar_path}")
    existing_contract = existing.get("experiment_contract")
    if not isinstance(existing_contract, dict):
        raise ValueError(f"candidate sidecar lacks experiment contract: {sidecar_path}")
    existing_contract_sha256 = _sha256(_canonical_json_bytes(existing_contract))
    if existing_contract_sha256 != candidate_contract.get("experiment_contract_sha256"):
        raise ValueError(f"candidate sidecar experiment contract SHA is invalid: {sidecar_path}")
    if existing_contract != experiment_contract:
        raise ValueError(f"candidate sidecar experiment contract does not match: {sidecar_path}")
    if existing.get("status") != "completed":
        raise ValueError(f"candidate sidecar is not completed: {sidecar_path}")
    terminal = existing.get("terminal")
    stream_outcome = existing.get("stream_outcome")
    trace = existing.get("trace")
    reset = existing.get("reset")
    if not isinstance(stream_outcome, dict) or not isinstance(trace, dict) or not isinstance(reset, dict):
        raise ValueError(f"candidate sidecar lacks terminal evidence: {sidecar_path}")
    recomputed_terminal = _terminal_outcome(stream_outcome, trace, reset)
    if recomputed_terminal.get("passed") is not True:
        raise ValueError(f"candidate sidecar terminal evidence does not pass: {sidecar_path}")
    if terminal != recomputed_terminal:
        raise ValueError(f"candidate sidecar terminal outcome does not match evidence: {sidecar_path}")

    with wave.open(str(output_path), "rb") as reader:
        if reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise ValueError(f"existing candidate has unexpected PCM format: {output_path}")
        sample_rate = reader.getframerate()
        pcm = reader.readframes(reader.getnframes())
    if not pcm:
        raise ValueError(f"existing candidate is empty: {output_path}")
    if existing.get("pcm_sha256") != _sha256(pcm):
        raise ValueError(f"candidate PCM hash does not match sidecar: {output_path}")
    if existing.get("pcm_bytes") != len(pcm):
        raise ValueError(f"candidate PCM size does not match sidecar: {output_path}")
    if existing.get("sample_rate") != sample_rate:
        raise ValueError(f"candidate sample rate does not match sidecar: {output_path}")
    if existing.get("wav_sha256") != _sha256_file(output_path):
        raise ValueError(f"candidate WAV hash does not match sidecar: {output_path}")
    existing["status"] = "resumed"
    return existing


def _prepend_paths(args: argparse.Namespace) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    paths = (Path(args.faster_source).resolve(), repo_root / "worker" / "src")
    for path in reversed(paths):
        path_text = str(path)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)


def _seed(seed: int, np: Any, torch: Any) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _consume(
    stream: Iterable[tuple[Any, int, dict[str, object]]],
    np: Any,
    max_audio_seconds: float,
) -> tuple[bytes, int, dict[str, object]]:
    if max_audio_seconds <= 0:
        raise ValueError("max_audio_seconds must be greater than zero")

    sample_rate = 24_000
    chunks: list[bytes] = []
    final_metadata: dict[str, object] = {}
    stream_exhausted = True
    safety_truncated = False
    for audio, sample_rate, metadata in stream:
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        maximum_pcm_bytes = int(max_audio_seconds * sample_rate * 2)
        remaining = maximum_pcm_bytes - sum(len(chunk) for chunk in chunks)
        if remaining < len(pcm):
            safety_truncated = True
            stream_exhausted = False
            break
        chunks.append(pcm)
        if isinstance(metadata, dict) and metadata.get("is_final") is True:
            final_metadata = _terminal_metadata(metadata)
    return b"".join(chunks), sample_rate, {
        "stream_exhausted": stream_exhausted,
        "safety_truncated": safety_truncated,
        "final_metadata": final_metadata,
    }


def _write_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with wave.open(str(temporary_path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    temporary_path.replace(path)


def _sync_cuda(torch: Any) -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sidecar_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".json")


def _write_json(path: Path, payload: object) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"candidate sidecar is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"candidate sidecar must contain an object: {path}")
    return value


def _candidate_contract(
    *,
    args: argparse.Namespace,
    voice_id: str,
    seed: int,
    profile: Any,
    experiment_contract_sha256: str,
) -> dict[str, object]:
    return {
        "experiment_contract_sha256": experiment_contract_sha256,
        "voice_id": voice_id,
        "seed": seed,
        "text": args.text,
        "language": _LANGUAGE,
        "sampling": {
            "temperature": args.temperature,
            "top_k": args.top_k,
            "top_p": args.top_p,
            "repetition_penalty": args.repetition_penalty,
            "do_sample": True,
        },
        "generation": {
            "chunk_frames": args.chunk_frames,
            "max_new_tokens": args.max_new_tokens,
            "max_audio_seconds": args.max_audio_seconds,
        },
        "voice_profile": _profile_metadata(profile),
    }


def _terminal_metadata(metadata: dict[str, object]) -> dict[str, object]:
    keys = (
        "is_final",
        "termination_reason",
        "hit_eos",
        "hit_max_new_tokens",
        "hit_max_seq_len",
        "terminal_token_id",
        "terminal_step_index",
        "generated_steps",
        "emitted_steps",
    )
    return {key: metadata.get(key) for key in keys}


def _copy_trace(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _terminal_outcome(
    stream_outcome: dict[str, object],
    trace: dict[str, object],
    reset: dict[str, object],
) -> dict[str, object]:
    failures: list[str] = []
    final_metadata = stream_outcome.get("final_metadata")
    if stream_outcome.get("stream_exhausted") is not True:
        failures.append("stream_not_exhausted")
    if stream_outcome.get("safety_truncated") is not False:
        failures.append("safety_truncated")
    if not isinstance(final_metadata, dict):
        failures.append("missing_final_metadata")
        final_metadata = {}
    if final_metadata.get("is_final") is not True:
        failures.append("final_chunk_not_marked")
    if final_metadata.get("termination_reason") != "eos":
        failures.append("terminal_reason_not_eos")
    if final_metadata.get("hit_eos") is not True:
        failures.append("terminal_eos_not_confirmed")
    if final_metadata.get("hit_max_new_tokens") is not False:
        failures.append("terminal_hit_max_new_tokens")
    if final_metadata.get("hit_max_seq_len") is not False:
        failures.append("terminal_hit_max_seq_len")

    generated_codec_sha256 = trace.get("generated_codec_sha256")
    generated_codec_frame_count = trace.get("generated_codec_frame_count")
    trace_complete = (
        trace.get("trace_kind") == "voice_clone_streaming_v1"
        and isinstance(generated_codec_sha256, str)
        and bool(generated_codec_sha256)
        and isinstance(generated_codec_frame_count, int)
        and generated_codec_frame_count > 0
    )
    if not trace_complete:
        failures.append("generation_trace_incomplete")

    trace_consistent = _trace_matches_terminal_metadata(final_metadata, trace)
    if not trace_consistent:
        failures.append("generation_trace_inconsistent")

    predictor_graphs_reset = reset.get("predictor_graphs_reset")
    diagnostic_reset_state = reset.get("diagnostic_reset_state")
    talker_cache_length: object = None
    predictor_cache_lengths: object = None
    if isinstance(diagnostic_reset_state, dict):
        talker_cache_length = diagnostic_reset_state.get(
            "talker_static_cache_sequence_length"
        )
        predictor_cache_lengths = diagnostic_reset_state.get(
            "predictor_static_cache_sequence_lengths"
        )
    cache_lengths_reset = (
        talker_cache_length == 0
        and isinstance(predictor_cache_lengths, list)
        and bool(predictor_cache_lengths)
        and all(length == 0 for length in predictor_cache_lengths)
    )
    reset_passed = (
        reset.get("talker_graph_reset") is True
        and isinstance(predictor_graphs_reset, int)
        and predictor_graphs_reset > 0
        and cache_lengths_reset
    )
    if not reset_passed:
        failures.append("generation_reset_incomplete")

    return {
        "status": "completed" if not failures else "failed",
        "passed": not failures,
        "failures": failures,
        "stream_exhausted": stream_outcome.get("stream_exhausted") is True,
        "safety_truncated": stream_outcome.get("safety_truncated") is True,
        "final_metadata": final_metadata,
        "trace_complete": trace_complete,
        "trace_consistent": trace_consistent,
        "reset_passed": reset_passed,
        "cache_lengths_reset": cache_lengths_reset,
    }


def _trace_matches_terminal_metadata(
    final_metadata: dict[str, object],
    trace: dict[str, object],
) -> bool:
    for field in (
        "terminal_step_index",
        "generated_steps",
        "emitted_steps",
        "hit_eos",
        "hit_max_new_tokens",
        "hit_max_seq_len",
    ):
        if final_metadata.get(field) != trace.get(field):
            return False
    trace_frames = trace.get("generated_codec_frame_count")
    emitted_steps = trace.get("emitted_steps")
    return (
        isinstance(trace_frames, int)
        and trace_frames > 0
        and trace_frames == emitted_steps
    )


def _experiment_contract(
    *,
    args: argparse.Namespace,
    torch: Any,
    model_manifest: dict[str, object],
    python_runtime_manifest: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "runner": {
            "sha256": _sha256_file(Path(__file__).resolve()),
        },
        "model_runtime_manifest": {
            "directory_manifest_sha256": model_manifest.get(
                "directory_manifest_sha256"
            ),
            "repository": model_manifest.get("repository"),
            "revision": model_manifest.get("revision"),
        },
        "faster_source": _git_source_metadata(Path(args.faster_source)),
        "bridge_source": _git_source_metadata(Path(__file__).resolve().parents[1]),
        "runtime": _runtime_metadata(torch),
        "python_runtime_manifest": {
            "installed_distributions_manifest_sha256": python_runtime_manifest.get(
                "installed_distributions_manifest_sha256"
            ),
        },
    }


def _experiment_locations(
    *,
    args: argparse.Namespace,
    model_manifest_path: Path,
    python_runtime_manifest_path: Path,
) -> dict[str, object]:
    return {
        "runner_path": str(Path(__file__).resolve()),
        "model_path": str(Path(args.model_path).resolve()),
        "model_runtime_manifest_path": str(model_manifest_path),
        "python_runtime_manifest_path": str(python_runtime_manifest_path),
        "faster_source_path": str(Path(args.faster_source).resolve()),
        "bridge_source_path": str(Path(__file__).resolve().parents[1]),
    }


def _verify_model_runtime_manifest(
    model_path: Path,
    manifest: dict[str, object],
) -> None:
    from model_runtime_manifest import verify_manifest

    verify_manifest(model_path, manifest)


def _verify_python_runtime_manifest(manifest: dict[str, object]) -> None:
    from python_runtime_manifest import verify_manifest

    verify_manifest(manifest)


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _git_source_metadata(source_path: Path) -> dict[str, object]:
    source_path = source_path.resolve()
    status = _git_command(source_path, "status", "--porcelain")
    return {
        "commit": _git_command(source_path, "rev-parse", "HEAD"),
        "tree": _git_command(source_path, "rev-parse", "HEAD^{tree}"),
        "dirty": bool(status),
        "status_sha256": _sha256(status.encode("utf-8")),
        "module_bundle_sha256": _source_bundle_sha256(source_path),
    }


def _runtime_metadata(torch: Any) -> dict[str, object]:
    gpu = torch.cuda.get_device_properties(0) if torch.cuda.is_available() else None
    return {
        "python": sys.version,
        "torch": str(torch.__version__),
        "cuda_runtime": str(torch.version.cuda),
        "triton": _module_version("triton"),
        "nvidia_driver_version": _nvidia_driver_version(),
        "gpu_name": getattr(gpu, "name", None),
        "gpu_capability": list(torch.cuda.get_device_capability(0)) if gpu else None,
        "gpu_total_memory_bytes": getattr(gpu, "total_memory", None),
    }


def _git_command(source_path: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(source_path), *args], text=True, encoding="utf-8"
    ).strip()


def _profile_metadata(profile: Any) -> dict[str, object]:
    audio = profile.reference_audio
    return {
        "voice_id": profile.voice_id,
        "reference_audio_sha256": audio.sha256,
        "reference_audio_duration_seconds": audio.duration_seconds,
        "reference_text_repr": repr(profile.reference_text),
        "reference_text_sha256": _sha256(profile.reference_text.encode("utf-8")),
        "x_vector_only": profile.x_vector_only,
    }


def _module_version(name: str) -> str:
    try:
        module = __import__(name)
    except ModuleNotFoundError:
        return ""
    return str(getattr(module, "__version__", ""))


def _nvidia_driver_version() -> str:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def _source_bundle_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    tracked_files = _git_command(root, "ls-files", "-z", "--", "*.py")
    for relative_path in sorted(filter(None, tracked_files.split("\0"))):
        path = root / relative_path
        if not path.is_file():
            raise ValueError(f"tracked Python source file is missing: {path}")
        relative = relative_path.replace("\\", "/").encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
