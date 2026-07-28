"""Collect talker prefill length histogram without audio generation."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from faster_qwen3_tts import FasterQwen3TTS
from qwen_prefill_compile_parity import _configure_precision, _runtime_metadata

_BASE_TEXTS = (
    "I am your robot, I am your worker.",
    "The avatar answers with a calm and friendly voice.",
    "Please summarize the current task in one clear sentence.",
    "Latency matters most when the first audio chunk arrives.",
    "We are testing a persistent local text to speech worker.",
    "The machine should speak naturally while the model stays warm.",
    "A short reply is often enough for conversational avatars.",
    "Longer replies need predictable streaming behavior as well.",
    "Read this as a precise laboratory note for performance profiling.",
    "Tell the operator that the bridge is ready for another request.",
    "Use a neutral studio voice and avoid dramatic emphasis.",
    "Say hello, pause briefly, and continue with the status update.",
    "The renderer waits for audio frames while the Python worker computes.",
    "Measure the first chunk, the total duration, and the real time factor.",
    "Repeat the key point: exact lengths compile, unknown lengths stay eager.",
    "This is a longer request with enough words to exercise another prompt shape.",
    "A production avatar can receive questions, commands, jokes, and status text.",
    "When the prompt is bilingual, the bridge should still report the same metrics.",
    "Ya tvoy robot, ya tvoy rabotnik, and the profiler is watching.",
    "Kraftwerk said the machine has rhythm, but the benchmark needs numbers.",
)

_PREFIXES = (
    "",
    "Please say: ",
    "For the demo, say: ",
    "In a relaxed tone, say: ",
    "For a realtime avatar, say: ",
)

_SUFFIXES = (
    "",
    " Keep it concise.",
    " Speak clearly.",
    " Use a natural pace.",
    " End with a confident tone.",
    " This request is part of a mixed workload.",
)

_INSTRUCTIONS = (
    "",
    "Speak neutrally.",
    "Speak with quiet confidence.",
    "Use a warm but restrained delivery.",
    "Sound like a helpful desktop assistant.",
    "Keep the emotion subtle and professional.",
)

_LANGUAGES = ("English", "Auto")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--prompt-count", type=int, default=500)
    parser.add_argument("--select-count", type=int, default=6)
    parser.add_argument("--matmul-precision", default="high")
    parser.add_argument("--disable-tf32", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.prompt_count < 1:
        parser.error("--prompt-count must be greater than zero")
    if args.select_count < 1:
        parser.error("--select-count must be greater than zero")

    _configure_precision(args)
    started = time.perf_counter()
    model = FasterQwen3TTS.from_pretrained(
        args.model,
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
        prefill_compile_compat_mode="strict_bf16_sdpa_v1",
    )
    try:
        prompts = _build_prompts(args.prompt_count)
        rows = [_measure_prompt(model, args, prompt) for prompt in prompts]
        histogram = _histogram(rows)
        report = {
            "artifact_schema_version": 1,
            "output": str(args.output),
            "method": "prepare_generation_custom_without_audio",
            "model": args.model,
            "device": args.device,
            "dtype": args.dtype,
            "attn_implementation": args.attn_implementation,
            "speaker": args.speaker,
            "prompt_count": len(rows),
            "runtime": _runtime_metadata(args.device),
            "histogram": histogram,
            "selected_exact_lengths": [
                item["talker_prefill_length"]
                for item in histogram[: args.select_count]
            ],
            "coverage": _coverage(histogram, len(rows), args.select_count),
            "rows": rows,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    finally:
        model.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(_summary(report), sort_keys=True))
    return 0


def _build_prompts(prompt_count: int) -> list[dict[str, object]]:
    prompts: list[dict[str, object]] = []
    index = 0
    while len(prompts) < prompt_count:
        text = (
            _PREFIXES[index % len(_PREFIXES)]
            + _BASE_TEXTS[index % len(_BASE_TEXTS)]
            + _SUFFIXES[(index // len(_BASE_TEXTS)) % len(_SUFFIXES)]
        )
        prompts.append(
            {
                "label": f"prompt_{len(prompts) + 1:04d}",
                "text": text,
                "language": _LANGUAGES[index % len(_LANGUAGES)],
                "instruction": _INSTRUCTIONS[
                    (index // (len(_BASE_TEXTS) * len(_SUFFIXES)))
                    % len(_INSTRUCTIONS)
                ],
            }
        )
        index += 1
    return prompts


def _measure_prompt(
    model: Any,
    args: argparse.Namespace,
    prompt: dict[str, object],
) -> dict[str, object]:
    prepared = model._prepare_generation_custom(
        text=str(prompt["text"]),
        language=str(prompt["language"]),
        speaker=args.speaker,
        instruct=_effective_instruction(model, prompt),
        non_streaming_mode=True,
        return_metadata=True,
    )
    _m, _talker, _config, talker_input_embeds, _tam, _tth, _tpe, metadata = prepared
    length = int(metadata.get("talker_prefill_length", talker_input_embeds.shape[1]))
    return {
        "label": prompt["label"],
        "language": prompt["language"],
        "text_characters": len(str(prompt["text"])),
        "instruction_characters": len(str(prompt["instruction"])),
        "talker_prefill_length": length,
        "text": prompt["text"],
        "instruction": prompt["instruction"],
    }


def _effective_instruction(
    model: Any,
    prompt: dict[str, object],
) -> str | None:
    instruction = str(prompt["instruction"]) or None
    model_size = str(getattr(model.model.model, "tts_model_size", "")).lower()
    if model_size in {"0b6", "0.6b", "0.6"}:
        return None
    return instruction


def _histogram(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    counter = Counter(int(row["talker_prefill_length"]) for row in rows)
    total = len(rows)
    result = []
    cumulative = 0
    for length, count in counter.most_common():
        cumulative += count
        result.append(
            {
                "talker_prefill_length": length,
                "count": count,
                "fraction": count / total,
                "cumulative_fraction": cumulative / total,
                "examples": [
                    row["label"]
                    for row in rows
                    if row["talker_prefill_length"] == length
                ][:5],
            }
        )
    return result


def _coverage(
    histogram: list[dict[str, object]],
    total: int,
    select_count: int,
) -> dict[str, object]:
    selected = histogram[:select_count]
    selected_count = sum(int(item["count"]) for item in selected)
    return {
        "selected_count": len(selected),
        "covered_prompts": selected_count,
        "covered_fraction": selected_count / total,
    }


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "output": report["output"],
        "prompt_count": report["prompt_count"],
        "selected_exact_lengths": report["selected_exact_lengths"],
        "coverage": report["coverage"],
        "elapsed_seconds": report["elapsed_seconds"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
