"""Qwen model loading boundary used by the worker engine adapter."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from qwen_tts_bridge_worker.config import QwenEngineConfig


class QwenModelLoadError(RuntimeError):
    """Raised when the bridge cannot import or construct the Qwen model."""


def load_qwen_model(config: QwenEngineConfig) -> Any:
    """Load the Qwen model wrapper from the vendored or installed runtime."""

    if config.runtime_backend == "faster":
        return load_faster_qwen_model(config)

    add_default_qwen_package_path()
    _set_matmul_precision(config)

    try:
        qwen_model = importlib.import_module("qwen_tts.inference.qwen3_tts_model")
        model_cls = qwen_model.Qwen3TTSModel
    except Exception as exc:
        raise QwenModelLoadError(
            "failed to import qwen_tts.inference.qwen3_tts_model; install the "
            "Qwen3-TTS streaming package or keep "
            "external/python/Qwen3-TTS-streaming available"
        ) from exc

    kwargs = _model_load_kwargs(config)
    try:
        model = model_cls.from_pretrained(config.model_path, **kwargs)
    except Exception as exc:
        raise QwenModelLoadError(f"failed to load Qwen model: {exc}") from exc
    _enable_streaming_optimizations(model, config)
    return model


def load_faster_qwen_model(config: QwenEngineConfig) -> Any:
    """Load the faster-qwen3-tts model wrapper."""

    _set_matmul_precision(config)
    try:
        faster_qwen = importlib.import_module("faster_qwen3_tts")
        model_cls = faster_qwen.FasterQwen3TTS
    except Exception as exc:
        raise QwenModelLoadError(
            "failed to import faster_qwen3_tts; install faster-qwen3-tts or "
            "select --runtime-backend upstream"
        ) from exc

    try:
        return model_cls.from_pretrained(
            config.model_path,
            device=config.device,
            dtype=_faster_dtype(config),
            attn_implementation=config.attn_implementation or "eager",
            max_seq_len=config.max_seq_len,
            prefill_backend=config.prefill_backend,
            prefill_compile_compat_mode=config.prefill_compile_compat_mode,
            prefill_compile_lengths=config.prefill_compile_lengths,
            prefill_compile_on_miss=config.prefill_compile_on_miss,
            prefill_unknown_shape_policy=config.prefill_unknown_shape_policy,
            prefill_require_precompiled=(
                False
                if config.prefill_compile_policy == "exact_allowlist"
                else config.prefill_require_precompiled
            ),
        )
    except Exception as exc:
        raise QwenModelLoadError(f"failed to load faster Qwen model: {exc}") from exc


def add_default_qwen_package_path() -> None:
    """Prepend the vendored Qwen fork to sys.path when it is available."""

    external_path = _repo_root() / "external" / "python" / "Qwen3-TTS-streaming"
    if not external_path.exists():
        return

    path_text = str(external_path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _model_load_kwargs(config: QwenEngineConfig) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"device_map": config.device}

    dtype = _torch_dtype(config.dtype)
    if dtype is not None:
        kwargs["dtype"] = dtype

    if config.attn_implementation:
        kwargs["attn_implementation"] = config.attn_implementation

    return kwargs


def _enable_streaming_optimizations(
    model: Any,
    config: QwenEngineConfig,
) -> None:
    if not config.enable_streaming_optimizations:
        return

    enable = getattr(model, "enable_streaming_optimizations", None)
    if not callable(enable):
        raise QwenModelLoadError(
            "qwen model does not expose enable_streaming_optimizations"
        )

    try:
        enable(
            decode_window_frames=config.decode_window_frames,
            use_compile=config.use_compile,
            use_cuda_graphs=config.use_cuda_graphs,
            compile_mode=config.compile_mode,
            use_fast_codebook=config.use_fast_codebook,
            compile_codebook_predictor=config.compile_codebook_predictor,
            compile_talker=config.compile_talker,
        )
    except Exception as exc:
        raise QwenModelLoadError(
            f"failed to enable Qwen streaming optimizations: {exc}"
        ) from exc


def _torch_dtype(dtype_name: str) -> Any | None:
    normalized = dtype_name.strip().lower()
    if normalized == "auto":
        return None

    try:
        torch = importlib.import_module("torch")
    except Exception as exc:
        raise QwenModelLoadError("torch is required for explicit qwen dtype") from exc

    mapping = {
        "float16": "float16",
        "fp16": "float16",
        "bfloat16": "bfloat16",
        "bf16": "bfloat16",
        "float32": "float32",
        "fp32": "float32",
    }
    attr = mapping.get(normalized)
    if attr is None:
        raise QwenModelLoadError(f"unsupported qwen dtype: {dtype_name}")
    return getattr(torch, attr)


def _faster_dtype(config: QwenEngineConfig) -> str:
    if config.dtype == "auto":
        return "bfloat16"
    return config.dtype


def _set_matmul_precision(config: QwenEngineConfig) -> None:
    if not config.matmul_precision:
        return

    try:
        torch = importlib.import_module("torch")
    except Exception as exc:
        raise QwenModelLoadError(
            "torch is required for qwen matmul precision configuration"
        ) from exc

    set_precision = getattr(torch, "set_float32_matmul_precision", None)
    if not callable(set_precision):
        raise QwenModelLoadError(
            "selected torch does not expose set_float32_matmul_precision"
        )
    set_precision(config.matmul_precision)
