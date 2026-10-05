"""Merge the published Russian-stress LoRA into an exact Qwen Base checkpoint.

This is a research-only preparation step. It deliberately writes a complete
Hugging Face safetensors checkpoint and never changes a bridge model profile.
The script fails closed on provenance, target-name, or tensor-shape mismatches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import torch
from safetensors import safe_open
from safetensors.torch import save_file


TARGET_MODULE_PATTERN = (
    r"layers\.\d+\.(self_attn\.(q|k|v|o)_proj|mlp\.(gate|up|down)_proj)"
)
TARGET_RE = re.compile(r"^" + TARGET_MODULE_PATTERN + r"$")

# This script is intentionally pinned to the published experiment.  Override
# these only when carrying out a separately reviewed experiment with a new
# source receipt; silently accepting a same-shaped checkpoint defeats the
# provenance guarantee.
EXPECTED_BASE_REVISION = "fd4b254389122332181a7c3db7f27e918eec64e3"
EXPECTED_BASE_SHA256 = "38fc7fc51c5e776e840414b6fd443962e9411b9654888fd7913e4da643cb857c"
EXPECTED_ADAPTER_SHA256 = "702338d0e81ef8d04715ebd19ebe5eaf43b83446c04ee37f1a9108a9235f2b99"
EXPECTED_LORA_PAIRS = 196
CONVERTER_METADATA_FILES = (
    "config.json",
    "generation_config.json",
    "merges.txt",
    "tokenizer_config.json",
    "vocab.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _pair_lora_tensors(
    adapter_path: Path,
    expected_pair_count: int,
) -> dict[str, tuple[str, str]]:
    with safe_open(str(adapter_path), framework="pt") as adapter:
        keys = set(adapter.keys())
    pairs: dict[str, tuple[str, str]] = {}
    for key in sorted(keys):
        if not key.endswith(".lora_A.weight"):
            continue
        stem = key[: -len(".lora_A.weight")]
        b_key = stem + ".lora_B.weight"
        if b_key not in keys:
            raise ValueError(f"missing LoRA B tensor for {key}")
        if not TARGET_RE.fullmatch(stem):
            raise ValueError(f"LoRA target is outside the declared contract: {stem}")
        pairs[stem] = (key, b_key)
    expected = len(pairs) * 2
    if len(keys) != expected:
        raise ValueError(
            f"unexpected adapter tensor count: {len(keys)} (expected {expected})"
        )
    if len(pairs) != expected_pair_count:
        raise ValueError(
            f"unexpected LoRA pair count: {len(pairs)} "
            f"(expected {expected_pair_count})"
        )
    return pairs


def _validate_provenance(
    adapter_metadata: dict[str, Any],
    expected_base_revision: str,
) -> tuple[int, float]:
    if adapter_metadata.get("base") != "Qwen/Qwen3-TTS-12Hz-1.7B-Base":
        raise ValueError(f"unexpected LoRA base: {adapter_metadata.get('base')!r}")
    if adapter_metadata.get("base_revision") != expected_base_revision:
        raise ValueError(
            "LoRA base revision mismatch: "
            f"{adapter_metadata.get('base_revision')!r} != {expected_base_revision!r}"
        )
    if adapter_metadata.get("applied_to") != "talker.model":
        raise ValueError(f"unexpected LoRA target root: {adapter_metadata.get('applied_to')!r}")
    rank = adapter_metadata.get("r")
    alpha = adapter_metadata.get("alpha")
    if not isinstance(rank, int) or rank <= 0:
        raise ValueError(f"invalid LoRA rank: {rank!r}")
    if not isinstance(alpha, (int, float)) or alpha <= 0:
        raise ValueError(f"invalid LoRA alpha: {alpha!r}")
    target_modules = adapter_metadata.get("target_modules")
    if not isinstance(target_modules, str) or target_modules != TARGET_MODULE_PATTERN:
        raise ValueError("adapter target_modules does not match the declared contract")
    return rank, float(alpha)


def merge_checkpoint(
    base_dir: Path,
    adapter_dir: Path,
    output_dir: Path,
    expected_base_revision: str,
    receipt_path: Path,
    expected_base_sha256: str = EXPECTED_BASE_SHA256,
    expected_adapter_sha256: str = EXPECTED_ADAPTER_SHA256,
    expected_pair_count: int = EXPECTED_LORA_PAIRS,
) -> dict[str, Any]:
    if output_dir.resolve() in (base_dir.resolve(), adapter_dir.resolve()):
        raise ValueError("output directory must be separate from Base and adapter inputs")
    base_model = base_dir / "model.safetensors"
    adapter_model = adapter_dir / "adapter.safetensors"
    adapter_json = adapter_dir / "adapter.json"
    config_path = base_dir / "config.json"
    if not all(path.is_file() for path in (base_model, adapter_model, adapter_json, config_path)):
        missing = [str(path) for path in (base_model, adapter_model, adapter_json, config_path) if not path.is_file()]
        raise FileNotFoundError("missing required checkpoint files: " + ", ".join(missing))

    base_sha256 = sha256_file(base_model)
    adapter_sha256 = sha256_file(adapter_model)
    if base_sha256 != expected_base_sha256:
        raise ValueError(
            f"Base model SHA-256 mismatch: {base_sha256} != {expected_base_sha256}"
        )
    if adapter_sha256 != expected_adapter_sha256:
        raise ValueError(
            "adapter SHA-256 mismatch: "
            f"{adapter_sha256} != {expected_adapter_sha256}"
        )

    missing_metadata = [
        name for name in CONVERTER_METADATA_FILES if not (base_dir / name).is_file()
    ]
    if missing_metadata:
        raise FileNotFoundError(
            "missing converter metadata in exact Base directory: "
            + ", ".join(missing_metadata)
        )

    metadata = _load_json(adapter_json)
    rank, alpha = _validate_provenance(metadata, expected_base_revision)
    pairs = _pair_lora_tensors(adapter_model, expected_pair_count)
    scale = alpha / rank

    merged: dict[str, torch.Tensor] = {}
    target_stats: list[dict[str, Any]] = []
    with safe_open(str(base_model), framework="pt") as base, safe_open(
        str(adapter_model), framework="pt"
    ) as adapter:
        base_keys = set(base.keys())
        expected_base_keys = {"talker.model." + stem + ".weight" for stem in pairs}
        missing_targets = sorted(expected_base_keys - base_keys)
        if missing_targets:
            raise ValueError("missing Base LoRA targets: " + ", ".join(missing_targets))

        for key in sorted(base_keys):
            tensor = base.get_tensor(key)
            stem = key[len("talker.model.") : -len(".weight")] if (
                key.startswith("talker.model.") and key.endswith(".weight")
            ) else ""
            pair = pairs.get(stem)
            if pair is None:
                merged[key] = tensor
                continue

            a = adapter.get_tensor(pair[0]).float()
            b = adapter.get_tensor(pair[1]).float()
            if tensor.ndim != 2 or a.ndim != 2 or b.ndim != 2:
                raise ValueError(f"LoRA target tensors must be matrices: {key}")
            if a.shape[1] != tensor.shape[1] or b.shape[0] != tensor.shape[0] or a.shape[0] != b.shape[1]:
                raise ValueError(
                    f"LoRA shape mismatch for {key}: base={tuple(tensor.shape)} "
                    f"A={tuple(a.shape)} B={tuple(b.shape)}"
                )
            delta = torch.matmul(b, a) * scale
            merged_tensor = (tensor.float() + delta).to(dtype=tensor.dtype)
            merged[key] = merged_tensor
            target_stats.append(
                {
                    "tensor": key,
                    "shape": list(tensor.shape),
                    "base_dtype": str(tensor.dtype),
                    "adapter_a_dtype": str(adapter.get_tensor(pair[0]).dtype),
                    "adapter_b_dtype": str(adapter.get_tensor(pair[1]).dtype),
                    "max_abs_delta": float(delta.abs().max().item()),
                    "mean_abs_delta": float(delta.abs().mean().item()),
                }
            )

    if len(target_stats) != expected_pair_count:
        raise ValueError(
            f"modified tensor count mismatch: {len(target_stats)} "
            f"(expected {expected_pair_count})"
        )
    if any(stat["max_abs_delta"] == 0.0 for stat in target_stats):
        raise ValueError("LoRA target produced an all-zero delta")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_model = output_dir / "model.safetensors"
    save_file(merged, str(output_model), metadata={"format": "pt"})
    for name in CONVERTER_METADATA_FILES:
        shutil.copy2(base_dir / name, output_dir / name)

    unchanged_prefixes = ("talker.code_predictor.", "speaker_encoder.")
    unchanged_count = 0
    with safe_open(str(base_model), framework="pt") as base, safe_open(
        str(output_model), framework="pt"
    ) as output:
        for key in base.keys():
            if key.startswith(unchanged_prefixes) and not torch.equal(
                base.get_tensor(key), output.get_tensor(key)
            ):
                raise ValueError(f"non-talker component changed unexpectedly: {key}")
            if key.startswith(unchanged_prefixes):
                unchanged_count += 1

    receipt: dict[str, Any] = {
        "schema_version": 1,
        "base_model": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "base_revision": expected_base_revision,
        "adapter_base_revision": metadata["base_revision"],
        "adapter_applied_to": metadata["applied_to"],
        "rank": rank,
        "alpha": alpha,
        "scale": scale,
        "base_sha256": base_sha256,
        "expected_base_sha256": expected_base_sha256,
        "adapter_sha256": adapter_sha256,
        "expected_adapter_sha256": expected_adapter_sha256,
        "merged_sha256": sha256_file(output_model),
        "base_tensor_count": len(merged),
        "lora_pair_count": len(pairs),
        "modified_tensor_count": len(target_stats),
        "unchanged_predictor_speaker_tensor_count": unchanged_count,
        "converter_metadata": {
            name: sha256_file(output_dir / name) for name in CONVERTER_METADATA_FILES
        },
        "target_stats": target_stats,
        "output_model": str(output_model),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--adapter-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-base-revision", default=EXPECTED_BASE_REVISION)
    parser.add_argument("--expected-base-sha256", default=EXPECTED_BASE_SHA256)
    parser.add_argument("--expected-adapter-sha256", default=EXPECTED_ADAPTER_SHA256)
    parser.add_argument("--expected-lora-pairs", type=int, default=EXPECTED_LORA_PAIRS)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    receipt = merge_checkpoint(
        args.base_dir,
        args.adapter_dir,
        args.output_dir,
        args.expected_base_revision,
        args.receipt,
        args.expected_base_sha256,
        args.expected_adapter_sha256,
        args.expected_lora_pairs,
    )
    print(json.dumps({key: value for key, value in receipt.items() if key != "target_stats"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
