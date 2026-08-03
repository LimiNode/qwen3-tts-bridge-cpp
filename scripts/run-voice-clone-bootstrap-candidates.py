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
    _prepend_paths(args)

    import numpy as np
    import torch
    from faster_qwen3_tts import FasterQwen3TTS

    from qwen_tts_bridge_worker.engine.voice_profiles import VoiceProfileRegistry

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    registry = VoiceProfileRegistry.from_json_file(args.voice_registry, len(args.voice_id))
    missing_voice_ids = [voice_id for voice_id in args.voice_id if not registry.has_voice(voice_id)]
    if missing_voice_ids:
        raise ValueError(f"voice registry lacks: {', '.join(missing_voice_ids)}")

    model = FasterQwen3TTS.from_pretrained(
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
            if args.resume and output_path.is_file():
                results.append(_read_existing(output_path, voice_id, seed, args))
            else:
                results.append(
                    _generate_one(
                        model=model,
                        np=np,
                        torch=torch,
                        prompt=prompts[voice_id],
                        output_path=output_path,
                        voice_id=voice_id,
                        seed=seed,
                        args=args,
                    )
                )
            print(
                f"[{voice_id}] {candidate_index + 1} "
                f"seed={seed} duration={results[-1]['audio_duration_ms']} ms "
                f"status={results[-1]['status']}"
            )

    summary = {
        "schema_version": 1,
        "purpose": "synthetic reference bootstrap candidate search",
        "inputs": {
            "model_path": str(Path(args.model_path).resolve()),
            "faster_source": _git_source_metadata(Path(args.faster_source)),
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
    return parser


def _generate_one(
    *,
    model: Any,
    np: Any,
    torch: Any,
    prompt: Any,
    output_path: Path,
    voice_id: str,
    seed: int,
    args: argparse.Namespace,
) -> dict[str, object]:
    _seed(seed, np, torch)
    started = time.perf_counter()
    stream = model.generate_voice_clone_streaming(
        text=args.text,
        language="Russian",
        voice_clone_prompt=prompt,
        chunk_size=args.chunk_frames,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        top_k=args.top_k,
        top_p=args.top_p,
        repetition_penalty=args.repetition_penalty,
        do_sample=True,
    )
    pcm, sample_rate = _consume(stream, np)
    _sync_cuda(torch)
    reset = model.reset_after_partial_generation()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_wav(output_path, pcm, sample_rate)
    return {
        "voice_id": voice_id,
        "seed": seed,
        "text": args.text,
        "temperature": args.temperature,
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "audio_duration_ms": round(len(pcm) / 2 / sample_rate * 1000.0, 3),
        "sample_rate": sample_rate,
        "pcm_sha256": _sha256(pcm),
        "pcm_bytes": len(pcm),
        "output_wav": str(output_path),
        "reset": reset,
        "status": "generated",
    }


def _read_existing(
    output_path: Path,
    voice_id: str,
    seed: int,
    args: argparse.Namespace,
) -> dict[str, object]:
    with wave.open(str(output_path), "rb") as reader:
        if reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise ValueError(f"existing candidate has unexpected PCM format: {output_path}")
        sample_rate = reader.getframerate()
        pcm = reader.readframes(reader.getnframes())
    if not pcm:
        raise ValueError(f"existing candidate is empty: {output_path}")
    return {
        "voice_id": voice_id,
        "seed": seed,
        "text": args.text,
        "temperature": args.temperature,
        "duration_ms": None,
        "audio_duration_ms": round(len(pcm) / 2 / sample_rate * 1000.0, 3),
        "sample_rate": sample_rate,
        "pcm_sha256": _sha256(pcm),
        "pcm_bytes": len(pcm),
        "output_wav": str(output_path),
        "reset": None,
        "status": "existing",
    }


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
) -> tuple[bytes, int]:
    sample_rate = 24_000
    chunks: list[bytes] = []
    close = getattr(stream, "close", None)
    try:
        for audio, sample_rate, _metadata in stream:
            samples = np.asarray(audio, dtype=np.float32).reshape(-1)
            chunks.append(
                (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
            )
    finally:
        if callable(close):
            close()
    return b"".join(chunks), sample_rate


def _write_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)


def _sync_cuda(torch: Any) -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_source_metadata(source_path: Path) -> dict[str, object]:
    source_path = source_path.resolve()
    return {
        "path": str(source_path),
        "commit": _git_command(source_path, "rev-parse", "HEAD"),
        "tree": _git_command(source_path, "rev-parse", "HEAD^{tree}"),
        "dirty": bool(_git_command(source_path, "status", "--porcelain")),
    }


def _git_command(source_path: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(source_path), *args], text=True, encoding="utf-8"
    ).strip()


def _profile_metadata(profile: Any) -> dict[str, object]:
    audio = profile.reference_audio
    return {
        "voice_id": profile.voice_id,
        "reference_audio_path": str(profile.reference_audio_path),
        "reference_audio_sha256": audio.sha256,
        "reference_audio_duration_seconds": audio.duration_seconds,
        "reference_text_repr": repr(profile.reference_text),
        "x_vector_only": profile.x_vector_only,
    }


if __name__ == "__main__":
    raise SystemExit(main())
