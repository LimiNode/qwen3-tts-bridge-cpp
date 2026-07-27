"""Bisect FasterQwen talker layer-0 attention parity without forward hooks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
import transformers.masking_utils as _masking_utils
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
    "key_states",
    "value_states",
    "scores",
    "causal_mask",
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
DEFAULT_CHECKPOINT_NAMES = tuple(
    name
    for name in CHECKPOINT_NAMES
    if name not in {"key_states", "value_states", "causal_mask"}
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    parser.add_argument("--text", default="I am your robot, I am your worker.")
    parser.add_argument("--language", default="English")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--device-profile", default="auto")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="eager")
    parser.add_argument("--right-backend", default="compile_backend_eager")
    parser.add_argument("--checkpoint", action="append", dest="checkpoints")
    parser.add_argument(
        "--qk-norm-variant",
        default="current",
        choices=(
            "current",
            "input_contiguous",
            "output_contiguous",
            "manual_fp32",
            "f_rms_norm",
            "aten_rms_norm",
        ),
    )
    parser.add_argument(
        "--layer-norm-variant",
        default="current",
        choices=(
            "current",
            "input_contiguous",
            "output_contiguous",
            "manual_fp32",
            "f_rms_norm",
            "aten_rms_norm",
        ),
    )
    parser.add_argument(
        "--rope-variant",
        default="current",
        choices=("current", "input_contiguous", "output_contiguous", "fp32"),
    )
    parser.add_argument("--attention-core-fp32", action="store_true")
    parser.add_argument("--force-mask-skip-during-compile", action="store_true")
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
    checkpoint_names = tuple(args.checkpoints or DEFAULT_CHECKPOINT_NAMES)
    for name in checkpoint_names:
        if name not in CHECKPOINT_INDEX:
            raise ValueError(f"Unsupported checkpoint: {name}")
    raw_full_gpu = tuple(
        tensor.detach().clone()
        for tensor in _layer0_trace(
            talker.model,
            tie,
            tam,
            layer_norm_variant=args.layer_norm_variant,
            qk_norm_variant=args.qk_norm_variant,
            rope_variant=args.rope_variant,
            attention_core_fp32=args.attention_core_fp32,
        )
    )
    raw_full = _snapshot(raw_full_gpu)
    compiled_trace_fn = _compile_fn(
        lambda embeds, mask: _layer0_trace(
            talker.model,
            embeds,
            mask,
            layer_norm_variant=args.layer_norm_variant,
            qk_norm_variant=args.qk_norm_variant,
            rope_variant=args.rope_variant,
            attention_core_fp32=args.attention_core_fp32,
            force_mask_skip=args.force_mask_skip_during_compile,
        ),
        args.right_backend,
    )
    with _maybe_force_mask_skip(args.force_mask_skip_during_compile):
        compiled_full = _snapshot(compiled_trace_fn(tie, tam))
    raw = _select(raw_full, checkpoint_names)
    compiled = _select(compiled_full, checkpoint_names)
    comparisons = [
        _compare(name, raw[index], compiled[index])
        for index, name in enumerate(checkpoint_names)
    ]
    stage_ladder = _materialized_stage_ladder(
        talker.model,
        raw_full_gpu,
        args.right_backend,
        layer_norm_variant=args.layer_norm_variant,
        qk_norm_variant=args.qk_norm_variant,
        rope_variant=args.rope_variant,
        attention_core_fp32=args.attention_core_fp32,
        force_mask_skip_during_compile=args.force_mask_skip_during_compile,
    )
    report = {
        "artifact_schema_version": 1,
        "trace_mode": "single_pass",
        "model": args.model,
        "text": args.text,
        "language": args.language,
        "speaker": args.speaker,
        "device": args.device,
        "device_profile": args.device_profile,
        "runtime": _runtime_metadata(args.device),
        "dtype": args.dtype,
        "attn_implementation": args.attn_implementation,
        "right_backend": args.right_backend,
        "layer_norm_variant": args.layer_norm_variant,
        "qk_norm_variant": args.qk_norm_variant,
        "rope_variant": args.rope_variant,
        "attention_core_fp32": args.attention_core_fp32,
        "force_mask_skip_during_compile": args.force_mask_skip_during_compile,
        "checkpoints": checkpoint_names,
        "metadata": metadata,
        "comparisons": comparisons,
        "materialized_stage_ladder": stage_ladder,
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


def _runtime_metadata(device: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "device": device,
    }
    if device.startswith("cuda") and torch.cuda.is_available():
        index = torch.cuda.current_device()
        props = torch.cuda.get_device_properties(index)
        metadata.update(
            {
                "cuda_device_index": index,
                "cuda_device_name": props.name,
                "cuda_compute_capability": [props.major, props.minor],
                "cuda_total_memory_bytes": int(props.total_memory),
                "cuda_total_memory_gib": props.total_memory / (1024**3),
            }
        )
    return metadata


def _compile_fn(
    function: Callable[..., Any],
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


def _layer0_trace(
    model: Any,
    inputs_embeds: torch.Tensor,
    attention_mask: torch.Tensor,
    *,
    layer_norm_variant: str = "current",
    qk_norm_variant: str = "current",
    rope_variant: str = "current",
    attention_core_fp32: bool = False,
    force_mask_skip: bool = False,
) -> tuple[torch.Tensor, ...]:
    cache_position, position_ids, causal_mask = _build_causal_mask(
        model,
        inputs_embeds,
        attention_mask,
        force_mask_skip=force_mask_skip,
    )
    position_embeddings = model.rotary_emb(inputs_embeds, position_ids)

    layer = model.layers[0]
    attn = layer.self_attn
    layer_input = inputs_embeds
    input_norm = _rms_norm(layer.input_layernorm, layer_input, layer_norm_variant)

    input_shape = input_norm.shape[:-1]
    hidden_shape = (*input_shape, -1, attn.head_dim)
    q_proj = attn.q_proj(input_norm).view(hidden_shape)
    k_proj = attn.k_proj(input_norm).view(hidden_shape)
    q_norm = _rms_norm(attn.q_norm, q_proj, qk_norm_variant).transpose(1, 2)
    k_norm = _rms_norm(attn.k_norm, k_proj, qk_norm_variant).transpose(1, 2)
    if qk_norm_variant == "output_contiguous":
        q_norm = q_norm.contiguous()
        k_norm = k_norm.contiguous()
    v_proj = attn.v_proj(input_norm).view(hidden_shape).transpose(1, 2)

    cos, sin = position_embeddings
    q_rope, k_rope = _apply_rope(
        q_norm,
        k_norm,
        cos,
        sin,
        attn.rope_scaling["mrope_section"],
        attn.rope_scaling["interleaved"],
        rope_variant,
    )

    key_states = repeat_kv(k_rope, attn.num_key_value_groups)
    value_states = repeat_kv(v_proj, attn.num_key_value_groups)
    attn_query = q_rope.float() if attention_core_fp32 else q_rope
    attn_key = key_states.float() if attention_core_fp32 else key_states
    attn_value = value_states.float() if attention_core_fp32 else value_states
    scores = torch.matmul(attn_query, attn_key.transpose(2, 3)) * attn.scaling
    if causal_mask is None:
        causal = torch.zeros_like(scores)
    else:
        causal = causal_mask[:, :, :, : key_states.shape[-2]]
    scores_for_softmax = scores + causal
    softmax_probs = F.softmax(scores_for_softmax, dim=-1, dtype=torch.float32)
    if not attention_core_fp32:
        softmax_probs = softmax_probs.to(q_rope.dtype)
    context = torch.matmul(softmax_probs, attn_value)
    if attention_core_fp32:
        context = context.to(q_rope.dtype)
    context = context.transpose(1, 2).contiguous()
    o_proj_input = context.reshape(*input_shape, -1).contiguous()
    o_proj_output = attn.o_proj(o_proj_input)
    post_attention_residual = layer_input + o_proj_output
    mlp_input = _rms_norm(
        layer.post_attention_layernorm,
        post_attention_residual,
        layer_norm_variant,
    )
    mlp_gate = layer.mlp.gate_proj(mlp_input)
    mlp_up = layer.mlp.up_proj(mlp_input)
    mlp_down = layer.mlp.down_proj(layer.mlp.act_fn(mlp_gate) * mlp_up)
    layer_output = post_attention_residual + mlp_down
    return (
        layer_input,
        input_norm,
        q_proj,
        q_norm,
        k_proj,
        k_norm,
        v_proj,
        q_rope,
        k_rope,
        key_states,
        value_states,
        scores,
        causal,
        scores_for_softmax,
        softmax_probs,
        context,
        o_proj_input,
        o_proj_output,
        post_attention_residual,
        mlp_input,
        mlp_gate,
        mlp_up,
        mlp_down,
        layer_output,
    )


def _rms_norm(norm: Any, tensor: torch.Tensor, variant: str) -> torch.Tensor:
    if variant == "current":
        return norm(tensor)
    if variant == "input_contiguous":
        return norm(tensor.contiguous())
    if variant == "manual_fp32":
        input_dtype = tensor.dtype
        values = tensor.float()
        variance = values.pow(2).mean(-1, keepdim=True)
        values = values * torch.rsqrt(variance + norm.variance_epsilon)
        return norm.weight * values.to(input_dtype)
    if variant == "f_rms_norm":
        return F.rms_norm(
            tensor,
            normalized_shape=(tensor.shape[-1],),
            weight=norm.weight,
            eps=norm.variance_epsilon,
        )
    if variant == "aten_rms_norm":
        return torch.ops.aten.rms_norm.default(
            tensor,
            [tensor.shape[-1]],
            norm.weight,
            norm.variance_epsilon,
        )
    if variant == "output_contiguous":
        return norm(tensor)
    raise ValueError(f"Unsupported RMSNorm variant: {variant}")


def _apply_rope(
    q_norm: torch.Tensor,
    k_norm: torch.Tensor,
    cos: torch.Tensor,
    sin: torch.Tensor,
    mrope_section: list[int],
    interleaved: bool,
    variant: str,
) -> tuple[torch.Tensor, torch.Tensor]:
    output_dtype = q_norm.dtype
    if variant == "input_contiguous":
        q_norm = q_norm.contiguous()
        k_norm = k_norm.contiguous()
    elif variant == "fp32":
        q_norm = q_norm.float()
        k_norm = k_norm.float()
        cos = cos.float()
        sin = sin.float()
    elif variant != "current" and variant != "output_contiguous":
        raise ValueError(f"Unsupported rope_variant: {variant}")

    q_rope, k_rope = apply_multimodal_rotary_pos_emb(
        q_norm,
        k_norm,
        cos,
        sin,
        mrope_section,
        interleaved,
    )
    if variant == "fp32":
        q_rope = q_rope.to(output_dtype)
        k_rope = k_rope.to(output_dtype)
    if variant == "output_contiguous":
        q_rope = q_rope.contiguous()
        k_rope = k_rope.contiguous()
    return q_rope, k_rope


def _select(
    trace: tuple[torch.Tensor, ...],
    names: tuple[str, ...],
) -> tuple[torch.Tensor, ...]:
    return tuple(trace[CHECKPOINT_INDEX[name]] for name in names)


def _materialized_stage_ladder(
    model: Any,
    trace: tuple[torch.Tensor, ...],
    backend: str,
    *,
    layer_norm_variant: str,
    qk_norm_variant: str,
    rope_variant: str,
    attention_core_fp32: bool,
    force_mask_skip_during_compile: bool,
) -> list[dict[str, Any]]:
    by_name = dict(zip(CHECKPOINT_NAMES, trace, strict=True))
    layer = model.layers[0]
    attn = layer.self_attn
    input_shape = by_name["input_layernorm"].shape[:-1]

    def causal_mask_stage(
        inputs_embeds: torch.Tensor,
        attention_mask: torch.Tensor,
    ) -> torch.Tensor:
        _, _, causal_mask = _build_causal_mask(
            model,
            inputs_embeds,
            attention_mask,
            force_mask_skip=force_mask_skip_during_compile,
        )
        if causal_mask is None:
            return torch.zeros(
                (
                    inputs_embeds.shape[0],
                    model.config.num_attention_heads,
                    inputs_embeds.shape[1],
                    inputs_embeds.shape[1],
                ),
                dtype=inputs_embeds.dtype,
                device=inputs_embeds.device,
            )
        return causal_mask

    def compare_stage(
        name: str,
        function: Callable[..., torch.Tensor | tuple[torch.Tensor, ...]],
        *inputs: torch.Tensor,
        output_names: tuple[str, ...],
    ) -> dict[str, Any]:
        with torch.inference_mode():
            raw_output = _as_tuple(function(*inputs))
            compiled = _compile_fn(function, backend)
            with _maybe_force_mask_skip(force_mask_skip_during_compile):
                compiled_output = _as_tuple(compiled(*inputs))
        rows = [
            _compare(output_name, left.detach().cpu(), right.detach().cpu())
            for output_name, left, right in zip(
                output_names,
                raw_output,
                compiled_output,
                strict=True,
            )
        ]
        first_diff = next((row for row in rows if row["max_abs"] != 0.0), None)
        return {"stage": name, "outputs": rows, "first_diff": first_diff}

    def qkv_stage(input_norm: torch.Tensor) -> tuple[torch.Tensor, ...]:
        hidden_shape = (*input_norm.shape[:-1], -1, attn.head_dim)
        q_proj = attn.q_proj(input_norm).view(hidden_shape)
        k_proj = attn.k_proj(input_norm).view(hidden_shape)
        q_norm = _rms_norm(attn.q_norm, q_proj, qk_norm_variant).transpose(1, 2)
        k_norm = _rms_norm(attn.k_norm, k_proj, qk_norm_variant).transpose(1, 2)
        if qk_norm_variant == "output_contiguous":
            q_norm = q_norm.contiguous()
            k_norm = k_norm.contiguous()
        v_proj = attn.v_proj(input_norm).view(hidden_shape).transpose(1, 2)
        return q_proj, q_norm, k_proj, k_norm, v_proj

    def rope_stage(
        q_norm: torch.Tensor,
        k_norm: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        cache_position = torch.arange(q_norm.shape[2], device=q_norm.device)
        position_ids = cache_position.view(1, 1, -1).expand(3, q_norm.shape[0], -1)
        cos, sin = model.rotary_emb(by_name["layer_input"], position_ids)
        return _apply_rope(
            q_norm,
            k_norm,
            cos,
            sin,
            attn.rope_scaling["mrope_section"],
            attn.rope_scaling["interleaved"],
            rope_variant,
        )

    def scores_stage(
        q_rope: torch.Tensor,
        k_rope: torch.Tensor,
    ) -> torch.Tensor:
        key_states = repeat_kv(k_rope, attn.num_key_value_groups)
        query = q_rope.float() if attention_core_fp32 else q_rope
        key = key_states.float() if attention_core_fp32 else key_states
        return torch.matmul(query, key.transpose(2, 3)) * attn.scaling

    def mask_stage(scores: torch.Tensor, causal: torch.Tensor) -> torch.Tensor:
        return scores + causal

    def softmax_stage(scores_masked: torch.Tensor) -> torch.Tensor:
        probs = F.softmax(scores_masked, dim=-1, dtype=torch.float32)
        return probs if attention_core_fp32 else probs.to(by_name["q_rope"].dtype)

    def context_stage(
        probs: torch.Tensor,
        value_states: torch.Tensor,
    ) -> torch.Tensor:
        value = value_states.float() if attention_core_fp32 else value_states
        context = torch.matmul(probs, value)
        return context.to(by_name["q_rope"].dtype) if attention_core_fp32 else context

    def o_proj_input_stage(context: torch.Tensor) -> torch.Tensor:
        context = context.transpose(1, 2).contiguous()
        return context.reshape(*input_shape, -1).contiguous()

    def o_proj_stage(o_proj_input: torch.Tensor) -> torch.Tensor:
        return attn.o_proj(o_proj_input)

    def mlp_stage(post_attention_residual: torch.Tensor) -> tuple[torch.Tensor, ...]:
        mlp_input = _rms_norm(
            layer.post_attention_layernorm,
            post_attention_residual,
            layer_norm_variant,
        )
        mlp_gate = layer.mlp.gate_proj(mlp_input)
        mlp_up = layer.mlp.up_proj(mlp_input)
        mlp_down = layer.mlp.down_proj(layer.mlp.act_fn(mlp_gate) * mlp_up)
        layer_output = post_attention_residual + mlp_down
        return mlp_input, mlp_gate, mlp_up, mlp_down, layer_output

    return [
        compare_stage(
            "input_layernorm",
            lambda layer_input: _rms_norm(
                layer.input_layernorm,
                layer_input,
                layer_norm_variant,
            ),
            by_name["layer_input"],
            output_names=("input_layernorm",),
        ),
        compare_stage(
            "causal_mask_build",
            causal_mask_stage,
            by_name["layer_input"],
            torch.ones(
                by_name["layer_input"].shape[:2],
                dtype=torch.long,
                device=by_name["layer_input"].device,
            ),
            output_names=("causal_mask",),
        ),
        compare_stage(
            "qkv",
            qkv_stage,
            by_name["input_layernorm"],
            output_names=("q_proj", "q_norm", "k_proj", "k_norm", "v_proj"),
        ),
        compare_stage(
            "rope",
            rope_stage,
            by_name["q_norm"],
            by_name["k_norm"],
            output_names=("q_rope", "k_rope"),
        ),
        compare_stage(
            "scores",
            scores_stage,
            by_name["q_rope"],
            by_name["k_rope"],
            output_names=("scores",),
        ),
        compare_stage(
            "mask_add",
            mask_stage,
            by_name["scores"],
            by_name["causal_mask"],
            output_names=("scores_masked",),
        ),
        compare_stage(
            "softmax",
            softmax_stage,
            by_name["scores_masked"],
            output_names=("softmax_probs",),
        ),
        compare_stage(
            "context",
            context_stage,
            by_name["softmax_probs"],
            by_name["value_states"],
            output_names=("attention_context",),
        ),
        compare_stage(
            "o_proj_input",
            o_proj_input_stage,
            by_name["attention_context"],
            output_names=("o_proj_input",),
        ),
        compare_stage(
            "o_proj",
            o_proj_stage,
            by_name["o_proj_input"],
            output_names=("o_proj_output",),
        ),
        compare_stage(
            "mlp",
            mlp_stage,
            by_name["post_attention_residual"],
            output_names=(
                "mlp_input",
                "mlp_gate",
                "mlp_up",
                "mlp_down",
                "layer_output",
            ),
        ),
    ]


def _build_causal_mask(
    model: Any,
    inputs_embeds: torch.Tensor,
    attention_mask: torch.Tensor,
    *,
    force_mask_skip: bool = False,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor | None]:
    cache_position = torch.arange(inputs_embeds.shape[1], device=inputs_embeds.device)
    position_ids = cache_position.view(1, 1, -1).expand(3, inputs_embeds.shape[0], -1)
    if force_mask_skip:
        return cache_position, position_ids, None
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
    return cache_position, position_ids, causal_mask


@contextmanager
def _maybe_force_mask_skip(enabled: bool):
    if not enabled:
        yield
        return
    original = _masking_utils.is_torchdynamo_compiling
    _masking_utils.is_torchdynamo_compiling = lambda: False
    try:
        yield
    finally:
        _masking_utils.is_torchdynamo_compiling = original


def _as_tuple(
    value: torch.Tensor | tuple[torch.Tensor, ...],
) -> tuple[torch.Tensor, ...]:
    if isinstance(value, tuple):
        return value
    return (value,)


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
