"""Standalone multimodal RoPE Inductor parity repro for Qwen3-TTS talker."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import torch
from faster_qwen3_tts import FasterQwen3TTS
from qwen_tts.core.models.modeling_qwen3_tts import repeat_kv


BACKENDS = (
    "eager",
    "compile_backend_eager",
    "compile_backend_aot_eager",
    "compile_inductor_default",
)
STAGES = (
    "cos_mixed",
    "sin_mixed",
    "q_rotate_half",
    "k_rotate_half",
    "q_mul_cos",
    "q_mul_sin",
    "k_mul_cos",
    "k_mul_sin",
    "q_rope",
    "k_rope",
    "scores",
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
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument("--compute-dtype", choices=("input", "float32"), default="input")
    parser.add_argument("--backend", action="append", dest="backends")
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
    prepared = model._prepare_generation_custom(
        text=args.text,
        language=args.language,
        speaker=args.speaker,
        instruct=None,
        non_streaming_mode=True,
        return_metadata=True,
    )
    _m, talker, _config, tie, tam, _tth, _tpe, metadata = prepared
    talker.eval()
    tensors = _capture_layer0_rope_inputs(talker.model, tie, tam)
    if args.compute_dtype == "float32":
        tensors = {
            key: value.float()
            if isinstance(value, torch.Tensor) and torch.is_floating_point(value)
            else value
            for key, value in tensors.items()
        }

    backends = tuple(args.backends or BACKENDS)
    raw = _snapshot(
        _rope_stages(
            tensors["q_norm"],
            tensors["k_norm"],
            tensors["cos"],
            tensors["sin"],
            tensors["sections"],
            tensors["interleaved"],
            tensors["num_key_value_groups"],
            tensors["scaling"],
        )
    )
    backend_rows = {}
    for backend in backends:
        fn = _compile_fn(lambda q, k, cos, sin: _rope_stages(q, k, cos, sin, tensors["sections"], tensors["interleaved"], tensors["num_key_value_groups"], tensors["scaling"]), backend)
        with torch.inference_mode():
            out = _snapshot(fn(tensors["q_norm"], tensors["k_norm"], tensors["cos"], tensors["sin"]))
        rows = {
            name: _compare(raw[name], out[name])
            for name in STAGES
        }
        first_diff = next(({"name": name, **row} for name, row in rows.items() if row["max_abs"] != 0.0), None)
        backend_rows[backend] = {
            "first_diff": first_diff,
            "stages": rows,
        }

    report = {
        "artifact_schema_version": 1,
        "model": args.model,
        "text": args.text,
        "language": args.language,
        "speaker": args.speaker,
        "device": args.device,
        "device_profile": args.device_profile,
        "runtime": _runtime_metadata(args.device),
        "dtype": args.dtype,
        "compute_dtype": args.compute_dtype,
        "attn_implementation": args.attn_implementation,
        "metadata": metadata,
        "tensor_fingerprints": {
            key: _tensor_fingerprint(value)
            for key, value in tensors.items()
            if isinstance(value, torch.Tensor)
        },
        "sections": list(tensors["sections"]),
        "interleaved": bool(tensors["interleaved"]),
        "backends": backend_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "first_diffs": {k: v["first_diff"] for k, v in backend_rows.items()}}))
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


def _capture_layer0_rope_inputs(model: Any, inputs_embeds: torch.Tensor, attention_mask: torch.Tensor) -> dict[str, Any]:
    cache_position = torch.arange(inputs_embeds.shape[1], device=inputs_embeds.device)
    position_ids = cache_position.view(1, 1, -1).expand(3, inputs_embeds.shape[0], -1)
    position_embeddings = model.rotary_emb(inputs_embeds, position_ids)
    layer = model.layers[0]
    attn = layer.self_attn
    input_norm = layer.input_layernorm(inputs_embeds)
    input_shape = input_norm.shape[:-1]
    hidden_shape = (*input_shape, -1, attn.head_dim)
    q_proj = attn.q_proj(input_norm).view(hidden_shape)
    k_proj = attn.k_proj(input_norm).view(hidden_shape)
    q_norm = attn.q_norm(q_proj).transpose(1, 2)
    k_norm = attn.k_norm(k_proj).transpose(1, 2)
    cos, sin = position_embeddings
    return {
        "q_norm": q_norm.detach(),
        "k_norm": k_norm.detach(),
        "cos": cos.detach(),
        "sin": sin.detach(),
        "sections": tuple(attn.rope_scaling["mrope_section"]),
        "interleaved": bool(attn.rope_scaling["interleaved"]),
        "num_key_value_groups": int(attn.num_key_value_groups),
        "scaling": float(attn.scaling),
        "attention_mask": attention_mask.detach(),
    }


def _compile_fn(function: Callable[..., Any], backend: str) -> Callable[..., Any]:
    if backend == "eager":
        return function
    compile_backend = "inductor"
    if backend == "compile_backend_eager":
        compile_backend = "eager"
    elif backend == "compile_backend_aot_eager":
        compile_backend = "aot_eager"
    elif backend != "compile_inductor_default":
        raise ValueError(f"Unsupported backend: {backend}")
    return torch.compile(function, backend=compile_backend, fullgraph=True, dynamic=False)


def _rope_stages(
    q_norm: torch.Tensor,
    k_norm: torch.Tensor,
    cos: torch.Tensor,
    sin: torch.Tensor,
    sections: tuple[int, ...],
    interleaved: bool,
    num_key_value_groups: int,
    scaling: float,
) -> dict[str, torch.Tensor]:
    cos_mixed, sin_mixed = _mix_multimodal_rope(cos, sin, sections, interleaved)
    q_rotate = _rotate_half(q_norm)
    k_rotate = _rotate_half(k_norm)
    q_mul_cos = q_norm * cos_mixed
    q_mul_sin = q_rotate * sin_mixed
    k_mul_cos = k_norm * cos_mixed
    k_mul_sin = k_rotate * sin_mixed
    q_rope = q_mul_cos + q_mul_sin
    k_rope = k_mul_cos + k_mul_sin
    key_states = repeat_kv(k_rope, num_key_value_groups)
    scores = torch.matmul(q_rope, key_states.transpose(2, 3)) * scaling
    return {
        "cos_mixed": cos_mixed,
        "sin_mixed": sin_mixed,
        "q_rotate_half": q_rotate,
        "k_rotate_half": k_rotate,
        "q_mul_cos": q_mul_cos,
        "q_mul_sin": q_mul_sin,
        "k_mul_cos": k_mul_cos,
        "k_mul_sin": k_mul_sin,
        "q_rope": q_rope,
        "k_rope": k_rope,
        "scores": scores,
    }


def _mix_multimodal_rope(
    cos: torch.Tensor,
    sin: torch.Tensor,
    sections: tuple[int, ...],
    interleaved: bool,
) -> tuple[torch.Tensor, torch.Tensor]:
    if interleaved:
        dim = cos.shape[-1]
        modality_count = len(sections)
        cos_half = _apply_interleaved_rope(cos[..., : dim // 2], sections, modality_count)
        sin_half = _apply_interleaved_rope(sin[..., : dim // 2], sections, modality_count)
        return (
            torch.cat((cos_half, cos_half), dim=-1).unsqueeze(1),
            torch.cat((sin_half, sin_half), dim=-1).unsqueeze(1),
        )
    split_sizes = tuple(sections) * 2
    cos_mixed = torch.cat(
        [chunk[index % 3] for index, chunk in enumerate(cos.split(split_sizes, dim=-1))],
        dim=-1,
    ).unsqueeze(1)
    sin_mixed = torch.cat(
        [chunk[index % 3] for index, chunk in enumerate(sin.split(split_sizes, dim=-1))],
        dim=-1,
    ).unsqueeze(1)
    return cos_mixed, sin_mixed


def _apply_interleaved_rope(
    tensor: torch.Tensor,
    sections: tuple[int, ...],
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


def _rotate_half(tensor: torch.Tensor) -> torch.Tensor:
    left = tensor[..., : tensor.shape[-1] // 2]
    right = tensor[..., tensor.shape[-1] // 2 :]
    return torch.cat((-right, left), dim=-1)


def _snapshot(stages: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    return {
        name: tensor.detach().cpu().contiguous()
        for name, tensor in stages.items()
    }


def _compare(left: torch.Tensor, right: torch.Tensor) -> dict[str, Any]:
    diff = (left.float() - right.float()).abs()
    max_abs = float(diff.max().item()) if diff.numel() else 0.0
    mean_abs = float(diff.mean().item()) if diff.numel() else 0.0
    rmse = float(torch.sqrt(torch.mean((left.float() - right.float()) ** 2)).item()) if diff.numel() else 0.0
    return {
        "shape": list(left.shape),
        "dtype": str(left.dtype),
        "max_abs": max_abs,
        "mean_abs": mean_abs,
        "rmse": rmse,
    }


def _tensor_fingerprint(tensor: torch.Tensor) -> dict[str, Any]:
    return {
        "shape": list(tensor.shape),
        "dtype": str(tensor.dtype),
        "device": str(tensor.device),
        "stride": list(tensor.stride()),
        "contiguous": bool(tensor.is_contiguous()),
    }


if __name__ == "__main__":
    raise SystemExit(main())
