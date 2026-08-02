"""Render a blinded WAV package for human sampling-quality review."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import threading
import wave
from pathlib import Path
from typing import cast

from qwen_sampling_matrix import _TEXTS, _provenance

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine import AudioFormat, QwenTtsEngine, SynthesisRequest
from qwen_tts_bridge_worker.engine.types import SamplingOptions

_PRESETS = (
    {
        "id": "stable_sampled",
        "sampling": SamplingOptions(
            temperature=0.4,
            top_k=50,
            top_p=1.0,
            repetition_penalty=1.05,
            do_sample=True,
        ),
    },
    {
        "id": "expressive_sampled",
        "sampling": SamplingOptions(
            temperature=0.8,
            top_k=50,
            top_p=0.9,
            repetition_penalty=1.05,
            do_sample=True,
        ),
    },
    {
        "id": "greedy_control",
        "sampling": SamplingOptions(
            temperature=0.4,
            top_k=50,
            top_p=1.0,
            repetition_penalty=1.05,
            do_sample=False,
        ),
    },
)


def main() -> int:
    """Generate a human-review package without exposing its preset mapping."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--speaker", default="serena")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--max-audio-seconds", type=float, default=30.0)
    args = parser.parse_args()
    args.profile = args.profile.resolve()
    if args.seed < 0:
        parser.error("--seed must be non-negative")
    if args.max_audio_seconds <= 0.0:
        parser.error("--max-audio-seconds must be positive")
    if not args.profile.is_file():
        parser.error(f"--profile was not found: {args.profile}")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error(f"--output-dir must be empty: {args.output_dir}")

    cases = _build_cases(args)
    random.Random(20_260_802).shuffle(cases)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    engine = QwenTtsEngine(_engine_config(args))
    try:
        engine.load()
        if not engine.capabilities.sampling_overrides:
            raise RuntimeError("loaded engine does not support sampling overrides")
        if not engine.capabilities.deterministic_seed:
            raise RuntimeError("loaded engine does not support deterministic seeds")
        warmup = engine.warmup()
        completed = _render_cases(engine, args, cases)
    finally:
        engine.close()

    _write_package(args, completed, warmup)
    print(f"Created blinded review package: {args.output_dir}")
    return 0


def _engine_config(args: argparse.Namespace) -> QwenEngineConfig:
    return QwenEngineConfig(
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
        allow_request_sampling_overrides=True,
        warmup_synthesis_enabled=True,
        warmup_synthesis_passes=1,
        warmup_seed=args.seed,
        warmup_unbounded_passes=1,
        warmup_text="Проверка готовности завершена.",
        warmup_language="Russian",
        warmup_speaker=args.speaker,
        warmup_instruction="Speak clearly in a neutral, natural tone.",
    )


def _build_cases(args: argparse.Namespace) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for label, text, language in _TEXTS:
        for preset in _PRESETS:
            cases.append(
                {
                    "source_label": label,
                    "text": text,
                    "language": language,
                    "speaker": args.speaker,
                    "seed": args.seed,
                    "instruction": args.instruction,
                    "preset_id": preset["id"],
                    "sampling": preset["sampling"],
                }
            )
    return cases


def _render_cases(
    engine: QwenTtsEngine,
    args: argparse.Namespace,
    cases: list[dict[str, object]],
) -> list[dict[str, object]]:
    completed: list[dict[str, object]] = []
    audio_format = AudioFormat.default()
    for index, case in enumerate(cases, start=1):
        item_id = f"item-{index:03d}"
        request = SynthesisRequest(
            request_id=index,
            text=str(case["text"]),
            language=str(case["language"]),
            speaker=str(case["speaker"]),
            instruction=str(case["instruction"]),
            sampling=cast(SamplingOptions, case["sampling"]),
            seed=cast(int, case["seed"]),
        )
        effective = engine.describe_request(request)
        pcm = bytearray()
        stream = engine.synthesize_stream(request, threading.Event())
        try:
            for chunk in stream:
                pcm.extend(chunk)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        trace = engine.pop_last_generation_trace() or {}
        audio_path = args.output_dir / f"{item_id}.wav"
        _write_wav(audio_path, bytes(pcm), audio_format)
        completed.append(
            {
                **case,
                "item_id": item_id,
                "audio_file": audio_path.name,
                "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
                "codec_sha256": trace.get("codec_sha256"),
                "termination_reason": trace.get("termination_reason"),
                "effective_settings": effective,
            }
        )
    return completed


def _write_wav(path: Path, pcm: bytes, audio_format: AudioFormat) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(audio_format.channels)
        output.setsampwidth(2)
        output.setframerate(audio_format.sample_rate)
        output.writeframes(pcm)


def _write_package(
    args: argparse.Namespace,
    cases: list[dict[str, object]],
    warmup: object,
) -> None:
    form_path = args.output_dir / "blind-review-form.jsonl"
    with form_path.open("w", encoding="utf-8", newline="\n") as form:
        for case in cases:
            form.write(
                json.dumps(
                    {
                        "item_id": case["item_id"],
                        "audio_file": case["audio_file"],
                        "text": case["text"],
                        "language": case["language"],
                        "speaker": case["speaker"],
                        "naturalness_1_to_5": None,
                        "clarity_1_to_5": None,
                        "stress_and_pronunciation_1_to_5": None,
                        "emotion_and_style_1_to_5": None,
                        "pace_1_to_5": None,
                        "repetition_or_artifacts": None,
                        "notes": "",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    key = {
        "schema_version": 1,
        "warning": "Keep this file closed until the human review is complete.",
        "items": [
            {
                "item_id": case["item_id"],
                "source_label": case["source_label"],
                "preset_id": case["preset_id"],
                "pcm_sha256": case["pcm_sha256"],
                "codec_sha256": case["codec_sha256"],
                "termination_reason": case["termination_reason"],
                "effective_settings": case["effective_settings"],
            }
            for case in cases
        ],
    }
    manifest = {
        "schema_version": 2,
        "experiment": "faster_qwen_sampling_blind_review",
        "review_form": form_path.name,
        "audio_format": AudioFormat.default().to_payload(),
        "item_count": len(cases),
        "preset_count": len(_PRESETS),
        "preset_mapping_hidden_in": "blind-review-key.json",
        "provenance": _provenance(args, script_path=Path(__file__)),
        "warmup": warmup,
        "quality_claim": "Human listening is required before comparing presets.",
    }
    (args.output_dir / "blind-review-key.json").write_text(
        json.dumps(key, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "blind-review-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
