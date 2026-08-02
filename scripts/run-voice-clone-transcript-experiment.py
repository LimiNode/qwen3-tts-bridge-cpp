"""Compare Base ICL behavior for punctuation and trailing-space transcripts."""

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

DEFAULT_TARGET_TEXT = (
    "\u042f \u0442\u0432\u043e\u0439 \u0440\u043e\u0431\u043e\u0442, "
    "\u044f \u0442\u0432\u043e\u0439 \u0440\u0430\u0431\u043e\u0442\u043d\u0438\u043a."
)
DEFAULT_REFERENCE_TEXT = (
    "\u042f \u0442\u0432\u043e\u0439 \u0441\u043b\u0443\u0433\u0430, "
    "\u044f \u0442\u0432\u043e\u0439 \u0440\u0430\u0431\u043e\u0442\u043d\u0438\u043a"
)


def main() -> int:
    args = _build_parser().parse_args()
    faster_source = Path(args.faster_source).resolve()
    if str(faster_source) not in sys.path:
        sys.path.insert(0, str(faster_source))

    import numpy as np
    import torch
    from faster_qwen3_tts import FasterQwen3TTS

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    model = FasterQwen3TTS.from_pretrained(
        args.model_path,
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
    )
    model.collect_generation_trace = True
    _sync_cuda(torch)

    warmup_started = time.perf_counter()
    if args.warmup:
        model.warmup()
        _sync_cuda(torch)
    warmup_ms = round((time.perf_counter() - warmup_started) * 1000.0, 3)

    variants = _variants(args.reference_text)
    results: list[dict[str, object]] = []
    for index, (label, reference_text) in enumerate(variants, start=1):
        _seed(args.seed, np, torch)
        started = time.perf_counter()
        stream = model.generate_voice_clone_streaming(
            text=args.target_text,
            language="Russian",
            ref_audio=args.reference_audio,
            ref_text=reference_text,
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
        output_path = output_dir / f"{index:02d}-{label}.wav"
        _write_wav(output_path, pcm, sample_rate)
        results.append(
            {
                "label": label,
                "reference_text": reference_text,
                "reference_text_repr": repr(reference_text),
                "reference_text_sha256": _sha256(reference_text.encode("utf-8")),
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "pcm_sha256": _sha256(pcm),
                "pcm_bytes": len(pcm),
                "output_wav": str(output_path),
                "reset": reset,
            }
        )

    summary = {
        "schema_version": 1,
        "purpose": "ICL reference transcript whitespace experiment",
        "reference_audio": str(Path(args.reference_audio).resolve()),
        "reference_audio_sha256": _sha256_file(Path(args.reference_audio)),
        "target_text": args.target_text,
        "seed": args.seed,
        "warmup": {"enabled": args.warmup, "duration_ms": warmup_ms},
        "sampling": {
            "temperature": args.temperature,
            "top_k": args.top_k,
            "top_p": args.top_p,
            "repetition_penalty": args.repetition_penalty,
        },
        "results": results,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--faster-source", required=True)
    parser.add_argument("--reference-audio", required=True)
    parser.add_argument("--output-dir", default="tmp/voice-clone-transcript-test")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument("--reference-text", default=DEFAULT_REFERENCE_TEXT)
    parser.add_argument("--target-text", default=DEFAULT_TARGET_TEXT)
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--temperature", type=float, default=0.45)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--repetition-penalty", type=float, default=1.05)
    parser.add_argument("--chunk-frames", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument(
        "--warmup",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser


def _variants(reference_text: str) -> tuple[tuple[str, str], ...]:
    base = reference_text.rstrip(" .")
    return (
        ("exact", base),
        ("period", base + "."),
        ("period-one-space", base + ". "),
        ("period-four-spaces", base + ".    "),
    )


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
