"""Smoke-test strict FasterQwen loading through the bridge Qwen engine."""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path
from typing import Any

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine import QwenTtsEngine, SynthesisRequest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument(
        "--prefill-backend",
        default="compile_reduce_overhead",
        choices=("compile_inductor_default", "compile_reduce_overhead"),
    )
    parser.add_argument("--text", default="I am your robot, I am your worker.")
    parser.add_argument("--language", default="English")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--emit-every-frames", type=int, default=8)
    parser.add_argument("--max-chunks", type=int, default=1)
    parser.add_argument("--warmup-synthesis", action="store_true")
    parser.add_argument("--warmup-max-output-chunks", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    config = QwenEngineConfig(
        model_path=args.model,
        runtime_backend="faster",
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
        emit_every_frames=args.emit_every_frames,
        prefill_backend=args.prefill_backend,
        prefill_compile_compat_mode="strict_bf16_sdpa_v1",
        warmup_synthesis_enabled=args.warmup_synthesis,
        warmup_max_output_chunks=args.warmup_max_output_chunks,
        warmup_text=args.text,
        warmup_language=args.language,
        warmup_speaker=args.speaker,
        warmup_instruction=args.instruction,
    )
    engine = QwenTtsEngine(config)
    chunks: list[dict[str, Any]] = []
    warmup: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    try:
        engine.load()
        model = getattr(engine, "_model")
        metadata = _metadata(model)
        warmup = engine.warmup()

        cancel_event = threading.Event()
        stream = engine.synthesize_stream(
            SynthesisRequest(
                request_id=1,
                text=args.text,
                language=args.language,
                speaker=args.speaker,
                instruction=args.instruction,
            ),
            cancel_event,
        )
        try:
            for index, pcm in enumerate(stream, 1):
                chunks.append(
                    {
                        "index": index,
                        "pcm_bytes": len(pcm),
                        "metrics": engine.pop_last_chunk_metrics(),
                    }
                )
                if index >= args.max_chunks:
                    cancel_event.set()
                    break
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
    finally:
        engine.close()

    result = {
        "config": {
            "model": args.model,
            "device": args.device,
            "dtype": args.dtype,
            "attn_implementation": args.attn_implementation,
            "prefill_backend": args.prefill_backend,
            "prefill_compile_compat_mode": "strict_bf16_sdpa_v1",
            "warmup_synthesis": args.warmup_synthesis,
            "warmup_max_output_chunks": args.warmup_max_output_chunks,
        },
        "metadata": metadata,
        "warmup": warmup,
        "chunks": chunks,
        "chunk_count": len(chunks),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


def _metadata(model: Any) -> dict[str, Any] | None:
    metadata = getattr(model, "prefill_compile_compat_metadata", None)
    if callable(metadata):
        metadata = metadata()
    if isinstance(metadata, dict):
        return dict(metadata)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
