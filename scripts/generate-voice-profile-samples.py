"""Generate a small, seed-matched listening set for registered Base profiles."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
import wave
from pathlib import Path
from typing import Any, Iterable

DEFAULT_VOICE_IDS = (
    "kraftwerk_robot_ru_icl_period",
    "kraftwerk_robot_ru_icl_period_space",
    "kraftwerk_robot_ru_icl_period_four_spaces",
)
DEFAULT_TEXTS = (
    "\u042f \u0442\u0432\u043e\u0439 \u0440\u043e\u0431\u043e\u0442, "
    "\u044f \u0442\u0432\u043e\u0439 \u0440\u0430\u0431\u043e\u0442\u043d\u0438\u043a.",
    "\u0421\u0438\u0441\u0442\u0435\u043c\u0430 \u0433\u043e\u0442\u043e\u0432\u0430 "
    "\u043a \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0439 \u043a\u043e\u043c\u0430\u043d\u0434\u0435.",
    "\u0412\u043d\u0438\u043c\u0430\u043d\u0438\u0435: \u043c\u043e\u0434\u0443\u043b\u044c "
    "\u043f\u0435\u0440\u0435\u0445\u043e\u0434\u0438\u0442 \u0432 \u0440\u0435\u0436\u0438\u043c \u043e\u0436\u0438\u0434\u0430\u043d\u0438\u044f.",
    "\u0417\u0430\u0434\u0430\u0447\u0430 \u043f\u0440\u0438\u043d\u044f\u0442\u0430. "
    "\u041d\u0430\u0447\u0438\u043d\u0430\u044e \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443 \u043a\u043e\u043d\u0442\u0443\u0440\u0430.",
    "\u041d\u0435 \u0442\u043e\u0440\u043e\u043f\u0438\u0441\u044c. "
    "\u041f\u043e\u0441\u043b\u0435\u0434\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c "
    "\u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0439 \u0432\u0430\u0436\u043d\u0435\u0435 \u0441\u043a\u043e\u0440\u043e\u0441\u0442\u0438.",
    "\u0414\u0430\u043d\u043d\u044b\u0435 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u044b. "
    "\u041c\u043e\u0436\u043d\u043e \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0442\u044c \u0440\u0430\u0431\u043e\u0442\u0443.",
    "\u0421\u0438\u0433\u043d\u0430\u043b \u0443\u0441\u0442\u043e\u0439\u0447\u0438\u0432. "
    "\u0412\u0441\u0435 \u043e\u0441\u043d\u043e\u0432\u043d\u044b\u0435 \u043a\u0430\u043d\u0430\u043b\u044b \u0441\u0432\u044f\u0437\u0438 \u0432 \u043d\u043e\u0440\u043c\u0435.",
    "\u041f\u043e\u0432\u0442\u043e\u0440\u044f\u044e: \u0441\u043d\u0430\u0447\u0430\u043b\u0430 "
    "\u043e\u0441\u043c\u043e\u0442\u0440\u0438\u043c \u043c\u0435\u0445\u0430\u043d\u0438\u0437\u043c, "
    "\u043f\u043e\u0442\u043e\u043c \u043f\u0440\u0438\u043d\u0438\u043c\u0430\u0435\u043c \u0440\u0435\u0448\u0435\u043d\u0438\u0435.",
    "\u0420\u0430\u0441\u0447\u0451\u0442 \u0437\u0430\u043a\u043e\u043d\u0447\u0435\u043d. "
    "\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0451\u043d.",
    "\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u043c\u0441\u044f \u043d\u0430 \u0441\u0435\u043a\u0443\u043d\u0434\u0443. "
    "\u041c\u043d\u0435 \u043d\u0443\u0436\u043d\u043e \u0443\u0442\u043e\u0447\u043d\u0438\u0442\u044c \u043e\u0434\u0438\u043d \u043f\u0430\u0440\u0430\u043c\u0435\u0442\u0440.",
)


def main() -> int:
    args = _build_parser().parse_args()
    _prepend_paths(args)

    import numpy as np
    import torch
    from faster_qwen3_tts import FasterQwen3TTS

    from qwen_tts_bridge_worker.engine.voice_profiles import VoiceProfileRegistry

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    registry = VoiceProfileRegistry.from_json_file(args.voice_registry, 8)
    voice_ids = tuple(args.voice_id) or DEFAULT_VOICE_IDS
    missing = [voice_id for voice_id in voice_ids if not registry.has_voice(voice_id)]
    if missing:
        raise ValueError("voice registry lacks: " + ", ".join(missing))

    model = FasterQwen3TTS.from_pretrained(
        args.model_path,
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
    )
    model.collect_generation_trace = True
    model.warmup()
    _sync_cuda(torch)

    profiles = {
        voice_id: registry.profile_for(voice_id)
        for voice_id in voice_ids
    }
    prompts = {
        voice_id: registry.prompt_for(model, voice_id, policy="shared")
        for voice_id in voice_ids
    }
    results: list[dict[str, object]] = []
    for sample_index, text in enumerate(DEFAULT_TEXTS, start=1):
        for voice_id in voice_ids:
            _seed(args.seed + sample_index, np, torch)
            started = time.perf_counter()
            stream = model.generate_voice_clone_streaming(
                text=text,
                language="Russian",
                voice_clone_prompt=prompts[voice_id],
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
            filename = f"{sample_index:02d}-{voice_id}.wav"
            output_path = output_dir / filename
            _write_wav(output_path, pcm, sample_rate)
            results.append(
                {
                    "sample_index": sample_index,
                    "voice_id": voice_id,
                    "text": text,
                    "seed": args.seed + sample_index,
                    "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "pcm_sha256": _sha256(pcm),
                    "pcm_bytes": len(pcm),
                    "output_wav": str(output_path),
                    "reference_text_repr": repr(profiles[voice_id].reference_text),
                    "reset": reset,
                }
            )

    summary = {
        "schema_version": 1,
        "purpose": "matched listening samples for ICL whitespace profiles",
        "sampling": {
            "temperature": args.temperature,
            "top_k": args.top_k,
            "top_p": args.top_p,
            "repetition_penalty": args.repetition_penalty,
        },
        "voice_ids": voice_ids,
        "results": results,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"generated {len(results)} samples in {output_dir}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--faster-source", required=True)
    parser.add_argument("--voice-registry", required=True)
    parser.add_argument("--output-dir", default="tmp/voice-profile-samples")
    parser.add_argument("--voice-id", action="append", default=[])
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--repetition-penalty", type=float, default=1.05)
    parser.add_argument("--chunk-frames", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=192)
    return parser


def _prepend_paths(args: argparse.Namespace) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for path in reversed((Path(args.faster_source).resolve(), repo_root / "worker" / "src")):
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
    sample_rate = 24000
    chunks: list[bytes] = []
    close = getattr(stream, "close", None)
    try:
        for audio, _sample_rate, _metadata in stream:
            sample_rate = _sample_rate
            samples = np.asarray(audio, dtype=np.float32).reshape(-1)
            pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
            chunks.append(pcm)
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


if __name__ == "__main__":
    raise SystemExit(main())
