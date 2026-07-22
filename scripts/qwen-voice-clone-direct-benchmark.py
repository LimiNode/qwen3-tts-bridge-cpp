"""Direct Qwen3-TTS Base voice-clone benchmark.

This intentionally bypasses the C++ bridge and worker protocol so the upstream
voice-clone streaming path can be compared with the bridge CustomVoice path.
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
from qwen_tts import Qwen3TTSModel


DEFAULT_REF_AUDIO = (
    "https://qianwen-res.oss-cn-beijing.aliyuncs.com/"
    "Qwen3-TTS-Repo/clone_2.wav"
)
DEFAULT_REF_TEXT = (
    "Okay. Yeah. I resent you. I love you. I respect you. "
    "But you know what? You blew it! And thanks to you."
)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ref_audio = _ensure_reference_audio(args.ref_audio, output_dir)

    torch.set_float32_matmul_precision(args.matmul_precision)

    total_start = time.perf_counter()
    model = _load_model(args)
    _sync_cuda()
    loaded_s = time.perf_counter() - total_start

    prompt_start = time.perf_counter()
    voice_clone_prompt = model.create_voice_clone_prompt(
        ref_audio=str(ref_audio),
        ref_text=args.ref_text,
        x_vector_only_mode=args.x_vector_only,
    )
    _sync_cuda()
    prompt_s = time.perf_counter() - prompt_start

    results: list[dict[str, Any]] = []
    if not args.skip_standard:
        standard = _run_standard(
            model=model,
            text=args.text,
            language=args.language,
            voice_clone_prompt=voice_clone_prompt,
            output_path=output_dir / "standard.wav",
        )
        results.append(standard)

    baseline = _run_streaming(
        model=model,
        text=args.text,
        language=args.language,
        voice_clone_prompt=voice_clone_prompt,
        emit_every_frames=args.emit_every_frames,
        decode_window_frames=args.decode_window_frames,
        label="streaming_baseline",
        output_path=output_dir / "streaming_baseline.wav",
    )
    results.append(baseline)

    model.enable_streaming_optimizations(
        decode_window_frames=args.decode_window_frames,
        use_compile=not args.no_compile,
        use_cuda_graphs=not args.no_cuda_graphs,
        compile_mode=args.compile_mode,
        use_fast_codebook=args.use_fast_codebook,
        compile_codebook_predictor=not args.no_compile_codebook_predictor,
        compile_talker=not args.no_compile_talker,
    )

    for index, warmup_text in enumerate(args.warmup_text, 1):
        warmup = _run_streaming(
            model=model,
            text=warmup_text,
            language=args.language,
            voice_clone_prompt=voice_clone_prompt,
            emit_every_frames=args.emit_every_frames,
            decode_window_frames=args.decode_window_frames,
            label=f"warmup_{index}",
            output_path=None,
        )
        results.append(warmup)

    for index in range(1, args.optimized_runs + 1):
        optimized = _run_streaming(
            model=model,
            text=args.text,
            language=args.language,
            voice_clone_prompt=voice_clone_prompt,
            emit_every_frames=args.emit_every_frames,
            decode_window_frames=args.decode_window_frames,
            label=f"optimized_{index}",
            output_path=output_dir / f"optimized_{index}.wav",
        )
        results.append(optimized)

    summary = {
        "model": args.model,
        "ref_audio": str(ref_audio),
        "ref_text": args.ref_text,
        "text": args.text,
        "language": args.language,
        "model_loaded_s": loaded_s,
        "prompt_created_s": prompt_s,
        "total_script_s": time.perf_counter() - total_start,
        "settings": {
            "dtype": args.dtype,
            "attn_implementation": args.attn_implementation,
            "matmul_precision": args.matmul_precision,
            "emit_every_frames": args.emit_every_frames,
            "decode_window_frames": args.decode_window_frames,
            "compile_mode": args.compile_mode,
            "use_fast_codebook": args.use_fast_codebook,
            "use_cuda_graphs": not args.no_cuda_graphs,
            "x_vector_only": args.x_vector_only,
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
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="flash_attention_2")
    parser.add_argument("--matmul-precision", default="high")
    parser.add_argument("--ref-audio", default=DEFAULT_REF_AUDIO)
    parser.add_argument("--ref-text", default=DEFAULT_REF_TEXT)
    parser.add_argument("--x-vector-only", action="store_true")
    parser.add_argument(
        "--text",
        default="I am your robot. I am your worker.",
    )
    parser.add_argument("--language", default="Auto")
    parser.add_argument("--emit-every-frames", type=int, default=4)
    parser.add_argument("--decode-window-frames", type=int, default=80)
    parser.add_argument("--compile-mode", default="reduce-overhead")
    parser.add_argument("--no-compile", action="store_true")
    parser.add_argument("--no-cuda-graphs", action="store_true")
    parser.add_argument("--use-fast-codebook", action="store_true")
    parser.add_argument("--no-compile-codebook-predictor", action="store_true")
    parser.add_argument("--no-compile-talker", action="store_true")
    parser.add_argument("--optimized-runs", type=int, default=2)
    parser.add_argument("--skip-standard", action="store_true")
    parser.add_argument(
        "--warmup-text",
        action="append",
        default=[],
        help="Warmup text. May be repeated.",
    )
    parser.add_argument(
        "--output-dir",
        default="tmp/qwen-voice-clone-direct",
    )
    return parser


def _ensure_reference_audio(ref_audio: str, output_dir: Path) -> Path:
    if ref_audio.startswith("http://") or ref_audio.startswith("https://"):
        target = output_dir / Path(ref_audio).name
        if not target.exists():
            urllib.request.urlretrieve(ref_audio, target)
        return target
    return Path(ref_audio)


def _load_model(args: argparse.Namespace) -> Qwen3TTSModel:
    return Qwen3TTSModel.from_pretrained(
        args.model,
        device_map=args.device,
        dtype=_torch_dtype(args.dtype),
        attn_implementation=args.attn_implementation,
    )


def _torch_dtype(name: str) -> Any:
    dtype = getattr(torch, name, None)
    if dtype is None:
        raise ValueError(f"unsupported torch dtype: {name}")
    return dtype


def _run_standard(
    *,
    model: Qwen3TTSModel,
    text: str,
    language: str,
    voice_clone_prompt: Any,
    output_path: Path,
) -> dict[str, Any]:
    start = time.perf_counter()
    wavs, sample_rate = model.generate_voice_clone(
        text=text,
        language=language,
        voice_clone_prompt=voice_clone_prompt,
    )
    _sync_cuda()
    total_s = time.perf_counter() - start
    audio = wavs[0]
    sf.write(output_path, audio, sample_rate)
    audio_s = len(audio) / sample_rate
    return _result(
        label="standard",
        total_s=total_s,
        audio_s=audio_s,
        chunks=0,
        first_chunk_s=None,
        sample_rate=sample_rate,
        output_path=output_path,
    )


def _run_streaming(
    *,
    model: Qwen3TTSModel,
    text: str,
    language: str,
    voice_clone_prompt: Any,
    emit_every_frames: int,
    decode_window_frames: int,
    label: str,
    output_path: Path | None,
) -> dict[str, Any]:
    start = time.perf_counter()
    chunks: list[np.ndarray] = []
    first_chunk_s: float | None = None
    sample_rate = 24000

    for chunk, sample_rate in model.stream_generate_voice_clone(
        text=text,
        language=language,
        voice_clone_prompt=voice_clone_prompt,
        emit_every_frames=emit_every_frames,
        decode_window_frames=decode_window_frames,
        overlap_samples=0,
    ):
        if first_chunk_s is None:
            _sync_cuda()
            first_chunk_s = time.perf_counter() - start
        chunks.append(chunk)

    _sync_cuda()
    total_s = time.perf_counter() - start
    audio = np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)
    if output_path is not None:
        sf.write(output_path, audio, sample_rate)
    audio_s = len(audio) / sample_rate if sample_rate else 0.0
    return _result(
        label=label,
        total_s=total_s,
        audio_s=audio_s,
        chunks=len(chunks),
        first_chunk_s=first_chunk_s,
        sample_rate=sample_rate,
        output_path=output_path,
    )


def _result(
    *,
    label: str,
    total_s: float,
    audio_s: float,
    chunks: int,
    first_chunk_s: float | None,
    sample_rate: int,
    output_path: Path | None,
) -> dict[str, Any]:
    rtf = total_s / audio_s if audio_s > 0 else None
    return {
        "label": label,
        "first_chunk_s": first_chunk_s,
        "total_s": total_s,
        "audio_s": audio_s,
        "rtf": rtf,
        "chunks": chunks,
        "sample_rate": sample_rate,
        "output": str(output_path) if output_path is not None else None,
    }


def _sync_cuda() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def _print_table(results: list[dict[str, Any]]) -> None:
    print()
    print(f"{'Method':<20} {'1st':>8} {'Total':>8} {'Audio':>8} {'RTF':>6} {'Chunks':>7}")
    print("-" * 64)
    for result in results:
        first = result["first_chunk_s"]
        first_text = "N/A" if first is None else f"{first:.2f}s"
        rtf = result["rtf"]
        rtf_text = "N/A" if rtf is None else f"{rtf:.2f}"
        print(
            f"{result['label']:<20} {first_text:>8} "
            f"{result['total_s']:>7.2f}s {result['audio_s']:>7.2f}s "
            f"{rtf_text:>6} {result['chunks']:>7}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
