"""Compare talker prefill module outputs between two FasterQwen backends."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch

from faster_qwen3_tts import FasterQwen3TTS
from faster_qwen3_tts.streaming import _run_talker_prefill


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    parser.add_argument("--text", default="I am your robot, I am your worker.")
    parser.add_argument("--language", default="English")
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--attn-implementation", default="eager")
    parser.add_argument("--left-backend", default="eager")
    parser.add_argument("--right-backend", default="compile_backend_eager")
    parser.add_argument("--scope", choices=("layers", "layer0"), default="layers")
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
    m, talker, _config, tie, tam, tth, tpe, metadata = model._prepare_generation_custom(
        text=args.text,
        language=args.language,
        speaker=args.speaker,
        instruct=None,
        non_streaming_mode=True,
        return_metadata=True,
    )
    del m
    talker.eval()

    left = _collect(talker, tie, tam, tth, tpe, args.left_backend, args.scope)
    right = _collect(talker, tie, tam, tth, tpe, args.right_backend, args.scope)
    comparisons = [
        _compare(name, left[name], right[name])
        for name in left
        if name in right
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
        "left_backend": args.left_backend,
        "right_backend": args.right_backend,
        "scope": args.scope,
        "metadata": metadata,
        "comparisons": comparisons,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "comparisons": comparisons[:5]}))
    return 0


def _configure_precision(args: argparse.Namespace) -> None:
    if args.matmul_precision:
        torch.set_float32_matmul_precision(args.matmul_precision)
    if args.disable_tf32:
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction = False
        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False


def _collect(
    talker: Any,
    tie: torch.Tensor,
    tam: torch.Tensor,
    tth: torch.Tensor,
    tpe: torch.Tensor,
    backend: str,
    scope: str,
) -> dict[str, torch.Tensor]:
    rows: dict[str, torch.Tensor] = {}
    names = set(_module_names(talker, scope))
    handles = []

    def make_hook(name: str):
        def hook(_module: Any, _inputs: Any, output: Any) -> None:
            tensor = _first_tensor(output)
            if tensor is not None and name not in rows:
                rows[name] = tensor.detach().cpu().contiguous()

        return hook

    for name, module in talker.named_modules():
        if name in names:
            handles.append(module.register_forward_hook(make_hook(name)))
    try:
        out, _profile = _run_talker_prefill(
            talker,
            tie,
            tam,
            tth,
            tpe,
            prefill_backend=backend,
        )
        rows["__logits_last__"] = out.logits[:, -1, :].detach().cpu().contiguous()
        rows["__past_hidden__"] = out.past_hidden.detach().cpu().contiguous()
    finally:
        for handle in handles:
            handle.remove()
    return rows


def _module_names(talker: Any, scope: str) -> list[str]:
    names = []
    exact = {"model.norm", "codec_head"}
    layer0_exact = {
        "model.layers.0",
        "model.layers.0.input_layernorm",
        "model.layers.0.self_attn",
        "model.layers.0.post_attention_layernorm",
        "model.layers.0.mlp",
    }
    layer0_parts = (
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "q_norm",
        "k_norm",
        "gate_proj",
        "up_proj",
        "down_proj",
        "act_fn",
    )
    for name, _module in talker.named_modules():
        if scope == "layers":
            if name in exact or (name.startswith("model.layers.") and name.count(".") == 2):
                names.append(name)
        elif name in layer0_exact or (
            name.startswith("model.layers.0.") and any(part in name for part in layer0_parts)
        ):
            names.append(name)
    return names


def _first_tensor(value: Any) -> torch.Tensor | None:
    if isinstance(value, torch.Tensor):
        return value
    if isinstance(value, (tuple, list)):
        for item in value:
            tensor = _first_tensor(item)
            if tensor is not None:
                return tensor
    if hasattr(value, "last_hidden_state"):
        return value.last_hidden_state
    return None


def _compare(name: str, left: torch.Tensor, right: torch.Tensor) -> dict[str, Any]:
    left_f = left.float()
    right_f = right.float()
    diff = (left_f - right_f).abs()
    rmse = torch.sqrt(torch.mean((left_f - right_f) ** 2))
    return {
        "name": name,
        "shape": list(left.shape),
        "dtype": str(left.dtype),
        "max_abs": float(diff.max().item()),
        "mean_abs": float(diff.mean().item()),
        "rmse": float(rmse.item()),
    }


if __name__ == "__main__":
    raise SystemExit(main())
