"""Run a same-seed CustomVoice instruction-control experiment through the bridge."""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
from pathlib import Path
from time import perf_counter
from typing import Any

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine import QwenTtsEngine, SynthesisRequest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--speaker", default="serena")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--max-audio-seconds", type=float, default=60.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not args.instruction.strip():
        parser.error("--instruction must not be empty")

    config = QwenEngineConfig(
        model_path=args.model,
        runtime_backend="faster",
        device="cuda",
        dtype="bfloat16",
        attn_implementation="sdpa",
        max_audio_seconds_per_utterance=args.max_audio_seconds,
        emit_every_frames=8,
        decode_window_frames=80,
        prefill_backend="eager",
        prefill_compile_compat_mode="none",
        prefill_compile_on_miss=False,
        prefill_unknown_shape_policy="eager",
        prefill_compile_policy="diagnostic_dynamic",
        collect_generation_trace=True,
        seed=args.seed,
        seed_mode="fixed",
    )
    engine = QwenTtsEngine(config)
    try:
        engine.load()
        if not engine.capabilities.instructions:
            raise RuntimeError(
                "loaded runtime does not advertise CustomVoice style instructions"
            )
        baseline = _run_case(engine, args, "")
        styled = _run_case(engine, args, args.instruction)
    finally:
        engine.close()

    checks = {
        "baseline_instruction_token_count_zero": (
            baseline["instruction_token_count"] == 0
        ),
        "styled_instruction_token_count_positive": (
            isinstance(styled["instruction_token_count"], int)
            and styled["instruction_token_count"] > 0
        ),
        "both_used_eager_prefill": (
            baseline["prefill_backend_used"] == "eager"
            and styled["prefill_backend_used"] == "eager"
        ),
        "both_completed_without_error": (
            baseline["completed"] and styled["completed"]
        ),
        "audio_hashes_differ": baseline["pcm_sha256"] != styled["pcm_sha256"],
    }
    result = {
        "schema_version": 1,
        "experiment": "customvoice_instruction_eager_ab",
        "configuration": {
            "runtime_backend": "faster",
            "prefill_backend": "eager",
            "compile_policy": "diagnostic_dynamic",
            "seed": args.seed,
            "speaker": args.speaker,
            "language": args.language,
        },
        "baseline": baseline,
        "styled": styled,
        "checks": checks,
        "acceptance_pass": all(checks.values()),
        "listening_review_required": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["acceptance_pass"] else 1


def _run_case(
    engine: QwenTtsEngine,
    args: argparse.Namespace,
    instruction: str,
) -> dict[str, object]:
    request = SynthesisRequest(
        request_id=1,
        text=args.text,
        language=args.language,
        speaker=args.speaker,
        instruction=instruction,
        seed=args.seed,
    )
    engine.validate_request(request)
    started_at = perf_counter()
    pcm = bytearray()
    first_metrics: dict[str, object] | None = None
    chunk_count = 0
    stream = engine.synthesize_stream(request, threading.Event())
    try:
        for chunk in stream:
            chunk_count += 1
            pcm.extend(chunk)
            metrics = engine.pop_last_chunk_metrics()
            if first_metrics is None and isinstance(metrics, dict):
                first_metrics = metrics
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    trace = engine.pop_last_generation_trace() or {}
    metrics = first_metrics or {}
    return {
        "completed": True,
        "duration_ms": round((perf_counter() - started_at) * 1000.0, 3),
        "chunk_count": chunk_count,
        "pcm_bytes": len(pcm),
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
        "instruction_token_count": metrics.get("instruction_token_count"),
        "text_token_count": metrics.get("text_token_count"),
        "talker_prefill_length": metrics.get("talker_prefill_length"),
        "prefill_backend_used": metrics.get("prefill_backend_used"),
        "termination_reason": trace.get("termination_reason"),
        "codec_frame_count": trace.get("codec_frame_count"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
