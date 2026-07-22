"""Direct faster-qwen3-tts benchmark.

This is an experiment harness for the optional StaticCache/CUDA Graph backend.
It does not use the bridge worker protocol.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
from faster_qwen3_tts import FasterQwen3TTS


DEFAULT_REF_AUDIO = (
    "https://qianwen-res.oss-cn-beijing.aliyuncs.com/"
    "Qwen3-TTS-Repo/clone_2.wav"
)
DEFAULT_REF_TEXT = (
    "Okay. Yeah. I resent you. I love you. I respect you. "
    "But you know what? You blew it! And thanks to you."
)


def main() -> int:
    args = _build_parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    torch.set_float32_matmul_precision(args.matmul_precision)

    total_start = time.perf_counter()
    model = FasterQwen3TTS.from_pretrained(
        args.model,
        device=args.device,
        dtype=_torch_dtype(args.dtype),
        attn_implementation=args.attn_implementation,
        max_seq_len=args.max_seq_len,
        local_files_only=args.local_files_only,
    )
    _sync_cuda()
    loaded_s = time.perf_counter() - total_start

    warmup_start = time.perf_counter()
    model.warmup(prefill_len=args.warmup_prefill_len)
    _sync_cuda()
    warmup_s = time.perf_counter() - warmup_start

    ref_audio = _ensure_reference_audio(args.ref_audio, output_dir)

    results: list[dict[str, Any]] = []
    for index in range(1, args.runs + 1):
        result = _run_clone(
            model=model,
            text=args.text,
            language=args.language,
            ref_audio=ref_audio,
            ref_text=args.ref_text,
            chunk_size=args.chunk_size,
            xvec_only=args.x_vector_only,
            non_streaming_mode=args.non_streaming_mode,
            label=f"run_{index}",
            output_path=output_dir / f"run_{index}.wav",
        )
        results.append(result)

    summary = {
        "model": args.model,
        "ref_audio": str(ref_audio),
        "ref_text": args.ref_text,
        "text": args.text,
        "language": args.language,
        "loaded_s": loaded_s,
        "warmup_s": warmup_s,
        "total_script_s": time.perf_counter() - total_start,
        "settings": {
            "dtype": args.dtype,
            "attn_implementation": args.attn_implementation,
            "matmul_precision": args.matmul_precision,
            "max_seq_len": args.max_seq_len,
            "chunk_size": args.chunk_size,
            "warmup_prefill_len": args.warmup_prefill_len,
            "x_vector_only": args.x_vector_only,
            "non_streaming_mode": args.non_streaming_mode,
        },
        "results": results,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    _print_table(results)
    print(f"summary: {summary_path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen3-TTS-12Hz-1.7B-Base")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument("--matmul-precision", default="high")
    parser.add_argument("--max-seq-len", type=int, default=2048)
    parser.add_argument("--warmup-prefill-len", type=int, default=100)
    parser.add_argument("--ref-audio", default=DEFAULT_REF_AUDIO)
    parser.add_argument("--ref-text", default=DEFAULT_REF_TEXT)
    parser.add_argument("--x-vector-only", action="store_true")
    parser.add_argument("--non-streaming-mode", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--text",
        default="Я твой робот. Я твой работник.",
    )
    parser.add_argument("--language", default="Russian")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--output-dir", default="tmp/faster-qwen-direct")
    return parser


def _ensure_reference_audio(ref_audio: str, output_dir: Path) -> Path:
    if ref_audio.startswith("http://") or ref_audio.startswith("https://"):
        target = output_dir / Path(ref_audio).name
        if not target.exists():
            urllib.request.urlretrieve(ref_audio, target)
        return target
    return Path(ref_audio)


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


def _run_clone(
    *,
    model: FasterQwen3TTS,
    text: str,
    language: str,
    ref_audio: Path,
    ref_text: str,
    chunk_size: int,
    xvec_only: bool,
    non_streaming_mode: bool,
    label: str,
    output_path: Path,
) -> dict[str, Any]:
    start = time.perf_counter()
    first_chunk_s: float | None = None
    chunks: list[np.ndarray] = []
    chunk_meta: list[dict[str, Any]] = []
    sample_rate = 24000

    for chunk, sample_rate, meta in model.generate_voice_clone_streaming(
        text=text,
        language=language,
        ref_audio=ref_audio,
        ref_text=ref_text,
        chunk_size=chunk_size,
        xvec_only=xvec_only,
        non_streaming_mode=non_streaming_mode,
    ):
        if first_chunk_s is None:
            _sync_cuda()
            first_chunk_s = time.perf_counter() - start
        chunks.append(chunk)
        chunk_meta.append(dict(meta))

    _sync_cuda()
    total_s = time.perf_counter() - start
    audio = np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)
    sf.write(output_path, audio, sample_rate)
    audio_s = len(audio) / sample_rate if sample_rate else 0.0
    return {
        "label": label,
        "first_chunk_s": first_chunk_s,
        "total_s": total_s,
        "audio_s": audio_s,
        "rtf_elapsed_over_audio": (total_s / audio_s) if audio_s > 0 else None,
        "rtf_audio_over_elapsed": (audio_s / total_s) if total_s > 0 else None,
        "chunks": len(chunks),
        "sample_rate": sample_rate,
        "output": str(output_path),
        "last_meta": chunk_meta[-1] if chunk_meta else {},
    }


def _sync_cuda() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def _print_table(results: list[dict[str, Any]]) -> None:
    print()
    print(f"{'Method':<12} {'1st':>8} {'Total':>8} {'Audio':>8} {'RTF':>6} {'Inv':>6} {'Chunks':>7}")
    print("-" * 66)
    for result in results:
        first = result["first_chunk_s"]
        first_text = "N/A" if first is None else f"{first:.2f}s"
        rtf = result["rtf_elapsed_over_audio"]
        inv = result["rtf_audio_over_elapsed"]
        print(
            f"{result['label']:<12} {first_text:>8} "
            f"{result['total_s']:>7.2f}s {result['audio_s']:>7.2f}s "
            f"{(0.0 if rtf is None else rtf):>6.2f} "
            f"{(0.0 if inv is None else inv):>6.2f} "
            f"{result['chunks']:>7}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
