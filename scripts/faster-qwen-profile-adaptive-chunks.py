"""Profile first-small, steady-large decode chunks for faster-qwen3-tts."""

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
        rows.extend(_run_once(model, args, run_index=run_index))

    report = {
        "model": args.model,
        "runtime": _runtime_info(),
        "settings": vars(args),
        "warmup_s": warmup_s,
        "summary": _summarize_positions(rows),
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
    parser.add_argument("--producer-chunk-size", type=int, default=4)
    parser.add_argument("--first-output-steps", type=int, default=4)
    parser.add_argument("--steady-output-steps", type=int, default=8)
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
    parser.add_argument("--output", default="tmp/faster-adaptive-chunks.json")
    return parser


def _run_once(model: FasterQwen3TTS, args: argparse.Namespace, *, run_index: int) -> list[dict[str, Any]]:
    from faster_qwen3_tts.streaming import fast_generate_streaming, parity_generate_streaming

    request_started = time.perf_counter()
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
    prepare_ms = (time.perf_counter() - request_started) * 1000.0

    stream_fn = parity_generate_streaming if args.parity_mode else fast_generate_streaming
    stream_kwargs = {
        "talker": talker,
        "talker_input_embeds": talker_input_embeds,
        "attention_mask": attention_mask,
        "trailing_text_hiddens": trailing_text_hiddens,
        "tts_pad_embed": tts_pad_embed,
        "config": config,
        "chunk_size": args.producer_chunk_size,
    }
    if not args.parity_mode:
        stream_kwargs["predictor_graph"] = model.predictor_graph
        stream_kwargs["talker_graph"] = model.talker_graph

    decoder = _AdaptiveDecoder(
        speech_tokenizer=wrapped_model.speech_tokenizer,
        ref_codes=ref_codes,
        min_calibration_frames=max(25, args.steady_output_steps),
    )
    rows: list[dict[str, Any]] = []
    pending: list[torch.Tensor] = []
    pending_steps = 0
    pending_ar_ms = 0.0
    pending_prefill_ms = 0.0
    pending_started = request_started
    output_index = 0
    target_steps = args.first_output_steps
    generated_steps = 0
    emitted_steps = 0
    codec_digest = hashlib.sha256()

    for codec_chunk, timing in stream_fn(**stream_kwargs):
        pending.append(codec_chunk)
        codec_digest.update(codec_chunk.detach().cpu().contiguous().numpy().tobytes())
        pending_steps += int(timing.get("chunk_steps", codec_chunk.shape[0]))
        generated_steps += int(timing.get("chunk_steps", codec_chunk.shape[0]))
        pending_ar_ms += float(timing.get("decode_ms", 0.0))
        pending_prefill_ms += float(timing.get("prefill_ms", 0.0))
        is_final = bool(timing.get("is_final", False))
        if pending_steps < target_steps and not is_final:
            continue

        output_index, emitted_steps, pending_started = _flush_pending(
            decoder=decoder,
            rows=rows,
            pending=pending,
            pending_started=pending_started,
            run_index=run_index,
            output_index=output_index,
            pending_steps=pending_steps,
            pending_prefill_ms=pending_prefill_ms,
            pending_ar_ms=pending_ar_ms,
            prepare_ms=prepare_ms if output_index == 0 else 0.0,
            is_final=is_final,
            generated_steps=generated_steps,
            emitted_steps=emitted_steps,
            codec_sha256=codec_digest.hexdigest(),
        )
        pending = []
        pending_steps = 0
        pending_ar_ms = 0.0
        pending_prefill_ms = 0.0
        target_steps = args.steady_output_steps

    if pending_steps:
        output_index, emitted_steps, pending_started = _flush_pending(
            decoder=decoder,
            rows=rows,
            pending=pending,
            pending_started=pending_started,
            run_index=run_index,
            output_index=output_index,
            pending_steps=pending_steps,
            pending_prefill_ms=pending_prefill_ms,
            pending_ar_ms=pending_ar_ms,
            prepare_ms=prepare_ms if output_index == 0 else 0.0,
            is_final=True,
            generated_steps=generated_steps,
            emitted_steps=emitted_steps,
            codec_sha256=codec_digest.hexdigest(),
        )
    elif rows and not bool(rows[-1]["is_final"]):
        rows[-1]["is_final"] = True

    if generated_steps != emitted_steps:
        raise RuntimeError(
            f"adaptive chunk accounting mismatch: generated={generated_steps}, "
            f"emitted={emitted_steps}"
        )
    for row in rows:
        row["run_generated_steps"] = generated_steps
        row["run_emitted_steps"] = emitted_steps
        row["run_codec_sha256"] = codec_digest.hexdigest()
    return rows


def _flush_pending(
    *,
    decoder: "_AdaptiveDecoder",
    rows: list[dict[str, Any]],
    pending: list[torch.Tensor],
    pending_started: float,
    run_index: int,
    output_index: int,
    pending_steps: int,
    pending_prefill_ms: float,
    pending_ar_ms: float,
    prepare_ms: float,
    is_final: bool,
    generated_steps: int,
    emitted_steps: int,
    codec_sha256: str,
) -> tuple[int, int, float]:
    combined = torch.cat(pending, dim=0)
    decoded = decoder.decode_next(combined)
    _sync_cuda()
    ended = time.perf_counter()
    wall_ms = (ended - pending_started) * 1000.0
    emitted_steps += pending_steps
    rows.append(
        {
            "run": run_index,
            "chunk": output_index,
            "wall_ms": wall_ms,
            "prepare_ms": prepare_ms,
            "prefill_ms": pending_prefill_ms,
            "ar_decode_ms": pending_ar_ms,
            "chunk_steps": pending_steps,
            "generated_steps_so_far": generated_steps,
            "emitted_steps_so_far": emitted_steps,
            "ar_ms_per_step": pending_ar_ms / pending_steps if pending_steps else 0.0,
            "outside_ms": wall_ms - pending_prefill_ms - pending_ar_ms,
            "decode_wall_ms": decoded["decode_wall_ms"],
            "audio_ms": decoded["audio_ms"],
            "audio_samples": decoded["audio_samples"],
            "codec_sha256_so_far": codec_sha256,
            "is_final": is_final,
        }
    )
    return output_index + 1, emitted_steps, time.perf_counter()


class _AdaptiveDecoder:
    def __init__(
        self,
        *,
        speech_tokenizer: Any,
        ref_codes: torch.Tensor | None,
        min_calibration_frames: int,
    ) -> None:
        self._speech_tokenizer = speech_tokenizer
        self._ref_codes = ref_codes
        self._min_calibration_frames = min_calibration_frames
        self._all_codes: list[torch.Tensor] = []
        self._prev_gen_audio_len = 0
        self._samples_per_frame: float | None = None
        self._sample_rate = 24000

    def decode_next(self, codec_chunk: torch.Tensor) -> dict[str, Any]:
        context_frames = 25
        self._all_codes.append(codec_chunk)
        n_new = codec_chunk.shape[0]
        all_flat = torch.cat(self._all_codes, dim=0)
        n_total = all_flat.shape[0]

        started = time.perf_counter()
        if self._samples_per_frame is None:
            if self._ref_codes is not None:
                codes_input = torch.cat([self._ref_codes.to(all_flat.device), all_flat], dim=0)
            else:
                codes_input = all_flat
            audio_list, self._sample_rate = self._speech_tokenizer.decode(
                {"audio_codes": codes_input.unsqueeze(0)}
            )
            audio = _to_numpy(audio_list[0])
            if self._ref_codes is not None:
                ref_len = self._ref_codes.shape[0]
                ref_audio_cut = int(ref_len / max(codes_input.shape[0], 1) * len(audio))
                gen_audio = audio[ref_audio_cut:]
            else:
                gen_audio = audio
            new_audio = gen_audio[self._prev_gen_audio_len:]
            self._prev_gen_audio_len = len(gen_audio)
            if n_total >= self._min_calibration_frames:
                self._samples_per_frame = len(gen_audio) / n_total
        else:
            ctx_start = max(0, n_total - n_new - context_frames)
            window = all_flat[ctx_start:]
            n_ctx = window.shape[0] - n_new
            audio_list, self._sample_rate = self._speech_tokenizer.decode(
                {"audio_codes": window.unsqueeze(0)}
            )
            audio = _to_numpy(audio_list[0])
            if n_ctx > 0:
                ctx_samples = int(round(n_ctx * self._samples_per_frame))
                new_audio = audio[ctx_samples:]
            else:
                new_audio = audio

        _sync_cuda()
        decode_wall_ms = (time.perf_counter() - started) * 1000.0
        audio_samples = int(np.asarray(new_audio).shape[-1])
        return {
            "decode_wall_ms": decode_wall_ms,
            "audio_ms": 1000.0 * audio_samples / self._sample_rate,
            "audio_samples": audio_samples,
        }


def _to_numpy(audio: Any) -> np.ndarray:
    if hasattr(audio, "cpu"):
        return audio.flatten().cpu().numpy()
    return np.asarray(audio).flatten()


def _summarize_positions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = [row for row in rows if row["chunk"] == 0]
    second = [row for row in rows if row["chunk"] == 1]
    steady = [row for row in rows if row["chunk"] >= 1 and not row["is_final"]]
    final = [row for row in rows if row["is_final"]]
    totals = _summarize_runs(rows)
    return {
        "first": _summary_stats(first),
        "second": _summary_stats(second),
        "steady_after_first": _summary_stats(steady),
        "final": _summary_stats(final),
        "totals": totals,
    }


def _summarize_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_run: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_run.setdefault(int(row["run"]), []).append(row)
    totals = []
    for run_rows in by_run.values():
        wall_ms = sum(float(row["wall_ms"]) for row in run_rows)
        audio_ms = sum(float(row["audio_ms"]) for row in run_rows)
        totals.append(
            {
                "wall_ms": wall_ms,
                "audio_ms": audio_ms,
                "inverse_rtf": audio_ms / wall_ms if wall_ms > 0 else 0.0,
                "local_rtf": wall_ms / audio_ms if audio_ms > 0 else 0.0,
                "chunks": len(run_rows),
            }
        )
    return {
        "wall_ms": _stats([row["wall_ms"] for row in totals]),
        "audio_ms": _stats([row["audio_ms"] for row in totals]),
        "inverse_rtf": _stats([row["inverse_rtf"] for row in totals]),
        "local_rtf": _stats([row["local_rtf"] for row in totals]),
        "chunks": _stats([row["chunks"] for row in totals]),
    }


def _summary_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    keys = (
        "wall_ms",
        "prepare_ms",
        "prefill_ms",
        "ar_decode_ms",
        "ar_ms_per_step",
        "outside_ms",
        "decode_wall_ms",
        "audio_ms",
    )
    out: dict[str, Any] = {"count": len(rows)}
    for key in keys:
        out[f"{key}_median"] = statistics.median(float(row[key]) for row in rows)
        out[f"{key}_p95"] = _percentile([float(row[key]) for row in rows], 95.0)
    return out


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
