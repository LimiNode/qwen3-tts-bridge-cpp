"""Qwen3-TTS engine adapter.

The adapter keeps heavyweight Qwen/Torch imports out of normal worker startup
until the qwen engine is actually selected and loaded.
"""

from __future__ import annotations

import gc
import importlib
import random
import threading
from collections.abc import Callable, Iterable, Iterator
from typing import Any, cast

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine.qwen import QwenModelLoadError, load_qwen_model
from qwen_tts_bridge_worker.engine.types import (
    AudioFormat,
    EngineCapabilities,
    EngineRequestValidationError,
    SynthesisRequest,
    UnsupportedAudioFormatError,
)
from qwen_tts_bridge_worker.timing import elapsed_milliseconds, monotonic_seconds

QwenModelLoader = Callable[[QwenEngineConfig], Any]

_STREAM_MAX_FRAMES = 10000


class QwenEngineError(RuntimeError):
    """Raised when the Qwen adapter cannot load or run the model."""


class QwenTtsEngine:
    """Adapter around the vendored Qwen3-TTS streaming package."""

    def __init__(
        self,
        config: QwenEngineConfig,
        model_loader: QwenModelLoader | None = None,
    ) -> None:
        self._config = config
        self._model_loader = model_loader or _default_model_loader
        self._model: Any | None = None
        self._synthesis_lock = threading.Lock()
        self._last_chunk_metrics: dict[str, object] | None = None
        self._profile_pair_range_open = False

    @property
    def capabilities(self) -> EngineCapabilities:
        """Return capabilities exposed by the Qwen adapter."""

        streaming = (
            self._model is not None
            and _supports_qwen_streaming(self._model)
        )
        return EngineCapabilities(
            streaming=streaming,
            cancellation=streaming,
            instructions=True,
            voice_clone=False,
        )

    def load(self) -> None:
        """Load the Qwen model wrapper."""

        if self._model is not None:
            return
        _seed_runtime(self._config.seed)
        self._model = self._model_loader(self._config)
        _validate_loaded_prefill_compile_compat(self._model, self._config)

    def warmup(self) -> dict[str, object] | None:
        """Ensure the model object exists before the worker sends ready."""

        if self._model is None:
            self.load()
        if self._config.warmup_synthesis_enabled:
            return self._run_warmup_synthesis()
        return None

    def validate_request(
        self,
        request: SynthesisRequest,
    ) -> None:
        """Validate output format support."""

        if request.output != AudioFormat.default():
            raise UnsupportedAudioFormatError(
                "qwen engine currently supports only s16le 24000 Hz mono"
            )

        model = self._require_model()
        model_type = _qwen_model_type(model)
        if model_type == "custom_voice":
            _validate_custom_voice_request(model, request)
            return

        if model_type == "voice_design":
            if not request.instruction.strip():
                raise EngineRequestValidationError(
                    "missing_required_field",
                    "qwen voice design model requires an instruction",
                )
            return

        if model_type == "base":
            raise EngineRequestValidationError(
                "missing_required_field",
                "qwen base voice-clone models require reference audio; "
                "the bridge protocol does not support voice clone requests yet",
            )

        raise EngineRequestValidationError(
            "invalid_field_type",
            f"unsupported qwen tts_model_type: {model_type or 'unknown'}",
        )

    def synthesize_stream(
        self,
        request: SynthesisRequest,
        cancel_event: threading.Event,
    ) -> Iterable[bytes]:
        """Generate Qwen audio and expose it as PCM chunks."""

        if cancel_event.is_set():
            return
        model = self._require_model()
        self._maybe_open_profile_pair_range(request.request_id)
        with self._synthesis_lock:
            _seed_runtime(_request_seed(self._config, request.request_id))
            audio_stream = self._generate_audio_stream(model, request)
            close_stream = getattr(audio_stream, "close", None)
            try:
                iterator = iter(audio_stream)
                while not cancel_event.is_set():
                    next_started_at = monotonic_seconds()
                    try:
                        wav, sample_rate, chunk_timing = _unpack_audio_chunk(
                            next(iterator)
                        )
                    except StopIteration:
                        break
                    next_wall_ms = elapsed_milliseconds(next_started_at)

                    if cancel_event.is_set():
                        return
                    if sample_rate != request.output.sample_rate:
                        raise QwenEngineError(
                            "qwen model returned unsupported sample rate "
                            f"{sample_rate}, expected {request.output.sample_rate}"
                        )
                    convert_started_at = monotonic_seconds()
                    pcm = _float_audio_to_s16le(wav)
                    pcm_convert_ms = elapsed_milliseconds(convert_started_at)
                    if pcm:
                        self._last_chunk_metrics = _first_chunk_timing_fields(
                            chunk_timing,
                            next_wall_ms=next_wall_ms,
                            pcm_convert_ms=pcm_convert_ms,
                        )
                        yield pcm
            finally:
                if callable(close_stream):
                    close_stream()
                self._maybe_close_profile_pair_range(request.request_id)

    def pop_last_chunk_metrics(self) -> dict[str, object] | None:
        """Return timing metadata for the last yielded PCM chunk, if available."""

        metrics = self._last_chunk_metrics
        self._last_chunk_metrics = None
        return metrics

    def close(self) -> None:
        """Release the loaded model reference."""

        model = self._model
        self._model = None
        close = getattr(model, "close", None)
        if callable(close):
            close()
        self._close_profile_pair_range()
        gc.collect()

    def _maybe_open_profile_pair_range(self, request_id: int) -> None:
        if not self._config.profile_nvtx or request_id != 1:
            return
        if self._profile_pair_range_open:
            return
        self._profile_pair_range_open = _nvtx_range_push(
            "qtb_profile_first_steady_pair"
        )

    def _maybe_close_profile_pair_range(self, request_id: int) -> None:
        if request_id >= 2:
            self._close_profile_pair_range()

    def _close_profile_pair_range(self) -> None:
        if not self._profile_pair_range_open:
            return
        _nvtx_range_pop()
        self._profile_pair_range_open = False

    def _run_warmup_synthesis(self) -> dict[str, object]:
        request = SynthesisRequest(
            request_id=0,
            text=self._config.warmup_text,
            language=self._config.warmup_language,
            speaker=self._config.warmup_speaker,
            instruction=self._config.warmup_instruction,
            output=AudioFormat.default(),
        )
        self.validate_request(request)

        passes: list[dict[str, object]] = []
        total_chunks = 0
        total_bytes = 0
        for pass_index in range(self._config.warmup_synthesis_passes):
            pass_fields = self._run_warmup_synthesis_pass(
                request,
                pass_index=pass_index + 1,
            )
            total_chunks += cast(int, pass_fields["audio_chunks"])
            total_bytes += cast(int, pass_fields["audio_bytes"])
            passes.append(pass_fields)

        audio_duration_ms = total_bytes * 1000.0 / (
            request.output.sample_rate * request.output.channels * 2
        )
        return {
            "warmup_synthesis": True,
            "warmup_synthesis_passes": len(passes),
            "warmup_audio_chunks": total_chunks,
            "warmup_audio_bytes": total_bytes,
            "warmup_audio_duration_ms": round(audio_duration_ms, 3),
            "warmup_passes": passes,
        }

    def _run_warmup_synthesis_pass(
        self,
        request: SynthesisRequest,
        *,
        pass_index: int,
    ) -> dict[str, object]:
        cancel_event = threading.Event()
        stream = self.synthesize_stream(request, cancel_event)
        close_stream = getattr(stream, "close", None)
        started_at = monotonic_seconds()
        first_audio_ms: float | None = None
        max_output_chunks = _warmup_pass_max_output_chunks(
            self._config,
            pass_index,
        )
        audio_chunks = 0
        audio_bytes = 0
        try:
            for chunk in stream:
                if not chunk:
                    continue
                if first_audio_ms is None:
                    first_audio_ms = elapsed_milliseconds(started_at)
                audio_chunks += 1
                audio_bytes += len(chunk)
                if max_output_chunks is not None and audio_chunks >= max_output_chunks:
                    break
        finally:
            if callable(close_stream):
                close_stream()
        completed_ms = elapsed_milliseconds(started_at)

        if audio_chunks == 0 or audio_bytes == 0:
            raise QwenEngineError(
                "warmup synthesis produced no audio "
                f"(pass={pass_index}, chunks={audio_chunks}, bytes={audio_bytes})"
            )

        audio_duration_ms = audio_bytes * 1000.0 / (
            request.output.sample_rate * request.output.channels * 2
        )
        real_time_factor = completed_ms / audio_duration_ms
        inverse_real_time_factor = audio_duration_ms / completed_ms
        return {
            "pass_index": pass_index,
            "first_audio_ms": first_audio_ms,
            "completed_ms": completed_ms,
            "audio_chunks": audio_chunks,
            "audio_bytes": audio_bytes,
            "audio_duration_ms": round(audio_duration_ms, 3),
            "local_rtf": round(real_time_factor, 6),
            "inverse_rtf": round(inverse_real_time_factor, 6),
            "bounded": max_output_chunks is not None,
            "max_output_chunks": max_output_chunks,
        }

    def _require_model(self) -> Any:
        if self._model is None:
            raise QwenEngineError("qwen model is not loaded")
        return self._model

    def _generate_audio(
        self,
        model: Any,
        request: SynthesisRequest,
    ) -> tuple[Iterable[Any], int]:
        model_type = _qwen_model_type(model)

        if model_type == "custom_voice":
            return model.generate_custom_voice(
                text=request.text,
                language=_model_call_language(self._config, request.language),
                speaker=request.speaker,
                instruct=request.instruction or None,
            )

        if model_type == "voice_design":
            return model.generate_voice_design(
                text=request.text,
                language=_model_call_language(self._config, request.language),
                instruct=request.instruction,
            )

        if model_type == "base":
            raise EngineRequestValidationError(
                "missing_required_field",
                "qwen base voice-clone models require reference audio; "
                "the bridge protocol does not support voice clone requests yet",
            )

        raise QwenEngineError(
            f"unsupported qwen tts_model_type: {model_type or 'unknown'}"
        )

    def _generate_audio_stream(
        self,
        model: Any,
        request: SynthesisRequest,
    ) -> Iterable[tuple[Any, int]]:
        stream = _qwen_stream_generate_audio(model, self._config, request)
        if stream is not None:
            return stream

        return _qwen_full_audio_as_stream(self._generate_audio(model, request))


def _default_model_loader(config: QwenEngineConfig) -> Any:
    try:
        return load_qwen_model(config)
    except QwenModelLoadError as exc:
        raise QwenEngineError(
            str(exc)
        ) from exc


def _qwen_model_type(model: Any) -> str:
    inner_model = getattr(model, "model", None)
    model_type = _nested_attr(inner_model, ("tts_model_type",))
    if model_type is None:
        model_type = _nested_attr(inner_model, ("model", "tts_model_type"))
    if model_type is None:
        model_type = getattr(model, "tts_model_type", "")
    return str(model_type)


def _validate_loaded_prefill_compile_compat(
    model: Any,
    config: QwenEngineConfig,
) -> None:
    if config.prefill_compile_compat_mode == "none":
        return

    model_type = _qwen_model_type(model)
    if model_type != "custom_voice":
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 is currently validated only for "
            f"CustomVoice models; loaded tts_model_type={model_type or 'unknown'}"
        )

    actual_mode = getattr(model, "prefill_compile_compat_mode", None)
    if actual_mode != config.prefill_compile_compat_mode:
        raise QwenEngineError(
            "loaded faster model did not apply requested prefill compile "
            f"compat mode: requested={config.prefill_compile_compat_mode!r}, "
            f"actual={actual_mode!r}"
        )

    actual_dtype = _normalized_dtype_name(getattr(model, "dtype", None))
    if actual_dtype != "bfloat16":
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 requires loaded faster model dtype=bfloat16; "
            f"actual={actual_dtype or 'unknown'}"
        )

    actual_attn = _loaded_talker_attention_implementation(model)
    if actual_attn != "sdpa":
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 requires loaded faster model attention=sdpa; "
            f"actual={actual_attn or 'unknown'}"
        )


def _normalized_dtype_name(dtype: Any) -> str:
    text = str(dtype or "").strip().lower()
    if text in {"torch.bfloat16", "bfloat16", "bf16"}:
        return "bfloat16"
    if text in {"torch.float16", "float16", "fp16"}:
        return "float16"
    if text in {"torch.float32", "float32", "fp32"}:
        return "float32"
    return text


def _loaded_talker_attention_implementation(model: Any) -> str:
    for path in (
        ("model", "model", "config", "talker_config", "_attn_implementation"),
        ("model", "config", "talker_config", "_attn_implementation"),
        ("model", "model", "talker", "config", "_attn_implementation"),
        ("model", "talker", "config", "_attn_implementation"),
    ):
        value = _nested_attr(model, path)
        if value is not None:
            return str(value)
    return ""


def _request_seed(config: QwenEngineConfig, request_id: int) -> int | None:
    base_seed = config.seed
    if request_id == 0 and config.warmup_seed is not None:
        return int(config.warmup_seed)
    if base_seed is None:
        return None
    if config.seed_mode == "fixed":
        return int(base_seed)
    return int(base_seed) + int(request_id)


def _nvtx_range_push(name: str) -> bool:
    try:
        torch = importlib.import_module("torch")
        torch.cuda.nvtx.range_push(name)
    except Exception:
        return False
    return True


def _nvtx_range_pop() -> None:
    try:
        torch = importlib.import_module("torch")
        torch.cuda.nvtx.range_pop()
    except Exception:
        pass


def _warmup_pass_max_output_chunks(
    config: QwenEngineConfig,
    pass_index: int,
) -> int | None:
    if pass_index <= config.warmup_unbounded_passes:
        return None
    return config.warmup_max_output_chunks


def _seed_runtime(seed: int | None) -> None:
    if seed is None:
        return
    random.seed(seed)
    try:
        numpy = importlib.import_module("numpy")
        numpy.random.seed(seed % (2**32))
    except Exception:
        pass
    try:
        torch = importlib.import_module("torch")
        torch.manual_seed(seed)
        cuda = getattr(torch, "cuda", None)
        manual_seed_all = getattr(cuda, "manual_seed_all", None)
        if callable(manual_seed_all):
            manual_seed_all(seed)
    except Exception:
        pass


def _nested_attr(obj: Any, path: tuple[str, ...]) -> Any | None:
    current = obj
    for name in path:
        if current is None:
            return None
        current = getattr(current, name, None)
    return current


def _qwen_language(language: str) -> str | None:
    if language.lower() == "auto":
        return None
    return language


def _qwen_runtime_language(language: str) -> str:
    if language.lower() == "auto":
        return "Auto"
    return language


def _profile_request_role(request_id: int) -> str | None:
    if request_id == 1:
        return "first_user"
    if request_id > 1:
        return "steady"
    return None


def _model_call_language(config: QwenEngineConfig, language: str) -> str | None:
    if config.runtime_backend == "faster":
        return _qwen_runtime_language(language)
    return _qwen_language(language)


def _supports_qwen_streaming(model: Any) -> bool:
    model_type = _qwen_model_type(model)
    if model_type == "custom_voice":
        if callable(getattr(model, "generate_custom_voice_streaming", None)):
            return True
        if callable(getattr(model, "stream_generate_custom_voice", None)):
            return True
        return _supports_qwen_stream_generate_pcm(model)

    if model_type == "voice_design":
        if callable(getattr(model, "generate_voice_design_streaming", None)):
            return True
        if callable(getattr(model, "stream_generate_voice_design", None)):
            return True
        return _supports_qwen_stream_generate_pcm(model)

    return False


def _supports_qwen_stream_generate_pcm(model: Any) -> bool:
    inner_model = getattr(model, "model", None)
    return (
        callable(getattr(inner_model, "stream_generate_pcm", None))
        and _has_qwen_stream_helpers(model)
    )


def _qwen_stream_generate_audio(
    model: Any,
    config: QwenEngineConfig,
    request: SynthesisRequest,
) -> Iterable[tuple[Any, int]] | None:
    model_type = _qwen_model_type(model)
    language = _qwen_language(request.language)

    if model_type == "custom_voice":
        if config.runtime_backend == "faster":
            public_stream = getattr(model, "generate_custom_voice_streaming", None)
            if callable(public_stream):
                stream_kwargs: dict[str, Any] = {
                    "text": request.text,
                    "language": _qwen_runtime_language(request.language),
                    "speaker": request.speaker,
                    "instruct": request.instruction or None,
                    "chunk_size": config.emit_every_frames,
                    "do_sample": config.do_sample,
                    "prefill_backend": config.prefill_backend,
                    "prefill_compile_compat_mode": (
                        config.prefill_compile_compat_mode
                    ),
                }
                if config.profile_prefill:
                    stream_kwargs["profile_prefill"] = True
                if config.profile_nvtx:
                    stream_kwargs["profile_nvtx"] = True
                if config.profile_prefill or config.profile_nvtx:
                    profile_request_role = _profile_request_role(request.request_id)
                    if profile_request_role is not None:
                        stream_kwargs["profile_request_role"] = profile_request_role
                return cast(
                    Iterable[tuple[Any, int]],
                    public_stream(**stream_kwargs),
                )
            return None

        public_stream = getattr(model, "stream_generate_custom_voice", None)
        if callable(public_stream):
            return cast(
                Iterable[tuple[Any, int]],
                public_stream(
                    text=request.text,
                    language=language,
                    speaker=request.speaker,
                    instruct=request.instruction or None,
                    emit_every_frames=config.emit_every_frames,
                    decode_window_frames=config.decode_window_frames,
                    overlap_samples=config.overlap_samples,
                ),
            )
        return _qwen_stream_generate_pcm(
            model,
            config,
            text=request.text,
            language=language,
            speaker=request.speaker,
            instruction=_custom_voice_instruction(model, request),
        )

    if model_type == "voice_design":
        if config.runtime_backend == "faster":
            public_stream = getattr(model, "generate_voice_design_streaming", None)
            if callable(public_stream):
                stream_kwargs = {
                    "text": request.text,
                    "language": _qwen_runtime_language(request.language),
                    "instruct": request.instruction,
                    "chunk_size": config.emit_every_frames,
                    "do_sample": config.do_sample,
                    "prefill_backend": config.prefill_backend,
                    "prefill_compile_compat_mode": (
                        config.prefill_compile_compat_mode
                    ),
                }
                if config.profile_prefill:
                    stream_kwargs["profile_prefill"] = True
                if config.profile_nvtx:
                    stream_kwargs["profile_nvtx"] = True
                if config.profile_prefill or config.profile_nvtx:
                    profile_request_role = _profile_request_role(request.request_id)
                    if profile_request_role is not None:
                        stream_kwargs["profile_request_role"] = profile_request_role
                return cast(
                    Iterable[tuple[Any, int]],
                    public_stream(**stream_kwargs),
                )
            return None

        public_stream = getattr(model, "stream_generate_voice_design", None)
        if callable(public_stream):
            return cast(
                Iterable[tuple[Any, int]],
                public_stream(
                    text=request.text,
                    language=language,
                    instruct=request.instruction,
                    emit_every_frames=config.emit_every_frames,
                    decode_window_frames=config.decode_window_frames,
                    overlap_samples=config.overlap_samples,
                ),
            )
        return _qwen_stream_generate_pcm(
            model,
            config,
            text=request.text,
            language=language,
            instruction=request.instruction,
        )

    return None


def _qwen_stream_generate_pcm(
    model: Any,
    config: QwenEngineConfig,
    *,
    text: str,
    language: str | None,
    speaker: str | None = None,
    instruction: str | None = None,
) -> Iterable[tuple[Any, int]] | None:
    inner_model = getattr(model, "model", None)
    stream_generate_pcm = getattr(inner_model, "stream_generate_pcm", None)
    if (
        not callable(stream_generate_pcm)
        or not _supports_qwen_stream_generate_pcm(model)
    ):
        return None

    input_ids = model._tokenize_texts([model._build_assistant_text(text)])
    instruct_ids = None
    if instruction:
        instruct_ids = [
            model._tokenize_texts([model._build_instruct_text(instruction)])[0]
        ]

    languages = [language if language is not None else "Auto"]
    kwargs: dict[str, Any] = {
        "input_ids": input_ids,
        "instruct_ids": instruct_ids,
        "languages": languages,
        "non_streaming_mode": False,
        "emit_every_frames": config.emit_every_frames,
        "decode_window_frames": config.decode_window_frames,
        "overlap_samples": config.overlap_samples,
        "max_frames": _STREAM_MAX_FRAMES,
    }
    if speaker is not None:
        kwargs["speakers"] = [speaker]

    return _with_input_metadata(
        cast(Iterable[tuple[Any, int]], stream_generate_pcm(**kwargs)),
        _qwen_input_metadata_from_ids(input_ids, instruct_ids),
    )


def _with_input_metadata(
    stream: Iterable[tuple[Any, int]],
    metadata: dict[str, object],
) -> Iterable[tuple[Any, int]]:
    if not metadata:
        return stream
    return cast(Iterable[tuple[Any, int]], _InputMetadataStream(stream, metadata))


class _InputMetadataStream:
    def __init__(
        self,
        stream: Iterable[tuple[Any, int]],
        metadata: dict[str, object],
    ) -> None:
        self._stream = stream
        self._metadata = metadata
        self._iterator: Iterator[tuple[Any, int]] | None = None

    def __iter__(self) -> "_InputMetadataStream":
        self._iterator = iter(self._stream)
        return self

    def __next__(self) -> tuple[Any, int, dict[str, object]]:
        if self._iterator is None:
            self._iterator = iter(self._stream)
        chunk = next(self._iterator)
        wav, sample_rate, timing = _unpack_audio_chunk(chunk)
        enriched_timing = dict(timing)
        for key, value in self._metadata.items():
            enriched_timing.setdefault(key, value)
        return wav, sample_rate, enriched_timing

    def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if callable(close):
            close()


def _qwen_input_metadata_from_ids(
    input_ids: list[Any],
    instruct_ids: list[Any] | None,
) -> dict[str, object]:
    text_token_count = _sequence_length(input_ids[0]) if input_ids else None
    instruction_token_count = (
        _sequence_length(instruct_ids[0]) if instruct_ids else 0
    )
    metadata: dict[str, object] = {}
    if text_token_count is not None:
        metadata["text_token_count"] = text_token_count
    if instruction_token_count is not None:
        metadata["instruction_token_count"] = instruction_token_count
    if text_token_count is not None and instruction_token_count is not None:
        metadata["prefill_sequence_length"] = (
            text_token_count + instruction_token_count
        )
    return metadata


def _sequence_length(value: Any) -> int | None:
    shape = getattr(value, "shape", None)
    if shape is not None:
        try:
            return int(shape[-1])
        except (IndexError, TypeError, ValueError):
            pass
    try:
        return len(value)
    except TypeError:
        return None


def _unpack_audio_chunk(chunk: Any) -> tuple[Any, int, dict[str, object]]:
    if not isinstance(chunk, tuple) or len(chunk) < 2:
        raise QwenEngineError("qwen model returned an invalid audio chunk")
    timing: dict[str, object] = {}
    if len(chunk) >= 3 and isinstance(chunk[2], dict):
        timing = {str(key): value for key, value in chunk[2].items()}
    return chunk[0], int(chunk[1]), timing


def _first_chunk_timing_fields(
    chunk_timing: dict[str, object],
    *,
    next_wall_ms: float,
    pcm_convert_ms: float,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "next_wall_ms": next_wall_ms,
        "pcm_convert_ms": pcm_convert_ms,
    }
    prefill_ms = _number_field(chunk_timing, "prefill_ms")
    decode_ms = (
        _number_field(chunk_timing, "ar_decode_ms")
        or _number_field(chunk_timing, "decode_ms")
    )
    chunk_steps = _number_field(chunk_timing, "chunk_steps")

    if prefill_ms is not None:
        fields["prefill_ms"] = prefill_ms
    if decode_ms is not None:
        fields["ar_decode_ms"] = decode_ms
    if chunk_steps is not None:
        fields["chunk_steps"] = int(chunk_steps)
        if decode_ms is not None and chunk_steps > 0:
            fields["ar_ms_per_step"] = decode_ms / chunk_steps

    for key in (
        "text_token_count",
        "instruction_token_count",
        "prefill_sequence_length",
        "talker_prefill_length",
        "profile_schema_version",
        "prefill_total_gpu_stream_id",
        "talker_forward_gpu_stream_id",
        "first_sample_gpu_stream_id",
        "prefill_kv_gpu_stream_id",
        "generation_state_gpu_stream_id",
        "prefill_to_sync_gpu_stream_id",
    ):
        value = _number_field(chunk_timing, key)
        if value is not None:
            fields[key] = int(value)
    for key in (
        "profile_path",
        "profile_status",
        "profile_request_role",
        "prefill_backend_requested",
        "prefill_backend_used",
        "prefill_compile_error",
        "prefill_compile_compat_mode",
    ):
        value = chunk_timing.get(key)
        if isinstance(value, str):
            fields[key] = value
    for key in (
        "profile_prefill_enabled",
        "profile_complete",
        "events_complete",
        "components_finite",
        "components_nonnegative",
        "all_component_streams_equal",
        "prefill_compile_fallback",
        "prefill_compile_compat_applied",
        "prefill_compile_compat_reused",
    ):
        value = chunk_timing.get(key)
        if isinstance(value, bool):
            fields[key] = value
    value = chunk_timing.get("prefill_compile_compat_patched_modules")
    if isinstance(value, dict):
        fields["prefill_compile_compat_patched_modules"] = dict(value)
    for key in (
        "tokenize_wall_ms",
        "build_talker_inputs_wall_ms",
        "prefill_total_gpu_ms",
        "talker_forward_launch_wall_ms",
        "talker_forward_gpu_ms",
        "first_sample_launch_wall_ms",
        "first_sample_gpu_ms",
        "prefill_kv_launch_wall_ms",
        "prefill_kv_gpu_ms",
        "generation_state_wall_ms",
        "generation_state_gpu_ms",
        "prefill_to_sync_gpu_ms",
        "prefill_sync_wait_ms",
        "prefill_gpu_component_sum_ms",
        "prefill_gpu_partition_error_ms",
        "prefill_gpu_accounting_error_ms",
    ):
        value = _number_field(chunk_timing, key)
        if value is not None:
            fields[key] = value
    for source_key, alias_key in (
        ("prefill_total_gpu_ms", "prefill_total_stream_elapsed_ms"),
        ("talker_forward_gpu_ms", "talker_forward_stream_elapsed_ms"),
        ("first_sample_gpu_ms", "first_sample_stream_elapsed_ms"),
        ("prefill_kv_gpu_ms", "prefill_kv_stream_elapsed_ms"),
        ("generation_state_gpu_ms", "generation_state_stream_elapsed_ms"),
        ("prefill_to_sync_gpu_ms", "prefill_to_sync_stream_elapsed_ms"),
    ):
        value = _number_field(chunk_timing, source_key)
        if value is not None:
            fields[alias_key] = value

    residual_ms = next_wall_ms
    if prefill_ms is not None:
        residual_ms -= prefill_ms
    if decode_ms is not None:
        residual_ms -= decode_ms
    fields["codec_wrapper_residual_ms"] = residual_ms
    return fields


def _number_field(fields: dict[str, object], name: str) -> float | None:
    value = fields.get(name)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _has_qwen_stream_helpers(model: Any) -> bool:
    helper_names = (
        "_tokenize_texts",
        "_build_assistant_text",
        "_build_instruct_text",
    )
    return all(callable(getattr(model, name, None)) for name in helper_names)


def _qwen_full_audio_as_stream(
    generated: tuple[Iterable[Any], int],
) -> Iterable[tuple[Any, int]]:
    wavs, sample_rate = generated
    return ((wav, sample_rate) for wav in wavs)


def _custom_voice_instruction(
    model: Any,
    request: SynthesisRequest,
) -> str | None:
    if not request.instruction:
        return None

    inner_model = getattr(model, "model", None)
    model_size = str(getattr(inner_model, "tts_model_size", ""))
    if model_size.lower() in {"0b6", "0.6b", "0.6"}:
        return None

    return request.instruction


def _validate_custom_voice_request(
    model: Any,
    request: SynthesisRequest,
) -> None:
    if _is_placeholder_speaker(request.speaker):
        raise EngineRequestValidationError(
            "missing_required_field",
            "qwen custom voice model requires an explicit speaker",
        )

    supported_speakers = _supported_speakers(model)
    if supported_speakers is None:
        return

    if request.speaker.lower() not in supported_speakers:
        raise EngineRequestValidationError(
            "invalid_field_type",
            f"qwen custom voice model does not support speaker: {request.speaker}",
        )


def _is_placeholder_speaker(speaker: str) -> bool:
    return not speaker.strip()


def _supported_speakers(model: Any) -> set[str] | None:
    get_supported_speakers = getattr(model, "get_supported_speakers", None)
    if not callable(get_supported_speakers):
        return None

    speakers = get_supported_speakers()
    if speakers is None:
        return None
    if not isinstance(speakers, (list, tuple, set)):
        return None

    return {str(speaker).lower() for speaker in speakers}


def _float_audio_to_s16le(audio: Any) -> bytes:
    try:
        numpy = importlib.import_module("numpy")
    except Exception:
        numpy = None

    if numpy is not None and isinstance(audio, numpy.ndarray):
        clipped = numpy.clip(audio.astype(numpy.float32, copy=False), -1.0, 1.0)
        pcm = (clipped * 32767.0).astype("<i2", copy=False)
        return bytes(pcm.tobytes())

    out = bytearray()
    for sample in _iter_float_samples(audio):
        clipped_sample = max(-1.0, min(1.0, sample))
        value = int(clipped_sample * 32767.0)
        out.extend(value.to_bytes(2, byteorder="little", signed=True))
    return bytes(out)


def _iter_float_samples(audio: Any) -> Iterator[float]:
    if hasattr(audio, "tolist"):
        audio = audio.tolist()

    if isinstance(audio, (int, float)):
        yield float(audio)
        return

    for item in audio:
        if isinstance(item, (list, tuple)):
            yield from _iter_float_samples(item)
        else:
            yield float(item)
