"""Split faster-qwen3-tts streaming into raw-code and codec-decode phases."""

from __future__ import annotations

import argparse
import hashlib
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
    model = FasterQwen3TTS.from_pretrained(
        args.model,
        device=args.device,
        dtype=_torch_dtype(args.dtype),
        attn_implementation=args.attn_implementation,
        max_seq_len=args.max_seq_len,
        local_files_only=args.local_files_only,
    )

    warmup_started = time.perf_counter()
    model.generate_voice_clone(
        text=args.text[: args.warmup_text_chars],
        language=args.language,
        ref_audio=args.ref_audio,
        ref_text=args.ref_text,
        max_new_tokens=args.warmup_max_new_tokens,
    )
    _sync_cuda()
    warmup_s = time.perf_counter() - warmup_started

    rows: list[dict[str, Any]] = []
    for run_index in range(args.runs):
        if args.seed is not None:
            _seed_everything(args.seed + run_index)
        rows.append(_run_once(model, args, run_index=run_index))

    report = {
        "model": args.model,
        "runtime": _runtime_info(),
        "settings": vars(args),
        "warmup_s": warmup_s,
        "summary": _summarize_runs(rows),
        "rows": rows,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
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
    parser.add_argument("--runs", type=int, default=5)
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
        default="tmp/faster-codec-split.json",
    )
    return parser


def _run_once(model: FasterQwen3TTS, args: argparse.Namespace, *, run_index: int) -> dict[str, Any]:
    prepared_started = time.perf_counter()
    (
        wrapped_model,
        talker,
        config,
        talker_input_embeds,
        attention_mask,
        trailing_text_hiddens,
        tts_pad_embed,
        ref_codes,
    ) = model._prepare_generation(
        text=args.text,
        language=args.language,
        ref_audio=args.ref_audio,
        ref_text=args.ref_text,
        xvec_only=args.x_vector_only,
        non_streaming_mode=args.non_streaming_mode,
    )
    _sync_cuda()
    prepare_ms = (time.perf_counter() - prepared_started) * 1000.0

    from faster_qwen3_tts.streaming import fast_generate_streaming, parity_generate_streaming

    stream_fn = parity_generate_streaming if args.parity_mode else fast_generate_streaming
    stream_kwargs = {
        "talker": talker,
        "talker_input_embeds": talker_input_embeds,
        "attention_mask": attention_mask,
        "trailing_text_hiddens": trailing_text_hiddens,
        "tts_pad_embed": tts_pad_embed,
        "config": config,
        "chunk_size": args.chunk_size,
    }
    if not args.parity_mode:
        stream_kwargs["predictor_graph"] = model.predictor_graph
        stream_kwargs["talker_graph"] = model.talker_graph

    raw_rows: list[dict[str, Any]] = []
    codec_chunks: list[torch.Tensor] = []
    raw_started = time.perf_counter()
    for codec_chunk, timing in stream_fn(**stream_kwargs):
        codec_chunks.append(codec_chunk)
        raw_rows.append(
            {
                "chunk": int(timing.get("chunk_index", len(raw_rows))),
                "chunk_steps": int(timing.get("chunk_steps", codec_chunk.shape[0])),
                "prefill_ms": float(timing.get("prefill_ms", 0.0)),
                "ar_decode_ms": float(timing.get("decode_ms", 0.0)),
                "is_final": bool(timing.get("is_final", False)),
            }
        )
    _sync_cuda()
    raw_wall_ms = (time.perf_counter() - raw_started) * 1000.0

    decode_result = _decode_like_wrapper(
        speech_tokenizer=wrapped_model.speech_tokenizer,
        codec_chunks=codec_chunks,
        ref_codes=ref_codes,
    )

    total_steps = sum(row["chunk_steps"] for row in raw_rows)
    audio_s_from_steps_12hz = total_steps / 12.0
    audio_s_from_steps_12_5hz = total_steps / 12.5
    waveform_audio_s = float(decode_result["codec_audio_s"])
    return {
        "run": run_index,
        "prepare_ms": prepare_ms,
        "raw_wall_ms": raw_wall_ms,
        "raw_prefill_ms": sum(row["prefill_ms"] for row in raw_rows),
        "raw_ar_decode_ms": sum(row["ar_decode_ms"] for row in raw_rows),
        "raw_chunks": len(codec_chunks),
        "raw_steps": total_steps,
        "codec_sha256": _codec_sha256(codec_chunks),
        "step_estimated_audio_s_12hz": audio_s_from_steps_12hz,
        "step_estimated_audio_s_12_5hz": audio_s_from_steps_12_5hz,
        "raw_inverse_rtf_waveform": waveform_audio_s / (raw_wall_ms / 1000.0)
        if raw_wall_ms > 0
        else 0.0,
        "raw_local_rtf_waveform": (raw_wall_ms / 1000.0) / waveform_audio_s
        if waveform_audio_s > 0
        else 0.0,
        "raw_inverse_rtf_steps_12_5hz": audio_s_from_steps_12_5hz / (raw_wall_ms / 1000.0)
        if raw_wall_ms > 0
        else 0.0,
        "raw_local_rtf_steps_12_5hz": (raw_wall_ms / 1000.0) / audio_s_from_steps_12_5hz
        if audio_s_from_steps_12_5hz > 0
        else 0.0,
        **decode_result,
        "chunk_rows": raw_rows,
    }


def _decode_like_wrapper(
    *,
    speech_tokenizer: Any,
    codec_chunks: list[torch.Tensor],
    ref_codes: torch.Tensor | None,
) -> dict[str, Any]:
    context_frames = 25
    min_calibration_frames = max(context_frames, codec_chunks[0].shape[0] if codec_chunks else 0)
    all_codes: list[torch.Tensor] = []
    prev_gen_audio_len = 0
    samples_per_frame: float | None = None
    sample_rate = 24000
    decode_rows: list[dict[str, Any]] = []
    total_audio_samples = 0

    for chunk_index, codec_chunk in enumerate(codec_chunks):
        all_codes.append(codec_chunk)
        n_new = codec_chunk.shape[0]
        all_flat = torch.cat(all_codes, dim=0)
        n_total = all_flat.shape[0]

        decode_started = time.perf_counter()
        if samples_per_frame is None:
            if ref_codes is not None:
                codes_input = torch.cat([ref_codes.to(all_flat.device), all_flat], dim=0)
            else:
                codes_input = all_flat
            audio_list, sample_rate = speech_tokenizer.decode(
                {"audio_codes": codes_input.unsqueeze(0)}
            )
            audio = audio_list[0]
            if hasattr(audio, "cpu"):
                audio = audio.flatten().cpu().numpy()
            else:
                audio = audio.flatten() if hasattr(audio, "flatten") else audio

            if ref_codes is not None:
                ref_len = ref_codes.shape[0]
                total_len = codes_input.shape[0]
                ref_audio_cut = int(ref_len / max(total_len, 1) * len(audio))
                gen_audio = audio[ref_audio_cut:]
            else:
                gen_audio = audio
            new_audio = gen_audio[prev_gen_audio_len:]
            prev_gen_audio_len = len(gen_audio)
            if n_total >= min_calibration_frames:
                samples_per_frame = len(gen_audio) / n_total
            phase = "accumulated"
        else:
            ctx_start = max(0, n_total - n_new - context_frames)
            window = all_flat[ctx_start:]
            n_ctx = window.shape[0] - n_new
            audio_list, sample_rate = speech_tokenizer.decode(
                {"audio_codes": window.unsqueeze(0)}
            )
            audio = audio_list[0]
            if hasattr(audio, "cpu"):
                audio = audio.flatten().cpu().numpy()
            else:
                audio = audio.flatten() if hasattr(audio, "flatten") else audio

            if n_ctx > 0:
                ctx_samples = int(round(n_ctx * samples_per_frame))
                new_audio = audio[ctx_samples:]
            else:
                new_audio = audio
            phase = "sliding"
        _sync_cuda()
        decode_ms = (time.perf_counter() - decode_started) * 1000.0
        audio_samples = int(np.asarray(new_audio).shape[-1])
        total_audio_samples += audio_samples
        decode_rows.append(
            {
                "chunk": chunk_index,
                "phase": phase,
                "decode_wall_ms": decode_ms,
                "audio_ms": 1000.0 * audio_samples / sample_rate,
                "audio_samples": audio_samples,
            }
        )

    decode_wall_ms = sum(row["decode_wall_ms"] for row in decode_rows)
    audio_s = total_audio_samples / sample_rate if sample_rate else 0.0
    return {
        "codec_decode_wall_ms": decode_wall_ms,
        "codec_audio_s": audio_s,
        "codec_inverse_rtf": audio_s / (decode_wall_ms / 1000.0)
        if decode_wall_ms > 0
        else 0.0,
        "codec_local_rtf": (decode_wall_ms / 1000.0) / audio_s if audio_s > 0 else 0.0,
        "codec_rows": decode_rows,
    }


def _summarize_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "prepare_ms",
        "raw_wall_ms",
        "raw_ar_decode_ms",
        "raw_inverse_rtf_waveform",
        "raw_inverse_rtf_steps_12_5hz",
        "codec_decode_wall_ms",
        "codec_inverse_rtf",
    )
    return {key: _stats([float(row[key]) for row in rows]) for key in keys}


def _codec_sha256(codec_chunks: list[torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for chunk in codec_chunks:
        array = chunk.detach().cpu().contiguous().numpy()
        digest.update(array.tobytes())
    return digest.hexdigest()


def _stats(values: list[float]) -> dict[str, float]:
    return {
        "median": statistics.median(values),
        "p95": _percentile(values, 95.0),
    }


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
