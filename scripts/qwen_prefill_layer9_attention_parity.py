"""Production-shaped layer-9 attention parity repro for Talker prefill."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from torch.nn.attention import SDPBackend, sdpa_kernel
from transformers.cache_utils import DynamicCache

from faster_qwen3_tts import FasterQwen3TTS
import qwen_tts.core.models.modeling_qwen3_tts as qwen_modeling
from qwen_prefill_compile_parity import (
    _actual_talker_attn,
    _compile_disable_context,
    _configure_precision,
    _force_talker_attn_implementation,
    _probe_attention_calls,
    _runtime_metadata,
    _tensor_fingerprint,
)


@torch.library.custom_op("qtb_layer9_repro::strict_sdpa", mutates_args=())
def _strict_sdpa(
    query: torch.Tensor,
    key: torch.Tensor,
    value: torch.Tensor,
    scaling: float,
    num_key_value_groups: int,
) -> torch.Tensor:
    key_states = qwen_modeling.repeat_kv(key, num_key_value_groups)
    value_states = qwen_modeling.repeat_kv(value, num_key_value_groups)
    output = F.scaled_dot_product_attention(
        query,
        key_states,
        value_states,
        attn_mask=None,
        dropout_p=0.0,
        scale=scaling,
    )
    return output.transpose(1, 2).contiguous()


@_strict_sdpa.register_fake
def _(
    query: torch.Tensor,
    key: torch.Tensor,
    value: torch.Tensor,
    scaling: float,
    num_key_value_groups: int,
) -> torch.Tensor:
    return torch.empty(
        (query.shape[0], query.shape[2], query.shape[1], query.shape[3]),
        dtype=query.dtype,
        device=query.device,
    )


STAGES = (
    "layer_input",
    "input_layernorm",
    "q_proj",
    "k_proj",
    "v_proj",
    "q_norm",
    "k_norm",
    "q_rope",
    "k_rope",
    "attention_context",
    "o_proj",
    "attention_output",
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
    parser.add_argument("--layer-index", type=int, default=9)
    parser.add_argument("--stage", choices=STAGES, default="attention_output")
    parser.add_argument(
        "--attention-core-mode",
        default="default",
        choices=("default", "math_sdpa", "eager_formula", "strict_sdpa"),
    )
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
        default="strict_mul",
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
    m, talker, _config, tie, tam, tth, tpe, metadata = model._prepare_generation_custom(
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

    attention_call_probe = _probe_attention_calls(
        talker,
        tie,
        tam,
        tth,
        tpe,
        prefill_mask_mode="skip",
    )

    with _compile_disable_context(
        rmsnorm=False,
        rope=False,
        rmsnorm_compat_mode=args.rmsnorm_compat_mode,
        rope_compat_mode=args.rope_compat_mode,
        mlp_compat_mode=args.mlp_compat_mode,
    ):
        layer_input, cache_position, position_embeddings = _materialize_layer_input(
            talker,
            tie,
            args.layer_index,
        )
        eager = _run_layer_stage(
            talker,
            layer_input,
            cache_position,
            position_embeddings,
            args,
            compiled=False,
        )
        compiled = _run_layer_stage(
            talker,
            layer_input,
            cache_position,
            position_embeddings,
            args,
            compiled=True,
        )

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
        "attention_call_probe": attention_call_probe,
        "layer_index": args.layer_index,
        "stage": args.stage,
        "attention_core_mode": args.attention_core_mode,
        "rmsnorm_compat_mode": args.rmsnorm_compat_mode,
        "rope_compat_mode": args.rope_compat_mode,
        "mlp_compat_mode": args.mlp_compat_mode,
        "metadata": metadata,
        "production_signature": {
            "use_cache": True,
            "cache_type": "DynamicCache",
            "attention_mask": None,
            "verified_mask_skip": True,
            "cache_position": _tensor_fingerprint(cache_position),
        },
        "input": {
            "talker_input_embeds": _tensor_fingerprint(tie),
            "attention_mask": _tensor_fingerprint(tam),
            "layer_input": _tensor_fingerprint(layer_input),
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
                "attention_call_probe": attention_call_probe,
                "stage": args.stage,
                "max_abs": comparison["max_abs"],
                "rmse": comparison["rmse"],
            },
            sort_keys=True,
        )
    )
    return 0


def _materialize_layer_input(
    talker: Any,
    inputs_embeds: torch.Tensor,
    layer_index: int,
) -> tuple[torch.Tensor, torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
    model = talker.model
    cache_position = torch.arange(
        0,
        inputs_embeds.shape[1],
        device=inputs_embeds.device,
    )
    position_ids = cache_position.view(1, 1, -1).expand(3, inputs_embeds.shape[0], -1)
    text_position_ids = position_ids[0]
    position_embeddings = model.rotary_emb(inputs_embeds, position_ids)
    hidden_states = inputs_embeds
    past_key_values = DynamicCache()
    with torch.inference_mode():
        for decoder_layer in model.layers[:layer_index]:
            hidden_states = decoder_layer(
                hidden_states,
                attention_mask=None,
                position_ids=text_position_ids,
                past_key_values=past_key_values,
                output_attentions=False,
                use_cache=True,
                cache_position=cache_position,
                position_embeddings=position_embeddings,
            )[0]
        torch.cuda.synchronize()
    return hidden_states.detach(), cache_position, position_embeddings


def _run_layer_stage(
    talker: Any,
    layer_input: torch.Tensor,
    cache_position: torch.Tensor,
    position_embeddings: tuple[torch.Tensor, torch.Tensor],
    args: argparse.Namespace,
    *,
    compiled: bool,
) -> torch.Tensor:
    fn = _make_layer_stage_target(talker, cache_position, position_embeddings, args)
    if compiled:
        fn = torch.compile(fn, backend="inductor", fullgraph=True, dynamic=False)
    with torch.inference_mode():
        if args.attention_core_mode == "math_sdpa":
            with sdpa_kernel(SDPBackend.MATH):
                out = fn(layer_input)
                torch.cuda.synchronize()
        else:
            out = fn(layer_input)
            torch.cuda.synchronize()
    return out.detach().cpu().contiguous()


def _make_layer_stage_target(
    talker: Any,
    cache_position: torch.Tensor,
    position_embeddings: tuple[torch.Tensor, torch.Tensor],
    args: argparse.Namespace,
):
    layer = talker.model.layers[args.layer_index]
    text_position_ids = cache_position.view(1, -1).expand(1, -1)

    def target(hidden_states: torch.Tensor) -> torch.Tensor:
        return _layer_stage(
            layer,
            hidden_states,
            text_position_ids,
            cache_position,
            position_embeddings,
            args.stage,
            args.attention_core_mode,
        )

    return target


def _layer_stage(
    layer: Any,
    hidden_states: torch.Tensor,
    position_ids: torch.Tensor,
    cache_position: torch.Tensor,
    position_embeddings: tuple[torch.Tensor, torch.Tensor],
    stage: str,
    attention_core_mode: str,
) -> torch.Tensor:
    if stage == "layer_input":
        return hidden_states

    residual = hidden_states
    hidden_states = layer.input_layernorm(hidden_states)
    if stage == "input_layernorm":
        return hidden_states

    self_attn = layer.self_attn
    input_shape = hidden_states.shape[:-1]
    hidden_shape = (*input_shape, -1, self_attn.head_dim)

    q_proj = self_attn.q_proj(hidden_states).view(hidden_shape)
    k_proj = self_attn.k_proj(hidden_states).view(hidden_shape)
    v_proj = self_attn.v_proj(hidden_states).view(hidden_shape)
    if stage == "q_proj":
        return q_proj
    if stage == "k_proj":
        return k_proj
    if stage == "v_proj":
        return v_proj

    query_states = self_attn.q_norm(q_proj).transpose(1, 2)
    key_states = self_attn.k_norm(k_proj).transpose(1, 2)
    value_states = v_proj.transpose(1, 2)
    if stage == "q_norm":
        return query_states
    if stage == "k_norm":
        return key_states

    cos, sin = position_embeddings
    query_states, key_states = qwen_rope(
        query_states,
        key_states,
        cos,
        sin,
        self_attn.rope_scaling["mrope_section"],
        self_attn.rope_scaling["interleaved"],
    )
    if stage == "q_rope":
        return query_states
    if stage == "k_rope":
        return key_states

    past_key_values = DynamicCache()
    cache_kwargs = {"sin": sin, "cos": cos, "cache_position": cache_position}
    key_states, value_states = past_key_values.update(
        key_states,
        value_states,
        self_attn.layer_idx,
        cache_kwargs,
    )
    if attention_core_mode == "strict_sdpa":
        attn_output = _strict_sdpa(
            query_states,
            key_states,
            value_states,
            self_attn.scaling,
            self_attn.num_key_value_groups,
        )
    else:
        attention_interface = qwen_attention_interface(self_attn, attention_core_mode)
        attn_output, _attn_weights = attention_interface(
            self_attn,
            query_states,
            key_states,
            value_states,
            None,
            dropout=0.0 if not self_attn.training else self_attn.attention_dropout,
            scaling=self_attn.scaling,
            sliding_window=self_attn.sliding_window,
        )
    if stage == "attention_context":
        return attn_output

    attn_output = attn_output.reshape(*input_shape, -1).contiguous()
    if stage == "o_proj":
        return self_attn.o_proj(attn_output)

    attn_output = self_attn.o_proj(attn_output)
    if stage == "attention_output":
        return attn_output

    raise ValueError(f"Unsupported stage: {stage}")


def qwen_rope(
    query_states: torch.Tensor,
    key_states: torch.Tensor,
    cos: torch.Tensor,
    sin: torch.Tensor,
    mrope_section: list[int],
    interleaved: bool,
) -> tuple[torch.Tensor, torch.Tensor]:
    return qwen_modeling.apply_multimodal_rotary_pos_emb(
        query_states,
        key_states,
        cos,
        sin,
        mrope_section,
        interleaved,
    )


def qwen_attention_interface(self_attn: Any, attention_core_mode: str):
    if attention_core_mode == "eager_formula":
        return qwen_modeling.eager_attention_forward
    if self_attn.config._attn_implementation == "eager":
        return qwen_modeling.eager_attention_forward
    return qwen_modeling.ALL_ATTENTION_FUNCTIONS[self_attn.config._attn_implementation]


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
