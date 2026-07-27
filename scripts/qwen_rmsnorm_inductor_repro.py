"""Standalone RMSNorm Inductor parity repro for Qwen3-TTS talker."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from faster_qwen3_tts import FasterQwen3TTS


BACKENDS = ("eager", "compile_backend_eager", "compile_backend_aot_eager", "compile_inductor_default")


@torch.library.custom_op("qtb_rmsnorm_repro::strict_rmsnorm", mutates_args=())
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
    parser.add_argument("--norm-target", choices=("input_layernorm", "q_norm", "k_norm"), default="q_norm")
    parser.add_argument("--norm-mode", choices=("current", "f_rms_norm", "aten_rms_norm", "strict_custom"), default="current")
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
    _m, talker, _config, tie, _tam, _tth, _tpe, metadata = prepared
    tensor, weight, eps = _capture_norm_input(talker.model, tie, args.norm_target)
    raw = _snapshot(_rmsnorm(tensor, weight, eps, args.norm_mode))
    backends = tuple(args.backends or BACKENDS)
    backend_rows = {}
    for backend in backends:
        fn = _compile_fn(lambda x, w: _rmsnorm(x, w, eps, args.norm_mode), backend)
        with torch.inference_mode():
            out = _snapshot(fn(tensor, weight))
        backend_rows[backend] = _compare(raw, out)

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
        "attn_implementation": args.attn_implementation,
        "metadata": metadata,
        "norm_target": args.norm_target,
        "norm_mode": args.norm_mode,
        "input": _tensor_fingerprint(tensor),
        "weight": _tensor_fingerprint(weight),
        "eps": eps,
        "backends": backend_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "backends": backend_rows}))
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


def _capture_norm_input(
    model: Any,
    inputs_embeds: torch.Tensor,
    target: str,
) -> tuple[torch.Tensor, torch.Tensor, float]:
    layer = model.layers[0]
    attn = layer.self_attn
    if target == "input_layernorm":
        norm = layer.input_layernorm
        return inputs_embeds.detach(), norm.weight.detach(), float(norm.variance_epsilon)

    input_norm = layer.input_layernorm(inputs_embeds)
    input_shape = input_norm.shape[:-1]
    hidden_shape = (*input_shape, -1, attn.head_dim)
    if target == "q_norm":
        norm = attn.q_norm
        tensor = attn.q_proj(input_norm).view(hidden_shape)
    elif target == "k_norm":
        norm = attn.k_norm
        tensor = attn.k_proj(input_norm).view(hidden_shape)
    else:
        raise ValueError(f"Unsupported norm target: {target}")
    return tensor.detach(), norm.weight.detach(), float(norm.variance_epsilon)


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


def _rmsnorm(
    tensor: torch.Tensor,
    weight: torch.Tensor,
    eps: float,
    mode: str,
) -> torch.Tensor:
    if mode == "current":
        input_dtype = tensor.dtype
        values = tensor.float()
        variance = values.pow(2).mean(-1, keepdim=True)
        values = values * torch.rsqrt(variance + eps)
        return weight * values.to(input_dtype)
    if mode == "f_rms_norm":
        return F.rms_norm(tensor, normalized_shape=(tensor.shape[-1],), weight=weight, eps=eps)
    if mode == "aten_rms_norm":
        return torch.ops.aten.rms_norm.default(tensor, [tensor.shape[-1]], weight, eps)
    if mode == "strict_custom":
        return _strict_rmsnorm(tensor, weight, eps)
    raise ValueError(f"Unsupported norm mode: {mode}")


def _snapshot(tensor: torch.Tensor) -> torch.Tensor:
    return tensor.detach().cpu().contiguous()


def _compare(left: torch.Tensor, right: torch.Tensor) -> dict[str, Any]:
    diff = (left.float() - right.float()).abs()
    return {
        "shape": list(left.shape),
        "dtype": str(left.dtype),
        "max_abs": float(diff.max().item()) if diff.numel() else 0.0,
        "mean_abs": float(diff.mean().item()) if diff.numel() else 0.0,
        "rmse": float(torch.sqrt(torch.mean((left.float() - right.float()) ** 2)).item()) if diff.numel() else 0.0,
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
