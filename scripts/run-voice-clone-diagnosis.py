"""Run a reproducible FasterQwen Base voice-clone diagnostic matrix.

The runner is intentionally offline and diagnostic-only.  It compares direct
Faster calls with the worker-engine profile paths, while retaining PCM and
trace evidence outside the repository by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import threading
import time
import wave
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable, Iterable

DEFAULT_A_TEXT = (
    "\u0422\u0435\u0441\u0442\u043e\u0432\u044b\u0439 "
    "\u0433\u043e\u043b\u043e\u0441."
)
DEFAULT_B_TEXT = (
    "\u0421\u0435\u0433\u043e\u0434\u043d\u044f "
    "\u0441\u0438\u0441\u0442\u0435\u043c\u0430 "
    "\u043e\u0442\u0432\u0435\u0447\u0430\u0435\u0442 "
    "\u0441\u043e\u0432\u0435\u0440\u0448\u0435\u043d\u043d\u043e "
    "\u043d\u043e\u0432\u043e\u0439 \u0444\u0440\u0430\u0437\u043e\u0439."
)
_METHODS = ("raw_direct", "cached_direct", "bridge_shared", "bridge_rebuild")


def main() -> int:
    args = _build_parser().parse_args()
    _prepend_import_paths(args)

    import numpy as np
    import torch

    from qwen_tts_bridge_worker.config import QwenEngineConfig
    from qwen_tts_bridge_worker.engine.qwen_engine import (
        QwenTtsEngine,
        _seed_runtime,
    )
    from qwen_tts_bridge_worker.engine.types import SynthesisRequest
    from qwen_tts_bridge_worker.engine.voice_profiles import VoiceProfileRegistry

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    registry_path = Path(args.voice_registry).resolve()
    registry = VoiceProfileRegistry.from_json_file(registry_path, 8)
    profile_ids = _profile_ids(args, registry)

    config = QwenEngineConfig(
        model_path=str(Path(args.model_path).resolve()),
        runtime_backend="faster",
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
        emit_every_frames=args.chunk_frames,
        max_audio_seconds_per_utterance=args.max_audio_seconds,
        voice_registry_path=str(registry_path),
        voice_prompt_cache_max_entries=8,
        voice_profile_prompt_policy="shared",
        preload_voice_profiles=args.preload_profiles,
        use_compile=False,
        use_cuda_graphs=True,
        do_sample=args.do_sample,
        temperature=args.temperature,
        top_k=args.top_k,
        top_p=args.top_p,
        repetition_penalty=args.repetition_penalty,
        seed=args.seed,
        seed_mode="fixed",
        collect_generation_trace=True,
    )
    engine = QwenTtsEngine(config)
    loaded_started = time.perf_counter()
    engine.load()
    model = engine._require_model()  # The runner intentionally compares this model.
    _sync_cuda(torch)
    loaded_ms = _milliseconds(loaded_started)

    baseline = _runtime_baseline(
        args=args,
        torch=torch,
        registry_path=registry_path,
        registry=registry,
        profile_ids=profile_ids,
        loaded_ms=loaded_ms,
    )
    _write_json(output_dir / "runtime-baseline.json", baseline)

    warmup_metadata: dict[str, Any] = {"enabled": False}
    if args.warmup:
        warmup_started = time.perf_counter()
        model_warmup = getattr(model, "warmup", None)
        if callable(model_warmup):
            model_warmup()
        engine_warmup = engine.warmup() or {}
        _sync_cuda(torch)
        warmup_metadata = {
            "enabled": True,
            "duration_ms": round(_milliseconds(warmup_started), 3),
            "preload_profiles": args.preload_profiles,
            "engine_details": engine_warmup,
        }
    _write_json(output_dir / "warmup.json", warmup_metadata)

    records: list[dict[str, Any]] = []
    request_id = 1
    try:
        for profile_id in profile_ids:
            profile = registry.profile_for(profile_id)
            cached_prompt = registry.prompt_for(model, profile_id, policy="shared")
            for method in args.method or _METHODS:
                for sequence_name, texts in _sequences(args.a_text, args.b_text):
                    for sequence_index, text in enumerate(texts, start=1):
                        label = (
                            f"{profile_id}-{method}-{sequence_name}-{sequence_index:02d}"
                        )
                        request_id, record = _run_one(
                            method=method,
                            label=label,
                            text=text,
                            profile=profile,
                            cached_prompt=cached_prompt,
                            engine=engine,
                            model=model,
                            request_id=request_id,
                            args=args,
                            np=np,
                            torch=torch,
                            seed_runtime=_seed_runtime,
                            request_type=SynthesisRequest,
                            output_dir=output_dir,
                        )
                        record["profile_id"] = profile_id
                        record["sequence"] = sequence_name
                        record["sequence_index"] = sequence_index
                        records.append(record)
    finally:
        engine.close()

    summary = {
        "schema_version": 1,
        "purpose": "voice-clone ICL/x-vector cache and reset diagnosis",
        "baseline": baseline,
        "warmup": warmup_metadata,
        "records": records,
        "comparisons": _comparisons(records),
    }
    _write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary["comparisons"], ensure_ascii=False, indent=2))
    print(f"diagnosis evidence: {output_dir}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--faster-source", required=True)
    parser.add_argument("--voice-registry", required=True)
    parser.add_argument("--output-dir", default="tmp/voice-clone-diagnosis")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument("--icl-voice-id", default="kraftwerk_robot_ru")
    parser.add_argument("--xvector-voice-id", default="kraftwerk_robot_ru_xvector")
    parser.add_argument(
        "--profile-id",
        action="append",
        default=[],
        help="Restrict the run to one or more registered profiles.",
    )
    parser.add_argument("--a-text", default=DEFAULT_A_TEXT)
    parser.add_argument("--b-text", default=DEFAULT_B_TEXT)
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--temperature", type=float, default=0.45)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--repetition-penalty", type=float, default=1.05)
    parser.add_argument(
        "--do-sample",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--warmup",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--preload-profiles", action="store_true")
    parser.add_argument("--chunk-frames", type=int, default=8)
    parser.add_argument("--max-audio-seconds", type=float, default=30.0)
    parser.add_argument("--method", choices=_METHODS, action="append", default=[])
    return parser


def _prepend_import_paths(args: argparse.Namespace) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    paths = (Path(args.faster_source).resolve(), repo_root / "worker" / "src")
    for path in reversed(paths):
        path_text = str(path)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)


def _profile_ids(args: argparse.Namespace, registry: Any) -> tuple[str, ...]:
    requested = tuple(args.profile_id) or (args.icl_voice_id, args.xvector_voice_id)
    missing = [voice_id for voice_id in requested if not registry.has_voice(voice_id)]
    if missing:
        raise ValueError(
            "voice registry lacks required profiles: " + ", ".join(missing)
        )
    return requested


def _sequences(a_text: str, b_text: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        ("A", (a_text,)),
        ("A-A-A", (a_text, a_text, a_text)),
        ("A-B-A", (a_text, b_text, a_text)),
    )


def _run_one(
    *,
    method: str,
    label: str,
    text: str,
    profile: Any,
    cached_prompt: Any,
    engine: Any,
    model: Any,
    request_id: int,
    args: argparse.Namespace,
    np: Any,
    torch: Any,
    seed_runtime: Callable[..., None],
    request_type: Any,
    output_dir: Path,
) -> tuple[int, dict[str, Any]]:
    if method in {"raw_direct", "cached_direct"}:
        seed_runtime(
            args.seed,
            strict=True,
            require_cuda=args.device.startswith("cuda"),
        )
        kwargs = {
            "text": text,
            "language": "Russian",
            "chunk_size": args.chunk_frames,
            "temperature": args.temperature,
            "top_k": args.top_k,
            "top_p": args.top_p,
            "do_sample": args.do_sample,
            "repetition_penalty": args.repetition_penalty,
        }
        if method == "raw_direct":
            kwargs.update(
                ref_audio=str(profile.reference_audio_path),
                ref_text=profile.reference_text,
                xvec_only=profile.x_vector_only,
            )
        else:
            kwargs["voice_clone_prompt"] = cached_prompt
        started = time.perf_counter()
        pcm, sample_rate, chunks, safety_truncated = _consume_direct(
            model.generate_voice_clone_streaming(**kwargs),
            np,
            args.max_audio_seconds,
        )
        _sync_cuda(torch)
        reset = model.reset_after_partial_generation()
        trace = _copy_trace(model.last_generation_trace)
        trace["bridge_reset_after_generation"] = reset
        duration_ms = _milliseconds(started)
    else:
        policy = "shared" if method == "bridge_shared" else "rebuild_per_request"
        engine._config = replace(
            engine._config,
            voice_profile_prompt_policy=policy,
        )
        request = request_type(
            request_id=request_id,
            text=text,
            language="Russian",
            voice_id=profile.voice_id,
            seed=args.seed,
        )
        started = time.perf_counter()
        chunks = list(engine.synthesize_stream(request, threading.Event()))
        _sync_cuda(torch)
        pcm = b"".join(chunks)
        sample_rate = 24000
        trace = engine.pop_last_generation_trace() or {}
        duration_ms = _milliseconds(started)
        safety_truncated = False

    output_path = output_dir / "pcm" / f"{label}.wav"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_pcm_wav(output_path, pcm, sample_rate)
    record = {
        "label": label,
        "method": method,
        "text": text,
        "duration_ms": round(duration_ms, 3),
        "sample_rate": sample_rate,
        "chunk_count": len(chunks),
        "pcm_bytes": len(pcm),
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
        "pcm_prefix_sha256": hashlib.sha256(pcm[: 24000 * 2 * 2]).hexdigest(),
        "safety_truncated": safety_truncated,
        "output_wav": str(output_path),
        "trace": trace,
    }
    return request_id + 1, record


def _consume_direct(
    stream: Iterable[tuple[Any, int, dict[str, Any]]],
    np: Any,
    max_audio_seconds: float,
) -> tuple[bytes, int, list[bytes], bool]:
    sample_rate = 24000
    chunks: list[bytes] = []
    safety_truncated = False
    close = getattr(stream, "close", None)
    try:
        for audio, _sample_rate, _metadata in stream:
            sample_rate = _sample_rate
            chunk = _float_to_s16le(audio, np)
            max_bytes = int(max_audio_seconds * sample_rate * 2)
            remaining = max_bytes - sum(len(item) for item in chunks)
            if remaining <= 0:
                safety_truncated = True
                break
            if len(chunk) > remaining:
                chunks.append(chunk[: remaining - (remaining % 2)])
                safety_truncated = True
                break
            chunks.append(chunk)
    finally:
        if callable(close):
            close()
    return b"".join(chunks), sample_rate, chunks, safety_truncated


def _float_to_s16le(audio: Any, np: Any) -> bytes:
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    samples = np.clip(samples, -1.0, 1.0)
    return (samples * 32767.0).astype("<i2").tobytes()


def _write_pcm_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)


def _runtime_baseline(
    *,
    args: argparse.Namespace,
    torch: Any,
    registry_path: Path,
    registry: Any,
    profile_ids: tuple[str, ...],
    loaded_ms: float,
) -> dict[str, Any]:
    faster_source = Path(args.faster_source).resolve()
    profiles = []
    for voice_id in profile_ids:
        profile = registry.profile_for(voice_id)
        profiles.append(
            {
                "voice_id": voice_id,
                "x_vector_only": profile.x_vector_only,
                "reference_text_sha256": hashlib.sha256(
                    profile.reference_text.encode("utf-8")
                ).hexdigest(),
                "reference_audio": {
                    **asdict(profile.reference_audio),
                    "path": str(profile.reference_audio.path),
                },
            }
        )
    gpu = torch.cuda.get_device_properties(0) if torch.cuda.is_available() else None
    return {
        "schema_version": 1,
        "bridge_commit": _git(
            Path(__file__).resolve().parents[1],
            "rev-parse",
            "--verify",
            "HEAD^{commit}",
        ),
        "faster_source": {
            "path": str(faster_source),
            "commit": _git(faster_source, "rev-parse", "HEAD"),
            "tree": _git(faster_source, "rev-parse", "HEAD^{tree}"),
            "status": _git(faster_source, "status", "--porcelain"),
            "remote": _git(faster_source, "remote", "get-url", "fork"),
            "module_bundle_sha256": _source_bundle_sha256(faster_source),
        },
        "runtime": {
            "python": sys.version,
            "torch": str(torch.__version__),
            "cuda_runtime": str(torch.version.cuda),
            "triton": _module_version("triton"),
            "nvidia_driver_version": _nvidia_driver_version(),
            "gpu_name": getattr(gpu, "name", None),
            "gpu_capability": (
                list(torch.cuda.get_device_capability(0)) if gpu else None
            ),
            "gpu_total_memory_bytes": getattr(gpu, "total_memory", None),
            "loaded_ms": round(loaded_ms, 3),
        },
        "registry_path": str(registry_path),
        "registry_sha256": _sha256_file(registry_path),
        "profiles": profiles,
        "sampling": {
            "seed": args.seed,
            "temperature": args.temperature,
            "top_k": args.top_k,
            "top_p": args.top_p,
            "repetition_penalty": args.repetition_penalty,
            "do_sample": args.do_sample,
        },
    }


def _comparisons(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (record["profile_id"], record["method"], record["sequence"])
        grouped.setdefault(key, []).append(record)
    return [
        {
            "profile_id": profile_id,
            "method": method,
            "sequence": sequence,
            "pcm_sha256": [record["pcm_sha256"] for record in values],
            "all_pcm_identical": len({record["pcm_sha256"] for record in values}) == 1,
            "prompt_sha256": [
                record["trace"].get("voice_clone_prompt_sha256_before")
                for record in values
            ],
            "generated_codec_sha256": [
                record["trace"].get("generated_codec_sha256") for record in values
            ],
        }
        for (profile_id, method, sequence), values in grouped.items()
    ]


def _copy_trace(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _sync_cuda(torch: Any) -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def _milliseconds(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _git(directory: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


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
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
