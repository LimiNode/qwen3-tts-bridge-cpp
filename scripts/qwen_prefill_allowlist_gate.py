"""Verify exact-length compiled prefill allowlist against eager prefill."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import torch
from faster_qwen3_tts import FasterQwen3TTS
from faster_qwen3_tts.streaming import (
    _run_talker_prefill,
    clear_prefill_compile_cache,
    configure_prefill_compile_cache,
    prefill_compile_cache_stats,
    select_prefill_mask_mode,
)
from qwen_prefill_compile_parity import (
    _compare_prefill_outputs,
    _configure_precision,
    _eval_inner_modules,
    _runtime_metadata,
    _snapshot_prefill_output,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--histogram", type=Path, required=True)
    parser.add_argument("--lengths", default="")
    parser.add_argument("--select-count", type=int, default=6)
    parser.add_argument("--compiled-repeats", type=int, default=3)
    parser.add_argument("--backend", default="compile_reduce_overhead")
    parser.add_argument("--prefill-mask-mode", default="auto")
    parser.add_argument("--matmul-precision", default="high")
    parser.add_argument("--disable-tf32", action="store_true")
    parser.add_argument("--max-abs-threshold", type=float, default=1.0e-2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.compiled_repeats < 3:
        parser.error("--compiled-repeats must be at least 3")

    histogram = json.loads(args.histogram.read_text(encoding="utf-8"))
    lengths = _selected_lengths(args, histogram)
    prompts = _prompt_by_length(histogram, lengths)

    _configure_precision(args)
    configure_prefill_compile_cache(max_entries=max(len(lengths) + 4, 16))
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
        rows = [
            _run_length_gate(
                model,
                args,
                length=length,
                prompt=prompts[length],
                all_lengths=lengths,
            )
            for length in lengths
        ]
        report = {
            "artifact_schema_version": 1,
            "output": str(args.output),
            "method": "eager_vs_exact_length_compiled_prefill_replay",
            "model": args.model,
            "device": args.device,
            "dtype": args.dtype,
            "attn_implementation": args.attn_implementation,
            "speaker": args.speaker,
            "backend": args.backend,
            "prefill_compile_compat_mode": "strict_bf16_sdpa_v1",
            "prefill_compile_lengths": lengths,
            "compiled_repeats": args.compiled_repeats,
            "max_abs_threshold": args.max_abs_threshold,
            "runtime": _runtime_metadata(args.device),
            "rows": rows,
            "cache_stats_after_gate": prefill_compile_cache_stats(),
            "passed": all(row["passed"] for row in rows),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    finally:
        model.close()
        clear_prefill_compile_cache()
        configure_prefill_compile_cache(max_entries=64)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(_summary(report), sort_keys=True))
    if not report["passed"]:
        raise RuntimeError("prefill allowlist gate failed")
    return 0


def _selected_lengths(args: argparse.Namespace, histogram: dict[str, Any]) -> list[int]:
    if args.lengths.strip():
        return [int(item.strip()) for item in args.lengths.split(",") if item.strip()]
    selected = histogram.get("selected_exact_lengths")
    if isinstance(selected, list) and selected:
        return [int(value) for value in selected[: args.select_count]]
    hist = histogram.get("histogram")
    if not isinstance(hist, list):
        raise ValueError("histogram artifact is missing histogram rows")
    return [
        int(row["talker_prefill_length"])
        for row in hist[: args.select_count]
        if isinstance(row, dict)
    ]


def _prompt_by_length(
    histogram: dict[str, Any],
    lengths: list[int],
) -> dict[int, dict[str, object]]:
    rows = histogram.get("rows")
    if not isinstance(rows, list):
        raise ValueError("histogram artifact is missing prompt rows")
    result: dict[int, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        length = int(row.get("talker_prefill_length", 0))
        if length in lengths and length not in result:
            result[length] = row
    missing = [length for length in lengths if length not in result]
    if missing:
        raise ValueError(f"histogram artifact has no prompt rows for {missing}")
    return result


def _run_length_gate(
    model: Any,
    args: argparse.Namespace,
    *,
    length: int,
    prompt: dict[str, object],
    all_lengths: list[int],
) -> dict[str, object]:
    prepared = model._prepare_generation_custom(
        text=str(prompt["text"]),
        language=str(prompt["language"]),
        speaker=args.speaker,
        instruct=_effective_instruction(model, prompt),
        non_streaming_mode=True,
        return_metadata=True,
    )
    _m, talker, _config, tie, tam, tth, tpe, metadata = prepared
    actual_length = int(metadata.get("talker_prefill_length", tie.shape[1]))
    if actual_length != length:
        raise RuntimeError(f"prepared length changed: {actual_length} != {length}")
    mask_mode = (
        select_prefill_mask_mode(metadata)
        if args.prefill_mask_mode == "auto"
        else args.prefill_mask_mode
    )

    eager_out, eager_profile = _prefill_call(
        talker,
        tie,
        tam,
        tth,
        tpe,
        metadata,
        backend="eager",
        mask_mode=mask_mode,
        compile_lengths=all_lengths,
    )
    eager_snapshot = _snapshot_prefill_output(eager_out)
    compiled = []
    for repeat in range(args.compiled_repeats):
        out, profile = _prefill_call(
            talker,
            tie,
            tam,
            tth,
            tpe,
            metadata,
            backend=args.backend,
            mask_mode=mask_mode,
            compile_lengths=all_lengths,
        )
        compiled.append(
            {
                "repeat": repeat + 1,
                "profile": profile,
                "snapshot": _snapshot_prefill_output(out),
            }
        )

    comparison = _compare_prefill_outputs(
        eager_snapshot,
        compiled[-1]["snapshot"],
    )
    max_abs = _comparison_max_abs(comparison)
    last_profile = compiled[-1]["profile"]
    passed = (
        max_abs <= args.max_abs_threshold
        and last_profile.get("prefill_backend_used") == args.backend
        and last_profile.get("prefill_compile_fallback") is False
        and last_profile.get("prefill_shape_policy") == "compiled_allowlist"
        and last_profile.get("prefill_shape_allowlist_hit") is True
        and int(last_profile.get("prefill_shape_call_ordinal", 0)) >= 3
    )
    return {
        "talker_prefill_length": length,
        "label": prompt["label"],
        "text_characters": prompt["text_characters"],
        "instruction_characters": prompt["instruction_characters"],
        "eager_profile": eager_profile,
        "compiled_profiles": [row["profile"] for row in compiled],
        "comparison": comparison,
        "max_abs_observed": max_abs,
        "passed": passed,
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


def _prefill_call(
    talker: Any,
    tie: torch.Tensor,
    tam: torch.Tensor,
    tth: torch.Tensor,
    tpe: torch.Tensor,
    metadata: dict[str, Any],
    *,
    backend: str,
    mask_mode: str,
    compile_lengths: list[int],
) -> tuple[Any, dict[str, Any]]:
    torch.cuda.synchronize()
    with torch.inference_mode():
        out, profile = _run_talker_prefill(
            talker,
            tie,
            tam,
            tth,
            tpe,
            prefill_backend=backend,
            prefill_mask_mode=mask_mode,
            prefill_compile_compat_mode=(
                "none" if backend == "eager" else "strict_bf16_sdpa_v1"
            ),
            input_metadata=metadata,
            prefill_compile_lengths=compile_lengths,
            prefill_compile_on_miss=False,
            prefill_unknown_shape_policy="eager",
        )
    torch.cuda.synchronize()
    return out, profile


def _comparison_max_abs(comparison: dict[str, Any]) -> float:
    values = [
        float(comparison["logits_last"]["max_abs"]),
        float(comparison["logits_all"]["max_abs"]),
        float(comparison["past_hidden"]["max_abs"]),
    ]
    pkv = comparison.get("past_key_values")
    if isinstance(pkv, dict) and pkv.get("max_abs_max") is not None:
        values.append(float(pkv["max_abs_max"]))
    return max(values)


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "output": report["output"],
        "passed": report["passed"],
        "prefill_compile_lengths": report["prefill_compile_lengths"],
        "max_abs": max(
            (float(row["max_abs_observed"]) for row in report["rows"]),
            default=None,
        ),
        "elapsed_seconds": report["elapsed_seconds"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
