"""Opt-in adapter for the local qwentts.cpp GGML experiment."""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from qwen_tts_bridge_worker.config import QwenEngineConfig

from .model_loader import QwenModelLoadError

_DLL_DIRECTORY_HANDLES: list[object] = []

class GgmlCustomVoiceModel:
    """Expose qwentts.cpp CustomVoice streaming through the worker's model shape."""

    tts_model_type = "custom_voice"
    supports_custom_voice_instructions = False

    def __init__(self, tts: Any, config: QwenEngineConfig) -> None:
        self._tts = tts
        self._config = config

    def close(self) -> None:
        self._tts.close()

    def stream_generate_custom_voice(
        self,
        *,
        text: str,
        language: str | None,
        speaker: str,
        instruct: str | None,
        emit_every_frames: int,
        decode_window_frames: int,
        overlap_samples: int,
        seed: int | None = None,
        do_sample: bool | None = None,
        temperature: float | None = None,
        top_k: int | None = None,
        top_p: float | None = None,
        repetition_penalty: float | None = None,
    ) -> Iterable[tuple[Any, int]]:
        """Return native callback chunks through the constrained GGML contract."""

        # The shared adapter calls all CustomVoice models with this shape. The
        # GGML config rejects non-default values before a request reaches here.
        del emit_every_frames, decode_window_frames, overlap_samples
        if instruct:
            raise RuntimeError("qwentts.cpp CustomVoice instructions are not validated")
        if language is None:
            raise RuntimeError(
                "qwentts.cpp CustomVoice requires an explicit language; auto is "
                "not supported"
            )
        return self._tts.stream(
            text=text,
            lang=language,
            speaker=speaker,
            seed=-1 if seed is None else seed,
            do_sample=self._config.do_sample if do_sample is None else do_sample,
            temperature=(
                self._config.temperature if temperature is None else temperature
            ),
            top_k=self._config.top_k if top_k is None else top_k,
            top_p=self._config.top_p if top_p is None else top_p,
            repetition_penalty=(
                self._config.repetition_penalty
                if repetition_penalty is None
                else repetition_penalty
            ),
            codec_chunk_sec=self._config.ggml_codec_chunk_seconds,
        )


def load_ggml_custom_voice_model(config: QwenEngineConfig) -> GgmlCustomVoiceModel:
    """Load local GGUF weights through qwentts.cpp without touching Faster."""

    _add_windows_dll_directory(config.ggml_cuda_dll_dir)
    _add_python_package_path(config.ggml_python_path)
    try:
        qwentts = importlib.import_module("qwentts_cpp")
        model_cls = qwentts.QwenTTS
    except Exception as exc:
        raise QwenModelLoadError(
            "failed to import qwentts_cpp; install the local native GGML adapter "
            "only for --runtime-backend ggml"
        ) from exc

    kwargs: dict[str, object] = {
        "quant": config.ggml_quant,
        "cache_dir": config.ggml_cache_dir,
        "local_files_only": True,
    }
    if config.ggml_library_path:
        kwargs["library_path"] = config.ggml_library_path
    try:
        tts = model_cls.from_pretrained(config.model_path, **kwargs)
    except Exception as exc:
        raise QwenModelLoadError(f"failed to load GGML Qwen model: {exc}") from exc
    return GgmlCustomVoiceModel(tts, config)


def _add_windows_dll_directory(directory: str) -> None:
    path = Path(directory)
    if not path.is_dir():
        raise QwenModelLoadError(
            f"GGML CUDA DLL directory does not exist: {path}"
        )
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(path)))


def _add_python_package_path(directory: str) -> None:
    path = Path(directory)
    if not path.is_dir():
        raise QwenModelLoadError(
            f"GGML Python package directory does not exist: {path}"
        )
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)
