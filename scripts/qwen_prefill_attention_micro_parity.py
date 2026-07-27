"""Bisect FasterQwen talker layer-0 attention parity without forward hooks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from faster_qwen3_tts import FasterQwen3TTS
from qwen_tts.core.models.modeling_qwen3_tts import (
    apply_multimodal_rotary_pos_emb,
    repeat_kv,
)
from transformers.cache_utils import DynamicCache
from transformers.masking_utils import (
    create_causal_mask,
    create_sliding_window_causal_mask,
)

CHECKPOINT_NAMES = (
    "layer_input",
    "input_layernorm",
    "q_proj",
    "q_norm",
    "k_proj",
    "k_norm",
    "v_proj",
    "q_rope",
    "k_rope",
    "scores",
    "scores_masked",
    "softmax_probs",
    "attention_context",
    "o_proj_input",
    "o_proj_output",
    "post_attention_residual",
    "mlp_input",
    "mlp_gate",
    "mlp_up",
    "mlp_down",
    "layer_output",
)
CHECKPOINT_INDEX = {name: index for index, name in enumerate(CHECKPOINT_NAMES)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    parser.add_argument("--text", default="I am your robot, I am your worker.")
    parser.add_argument("--language", default="English")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="eager")
    parser.add_argument("--right-backend", default="compile_backend_eager")
    parser.add_argument("--checkpoint", action="append", dest="checkpoints")
    parser.add_argument("--attention-core-fp32", action="store_true")
    parser.add_argument("--matmul-precision", default="high")
    parser.add_argument("--disable-tf32", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    _configure_precision(args)
    model = FasterQwen3TTS.from_pretrained(
        args.model,
        device=args.device,
        dtype=args.dtype,
        attn_implementation=args.attn_implementation,
    )
    (
        _m,
        talker,
        _config,
        tie,
        tam,
        _tth,
        _tpe,
        metadata,
    ) = model._prepare_generation_custom(
        text=args.text,
        language=args.language,
        speaker=args.speaker,
        instruct=None,
        non_streaming_mode=True,
        return_metadata=True,
    )
    talker.eval()
    checkpoint_names = tuple(args.checkpoints or CHECKPOINT_NAMES)
    for name in checkpoint_names:
        if name not in CHECKPOINT_INDEX:
            raise ValueError(f"Unsupported checkpoint: {name}")
    raw = _snapshot(
        tuple(
            _layer0_attention_checkpoint(talker.model, tie, tam, name)
            if not args.attention_core_fp32
            else _layer0_attention_checkpoint(
                talker.model,
                tie,
                tam,
                name,
                attention_core_fp32=True,
            )
            for name in checkpoint_names
        )
    )
    compiled_fn = _compile_checkpoint_fn(
        lambda embeds, mask: tuple(
            _layer0_attention_checkpoint(
                talker.model,
                embeds,
                mask,
                name,
                attention_core_fp32=args.attention_core_fp32,
            )
            for name in checkpoint_names
        ),
        args.right_backend,
    )
    compiled = _snapshot(compiled_fn(tie, tam))
    comparisons = [
        _compare(name, raw[index], compiled[index])
        for index, name in enumerate(checkpoint_names)
    ]
    report = {
        "artifact_schema_version": 1,
        "model": args.model,
        "text": args.text,
        "language": args.language,
        "speaker": args.speaker,
        "device": args.device,
        "dtype": args.dtype,
        "attn_implementation": args.attn_implementation,
        "right_backend": args.right_backend,
        "attention_core_fp32": args.attention_core_fp32,
        "checkpoints": checkpoint_names,
        "metadata": metadata,
        "comparisons": comparisons,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    first_diff = next((row for row in comparisons if row["max_abs"] != 0.0), None)
    print(json.dumps({"output": str(args.output), "first_diff": first_diff}))
    return 0


def _configure_precision(args: argparse.Namespace) -> None:
    if args.matmul_precision:
        torch.set_float32_matmul_precision(args.matmul_precision)
    if args.disable_tf32:
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction = False
        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False


def _compile_checkpoint_fn(
    function: Callable[..., tuple[torch.Tensor, ...]],
    backend: str,
) -> Callable[..., Any]:
    if backend == "eager":
        return function
    compile_backend = "inductor"
    mode = None
    if backend == "compile_backend_eager":
        compile_backend = "eager"
    elif backend == "compile_backend_aot_eager":
        compile_backend = "aot_eager"
    elif backend == "compile_reduce_overhead":
        mode = "reduce-overhead"
    elif backend not in {"compile_default", "compile_inductor_default"}:
        raise ValueError(f"Unsupported backend: {backend}")
    return torch.compile(
        function,
        backend=compile_backend,
        mode=mode,
        fullgraph=True,
        dynamic=False,
    )


def _layer0_attention_checkpoint(
    model: Any,
    inputs_embeds: torch.Tensor,
    attention_mask: torch.Tensor,
    checkpoint: str,
    *,
    attention_core_fp32: bool = False,
) -> torch.Tensor:
    cache_position = torch.arange(inputs_embeds.shape[1], device=inputs_embeds.device)
    position_ids = cache_position.view(1, 1, -1).expand(3, inputs_embeds.shape[0], -1)
    text_position_ids = position_ids[0]
    cache = DynamicCache()
    mask_function = (
        create_causal_mask
        if model.config.sliding_window is None
        else create_sliding_window_causal_mask
    )
    causal_mask = mask_function(
        config=model.config,
        input_embeds=inputs_embeds,
        attention_mask=attention_mask,
        cache_position=cache_position,
        past_key_values=cache,
        position_ids=text_position_ids,
    )
    position_embeddings = model.rotary_emb(inputs_embeds, position_ids)

    layer = model.layers[0]
    attn = layer.self_attn
    layer_input = inputs_embeds
    if checkpoint == "layer_input":
        return layer_input
    input_norm = layer.input_layernorm(layer_input)
    if checkpoint == "input_layernorm":
        return input_norm

    input_shape = input_norm.shape[:-1]
    hidden_shape = (*input_shape, -1, attn.head_dim)
    q_proj = attn.q_proj(input_norm).view(hidden_shape)
    if checkpoint == "q_proj":
        return q_proj
    q_norm = attn.q_norm(q_proj).transpose(1, 2)
    if checkpoint == "q_norm":
        return q_norm
    k_proj = attn.k_proj(input_norm).view(hidden_shape)
    if checkpoint == "k_proj":
        return k_proj
    k_norm = attn.k_norm(k_proj).transpose(1, 2)
    if checkpoint == "k_norm":
        return k_norm
    v_proj = attn.v_proj(input_norm).view(hidden_shape).transpose(1, 2)
    if checkpoint == "v_proj":
        return v_proj

    cos, sin = position_embeddings
    q_rope, k_rope = apply_multimodal_rotary_pos_emb(
        q_norm,
        k_norm,
        cos,
        sin,
        attn.rope_scaling["mrope_section"],
        attn.rope_scaling["interleaved"],
    )
    if checkpoint == "q_rope":
        return q_rope
    if checkpoint == "k_rope":
        return k_rope

    key_states = repeat_kv(k_rope, attn.num_key_value_groups)
    value_states = repeat_kv(v_proj, attn.num_key_value_groups)
    attn_query = q_rope.float() if attention_core_fp32 else q_rope
    attn_key = key_states.float() if attention_core_fp32 else key_states
    attn_value = value_states.float() if attention_core_fp32 else value_states
    scores = torch.matmul(attn_query, attn_key.transpose(2, 3)) * attn.scaling
    if checkpoint == "scores":
        return scores
    if causal_mask is None:
        scores_for_softmax = scores
    else:
        causal = causal_mask[:, :, :, : key_states.shape[-2]]
        scores_for_softmax = scores + causal
    if checkpoint == "scores_masked":
        return scores_for_softmax
    softmax_probs = F.softmax(scores_for_softmax, dim=-1, dtype=torch.float32)
    if not attention_core_fp32:
        softmax_probs = softmax_probs.to(q_rope.dtype)
    if checkpoint == "softmax_probs":
        return softmax_probs
    context = torch.matmul(softmax_probs, attn_value)
    if attention_core_fp32:
        context = context.to(q_rope.dtype)
    if checkpoint == "attention_context":
        return context
    context = context.transpose(1, 2).contiguous()
    o_proj_input = context.reshape(*input_shape, -1).contiguous()
    if checkpoint == "o_proj_input":
        return o_proj_input
    o_proj_output = attn.o_proj(o_proj_input)
    if checkpoint == "o_proj_output":
        return o_proj_output
    post_attention_residual = layer_input + o_proj_output
    if checkpoint == "post_attention_residual":
        return post_attention_residual
    mlp_input = layer.post_attention_layernorm(post_attention_residual)
    if checkpoint == "mlp_input":
        return mlp_input
    mlp_gate = layer.mlp.gate_proj(mlp_input)
    if checkpoint == "mlp_gate":
        return mlp_gate
    mlp_up = layer.mlp.up_proj(mlp_input)
    if checkpoint == "mlp_up":
        return mlp_up
    mlp_down = layer.mlp.down_proj(layer.mlp.act_fn(mlp_gate) * mlp_up)
    if checkpoint == "mlp_down":
        return mlp_down
    layer_output = post_attention_residual + mlp_down
    if checkpoint == "layer_output":
        return layer_output
    raise ValueError(f"Unsupported checkpoint: {checkpoint}")


def _snapshot(tensors: tuple[torch.Tensor, ...]) -> tuple[torch.Tensor, ...]:
    return tuple(tensor.detach().cpu().contiguous() for tensor in tensors)


def _compare(name: str, left: torch.Tensor, right: torch.Tensor) -> dict[str, Any]:
    left_f = left.float()
    right_f = right.float()
    diff = (left_f - right_f).abs()
    rmse = torch.sqrt(torch.mean((left_f - right_f) ** 2))
    flat_index = int(torch.argmax(diff).item()) if diff.numel() else 0
    return {
        "name": name,
        "shape": list(left.shape),
        "dtype": str(left.dtype),
        "stride": list(left.stride()),
        "contiguous": bool(left.is_contiguous()),
        "max_abs": float(diff.max().item()) if diff.numel() else 0.0,
        "mean_abs": float(diff.mean().item()) if diff.numel() else 0.0,
        "rmse": float(rmse.item()) if diff.numel() else 0.0,
        "max_abs_flat_index": flat_index,
        "cosine": _cosine(left_f, right_f),
    }


def _cosine(left: torch.Tensor, right: torch.Tensor) -> float | None:
    left_flat = left.flatten()
    right_flat = right.flatten()
    denom = torch.linalg.vector_norm(left_flat) * torch.linalg.vector_norm(right_flat)
    if float(denom.item()) == 0.0:
        return None
    return float(torch.dot(left_flat, right_flat).item() / denom.item())


if __name__ == "__main__":
    raise SystemExit(main())
