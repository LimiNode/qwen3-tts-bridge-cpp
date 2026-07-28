"""Measure compiled prefill cache behavior across prompt shapes."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import torch

from faster_qwen3_tts import FasterQwen3TTS
from faster_qwen3_tts.streaming import (
    clear_prefill_compile_cache,
    configure_prefill_compile_cache,
    prefill_compile_cache_stats,
)
from qwen_prefill_compile_parity import (
    _configure_precision,
    _eval_inner_modules,
    _prefill_once,
    _runtime_metadata,
    _tensor_fingerprint,
)


_TEXT_CANDIDATES = [
    ("short_robot_a", "I am your robot, I am your worker."),
    ("short_robot_b", "I am your worker, I am your robot."),
    ("tiny_a", "The machine speaks clearly."),
    ("tiny_b", "The system speaks clearly."),
    ("medium_a", "We are testing the compiled prefill cache on one persistent worker."),
    ("medium_b", "We are measuring the compiled prefill cache on one persistent worker."),
    ("numbers_a", "Count one, two, three, four, five, then return to the first phrase."),
    ("numbers_b", "Count five, four, three, two, one, then return to the first phrase."),
    ("instructional_a", "Say this line as a calm laboratory note for latency profiling."),
    ("instructional_b", "Say this line as a precise laboratory note for latency profiling."),
    (
        "long_a",
        "This longer sentence exists to produce a different prefill shape while the "
        "worker stays alive and the compiled callable cache accumulates entries.",
    ),
    (
        "long_b",
        "This longer paragraph exists to produce another prefill shape while the "
        "worker remains alive and the compiled callable cache accumulates entries.",
    ),
    (
        "russian_a",
        "Я твой робот, я твой работник, и мы проверяем задержку синтеза речи.",
    ),
    (
        "russian_b",
        "Я твой работник, я твой робот, и мы проверяем задержку синтеза речи.",
    ),
    (
        "mixed_a",
        "Kraftwerk said: I am your robot, я твой работник, version forty two.",
    ),
    (
        "mixed_b",
        "Kraftwerk said: I am your worker, я твой робот, version forty three.",
    ),
    (
        "very_long_a",
        "A production avatar needs predictable first audio latency even when users "
        "type short messages, long messages, bilingual phrases, and repeated "
        "instructions during the same session.",
    ),
    (
        "very_long_b",
        "A production avatar needs stable first audio latency even when users type "
        "brief messages, extended messages, bilingual phrases, and repeated "
        "instructions during the same session.",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--language", default="English")
    parser.add_argument("--max-shapes", type=int, default=10)
    parser.add_argument("--cache-max-entries", type=int, default=64)
    parser.add_argument("--eviction-cache-max-entries", type=int, default=4)
    parser.add_argument(
        "--contexts",
        default="eager,strict_inductor_default,strict_reduce_overhead",
        help="Comma-separated context labels to run.",
    )
    parser.add_argument("--matmul-precision", default="high")
    parser.add_argument("--disable-tf32", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    _configure_precision(args)
    configure_prefill_compile_cache(max_entries=args.cache_max_entries)
    clear_prefill_compile_cache()

    started = time.perf_counter()
    model = FasterQwen3TTS.from_pretrained(
        args.model,
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
        prefill_compile_compat_mode="strict_bf16_sdpa_v1",
    )
    _eval_inner_modules(model)
    try:
        shapes = _select_shapes(model, args)
        requested_contexts = {
            value.strip()
            for value in args.contexts.split(",")
            if value.strip()
        }
        contexts = [
            {
                "label": "eager",
                "backend": "eager",
                "prefill_compile_compat_mode": "none",
            },
            {
                "label": "strict_inductor_default",
                "backend": "compile_inductor_default",
                "prefill_compile_compat_mode": "strict_bf16_sdpa_v1",
            },
            {
                "label": "strict_reduce_overhead",
                "backend": "compile_reduce_overhead",
                "prefill_compile_compat_mode": "strict_bf16_sdpa_v1",
            },
        ]
        contexts = [row for row in contexts if row["label"] in requested_contexts]
        if not contexts:
            raise ValueError(f"No contexts selected by --contexts={args.contexts!r}")
        report = {
            "artifact_schema_version": 1,
            "output": str(args.output),
            "model": args.model,
            "device": args.device,
            "dtype": args.dtype,
            "attn_implementation": args.attn_implementation,
            "speaker": args.speaker,
            "language": args.language,
            "cache_max_entries": args.cache_max_entries,
            "eviction_cache_max_entries": args.eviction_cache_max_entries,
            "runtime": _runtime_metadata(args.device),
            "shapes": [_shape_summary(row) for row in shapes],
            "contexts": [],
        }
        for context in contexts:
            configure_prefill_compile_cache(max_entries=args.cache_max_entries)
            clear_prefill_compile_cache()
            eviction_baseline = int(prefill_compile_cache_stats()["evictions"])
            report["contexts"].append(
                _run_context(
                    model,
                    shapes,
                    context,
                    args.cache_max_entries,
                    eviction_baseline,
                )
            )
        report["eviction"] = _run_eviction_context(
            model,
            shapes,
            args.eviction_cache_max_entries,
        )
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    finally:
        model.close()
        clear_prefill_compile_cache()
        configure_prefill_compile_cache(max_entries=64)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(_summary(report), sort_keys=True))
    return 0


def _select_shapes(model: Any, args: argparse.Namespace) -> list[dict[str, Any]]:
    by_length: dict[int, list[dict[str, Any]]] = {}
    for label, text in _TEXT_CANDIDATES:
        language = "Russian" if label.startswith("russian") else args.language
        prepared = model._prepare_generation_custom(
            text=text,
            language=language,
            speaker=args.speaker,
            instruct=None,
            non_streaming_mode=True,
            return_metadata=True,
        )
        _m, talker, _config, tie, tam, tth, tpe, metadata = prepared
        length = int(metadata.get("talker_prefill_length", tie.shape[1]))
        by_length.setdefault(length, []).append(
            {
                "label": label,
                "text": text,
                "language": language,
                "talker": talker,
                "tie": tie,
                "tam": tam,
                "tth": tth,
                "tpe": tpe,
                "metadata": metadata,
                "talker_prefill_length": length,
                "shape_fingerprint": {
                    "talker_input_embeds": _tensor_fingerprint(tie),
                    "attention_mask": _tensor_fingerprint(tam),
                    "trailing_text_hiddens": _tensor_fingerprint(tth),
                    "tts_pad_embed": _tensor_fingerprint(tpe),
                },
            }
        )
    pairs = [rows for _length, rows in sorted(by_length.items()) if len(rows) >= 2]
    if len(pairs) < args.max_shapes:
        singles = [
            rows
            for _length, rows in sorted(by_length.items())
            if len(rows) == 1
        ]
        pairs.extend(singles)
    return [rows[:2] for rows in pairs[: args.max_shapes]]


def _run_context(
    model: Any,
    shapes: list[list[dict[str, Any]]],
    context: dict[str, str],
    cache_max_entries: int,
    eviction_baseline: int,
) -> dict[str, Any]:
    rows = []
    previous_first: dict[str, Any] | None = None
    for shape_index, pair in enumerate(shapes, 1):
        first = pair[0]
        second = pair[1] if len(pair) > 1 else pair[0]
        sequence = [
            ("A1", first),
            ("A2", first),
            ("A3", first),
            ("A4", first),
            ("B_same_length", second),
            ("A_return", first),
        ]
        if previous_first is not None:
            sequence.append(("previous_shape_return", previous_first))
        for role, shape in sequence:
            rows.append(
                _run_prefill_row(
                    shape_index=shape_index,
                    role=role,
                    shape=shape,
                    backend=context["backend"],
                    prefill_compile_compat_mode=context[
                        "prefill_compile_compat_mode"
                    ],
                    eviction_baseline=eviction_baseline,
                )
            )
        previous_first = first
    return {
        **context,
        "cache_max_entries": cache_max_entries,
        "cache_evictions_baseline": eviction_baseline,
        "rows": rows,
        "cache_stats_after_context": prefill_compile_cache_stats(),
    }


def _run_eviction_context(
    model: Any,
    shapes: list[list[dict[str, Any]]],
    cache_max_entries: int,
) -> dict[str, Any]:
    configure_prefill_compile_cache(max_entries=cache_max_entries)
    clear_prefill_compile_cache()
    eviction_baseline = int(prefill_compile_cache_stats()["evictions"])
    rows = []
    first_shapes = [pair[0] for pair in shapes[: max(cache_max_entries + 1, 5)]]
    if len(first_shapes) < 5:
        return {"skipped": True, "reason": "not enough distinct shapes"}
    sequence: list[tuple[str, dict[str, Any]]] = []
    for index, shape in enumerate(first_shapes[:cache_max_entries], 1):
        sequence.append((f"L{index}_cold", shape))
    sequence.append(("L1_refresh", first_shapes[0]))
    sequence.append((f"L{cache_max_entries + 1}_cold", first_shapes[cache_max_entries]))
    sequence.append(("L2_after_eviction_candidate", first_shapes[1]))
    sequence.append(("L1_after_refresh", first_shapes[0]))
    for role, shape in sequence:
        rows.append(
            _run_prefill_row(
                shape_index=first_shapes.index(shape) + 1,
                role=role,
                shape=shape,
                backend="compile_reduce_overhead",
                prefill_compile_compat_mode="strict_bf16_sdpa_v1",
                eviction_baseline=eviction_baseline,
            )
        )
    return {
        "skipped": False,
        "backend": "compile_reduce_overhead",
        "prefill_compile_compat_mode": "strict_bf16_sdpa_v1",
        "cache_max_entries": cache_max_entries,
        "cache_evictions_baseline": eviction_baseline,
        "rows": rows,
        "cache_stats_after_context": prefill_compile_cache_stats(),
    }


def _run_prefill_row(
    *,
    shape_index: int,
    role: str,
    shape: dict[str, Any],
    backend: str,
    prefill_compile_compat_mode: str,
    eviction_baseline: int,
) -> dict[str, Any]:
    out, profile = _prefill_once(
        shape["talker"],
        shape["tie"],
        shape["tam"],
        shape["tth"],
        shape["tpe"],
        shape["metadata"],
        backend,
        "auto",
        prefill_compile_compat_mode,
    )
    profile["prefill_compile_cache_evictions_delta_from_context_start"] = (
        int(profile.get("prefill_compile_cache_evictions", 0)) - eviction_baseline
    )
    logits = out.logits[:, -1, :].detach()
    return {
        "shape_index": shape_index,
        "role": role,
        "label": shape["label"],
        "language": shape["language"],
        "talker_prefill_length": shape["talker_prefill_length"],
        "text_characters": len(shape["text"]),
        "shape_fingerprint": shape["shape_fingerprint"],
        "profile": profile,
        "logits_last": _tensor_fingerprint(logits),
    }


def _shape_summary(pair: list[dict[str, Any]]) -> dict[str, Any]:
    first = pair[0]
    second = pair[1] if len(pair) > 1 else pair[0]
    return {
        "talker_prefill_length": first["talker_prefill_length"],
        "a_label": first["label"],
        "b_label": second["label"],
        "a_text_characters": len(first["text"]),
        "b_text_characters": len(second["text"]),
    }


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    contexts = {}
    for context in report["contexts"]:
        rows = context["rows"]
        compiled_rows = [
            row for row in rows if row["profile"].get("prefill_backend_used") != "eager"
        ]
        contexts[context["label"]] = {
            "rows": len(rows),
            "compiled_rows": len(compiled_rows),
            "cache_entries": context["cache_stats_after_context"]["entries"],
            "evictions_delta": int(
                context["cache_stats_after_context"]["evictions"]
            )
            - int(context.get("cache_evictions_baseline", 0)),
            "max_ordinal": max(
                (
                    row["profile"].get("prefill_shape_call_ordinal", 0)
                    for row in rows
                ),
                default=0,
            ),
        }
    eviction = report["eviction"]
    return {
        "output": report["output"],
        "shape_count": len(report["shapes"]),
        "contexts": contexts,
        "eviction": {
            "skipped": eviction.get("skipped"),
            "rows": len(eviction.get("rows", [])),
            "cache_entries": eviction.get("cache_stats_after_context", {}).get(
                "entries"
            ),
            "evictions_delta": (
                int(eviction.get("cache_stats_after_context", {}).get("evictions", 0))
                - int(eviction.get("cache_evictions_baseline", 0))
                if eviction.get("cache_stats_after_context")
                else None
            ),
        },
        "elapsed_seconds": report["elapsed_seconds"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
