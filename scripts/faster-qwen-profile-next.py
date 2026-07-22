"""Profile each pull from faster-qwen3-tts streaming generators."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from faster_qwen3_tts import FasterQwen3TTS


TEXT = (
    "Ladies and gentlemen, I have just been informed that this speech is being "
    "generated faster than I can speak it. The robots have officially won. "
    "Please remain calm."
)
REF_TEXT = (
    "I'm confused why some people have super short timelines, yet at the same "
    "time are bullish on scaling up reinforcement learning atop LLMs. If we're "
    "actually close to a human-like learner, then this whole approach of "
    "training on verifiable outcomes."
)


def main() -> int:
    args = _build_parser().parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    torch.set_float32_matmul_precision(args.matmul_precision)

    started = time.perf_counter()
    model = FasterQwen3TTS.from_pretrained(
        args.model,
        device=args.device,
        dtype=_torch_dtype(args.dtype),
        attn_implementation=args.attn_implementation,
        max_seq_len=args.max_seq_len,
        local_files_only=args.local_files_only,
    )
    _sync_cuda()
    load_s = time.perf_counter() - started

    warmup_started = time.perf_counter()
    audio_list, sample_rate = model.generate_voice_clone(
        text=args.text[: args.warmup_text_chars],
        language=args.language,
        ref_audio=args.ref_audio,
        ref_text=args.ref_text,
        max_new_tokens=args.warmup_max_new_tokens,
    )
    _sync_cuda()
    warmup_s = time.perf_counter() - warmup_started
    warmup_audio_s = len(audio_list[0]) / sample_rate if audio_list else 0.0

    rows: list[dict[str, Any]] = []
    for run_index in range(args.runs):
        if args.seed is not None:
            _seed_everything(args.seed + run_index)
        rows.extend(
            _profile_stream(
                model,
                run_index=run_index,
                text=args.text,
                language=args.language,
                ref_audio=args.ref_audio,
                ref_text=args.ref_text,
                chunk_size=args.chunk_size,
                xvec_only=args.x_vector_only,
                parity_mode=args.parity_mode,
                non_streaming_mode=args.non_streaming_mode,
            )
        )

    report = {
        "model": args.model,
        "runtime": _runtime_info(),
        "settings": vars(args),
        "load_s": load_s,
        "warmup_s": warmup_s,
        "warmup_audio_s": warmup_audio_s,
        "chunk_summary": _summarize_by_chunk(rows),
        "position_summary": _summarize_positions(rows),
        "rows": rows,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["chunk_summary"], ensure_ascii=False, indent=2))
    print(json.dumps(report["position_summary"], ensure_ascii=False, indent=2))
    print(f"wrote {output}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen3-TTS-12Hz-1.7B-Base")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="eager")
    parser.add_argument("--matmul-precision", default="high")
    parser.add_argument("--max-seq-len", type=int, default=2048)
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--text", default=TEXT)
    parser.add_argument("--language", default="English")
    parser.add_argument("--ref-audio", default="ref_audio.wav")
    parser.add_argument("--ref-text", default=REF_TEXT)
    parser.add_argument("--warmup-text-chars", type=int, default=50)
    parser.add_argument("--warmup-max-new-tokens", type=int, default=20)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--x-vector-only", action="store_true")
    parser.add_argument("--parity-mode", action="store_true")
    parser.add_argument("--non-streaming-mode", action="store_true")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument(
        "--output",
        default="tmp/faster-profile-next.json",
    )
    return parser


def _profile_stream(
    model: FasterQwen3TTS,
    *,
    run_index: int,
    text: str,
    language: str,
    ref_audio: str,
    ref_text: str,
    chunk_size: int,
    xvec_only: bool,
    parity_mode: bool,
    non_streaming_mode: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    generator = model.generate_voice_clone_streaming(
        text=text,
        language=language,
        ref_audio=ref_audio,
        ref_text=ref_text,
        chunk_size=chunk_size,
        xvec_only=xvec_only,
        parity_mode=parity_mode,
        non_streaming_mode=non_streaming_mode,
    )
    previous_end = time.perf_counter()

    try:
        chunk_index = 0
        while True:
            _sync_cuda()
            pull_started = time.perf_counter()
            try:
                audio, sample_rate, timing = next(generator)
            except StopIteration:
                break
            _sync_cuda()
            pull_ended = time.perf_counter()

            wall_ms = (pull_ended - pull_started) * 1000.0
            gap_before_ms = (pull_started - previous_end) * 1000.0
            previous_end = pull_ended
            prefill_ms = float(timing.get("prefill_ms", 0.0))
            ar_decode_ms = float(timing.get("decode_ms", 0.0))
            chunk_steps = int(timing.get("chunk_steps", 0))
            audio_samples = int(audio.shape[-1])
            audio_ms = 1000.0 * audio_samples / float(sample_rate)
            rows.append(
                {
                    "run": run_index,
                    "chunk": chunk_index,
                    "wall_ms": wall_ms,
                    "gap_before_ms": gap_before_ms,
                    "prefill_ms": prefill_ms,
                    "ar_decode_ms": ar_decode_ms,
                    "chunk_steps": chunk_steps,
                    "ar_ms_per_step": ar_decode_ms / chunk_steps if chunk_steps else 0.0,
                    "outside_ms": wall_ms - prefill_ms - ar_decode_ms,
                    "audio_ms": audio_ms,
                    "is_final": bool(timing.get("is_final", False)),
                }
            )
            chunk_index += 1
    finally:
        generator.close()

    return rows


def _summarize_by_chunk(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks = sorted({int(row["chunk"]) for row in rows})
    return [_summarize_subset(rows, chunk=chunk) for chunk in chunks]


def _summarize_positions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = [row for row in rows if row["chunk"] == 0]
    second = [row for row in rows if row["chunk"] == 1]
    steady = [row for row in rows if row["chunk"] >= 2 and not row["is_final"]]
    final = [row for row in rows if row["is_final"]]
    return {
        "first": _summary_stats(first),
        "second": _summary_stats(second),
        "steady": _summary_stats(steady),
        "final": _summary_stats(final),
    }


def _summarize_subset(rows: list[dict[str, Any]], *, chunk: int) -> dict[str, Any]:
    return {"chunk": chunk, **_summary_stats([row for row in rows if row["chunk"] == chunk])}


def _summary_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    keys = (
        "wall_ms",
        "prefill_ms",
        "ar_decode_ms",
        "ar_ms_per_step",
        "outside_ms",
        "audio_ms",
    )
    out: dict[str, Any] = {"count": len(rows)}
    for key in keys:
        values = [float(row[key]) for row in rows]
        out[f"{key}_median"] = statistics.median(values)
        out[f"{key}_p95"] = _percentile(values, 95.0)
    return out


def _percentile(values: list[float], percentile: float) -> float:
    if len(values) == 1:
        return values[0]
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * percentile / 100.0
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = index - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _torch_dtype(name: str) -> Any:
    if name == "bf16":
        return torch.bfloat16
    if name == "fp16":
        return torch.float16
    if name == "fp32":
        return torch.float32
    dtype = getattr(torch, name, None)
    if dtype is None:
        raise ValueError(f"unsupported torch dtype: {name}")
    return dtype


def _sync_cuda() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _runtime_info() -> dict[str, Any]:
    return {
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
    }


if __name__ == "__main__":
    raise SystemExit(main())
