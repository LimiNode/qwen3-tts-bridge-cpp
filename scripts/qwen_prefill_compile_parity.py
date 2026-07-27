"""Diagnose faster-qwen3-tts prefill compile parity on a real model."""

from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
import qwen_tts.core.models.modeling_qwen3_tts as qwen_modeling
from faster_qwen3_tts import FasterQwen3TTS
from faster_qwen3_tts.streaming import (
    _run_talker_prefill,
    fast_generate_streaming,
    select_prefill_mask_mode,
)

DEFAULT_BACKENDS = (
    "eager",
    "compile_backend_eager",
    "compile_backend_aot_eager",
    "compile_inductor_default",
    "compile_inductor_graphbreak",
    "compile_reduce_overhead",
)


@torch.library.custom_op("qtb_prefill_parity::strict_add", mutates_args=())
def _strict_add(left: torch.Tensor, right: torch.Tensor) -> torch.Tensor:
    return left + right


@_strict_add.register_fake
def _(left: torch.Tensor, right: torch.Tensor) -> torch.Tensor:
    return torch.empty_like(left)


@torch.library.custom_op("qtb_prefill_parity::strict_rmsnorm", mutates_args=())
def _strict_rmsnorm(
    tensor: torch.Tensor,
    weight: torch.Tensor,
    eps: float,
) -> torch.Tensor:
    input_dtype = tensor.dtype
    values = tensor.float()
    variance = values.pow(2).mean(-1, keepdim=True)
    values = values * torch.rsqrt(variance + eps)
    return weight * values.to(input_dtype)


@_strict_rmsnorm.register_fake
def _(tensor: torch.Tensor, weight: torch.Tensor, eps: float) -> torch.Tensor:
    return torch.empty_like(tensor)


@torch.library.custom_op("qtb_prefill_parity::strict_mul", mutates_args=())
def _strict_mul(left: torch.Tensor, right: torch.Tensor) -> torch.Tensor:
    return left * right


@_strict_mul.register_fake
def _(left: torch.Tensor, right: torch.Tensor) -> torch.Tensor:
    return torch.empty_like(left)


@torch.library.custom_op("qtb_prefill_parity::strict_sdpa", mutates_args=())
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
    parser.add_argument("--attn-implementation", default="eager")
    parser.add_argument(
        "--force-talker-attn-implementation",
        default="",
        choices=("", "eager", "sdpa"),
        help="Diagnostic override for configs already loaded into the Talker modules.",
    )
    parser.add_argument("--trace-attention-calls", action="store_true")
    parser.add_argument("--backend", action="append", dest="backends")
    parser.add_argument(
        "--prefill-mask-mode",
        default="auto",
        choices=("auto", "explicit", "skip"),
    )
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--skip-generation", action="store_true")
    parser.add_argument("--matmul-precision", default="high")
    parser.add_argument("--disable-tf32", action="store_true")
    parser.add_argument("--disable-compile-rmsnorm", action="store_true")
    parser.add_argument("--disable-compile-rope", action="store_true")
    parser.add_argument(
        "--rmsnorm-compat-mode",
        default="current",
        choices=("current", "aten_rms_norm", "f_rms_norm", "strict_custom"),
    )
    parser.add_argument(
        "--rope-compat-mode",
        default="current",
        choices=("current", "strict_add"),
    )
    parser.add_argument(
        "--mlp-compat-mode",
        default="current",
        choices=("current", "strict_mul"),
    )
    parser.add_argument(
        "--attention-compat-mode",
        default="current",
        choices=("current", "strict_sdpa"),
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
    backends = tuple(args.backends or DEFAULT_BACKENDS)
    actual_talker_attn = _actual_talker_attn(talker)
    attention_call_probe = None
    if args.trace_attention_calls:
        resolved_mask_mode = _resolve_prefill_mask_mode(
            args.prefill_mask_mode,
            metadata,
        )
        attention_call_probe = _probe_attention_calls(
            talker,
            tie,
            tam,
            tth,
            tpe,
            prefill_mask_mode=resolved_mask_mode,
        )
        _validate_attention_probe(actual_talker_attn, attention_call_probe)

    with _compile_disable_context(
        rmsnorm=args.disable_compile_rmsnorm,
        rope=args.disable_compile_rope,
        rmsnorm_compat_mode=args.rmsnorm_compat_mode,
        rope_compat_mode=args.rope_compat_mode,
        mlp_compat_mode=args.mlp_compat_mode,
        attention_compat_mode=args.attention_compat_mode,
    ):
        prefill_outputs: dict[str, list[dict[str, Any]]] = {}
        prefill_objects: dict[str, list[Any]] = {}
        for backend in backends:
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
                    backend,
                    args.prefill_mask_mode,
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
            prefill_outputs[backend] = rows
            prefill_objects[backend] = objects

        eager_reference = prefill_objects["eager"][0]
        prefill_comparisons = {
            backend: _compare_prefill_outputs(eager_reference, objects[-1])
            for backend, objects in prefill_objects.items()
        }
        repeat_comparisons = {
            backend: _compare_prefill_outputs(objects[0], objects[-1])
            for backend, objects in prefill_objects.items()
            if len(objects) > 1
        }
        generation = {}
        generation_comparisons = {}
        if not args.skip_generation:
            generation = {
                backend: _generation_repeats(
                    model,
                    m,
                    talker,
                    config,
                    tie,
                    tam,
                    tth,
                    tpe,
                    metadata,
                    backend,
                    repeats=args.repeats,
                    max_new_tokens=args.max_new_tokens,
                    chunk_size=args.chunk_size,
                    prefill_mask_mode=args.prefill_mask_mode,
                )
                for backend in backends
            }
            generation_comparisons = {
                backend: _compare_generation(
                    generation["eager"][0],
                    rows[-1],
                    eos_id=int(config.codec_eos_token_id),
                )
                for backend, rows in generation.items()
            }

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
        "actual_talker_attn_implementation": actual_talker_attn,
        "forced_talker_attn_config_updates": forced_attn_updates,
        "attention_call_probe": attention_call_probe,
        "prefill_mask_mode_requested": args.prefill_mask_mode,
        "disable_compile_rmsnorm": args.disable_compile_rmsnorm,
        "disable_compile_rope": args.disable_compile_rope,
        "rmsnorm_compat_mode": args.rmsnorm_compat_mode,
        "rope_compat_mode": args.rope_compat_mode,
        "mlp_compat_mode": args.mlp_compat_mode,
        "attention_compat_mode": args.attention_compat_mode,
        "backends": backends,
        "repeats": args.repeats,
        "max_new_tokens": args.max_new_tokens,
        "chunk_size": args.chunk_size,
        "skip_generation": args.skip_generation,
        "precision": {
            "matmul_precision": args.matmul_precision,
            "disable_tf32": args.disable_tf32,
            "allow_tf32": torch.backends.cuda.matmul.allow_tf32,
            "allow_bf16_reduced_precision_reduction": (
                torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction
            ),
            "allow_fp16_reduced_precision_reduction": (
                torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction
            ),
        },
        "inputs": {
            "talker_input_embeds": _tensor_fingerprint(tie),
            "attention_mask": _tensor_fingerprint(tam),
            "trailing_text_hiddens": _tensor_fingerprint(tth),
            "tts_pad_embed": _tensor_fingerprint(tpe),
        },
        "prefill": {
            "runs": prefill_outputs,
            "vs_eager": prefill_comparisons,
            "repeat_stability": repeat_comparisons,
        },
        "generation": {
            "runs": generation,
            "vs_eager": generation_comparisons,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "actual_talker_attn_implementation": actual_talker_attn,
                "attention_call_probe": attention_call_probe,
                "prefill_vs_eager": {
                    key: value["logits_last"]["max_abs"]
                    for key, value in prefill_comparisons.items()
                },
                "generation_vs_eager": {
                    key: {
                        "same_codec": value["same_codec"],
                        "same_frame_count": value["same_frame_count"],
                        "eos_equal": value["eos_equal"],
                    }
                    for key, value in generation_comparisons.items()
                },
            },
            sort_keys=True,
        )
    )
    return 0


def _resolve_prefill_mask_mode(prefill_mask_mode: str, metadata: dict[str, Any]) -> str:
    requested = str(prefill_mask_mode or "auto").strip().lower()
    if requested == "auto":
        return select_prefill_mask_mode(metadata)
    return requested


def _probe_attention_calls(
    talker: Any,
    tie: torch.Tensor,
    tam: torch.Tensor,
    tth: torch.Tensor,
    tpe: torch.Tensor,
    *,
    prefill_mask_mode: str,
) -> dict[str, int]:
    counts = {
        "eager": 0,
        "sdpa": 0,
    }
    original_eager = qwen_modeling.eager_attention_forward
    original_sdpa = qwen_modeling.ALL_ATTENTION_FUNCTIONS.get("sdpa")

    def eager_wrapper(*args, **kwargs):
        counts["eager"] += 1
        return original_eager(*args, **kwargs)

    def sdpa_wrapper(*args, **kwargs):
        counts["sdpa"] += 1
        return original_sdpa(*args, **kwargs)

    try:
        qwen_modeling.eager_attention_forward = eager_wrapper
        if original_sdpa is not None:
            qwen_modeling.ALL_ATTENTION_FUNCTIONS["sdpa"] = sdpa_wrapper
        _run_talker_prefill(
            talker,
            tie,
            tam,
            tth,
            tpe,
            prefill_backend="eager",
            prefill_mask_mode=prefill_mask_mode,
        )
        torch.cuda.synchronize()
    finally:
        qwen_modeling.eager_attention_forward = original_eager
        if original_sdpa is not None:
            qwen_modeling.ALL_ATTENTION_FUNCTIONS["sdpa"] = original_sdpa
    return counts


def _validate_attention_probe(actual_talker_attn: str, counts: dict[str, int]) -> None:
    if actual_talker_attn == "eager":
        if counts.get("eager") != 28 or counts.get("sdpa") != 0:
            raise RuntimeError(
                "Attention probe mismatch for eager mode: "
                f"observed {counts!r}."
            )
    elif actual_talker_attn == "sdpa":
        if counts.get("sdpa") != 28 or counts.get("eager") != 0:
            raise RuntimeError(
                "Attention probe mismatch for sdpa mode: "
                f"observed {counts!r}."
            )


def _force_talker_attn_implementation(talker: Any, attn_implementation: str) -> int:
    updates = 0
    seen_configs = set()
    for module in talker.modules():
        config = getattr(module, "config", None)
        if config is None:
            continue
        config_id = id(config)
        if config_id in seen_configs:
            continue
        seen_configs.add(config_id)
        if hasattr(config, "_attn_implementation"):
            setattr(config, "_attn_implementation", attn_implementation)
            updates += 1
    return updates


def _actual_talker_attn(talker: Any) -> str:
    talker_model_config = getattr(
        getattr(talker, "model", None),
        "config",
        getattr(talker, "config", None),
    )
    return str(getattr(talker_model_config, "_attn_implementation", "unknown"))


def _configure_precision(args: argparse.Namespace) -> None:
    if args.matmul_precision:
        torch.set_float32_matmul_precision(args.matmul_precision)
    if args.disable_tf32:
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction = False
        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False


@contextmanager
def _compile_disable_context(
    *,
    rmsnorm: bool,
    rope: bool,
    rmsnorm_compat_mode: str,
    rope_compat_mode: str,
    mlp_compat_mode: str = "current",
    attention_compat_mode: str = "current",
):
    original_rmsnorm_forward = qwen_modeling.Qwen3TTSRMSNorm.forward
    original_rope = qwen_modeling.apply_multimodal_rotary_pos_emb
    original_mlp_forward = qwen_modeling.Qwen3TTSTalkerTextMLP.forward
    original_sdpa = qwen_modeling.ALL_ATTENTION_FUNCTIONS.get("sdpa")
    try:
        if rmsnorm:
            qwen_modeling.Qwen3TTSRMSNorm.forward = torch.compiler.disable(
                original_rmsnorm_forward
            )
        elif rmsnorm_compat_mode != "current":
            qwen_modeling.Qwen3TTSRMSNorm.forward = _make_rmsnorm_forward(
                rmsnorm_compat_mode
            )
        if rope:
            qwen_modeling.apply_multimodal_rotary_pos_emb = torch.compiler.disable(
                original_rope
            )
        elif rope_compat_mode != "current":
            qwen_modeling.apply_multimodal_rotary_pos_emb = _make_rope_forward(
                rope_compat_mode
            )
        if mlp_compat_mode != "current":
            qwen_modeling.Qwen3TTSTalkerTextMLP.forward = _make_mlp_forward(
                mlp_compat_mode
            )
        if attention_compat_mode != "current":
            if original_sdpa is None:
                raise ValueError("SDPA attention function is unavailable.")
            qwen_modeling.ALL_ATTENTION_FUNCTIONS["sdpa"] = _make_attention_forward(
                attention_compat_mode,
                original_sdpa,
            )
        yield
    finally:
        qwen_modeling.Qwen3TTSRMSNorm.forward = original_rmsnorm_forward
        qwen_modeling.apply_multimodal_rotary_pos_emb = original_rope
        qwen_modeling.Qwen3TTSTalkerTextMLP.forward = original_mlp_forward
        if original_sdpa is not None:
            qwen_modeling.ALL_ATTENTION_FUNCTIONS["sdpa"] = original_sdpa


def _make_rmsnorm_forward(mode: str):
    def forward(self, hidden_states):
        if mode == "aten_rms_norm":
            return torch.ops.aten.rms_norm.default(
                hidden_states,
                [hidden_states.shape[-1]],
                self.weight,
                self.variance_epsilon,
            )
        if mode == "f_rms_norm":
            return F.rms_norm(
                hidden_states,
                normalized_shape=(hidden_states.shape[-1],),
                weight=self.weight,
                eps=self.variance_epsilon,
            )
        if mode == "strict_custom":
            return _strict_rmsnorm(hidden_states, self.weight, self.variance_epsilon)
        raise ValueError(f"Unsupported RMSNorm compatibility mode: {mode}")

    return forward


def _make_rope_forward(mode: str):
    if mode != "strict_add":
        raise ValueError(f"Unsupported RoPE compatibility mode: {mode}")

    def forward(q, k, cos, sin, mrope_section, mrope_interleaved=False, unsqueeze_dim=1):
        q_mul_cos, q_mul_sin, k_mul_cos, k_mul_sin = _rope_terms(
            q,
            k,
            cos,
            sin,
            mrope_section,
            mrope_interleaved,
            unsqueeze_dim,
        )
        return _strict_add(q_mul_cos, q_mul_sin), _strict_add(k_mul_cos, k_mul_sin)

    return forward


def _make_mlp_forward(mode: str):
    if mode != "strict_mul":
        raise ValueError(f"Unsupported MLP compatibility mode: {mode}")

    def forward(self, x):
        return self.down_proj(
            _strict_mul(
                self.act_fn(self.gate_proj(x)),
                self.up_proj(x),
            )
        )

    return forward


def _make_attention_forward(mode: str, original_sdpa):
    if mode != "strict_sdpa":
        raise ValueError(f"Unsupported attention compatibility mode: {mode}")

    def forward(
        module,
        query,
        key,
        value,
        attention_mask,
        scaling,
        dropout=0.0,
        **_kwargs,
    ):
        if attention_mask is not None or dropout != 0.0:
            return original_sdpa(
                module,
                query,
                key,
                value,
                attention_mask,
                scaling=scaling,
                dropout=dropout,
                **_kwargs,
            )
        return (
            _strict_sdpa(
                query,
                key,
                value,
                scaling,
                module.num_key_value_groups,
            ),
            None,
        )

    return forward


def _rope_terms(
    q: torch.Tensor,
    k: torch.Tensor,
    cos: torch.Tensor,
    sin: torch.Tensor,
    mrope_section: list[int],
    mrope_interleaved: bool,
    unsqueeze_dim: int,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    if mrope_interleaved:
        dim = cos.shape[-1]
        modality_count = len(mrope_section)
        cos_half = _apply_interleaved_rope(
            cos[..., : dim // 2],
            mrope_section,
            modality_count,
        )
        sin_half = _apply_interleaved_rope(
            sin[..., : dim // 2],
            mrope_section,
            modality_count,
        )
        cos = torch.cat((cos_half, cos_half), dim=-1).unsqueeze(unsqueeze_dim)
        sin = torch.cat((sin_half, sin_half), dim=-1).unsqueeze(unsqueeze_dim)
    else:
        sections = mrope_section * 2
        cos = torch.cat(
            [chunk[index % 3] for index, chunk in enumerate(cos.split(sections, dim=-1))],
            dim=-1,
        ).unsqueeze(unsqueeze_dim)
        sin = torch.cat(
            [chunk[index % 3] for index, chunk in enumerate(sin.split(sections, dim=-1))],
            dim=-1,
        ).unsqueeze(unsqueeze_dim)
    q_rotate = qwen_modeling.rotate_half(q)
    k_rotate = qwen_modeling.rotate_half(k)
    return q * cos, q_rotate * sin, k * cos, k_rotate * sin


def _apply_interleaved_rope(
    tensor: torch.Tensor,
    sections: list[int],
    modality_count: int,
) -> torch.Tensor:
    output = tensor[0].clone()
    for index, section_size in enumerate(sections[1:], 1):
        begin = index
        end = section_size * modality_count
        output[..., begin:end:modality_count] = tensor[
            index,
            ...,
            begin:end:modality_count,
        ]
    return output


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


def _eval_inner_modules(model: Any) -> None:
    for item in (
        getattr(getattr(model, "model", None), "model", None),
        getattr(getattr(getattr(model, "model", None), "model", None), "talker", None),
    ):
        eval_fn = getattr(item, "eval", None)
        if callable(eval_fn):
            eval_fn()


def _prefill_once(
    talker: Any,
    tie: torch.Tensor,
    tam: torch.Tensor,
    tth: torch.Tensor,
    tpe: torch.Tensor,
    metadata: dict[str, Any],
    backend: str,
    prefill_mask_mode: str,
) -> tuple[Any, dict[str, Any]]:
    mask_mode = (
        select_prefill_mask_mode(metadata)
        if prefill_mask_mode == "auto"
        else prefill_mask_mode
    )
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
        )
    torch.cuda.synchronize()
    return out, profile


def _snapshot_prefill_output(out: Any) -> dict[str, Any]:
    return {
        "logits": out.logits.detach().cpu().clone(),
        "past_hidden": out.past_hidden.detach().cpu().clone(),
        "past_key_values": [
            tuple(tensor.detach().cpu().clone() for tensor in layer)
            for layer in out.past_key_values
        ],
    }


def _compare_prefill_outputs(
    left: dict[str, Any],
    right: dict[str, Any],
) -> dict[str, Any]:
    return {
        "logits_last": _compare_tensors(
            left["logits"][:, -1, :],
            right["logits"][:, -1, :],
        ),
        "logits_all": _compare_tensors(left["logits"], right["logits"]),
        "past_hidden": _compare_tensors(left["past_hidden"], right["past_hidden"]),
        "top_logits": {
            "left": _top_logit_summary(left["logits"][:, -1, :]),
            "right": _top_logit_summary(right["logits"][:, -1, :]),
        },
        "past_key_values": _compare_past_key_values(
            left["past_key_values"],
            right["past_key_values"],
        ),
    }


def _compare_past_key_values(left: Any, right: Any) -> dict[str, Any]:
    rows = []
    max_abs_values = []
    rmse_values = []
    for layer_index, (left_layer, right_layer) in enumerate(
        zip(left, right, strict=True)
    ):
        for name, left_tensor, right_tensor in (
            ("key", left_layer[0], right_layer[0]),
            ("value", left_layer[1], right_layer[1]),
        ):
            comparison = _compare_tensors(left_tensor, right_tensor)
            rows.append(
                {
                    "layer": layer_index,
                    "kind": name,
                    "comparison": comparison,
                }
            )
            max_abs_values.append(comparison["max_abs"])
            rmse_values.append(comparison["rmse"])
    return {
        "tensor_count": len(rows),
        "max_abs_max": max(max_abs_values) if max_abs_values else None,
        "rmse_max": max(rmse_values) if rmse_values else None,
        "per_tensor": rows,
    }


def _generation_repeats(
    model: FasterQwen3TTS,
    m: Any,
    talker: Any,
    config: Any,
    tie: torch.Tensor,
    tam: torch.Tensor,
    tth: torch.Tensor,
    tpe: torch.Tensor,
    metadata: dict[str, Any],
    backend: str,
    *,
    repeats: int,
    max_new_tokens: int,
    chunk_size: int,
    prefill_mask_mode: str,
) -> list[dict[str, Any]]:
    return [
        _generate_once(
            model,
            m,
            talker,
            config,
            tie,
            tam,
            tth,
            tpe,
            metadata,
            backend,
            max_new_tokens=max_new_tokens,
            chunk_size=chunk_size,
            prefill_mask_mode=prefill_mask_mode,
            repeat=repeat_index + 1,
        )
        for repeat_index in range(repeats)
    ]


def _generate_once(
    model: FasterQwen3TTS,
    m: Any,
    talker: Any,
    config: Any,
    tie: torch.Tensor,
    tam: torch.Tensor,
    tth: torch.Tensor,
    tpe: torch.Tensor,
    metadata: dict[str, Any],
    backend: str,
    *,
    max_new_tokens: int,
    chunk_size: int,
    prefill_mask_mode: str,
    repeat: int,
) -> dict[str, Any]:
    chunks = []
    timings = []
    with torch.inference_mode():
        for codec_chunk, timing in fast_generate_streaming(
            talker=talker,
            talker_input_embeds=tie,
            attention_mask=tam,
            trailing_text_hiddens=tth,
            tts_pad_embed=tpe,
            config=config,
            predictor_graph=_select_predictor_graph(model, do_sample=False),
            talker_graph=model.talker_graph,
            max_new_tokens=max_new_tokens,
            min_new_tokens=2,
            temperature=0.9,
            top_k=50,
            top_p=1.0,
            do_sample=False,
            repetition_penalty=1.05,
            chunk_size=chunk_size,
            input_metadata=metadata,
            profile_prefill=True,
            prefill_backend=backend,
            prefill_mask_mode=prefill_mask_mode,
        ):
            chunks.append(codec_chunk.detach().cpu().contiguous())
            timings.append(timing)
    codec = (
        torch.cat(chunks, dim=0)
        if chunks
        else torch.empty((0, 16), dtype=torch.long)
    )
    audio = _decode_audio(m.speech_tokenizer, codec)
    eos_id = int(config.codec_eos_token_id)
    frame_accounting = _frame_accounting(
        codec,
        timings,
        eos_id=eos_id,
        requested_max_new_tokens=max_new_tokens,
    )
    return {
        "repeat": repeat,
        "backend": backend,
        "requested_max_new_tokens": max_new_tokens,
        "codec_shape": list(codec.shape),
        "codec_values": codec.tolist(),
        "codec_sha256": _tensor_sha256(codec),
        "first_codec_token": int(codec[0, 0]) if codec.numel() else None,
        "generated_frames": int(codec.shape[0]),
        "eos_frame": _eos_frame(codec, eos_id),
        "frame_accounting": frame_accounting,
        "audio_samples": int(audio.shape[0]),
        "audio_duration_ms": float(audio.shape[0]) * 1000.0 / 24000.0,
        "waveform_sha256": hashlib.sha256(
            np.ascontiguousarray(audio).tobytes()
        ).hexdigest(),
        "timings": timings,
    }


def _select_predictor_graph(model: Any, *, do_sample: bool) -> Any:
    selector = getattr(model, "_select_predictor_graph", None)
    if callable(selector):
        return selector(do_sample)
    return model.predictor_graph


def _frame_accounting(
    codec: torch.Tensor,
    timings: list[dict[str, Any]],
    *,
    eos_id: int,
    requested_max_new_tokens: int,
) -> dict[str, Any]:
    emitted_steps = int(codec.shape[0])
    final_timing = timings[-1] if timings else {}
    final_chunk_steps = int(final_timing.get("chunk_steps", 0)) if timings else 0
    final_is_final = bool(final_timing.get("is_final", False)) if timings else False
    generator_termination = _generator_termination(final_timing)
    eos_positions = _eos_positions(codec, eos_id)
    if generator_termination.get("termination_reason"):
        stop_reason = str(generator_termination["termination_reason"])
    elif eos_positions:
        stop_reason = "eos"
    elif emitted_steps == requested_max_new_tokens:
        stop_reason = "max_new_tokens"
    elif emitted_steps < requested_max_new_tokens:
        stop_reason = "short_without_eos"
    else:
        stop_reason = "unknown"
    return {
        "requested_max_new_tokens": requested_max_new_tokens,
        "emitted_steps": emitted_steps,
        "generated_steps": emitted_steps,
        "final_chunk_steps": final_chunk_steps,
        "final_is_final": final_is_final,
        "stop_reason": stop_reason,
        "stop_reason_source": (
            "generator_telemetry"
            if generator_termination.get("termination_reason")
            else "emitted_codec_derived"
        ),
        "generator_termination": generator_termination,
        "eos_positions": eos_positions,
        "timing_total_steps": [
            int(timing["total_steps_so_far"])
            for timing in timings
            if "total_steps_so_far" in timing
        ],
    }


def _eos_positions(codec: torch.Tensor, eos_id: int) -> list[dict[str, int]]:
    if codec.numel() == 0:
        return []
    hits = codec == eos_id
    indices = hits.nonzero(as_tuple=False)
    return [
        {"frame": int(index[0]), "codebook": int(index[1])}
        for index in indices.cpu()
    ]


def _generator_termination(timing: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "termination_reason",
        "hit_eos",
        "hit_max_new_tokens",
        "hit_max_seq_len",
        "terminal_token_id",
        "terminal_step_index",
        "generator_loop_iterations",
        "generated_steps",
        "emitted_steps",
    )
    return {field: timing[field] for field in fields if field in timing}


def _decode_audio(speech_tokenizer: Any, codec: torch.Tensor) -> np.ndarray:
    if codec.numel() == 0:
        return np.zeros(0, dtype=np.float32)
    audio_list, _sample_rate = speech_tokenizer.decode(
        {"audio_codes": codec.to("cuda").unsqueeze(0)}
    )
    audio = audio_list[0]
    if hasattr(audio, "cpu"):
        return audio.flatten().detach().cpu().numpy()
    return np.asarray(audio).reshape(-1)


def _compare_generation(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    eos_id: int,
) -> dict[str, Any]:
    first_divergence = _first_codec_divergence(
        left.get("codec_values"),
        right.get("codec_values"),
    )
    left_codec = left["codec_sha256"]
    right_codec = right["codec_sha256"]
    same_codec = left_codec == right_codec
    return {
        "same_codec": same_codec,
        "same_frame_count": left["generated_frames"] == right["generated_frames"],
        "same_audio_samples": left["audio_samples"] == right["audio_samples"],
        "same_waveform": left["waveform_sha256"] == right["waveform_sha256"],
        "eos_id": eos_id,
        "left_eos_frame": left["eos_frame"],
        "right_eos_frame": right["eos_frame"],
        "eos_equal": left["eos_frame"] == right["eos_frame"],
        "left_audio_duration_ms": left["audio_duration_ms"],
        "right_audio_duration_ms": right["audio_duration_ms"],
        "first_divergence": first_divergence,
    }


def _first_codec_divergence(left: object, right: object) -> dict[str, Any] | None:
    if not isinstance(left, list) or not isinstance(right, list):
        return None
    frame_count = min(len(left), len(right))
    for frame_index in range(frame_count):
        left_frame = left[frame_index]
        right_frame = right[frame_index]
        if not isinstance(left_frame, list) or not isinstance(right_frame, list):
            return {"frame": frame_index, "codebook": None}
        codebook_count = min(len(left_frame), len(right_frame))
        for codebook_index in range(codebook_count):
            if left_frame[codebook_index] != right_frame[codebook_index]:
                return {
                    "frame": frame_index,
                    "codebook": codebook_index,
                    "left": left_frame[codebook_index],
                    "right": right_frame[codebook_index],
                }
        if len(left_frame) != len(right_frame):
            return {"frame": frame_index, "codebook": codebook_count}
    if len(left) != len(right):
        return {"frame": frame_count, "codebook": 0}
    return None


def _top_logit_summary(logits: torch.Tensor) -> dict[str, Any]:
    values, indices = torch.topk(logits.float().flatten(), k=2)
    return {
        "top1_id": int(indices[0].item()),
        "top1_logit": float(values[0].item()),
        "top2_id": int(indices[1].item()),
        "top2_logit": float(values[1].item()),
        "margin": float((values[0] - values[1]).item()),
    }


def _tensor_fingerprint(tensor: torch.Tensor) -> dict[str, Any]:
    return {
        "shape": list(tensor.shape),
        "dtype": str(tensor.dtype),
        "device": str(tensor.device),
        "stride": list(tensor.stride()),
        "storage_offset": int(tensor.storage_offset()),
        "is_contiguous": bool(tensor.is_contiguous()),
        "sha256": _tensor_sha256(tensor.detach().cpu().contiguous()),
    }


def _compare_tensors(left: torch.Tensor, right: torch.Tensor) -> dict[str, Any]:
    left_f = left.detach().float()
    right_f = right.detach().float()
    if tuple(left.shape) != tuple(right.shape):
        return {
            "same_shape": False,
            "left": _tensor_fingerprint(left),
            "right": _tensor_fingerprint(right),
        }
    diff = left_f - right_f
    abs_diff = diff.abs()
    max_abs = float(abs_diff.max().item()) if abs_diff.numel() else 0.0
    mean_abs = float(abs_diff.mean().item()) if abs_diff.numel() else 0.0
    rmse = float(torch.sqrt((diff * diff).mean()).item()) if diff.numel() else 0.0
    denom = torch.maximum(left_f.abs(), right_f.abs()).clamp_min(1.0e-12)
    max_relative = float((abs_diff / denom).max().item()) if abs_diff.numel() else 0.0
    cosine = float(
        torch.nn.functional.cosine_similarity(
            left_f.flatten(),
            right_f.flatten(),
            dim=0,
        ).item()
    ) if left_f.numel() else 1.0
    max_index = int(abs_diff.argmax().item()) if abs_diff.numel() else 0
    return {
        "same_shape": True,
        "left": _tensor_fingerprint(left),
        "right": _tensor_fingerprint(right),
        "max_abs": max_abs,
        "mean_abs": mean_abs,
        "rmse": rmse,
        "max_relative": max_relative,
        "cosine_similarity": cosine,
        "max_abs_flat_index": max_index,
        "allclose_atol_1e_3_rtol_1e_3": bool(
            torch.allclose(left_f, right_f, atol=1.0e-3, rtol=1.0e-3)
        ),
        "allclose_atol_1e_2_rtol_1e_2": bool(
            torch.allclose(left_f, right_f, atol=1.0e-2, rtol=1.0e-2)
        ),
    }


def _tensor_sha256(tensor: torch.Tensor) -> str:
    tensor = tensor.detach().cpu().contiguous()
    if tensor.dtype == torch.bfloat16:
        tensor = tensor.view(torch.int16)
    array = tensor.numpy()
    return hashlib.sha256(array.tobytes()).hexdigest()


def _eos_frame(codec: torch.Tensor, eos_id: int) -> int | None:
    if codec.numel() == 0:
        return None
    hits = (codec[:, 0] == eos_id).nonzero(as_tuple=False)
    if hits.numel() == 0:
        return None
    return int(hits[0, 0].item())


if __name__ == "__main__":
    raise SystemExit(main())
