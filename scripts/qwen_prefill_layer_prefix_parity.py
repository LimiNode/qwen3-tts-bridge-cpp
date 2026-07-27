"""Compare Talker layer prefixes between eager and Inductor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch

from faster_qwen3_tts import FasterQwen3TTS
from qwen_prefill_compile_parity import (
    _actual_talker_attn,
    _compile_disable_context,
    _configure_precision,
    _force_talker_attn_implementation,
    _runtime_metadata,
    _tensor_fingerprint,
)


STAGES = (
    "layer_input",
    "input_layernorm",
    "attention_output",
    "post_attention_residual",
    "post_attention_layernorm",
    "mlp_gate",
    "mlp_up",
    "mlp_act",
    "mlp_mul",
    "mlp_output",
    "layer_output",
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
        default="",
        choices=("", "eager", "sdpa"),
    )
    parser.add_argument(
        "--mode",
        choices=("prefix", "layer-stage"),
        default="prefix",
    )
    parser.add_argument("--prefix-layers", type=int, default=1)
    parser.add_argument("--layer-index", type=int, default=0)
    parser.add_argument("--stage", choices=STAGES, default="layer_output")
    parser.add_argument("--matmul-precision", default="high")
    parser.add_argument("--disable-tf32", action="store_true")
    parser.add_argument(
        "--rmsnorm-compat-mode",
        default="strict_custom",
        choices=("current", "aten_rms_norm", "f_rms_norm", "strict_custom"),
    )
    parser.add_argument(
        "--rope-compat-mode",
        default="strict_add",
        choices=("current", "strict_add"),
    )
    parser.add_argument(
        "--mlp-compat-mode",
        default="current",
        choices=("current", "strict_mul"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    _configure_precision(args)
    model = FasterQwen3TTS.from_pretrained(
        args.model,
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
    )
    m, talker, _config, tie, tam, _tth, _tpe, metadata = model._prepare_generation_custom(
        text=args.text,
        language=args.language,
        speaker=args.speaker,
        instruct=args.instruction or None,
        non_streaming_mode=True,
        return_metadata=True,
    )
    del m
    talker.eval()
    forced_updates = 0
    if args.force_talker_attn_implementation:
        forced_updates = _force_talker_attn_implementation(
            talker,
            args.force_talker_attn_implementation,
        )
        metadata = dict(metadata)
        metadata["prefill_attn_implementation"] = _actual_talker_attn(talker)
        metadata["prefill_attn_implementation_forced"] = True
        metadata["prefill_attn_implementation_forced_updates"] = forced_updates

    with _compile_disable_context(
        rmsnorm=False,
        rope=False,
        rmsnorm_compat_mode=args.rmsnorm_compat_mode,
        rope_compat_mode=args.rope_compat_mode,
        mlp_compat_mode=args.mlp_compat_mode,
    ):
        eager = _run_target(talker, tie, args, compiled=False)
        compiled = _run_target(talker, tie, args, compiled=True)

    comparison = _compare(eager, compiled)
    report = {
        "artifact_schema_version": 1,
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
        "actual_talker_attn_implementation": _actual_talker_attn(talker),
        "forced_talker_attn_config_updates": forced_updates,
        "mode": args.mode,
        "prefix_layers": args.prefix_layers,
        "layer_index": args.layer_index,
        "stage": args.stage,
        "rmsnorm_compat_mode": args.rmsnorm_compat_mode,
        "rope_compat_mode": args.rope_compat_mode,
        "mlp_compat_mode": args.mlp_compat_mode,
        "metadata": metadata,
        "input": {
            "talker_input_embeds": _tensor_fingerprint(tie),
            "attention_mask": _tensor_fingerprint(tam),
        },
        "eager": _tensor_fingerprint(eager),
        "compile_inductor_default": _tensor_fingerprint(compiled),
        "comparison": comparison,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "actual_talker_attn_implementation": report[
                    "actual_talker_attn_implementation"
                ],
                "mode": args.mode,
                "prefix_layers": args.prefix_layers,
                "layer_index": args.layer_index,
                "stage": args.stage,
                "max_abs": comparison["max_abs"],
                "rmse": comparison["rmse"],
            },
            sort_keys=True,
        )
    )
    return 0


def _run_target(talker: Any, inputs_embeds: torch.Tensor, args: argparse.Namespace, *, compiled: bool) -> torch.Tensor:
    fn = _make_target(talker, args)
    if compiled:
        fn = torch.compile(fn, backend="inductor", fullgraph=True, dynamic=False)
    with torch.inference_mode():
        out = fn(inputs_embeds)
        torch.cuda.synchronize()
    return out.detach().cpu().contiguous()


def _make_target(talker: Any, args: argparse.Namespace):
    def target(inputs_embeds: torch.Tensor) -> torch.Tensor:
        return _layer_prefix_or_stage(talker, inputs_embeds, args)

    return target


def _layer_prefix_or_stage(talker: Any, inputs_embeds: torch.Tensor, args: argparse.Namespace) -> torch.Tensor:
    model = talker.model
    hidden_states = inputs_embeds
    cache_position = torch.arange(
        0,
        hidden_states.shape[1],
        device=hidden_states.device,
    )
    position_ids = cache_position.view(1, 1, -1).expand(3, hidden_states.shape[0], -1)
    text_position_ids = position_ids[0]
    position_embeddings = model.rotary_emb(hidden_states, position_ids)

    if args.mode == "prefix":
        for decoder_layer in model.layers[: args.prefix_layers]:
            hidden_states = decoder_layer(
                hidden_states,
                attention_mask=None,
                position_ids=text_position_ids,
                past_key_values=None,
                output_attentions=False,
                use_cache=False,
                cache_position=cache_position,
                position_embeddings=position_embeddings,
            )[0]
        return hidden_states

    for decoder_layer in model.layers[: args.layer_index]:
        hidden_states = decoder_layer(
            hidden_states,
            attention_mask=None,
            position_ids=text_position_ids,
            past_key_values=None,
            output_attentions=False,
            use_cache=False,
            cache_position=cache_position,
            position_embeddings=position_embeddings,
        )[0]

    return _layer_stage(
        model.layers[args.layer_index],
        hidden_states,
        text_position_ids,
        cache_position,
        position_embeddings,
        args.stage,
    )


def _layer_stage(
    layer: Any,
    hidden_states: torch.Tensor,
    position_ids: torch.Tensor,
    cache_position: torch.Tensor,
    position_embeddings: tuple[torch.Tensor, torch.Tensor],
    stage: str,
) -> torch.Tensor:
    if stage == "layer_input":
        return hidden_states

    residual = hidden_states
    hidden_states = layer.input_layernorm(hidden_states)
    if stage == "input_layernorm":
        return hidden_states

    hidden_states, _attn_weights = layer.self_attn(
        hidden_states=hidden_states,
        attention_mask=None,
        position_ids=position_ids,
        past_key_values=None,
        output_attentions=False,
        use_cache=False,
        cache_position=cache_position,
        position_embeddings=position_embeddings,
    )
    if stage == "attention_output":
        return hidden_states

    hidden_states = residual + hidden_states
    if stage == "post_attention_residual":
        return hidden_states

    residual = hidden_states
    hidden_states = layer.post_attention_layernorm(hidden_states)
    if stage == "post_attention_layernorm":
        return hidden_states

    mlp = layer.mlp
    gate = mlp.gate_proj(hidden_states)
    if stage == "mlp_gate":
        return gate

    up = mlp.up_proj(hidden_states)
    if stage == "mlp_up":
        return up

    activated = mlp.act_fn(gate)
    if stage == "mlp_act":
        return activated

    hidden_states = activated * up
    if stage == "mlp_mul":
        return hidden_states

    hidden_states = mlp.down_proj(hidden_states)
    if stage == "mlp_output":
        return hidden_states

    hidden_states = residual + hidden_states
    if stage == "layer_output":
        return hidden_states

    raise ValueError(f"Unsupported stage: {stage}")


def _compare(left: torch.Tensor, right: torch.Tensor) -> dict[str, Any]:
    left_f = left.float()
    right_f = right.float()
    diff = (left_f - right_f).abs()
    rmse = torch.sqrt(torch.mean((left_f - right_f) ** 2))
    return {
        "shape": list(left.shape),
        "dtype": str(left.dtype),
        "max_abs": float(diff.max().item()),
        "mean_abs": float(diff.mean().item()),
        "rmse": float(rmse.item()),
        "cosine_similarity": float(
            torch.nn.functional.cosine_similarity(
                left_f.flatten(),
                right_f.flatten(),
                dim=0,
            ).item()
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
