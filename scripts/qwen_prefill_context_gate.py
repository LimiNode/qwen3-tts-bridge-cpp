"""Run raw/strict/compiled prefill compatibility gates on one real prompt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch

from faster_qwen3_tts import FasterQwen3TTS
from qwen_prefill_compile_parity import (
    _actual_talker_attn,
    _compare_generation,
    _compare_prefill_outputs,
    _compile_disable_context,
    _configure_precision,
    _force_talker_attn_implementation,
    _generation_repeats,
    _prefill_once,
    _probe_attention_calls,
    _resolve_prefill_mask_mode,
    _runtime_metadata,
    _snapshot_prefill_output,
    _tensor_fingerprint,
    _top_logit_summary,
    _validate_generation_comparisons,
    _validate_attention_probe,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    parser.add_argument("--text", default="I am your robot, I am your worker.")
    parser.add_argument("--language", default="English")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--device-profile", default="auto")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument(
        "--force-talker-attn-implementation",
        default="sdpa",
        choices=("", "eager", "sdpa"),
    )
    parser.add_argument(
        "--prefill-mask-mode",
        default="auto",
        choices=("auto", "explicit", "skip"),
    )
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--skip-generation", action="store_true")
    parser.add_argument("--allow-partial-generation", action="store_true")
    parser.add_argument("--matmul-precision", default="high")
    parser.add_argument("--disable-tf32", action="store_true")
    parser.add_argument("--trace-attention-calls", action="store_true")
    parser.add_argument("--include-reduce-overhead", action="store_true")
    parser.add_argument("--include-component-ablation", action="store_true")
    parser.add_argument("--include-product-compat", action="store_true")
    parser.add_argument("--compact-output", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    _configure_precision(args)
    model = FasterQwen3TTS.from_pretrained(
        args.model,
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
        prefill_compile_compat_mode=None,
    )
    _eval_inner_modules(model)
    prepared = model._prepare_generation_custom(
        text=args.text,
        language=args.language,
        speaker=args.speaker,
        instruct=args.instruction or None,
        non_streaming_mode=True,
        return_metadata=True,
    )
    m, talker, config, tie, tam, tth, tpe, metadata = prepared

    forced_attn_updates = 0
    if args.force_talker_attn_implementation:
        forced_attn_updates = _force_talker_attn_implementation(
            talker,
            args.force_talker_attn_implementation,
        )
        metadata = dict(metadata)
        metadata["prefill_attn_implementation"] = _actual_talker_attn(talker)
        metadata["prefill_attn_implementation_forced"] = True
        metadata["prefill_attn_implementation_forced_updates"] = forced_attn_updates
    actual_talker_attn = _actual_talker_attn(talker)

    attention_call_probe = None
    if args.trace_attention_calls:
        resolved_mask_mode = _resolve_prefill_mask_mode(args.prefill_mask_mode, metadata)
        attention_call_probe = _probe_attention_calls(
            talker,
            tie,
            tam,
            tth,
            tpe,
            prefill_mask_mode=resolved_mask_mode,
        )
        _validate_attention_probe(actual_talker_attn, attention_call_probe)

    contexts = _context_specs(
        include_reduce_overhead=args.include_reduce_overhead,
        include_component_ablation=args.include_component_ablation,
        include_product_compat=args.include_product_compat,
    )
    prefill_runs: dict[str, list[dict[str, Any]]] = {}
    prefill_objects: dict[str, list[Any]] = {}
    generation_runs: dict[str, list[dict[str, Any]]] = {}

    for spec in contexts:
        with _compile_disable_context(**spec["compat"]):
            rows = []
            objects = []
            for repeat_index in range(args.repeats):
                out, profile = _prefill_once(
                    talker,
                    tie,
                    tam,
                    tth,
                    tpe,
                    metadata,
                    spec["backend"],
                    args.prefill_mask_mode,
                    spec.get("prefill_compile_compat_mode", "none"),
                )
                snapshot = _snapshot_prefill_output(out)
                objects.append(snapshot)
                rows.append(
                    {
                        "repeat": repeat_index + 1,
                        "profile": profile,
                        "logits_last": _tensor_fingerprint(
                            snapshot["logits"][:, -1, :]
                        ),
                        "past_hidden": _tensor_fingerprint(snapshot["past_hidden"]),
                        "top_logits": _top_logit_summary(snapshot["logits"][:, -1, :]),
                    }
                )
            prefill_runs[spec["label"]] = rows
            prefill_objects[spec["label"]] = objects

            if not args.skip_generation:
                generation_runs[spec["label"]] = _generation_repeats(
                    model,
                    m,
                    talker,
                    config,
                    tie,
                    tam,
                    tth,
                    tpe,
                    metadata,
                    spec["backend"],
                    repeats=args.repeats,
                    max_new_tokens=args.max_new_tokens,
                    chunk_size=args.chunk_size,
                    prefill_mask_mode=args.prefill_mask_mode,
                    prefill_compile_compat_mode=spec.get(
                        "prefill_compile_compat_mode",
                        "none",
                    ),
                )

    prefill_comparisons = _compare_all_prefill(prefill_objects)
    generation_comparisons = {}
    if generation_runs:
        generation_comparisons = _compare_all_generation(
            generation_runs,
            eos_id=int(config.codec_eos_token_id),
            allow_partial_generation=args.allow_partial_generation,
        )
        _validate_context_generation_comparisons(generation_comparisons)

    report = {
        "artifact_schema_version": 1,
        "output": str(args.output),
        "model": args.model,
        "text": args.text,
        "language": args.language,
        "speaker": args.speaker,
        "instruction": args.instruction,
        "device": args.device,
        "device_profile": args.device_profile,
        "runtime": _runtime_metadata(args.device),
        "dtype": args.dtype,
        "attn_implementation": args.attn_implementation,
        "force_talker_attn_implementation": args.force_talker_attn_implementation,
        "actual_talker_attn_implementation": actual_talker_attn,
        "forced_talker_attn_config_updates": forced_attn_updates,
        "attention_call_probe": attention_call_probe,
        "include_component_ablation": args.include_component_ablation,
        "include_product_compat": args.include_product_compat,
        "prefill_mask_mode_requested": args.prefill_mask_mode,
        "contexts": contexts,
        "repeats": args.repeats,
        "max_new_tokens": args.max_new_tokens,
        "chunk_size": args.chunk_size,
        "skip_generation": args.skip_generation,
        "allow_partial_generation": args.allow_partial_generation,
        "compact_output": args.compact_output,
        "inputs": {
            "talker_input_embeds": _tensor_fingerprint(tie),
            "attention_mask": _tensor_fingerprint(tam),
            "trailing_text_hiddens": _tensor_fingerprint(tth),
            "tts_pad_embed": _tensor_fingerprint(tpe),
        },
        "prefill": {
            "runs": prefill_runs,
            "comparisons": prefill_comparisons,
        },
        "generation": {
            "runs": generation_runs,
            "comparisons": generation_comparisons,
        },
    }
    if args.compact_output:
        _compact_report(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(_summary(report), sort_keys=True))
    return 0


def _context_specs(
    *,
    include_reduce_overhead: bool,
    include_component_ablation: bool,
    include_product_compat: bool,
) -> list[dict[str, Any]]:
    raw = _compat("current", "current", "current", "current")
    strict = _compat("strict_custom", "strict_add", "strict_mul", "strict_sdpa")
    rows = [
        {"label": "raw_eager", "backend": "eager", "compat": raw},
        {"label": "strict_eager", "backend": "eager", "compat": strict},
        {
            "label": "strict_inductor_default",
            "backend": "compile_inductor_default",
            "compat": strict,
        },
    ]
    if include_reduce_overhead:
        rows.append(
            {
                "label": "strict_reduce_overhead",
                "backend": "compile_reduce_overhead",
                "compat": strict,
            }
        )
    if include_component_ablation:
        rows.extend(
            [
                {
                    "label": "strict_rmsnorm_eager",
                    "backend": "eager",
                    "compat": _compat("strict_custom", "current", "current", "current"),
                },
                {
                    "label": "strict_rope_eager",
                    "backend": "eager",
                    "compat": _compat("current", "strict_add", "current", "current"),
                },
                {
                    "label": "strict_mlp_eager",
                    "backend": "eager",
                    "compat": _compat("current", "current", "strict_mul", "current"),
                },
                {
                    "label": "strict_sdpa_eager",
                    "backend": "eager",
                    "compat": _compat("current", "current", "current", "strict_sdpa"),
                },
                {
                    "label": "strict_rms_rope_eager",
                    "backend": "eager",
                    "compat": _compat("strict_custom", "strict_add", "current", "current"),
                },
                {
                    "label": "strict_rms_rope_mlp_eager",
                    "backend": "eager",
                    "compat": _compat(
                        "strict_custom",
                        "strict_add",
                        "strict_mul",
                        "current",
                    ),
                },
            ]
        )
    if include_product_compat:
        rows.extend(
            [
                {
                    "label": "product_strict_inductor_default",
                    "backend": "compile_inductor_default",
                    "compat": raw,
                    "prefill_compile_compat_mode": "strict_bf16_sdpa_v1",
                },
                {
                    "label": "product_strict_reduce_overhead",
                    "backend": "compile_reduce_overhead",
                    "compat": raw,
                    "prefill_compile_compat_mode": "strict_bf16_sdpa_v1",
                },
            ]
        )
    return rows


def _compat(
    rmsnorm: str,
    rope: str,
    mlp: str,
    attention: str,
) -> dict[str, Any]:
    return {
        "rmsnorm": False,
        "rope": False,
        "rmsnorm_compat_mode": rmsnorm,
        "rope_compat_mode": rope,
        "mlp_compat_mode": mlp,
        "attention_compat_mode": attention,
    }


def _compare_all_prefill(prefill_objects: dict[str, list[Any]]) -> dict[str, Any]:
    raw = prefill_objects["raw_eager"][0]
    strict = prefill_objects["strict_eager"][0]
    return {
        label: {
            "vs_raw_eager": _compare_prefill_outputs(raw, objects[-1]),
            "vs_strict_eager": _compare_prefill_outputs(strict, objects[-1]),
        }
        for label, objects in prefill_objects.items()
    }


def _compare_all_generation(
    generation_runs: dict[str, list[dict[str, Any]]],
    *,
    eos_id: int,
    allow_partial_generation: bool,
) -> dict[str, Any]:
    raw = generation_runs["raw_eager"][0]
    strict = generation_runs["strict_eager"][0]
    return {
        label: {
            "vs_strict_eager": _compare_generation(
                strict,
                rows[-1],
                eos_id=eos_id,
                allow_partial_generation=allow_partial_generation,
            ),
            "vs_raw_eager": _compare_generation(
                raw,
                rows[-1],
                eos_id=eos_id,
                allow_partial_generation=allow_partial_generation,
            ),
            "frame_accounting": rows[-1].get("frame_accounting"),
        }
        for label, rows in generation_runs.items()
    }


def _validate_context_generation_comparisons(comparisons: dict[str, Any]) -> None:
    _validate_generation_comparisons(
        {
            f"{label}.vs_raw_eager": values["vs_raw_eager"]
            for label, values in comparisons.items()
        }
    )
    _validate_generation_comparisons(
        {
            f"{label}.vs_strict_eager": values["vs_strict_eager"]
            for label, values in comparisons.items()
        }
    )


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    prefill = report["prefill"]["comparisons"]
    generation = report["generation"]["comparisons"]
    return {
        "output": str(report.get("output", "")),
        "attention_call_probe": report.get("attention_call_probe"),
        "prefill_vs_raw": {
            label: values["vs_raw_eager"]["logits_last"]["max_abs"]
            for label, values in prefill.items()
        },
        "generation_vs_raw": {
            label: {
                "same_codec": values["vs_raw_eager"]["same_codec"],
                "same_frame_count": values["vs_raw_eager"]["same_frame_count"],
                "eos_equal": values["vs_raw_eager"]["eos_equal"],
                "termination_equal": values["vs_raw_eager"]["termination_equal"],
                "semantic_pass": values["vs_raw_eager"]["semantic_pass"],
                "stop_reason": (values.get("frame_accounting") or {}).get("stop_reason"),
            }
            for label, values in generation.items()
        },
    }


def _compact_report(report: dict[str, Any]) -> None:
    for rows in report.get("generation", {}).get("runs", {}).values():
        for row in rows:
            row.pop("codec_values", None)
            row.pop("timings", None)


def _eval_inner_modules(model: Any) -> None:
    for name in ("model", "talker_graph", "predictor_graph", "predictor_graph_greedy"):
        module = getattr(model, name, None)
        if hasattr(module, "eval"):
            module.eval()


if __name__ == "__main__":
    raise SystemExit(main())
