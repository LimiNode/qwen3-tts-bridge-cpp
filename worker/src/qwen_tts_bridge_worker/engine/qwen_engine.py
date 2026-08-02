"""Qwen3-TTS engine adapter.

The adapter keeps heavyweight Qwen/Torch imports out of normal worker startup
until the qwen engine is actually selected and loaded.
"""

from __future__ import annotations

import gc
import hashlib
import importlib
import json
import math
import random
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
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
from qwen_tts_bridge_worker.engine.voice_profiles import (
    VoiceProfileError,
    VoiceProfileRegistry,
    preflight_reference_audio,
)
from qwen_tts_bridge_worker.timing import elapsed_milliseconds, monotonic_seconds

QwenModelLoader = Callable[[QwenEngineConfig], Any]

_STREAM_MAX_FRAMES = 10000


class QwenEngineError(RuntimeError):
    """Raised when the Qwen adapter cannot load or run the model."""


class GenerationSafetyLimitError(QwenEngineError):
    """Raised after generated PCM reaches the configured product safety limit."""

    def __init__(self, limit_seconds: float, emitted_seconds: float) -> None:
        self.limit_seconds = limit_seconds
        self.emitted_seconds = emitted_seconds
        super().__init__(
            "generated audio reached the safety duration limit "
            f"({emitted_seconds:.3f}s of {limit_seconds:.3f}s)"
        )


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
        self._last_generation_trace: dict[str, object] | None = None
        self._profile_pair_range_open = False
        self._prewarmed_prefill_lengths: set[int] = set()
        self._voice_profiles = (
            VoiceProfileRegistry.from_json_file(
                config.voice_registry_path,
                config.voice_prompt_cache_max_entries,
            )
            if config.voice_registry_path
            else None
        )

    @property
    def capabilities(self) -> EngineCapabilities:
        """Return capabilities exposed by the Qwen adapter."""

        streaming = self._model is not None and _supports_qwen_streaming(self._model)
        instructions = self._model is None or _supports_qwen_instructions(
            self._model,
            self._config,
        )
        return EngineCapabilities(
            streaming=streaming,
            cancellation=streaming,
            instructions=instructions,
            voice_clone=(
                self._model is not None
                and _qwen_model_type(self._model) == "base"
                and (
                    callable(getattr(self._model, "generate_voice_clone", None))
                    or callable(
                        getattr(self._model, "stream_generate_voice_clone", None)
                    )
                    or callable(
                        getattr(
                            self._model,
                            "generate_voice_clone_streaming",
                            None,
                        )
                    )
                )
            ),
            sampling_overrides=(
                self._config.runtime_backend == "faster"
                and self._config.allow_request_sampling_overrides
            ),
            deterministic_seed=True,
            voice_clone_streaming=(
                self._model is not None
                and _qwen_model_type(self._model) == "base"
                and _supports_base_voice_clone_streaming(self._model)
            ),
            voice_profiles=(
                self._model is not None
                and _qwen_model_type(self._model) == "base"
                and self._voice_profiles is not None
            ),
        )

    @property
    def voice_ids(self) -> tuple[str, ...]:
        """Return the registered Base voice IDs advertised to local clients."""

        if (
            self._voice_profiles is None
            or self._model is None
            or _qwen_model_type(self._model) != "base"
        ):
            return ()
        return self._voice_profiles.voice_ids

    def load(self) -> None:
        """Load the Qwen model wrapper."""

        if self._model is not None:
            return
        _seed_runtime(
            self._config.seed,
            require_cuda=self._config.device.lower().startswith("cuda"),
        )
        self._model = self._model_loader(self._config)
        model = self._require_model()
        _validate_loaded_prefill_compile_compat(model, self._config)
        if self._config.collect_generation_trace:
            if not hasattr(model, "collect_generation_trace"):
                raise QwenEngineError(
                    "faster backend does not expose generation trace collection"
                )
            model.collect_generation_trace = True

    def warmup(self) -> dict[str, object] | None:
        """Ensure the model object exists before the worker sends ready."""

        if self._model is None:
            self.load()
        warmup_fields: dict[str, object] = {}
        if self._config.prefill_compile_policy == "exact_allowlist":
            warmup_fields.update(
                self._run_prefill_allowlist_warmup(self._require_model())
            )
            _set_prefill_require_precompiled(self._require_model(), True)
        if self._config.prefill_first_chunk_warmup_enabled:
            warmup_fields.update(self._run_prefill_first_chunk_warmup())
        if self._config.prefill_generation_prime_enabled:
            warmup_fields.update(self._run_prefill_generation_prime())
        if self._config.warmup_synthesis_enabled:
            warmup_fields.update(self._run_warmup_synthesis())
        return warmup_fields or None

    def validate_request(
        self,
        request: SynthesisRequest,
    ) -> None:
        """Validate output format support."""

        if request.output != AudioFormat.default():
            raise UnsupportedAudioFormatError(
                "qwen engine currently supports only s16le 24000 Hz mono"
            )

        if (
            not request.sampling.is_default()
            and not self._config.allow_request_sampling_overrides
        ):
            raise EngineRequestValidationError(
                "unsupported_feature",
                "the active runtime profile does not allow per-request "
                "sampling overrides",
            )
        if (
            self._config.runtime_backend != "faster"
            and not request.sampling.is_default()
        ):
            raise EngineRequestValidationError(
                "unsupported_feature",
                "per-request sampling controls require runtime_backend=faster",
            )
        sampling = _resolve_faster_sampling(self._config, request)

        model = self._require_model()
        _validate_sampling_top_k_for_model(model, int(sampling["top_k"]))
        model_type = _qwen_model_type(model)
        if model_type == "custom_voice":
            _reject_voice_clone_fields_for_non_base_model(request)
            _validate_custom_voice_request(model, request)
            if request.instruction.strip() and not _supports_custom_voice_instructions(
                model,
                self._config,
            ):
                raise EngineRequestValidationError(
                    "unsupported_feature",
                    "the loaded FasterQwen CustomVoice runtime does not support "
                    "style instructions for this model; use a runtime that "
                    "advertises supports_custom_voice_instructions",
                )
            return

        if model_type == "voice_design":
            _reject_voice_clone_fields_for_non_base_model(request)
            if not request.instruction.strip():
                raise EngineRequestValidationError(
                    "missing_required_field",
                    "qwen voice design model requires an instruction",
                )
            return

        if model_type == "base":
            _validate_voice_clone_request(request, self._voice_profiles)
            return

        raise EngineRequestValidationError(
            "invalid_field_type",
            f"unsupported qwen tts_model_type: {model_type or 'unknown'}",
        )

    def describe_request(self, request: SynthesisRequest) -> dict[str, object]:
        """Apply explicit RNG state and report effective generation controls."""

        self.validate_request(request)
        sampling = _resolve_faster_sampling(self._config, request)
        effective_seed = _request_seed(self._config, request)
        _seed_runtime(
            effective_seed,
            strict=request.seed is not None,
            require_cuda=self._config.device.lower().startswith("cuda"),
        )
        return {
            "effective_seed": effective_seed,
            "effective_seed_explicit": request.seed is not None,
            "effective_temperature": sampling["temperature"],
            "effective_top_k": sampling["top_k"],
            "effective_top_p": sampling["top_p"],
            "effective_repetition_penalty": sampling["repetition_penalty"],
            "effective_do_sample": sampling["do_sample"],
        }

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
            self._last_generation_trace = None
            _seed_runtime(
                _request_seed(self._config, request),
                strict=request.seed is not None,
                require_cuda=self._config.device.lower().startswith("cuda"),
            )
            audio_stream = self._generate_audio_stream(model, request, cancel_event)
            emitted_audio_bytes = 0
            max_audio_bytes = _max_audio_bytes(self._config, request)
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
                        truncated_to_safety_limit = False
                        if max_audio_bytes is not None:
                            remaining_bytes = max_audio_bytes - emitted_audio_bytes
                            if remaining_bytes <= 0:
                                raise _safety_duration_limit_error(
                                    self._config,
                                    emitted_audio_bytes,
                                    request,
                                )
                            if len(pcm) > remaining_bytes:
                                pcm = pcm[: remaining_bytes - (remaining_bytes % 2)]
                                if not pcm:
                                    raise _safety_duration_limit_error(
                                        self._config,
                                        emitted_audio_bytes,
                                        request,
                                    )
                                truncated_to_safety_limit = True
                        self._last_chunk_metrics = _first_chunk_timing_fields(
                            chunk_timing,
                            next_wall_ms=next_wall_ms,
                            pcm_convert_ms=pcm_convert_ms,
                        )
                        emitted_audio_bytes += len(pcm)
                        yield pcm
                        if truncated_to_safety_limit:
                            raise _safety_duration_limit_error(
                                self._config,
                                emitted_audio_bytes,
                                request,
                            )
                if not cancel_event.is_set():
                    self._capture_generation_trace(model)
            finally:
                if callable(close_stream):
                    close_stream()
                self._maybe_close_profile_pair_range(request.request_id)

    def pop_last_chunk_metrics(self) -> dict[str, object] | None:
        """Return timing metadata for the last yielded PCM chunk, if available."""

        metrics = self._last_chunk_metrics
        self._last_chunk_metrics = None
        return metrics

    def pop_last_generation_trace(self) -> dict[str, object] | None:
        """Return the completed diagnostic generation trace, if collected."""

        trace = self._last_generation_trace
        self._last_generation_trace = None
        return trace

    def _capture_generation_trace(self, model: Any) -> None:
        if not self._config.collect_generation_trace:
            return
        trace = getattr(model, "last_generation_trace", None)
        if not isinstance(trace, dict):
            raise QwenEngineError("faster backend did not produce a generation trace")
        self._last_generation_trace = {str(key): value for key, value in trace.items()}

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

        audio_duration_ms = (
            total_bytes
            * 1000.0
            / (request.output.sample_rate * request.output.channels * 2)
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
        output_chunk_limit: int | None = None,
    ) -> dict[str, object]:
        cancel_event = threading.Event()
        stream = self.synthesize_stream(request, cancel_event)
        close_stream = getattr(stream, "close", None)
        started_at = monotonic_seconds()
        first_audio_ms: float | None = None
        max_output_chunks = (
            output_chunk_limit
            if output_chunk_limit is not None
            else _warmup_pass_max_output_chunks(self._config, pass_index)
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

        audio_duration_ms = (
            audio_bytes
            * 1000.0
            / (request.output.sample_rate * request.output.channels * 2)
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

    def _run_prefill_first_chunk_warmup(self) -> dict[str, object]:
        entries = _load_prefill_allowlist_warmup_manifest(
            Path(self._config.prefill_allowlist_warmup_manifest),
            self._config.prefill_compile_lengths,
        )
        length = self._config.prefill_first_chunk_warmup_length
        if length is None:
            raise QwenEngineError(
                "first-chunk warmup requires an explicit allowlisted length"
            )
        entry = entries[length]
        model = self._require_model()
        request = SynthesisRequest(
            request_id=0,
            text=str(entry["text"]),
            language=str(entry["language"]),
            speaker=str(entry.get("speaker") or self._config.warmup_speaker),
            instruction=_prefill_warmup_instruction(model, entry) or "",
            output=AudioFormat.default(),
        )
        self.validate_request(request)

        started_at = monotonic_seconds()
        with _preserved_rng_state():
            pass_fields = self._run_warmup_synthesis_pass(
                request,
                pass_index=1,
                output_chunk_limit=1,
            )
        reset_started = monotonic_seconds()
        reset_metadata = _reset_after_partial_generation(model)
        torch = importlib.import_module("torch")
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        self._last_chunk_metrics = None

        return {
            "prefill_first_chunk_warmup": True,
            "prefill_first_chunk_warmup_ready": True,
            "prefill_first_chunk_warmup_length": length,
            "prefill_first_chunk_warmup_duration_ms": elapsed_milliseconds(started_at),
            "prefill_first_chunk_warmup_reset_ms": elapsed_milliseconds(reset_started),
            "prefill_first_chunk_warmup_reset": reset_metadata,
            "prefill_first_chunk_warmup_first_audio_ms": pass_fields["first_audio_ms"],
            "prefill_first_chunk_warmup_audio_chunks": pass_fields["audio_chunks"],
        }

    def _run_prefill_generation_prime(self) -> dict[str, object]:
        """Prime one internal generation to natural EOS before worker readiness.

        The existing partial first-chunk warmup is deliberately not reused here:
        a partial stream needs an explicit graph reset and did not establish
        decode parity for the first real request. This pass therefore consumes a
        finite, safety-limited prompt to natural EOS and fails startup otherwise.
        """
        entries = _load_prefill_allowlist_warmup_manifest(
            Path(self._config.prefill_allowlist_warmup_manifest),
            self._config.prefill_compile_lengths,
        )
        length = self._config.prefill_first_chunk_warmup_length
        if length is None:
            raise QwenEngineError("generation prime requires an allowlisted length")
        entry = entries[length]
        model = self._require_model()
        request = SynthesisRequest(
            request_id=0,
            text=str(entry["text"]),
            language=str(entry["language"]),
            speaker=str(entry.get("speaker") or self._config.warmup_speaker),
            instruction=_prefill_warmup_instruction(model, entry) or "",
            output=AudioFormat.default(),
        )
        self.validate_request(request)
        started_at = monotonic_seconds()
        rng_before = _rng_state_fingerprint()
        with _preserved_rng_state():
            pass_fields = self._run_warmup_synthesis_pass(
                request, pass_index=1, output_chunk_limit=None
            )
        rng_after = _rng_state_fingerprint()
        if rng_before != rng_after:
            raise QwenEngineError("generation prime changed caller RNG state")
        trace = self.pop_last_generation_trace()
        if not isinstance(trace, dict) or trace.get("termination_reason") != "eos":
            raise QwenEngineError("generation prime did not reach natural eos")
        if pass_fields["bounded"]:
            raise QwenEngineError("generation prime unexpectedly used a chunk limit")
        self._last_chunk_metrics = None
        return {
            "prefill_generation_prime": True,
            "prefill_generation_prime_ready": True,
            "prefill_generation_prime_internal_only": True,
            "prefill_generation_prime_requires_natural_eos": True,
            "prefill_generation_prime_safety_limit_seconds": (
                self._config.max_audio_seconds_per_utterance
            ),
            "prefill_generation_prime_length": length,
            "prefill_generation_prime_duration_ms": elapsed_milliseconds(started_at),
            "prefill_generation_prime_first_audio_ms": pass_fields["first_audio_ms"],
            "prefill_generation_prime_audio_chunks": pass_fields["audio_chunks"],
            "prefill_generation_prime_codec_frames": trace.get("codec_frame_count"),
            "prefill_generation_prime_rng_before": rng_before,
            "prefill_generation_prime_rng_after": rng_after,
        }

    def _run_prefill_allowlist_warmup(self, model: Any) -> dict[str, object]:
        _set_prefill_require_precompiled(model, False)
        entries = _load_prefill_allowlist_warmup_manifest(
            Path(self._config.prefill_allowlist_warmup_manifest),
            self._config.prefill_compile_lengths,
        )
        torch = importlib.import_module("torch")
        streaming = importlib.import_module("faster_qwen3_tts.streaming")
        prefill_call = streaming._run_talker_prefill
        select_mask_mode = streaming.select_prefill_mask_mode

        rows: list[dict[str, object]] = []
        decode_state_fields: dict[str, object] | None = None
        started_at = monotonic_seconds()
        for expected_length in self._config.prefill_compile_lengths:
            entry = entries[expected_length]
            with torch.inference_mode():
                prepared = model._prepare_generation_custom(
                    text=str(entry["text"]),
                    language=str(entry["language"]),
                    speaker=str(entry.get("speaker") or self._config.warmup_speaker),
                    instruct=_prefill_warmup_instruction(model, entry),
                    non_streaming_mode=True,
                    return_metadata=True,
                )
            _m, talker, _config, tie, tam, tth, tpe, metadata = prepared
            actual_length = int(metadata.get("talker_prefill_length", tie.shape[1]))
            if actual_length != expected_length:
                raise QwenEngineError(
                    "prefill warmup manifest length mismatch: "
                    f"expected={expected_length}, actual={actual_length}"
                )
            mask_mode = select_mask_mode(metadata)
            eager_out, _eager_profile = _call_prefill_for_warmup(
                prefill_call,
                talker,
                tie,
                tam,
                tth,
                tpe,
                metadata,
                backend="eager",
                mask_mode=mask_mode,
                config=self._config,
            )
            eager_snapshot = _snapshot_prefill_output(eager_out)
            compiled_profiles: list[dict[str, object]] = []
            compiled_snapshot: dict[str, Any] | None = None
            for _repeat in range(self._config.prefill_allowlist_warmup_repeats):
                out, profile = _call_prefill_for_warmup(
                    prefill_call,
                    talker,
                    tie,
                    tam,
                    tth,
                    tpe,
                    metadata,
                    backend=self._config.prefill_backend,
                    mask_mode=mask_mode,
                    config=self._config,
                )
                compiled_profiles.append(profile)
                compiled_snapshot = _snapshot_prefill_output(out)
            if compiled_snapshot is None:
                raise QwenEngineError("prefill warmup compiled pass did not run")
            max_abs = _prefill_snapshot_max_abs(eager_snapshot, compiled_snapshot)
            last_profile = compiled_profiles[-1]
            if max_abs > self._config.prefill_allowlist_max_abs_threshold:
                raise QwenEngineError(
                    "compiled prefill warmup drift exceeds threshold: "
                    f"length={expected_length}, max_abs={max_abs:.6g}, "
                    f"threshold={self._config.prefill_allowlist_max_abs_threshold}"
                )
            if last_profile.get("prefill_backend_used") != self._config.prefill_backend:
                raise QwenEngineError(
                    "compiled prefill warmup did not use requested backend: "
                    f"length={expected_length}, profile={last_profile}"
                )
            if last_profile.get("prefill_compile_fallback") is not False:
                raise QwenEngineError(
                    "compiled prefill warmup fell back to eager: "
                    f"length={expected_length}, profile={last_profile}"
                )
            if last_profile.get("prefill_shape_policy") != "compiled_allowlist":
                raise QwenEngineError(
                    "compiled prefill warmup did not use allowlist policy: "
                    f"length={expected_length}, profile={last_profile}"
                )
            ordinal = _profile_int(last_profile, "prefill_shape_call_ordinal")
            if ordinal < 3:
                raise QwenEngineError(
                    "compiled prefill warmup did not reach ordinal 3: "
                    f"length={expected_length}, profile={last_profile}"
                )
            if decode_state_fields is None:
                decode_state_fields = _run_prefill_decode_state_warmup(
                    model,
                    talker,
                    tam,
                    out,
                    metadata,
                )
            self._prewarmed_prefill_lengths.add(expected_length)
            rows.append(
                {
                    "talker_prefill_length": expected_length,
                    "mask_mode": mask_mode,
                    "max_abs_observed": round(max_abs, 8),
                    "prefill_shape_call_ordinal": ordinal,
                    "prefill_compile_cache_hit": bool(
                        last_profile.get("prefill_compile_cache_hit")
                    ),
                    "prefill_shape_talker_input_embeds": last_profile.get(
                        "prefill_shape_talker_input_embeds"
                    ),
                    "prefill_shape_attention_mask": last_profile.get(
                        "prefill_shape_attention_mask"
                    ),
                    "prefill_shape_trailing_text_hiddens": last_profile.get(
                        "prefill_shape_trailing_text_hiddens"
                    ),
                    "prefill_shape_tts_pad_embed": last_profile.get(
                        "prefill_shape_tts_pad_embed"
                    ),
                }
            )

        if decode_state_fields is None:
            raise QwenEngineError("prefill decode-state warmup did not run")

        return {
            "prefill_allowlist_warmup": True,
            "prefill_allowlist_ready": True,
            "prefill_allowlist_lengths": list(self._config.prefill_compile_lengths),
            "prefill_allowlist_warmup_repeats": (
                self._config.prefill_allowlist_warmup_repeats
            ),
            "prefill_allowlist_warmup_duration_ms": elapsed_milliseconds(started_at),
            "prefill_allowlist_warmup_passes": rows,
            **decode_state_fields,
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
            voice_clone_prompt = self._voice_clone_prompt_for(model, request)
            wavs, sample_rate = model.generate_voice_clone(
                text=request.text,
                language=_model_call_language(self._config, request.language),
                ref_audio=(
                    None
                    if voice_clone_prompt is not None
                    else request.reference_audio_path
                ),
                ref_text=(
                    None
                    if voice_clone_prompt is not None
                    else request.reference_text or None
                ),
                x_vector_only_mode=(
                    False if voice_clone_prompt is not None else request.x_vector_only
                ),
                voice_clone_prompt=voice_clone_prompt,
            )
            return wavs, sample_rate

        raise QwenEngineError(
            f"unsupported qwen tts_model_type: {model_type or 'unknown'}"
        )

    def _generate_audio_stream(
        self,
        model: Any,
        request: SynthesisRequest,
        cancel_event: threading.Event,
    ) -> Iterable[tuple[Any, int]]:
        stream = _qwen_stream_generate_audio(
            model,
            self._config,
            request,
            cancel_event,
            voice_clone_prompt=self._voice_clone_prompt_for(model, request),
        )
        if stream is not None:
            return stream

        return _qwen_full_audio_as_stream(self._generate_audio(model, request))

    def _voice_clone_prompt_for(
        self,
        model: Any,
        request: SynthesisRequest,
    ) -> Any | None:
        if not request.voice_id:
            return None
        if self._voice_profiles is None:
            raise QwenEngineError("the loaded worker has no voice profile registry")
        try:
            return self._voice_profiles.prompt_for(model, request.voice_id)
        except VoiceProfileError as exc:
            raise QwenEngineError(str(exc)) from exc


def _max_audio_bytes(
    config: QwenEngineConfig,
    request: SynthesisRequest,
) -> int | None:
    if config.max_audio_seconds_per_utterance is None:
        return None
    bytes_per_second = request.output.sample_rate * request.output.channels * 2
    return int(config.max_audio_seconds_per_utterance * bytes_per_second)


def _safety_duration_limit_error(
    config: QwenEngineConfig,
    emitted_audio_bytes: int,
    request: SynthesisRequest,
) -> GenerationSafetyLimitError:
    assert config.max_audio_seconds_per_utterance is not None
    bytes_per_second = request.output.sample_rate * request.output.channels * 2
    emitted_seconds = emitted_audio_bytes / bytes_per_second
    return GenerationSafetyLimitError(
        config.max_audio_seconds_per_utterance,
        emitted_seconds,
    )


def _default_model_loader(config: QwenEngineConfig) -> Any:
    try:
        return load_qwen_model(config)
    except QwenModelLoadError as exc:
        raise QwenEngineError(str(exc)) from exc


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
    _validate_loaded_prefill_compile_compat_metadata(model, config)

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


def _validate_loaded_prefill_compile_compat_metadata(
    model: Any,
    config: QwenEngineConfig,
) -> None:
    metadata = getattr(model, "prefill_compile_compat_metadata", None)
    if callable(metadata):
        metadata = metadata()
    if not isinstance(metadata, dict):
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 requires loaded faster model compat metadata"
        )

    expected = config.prefill_compile_compat_mode
    version = metadata.get("prefill_compile_compat_metadata_version")
    if version != 1:
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 requires compat metadata version 1; "
            f"actual={version!r}"
        )
    wrapper_mode = metadata.get("prefill_compile_compat_wrapper_mode", expected)
    declared_mode = metadata.get("prefill_compile_compat_declared_mode")
    applied_mode = metadata.get("prefill_compile_compat_mode")
    if (
        wrapper_mode != expected
        or declared_mode != expected
        or applied_mode != expected
    ):
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 compat metadata mode mismatch: "
            f"wrapper={wrapper_mode!r}, declared={declared_mode!r}, "
            f"applied={applied_mode!r}, expected={expected!r}"
        )
    if metadata.get("prefill_compile_compat_applied") is True:
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 compat patch must be idle after model load"
        )

    patched = metadata.get("prefill_compile_compat_validated_modules")
    if not isinstance(patched, dict):
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 compat metadata missing validated module counts"
        )
    for name in ("rmsnorm", "mlp", "attention"):
        count = patched.get(name)
        if not isinstance(count, int) or count <= 0:
            raise QwenEngineError(
                "strict_bf16_sdpa_v1 requires positive patched module count "
                f"for {name}; actual={count!r}"
            )
    _validate_loaded_prefill_compile_compat_fingerprint(patched, metadata)


def _validate_loaded_prefill_compile_compat_fingerprint(
    counts: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    fingerprint = metadata.get("prefill_compile_compat_target_fingerprint")
    if not isinstance(fingerprint, dict):
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 compat metadata missing target fingerprint"
        )
    if fingerprint.get("schema_version") != 1:
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 requires target fingerprint schema version 1; "
            f"actual={fingerprint.get('schema_version')!r}"
        )
    for name in ("rmsnorm", "mlp", "attention"):
        if fingerprint.get(name) != counts.get(name):
            raise QwenEngineError(
                "strict_bf16_sdpa_v1 target fingerprint/count mismatch for "
                f"{name}: fingerprint={fingerprint.get(name)!r}, "
                f"count={counts.get(name)!r}"
            )

    attention_count = counts["attention"]
    mlp_count = counts["mlp"]
    rmsnorm_count = counts["rmsnorm"]
    if attention_count != mlp_count:
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 requires attention and MLP target counts "
            f"to match; attention={attention_count}, mlp={mlp_count}"
        )
    if rmsnorm_count < attention_count * 3:
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 RMSNorm target count is too small for the "
            f"decoder stack; rmsnorm={rmsnorm_count}, layers={attention_count}"
        )
    if rmsnorm_count > attention_count * 5 + 8:
        raise QwenEngineError(
            "strict_bf16_sdpa_v1 RMSNorm target count is unexpectedly large "
            f"for the decoder stack; rmsnorm={rmsnorm_count}, "
            f"layers={attention_count}"
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


def _load_prefill_allowlist_warmup_manifest(
    path: Path,
    lengths: tuple[int, ...],
) -> dict[int, dict[str, object]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise QwenEngineError(
            f"failed to read prefill warmup manifest: {path}"
        ) from exc

    try:
        if text.lstrip().startswith("["):
            payload: Any = json.loads(text)
        elif text.lstrip().startswith("{"):
            payload = json.loads(text)
        else:
            payload = [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise QwenEngineError(
            f"prefill warmup manifest is not valid JSON/JSONL: {path}"
        ) from exc

    default_speaker = ""
    rows: list[Any]
    if isinstance(payload, dict):
        rows_value = payload.get("rows")
        if not isinstance(rows_value, list):
            raise QwenEngineError("prefill warmup manifest dict must contain rows")
        default_speaker = str(payload.get("speaker") or "")
        rows = rows_value
    elif isinstance(payload, list):
        rows = payload
    else:
        raise QwenEngineError("prefill warmup manifest must be an object or list")

    needed = set(lengths)
    result: dict[int, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_length = row.get("talker_prefill_length")
        if raw_length is None:
            raw_length = row.get("prefill_shape_length")
        if raw_length is None:
            continue
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            continue
        if length not in needed or length in result:
            continue
        text_value = row.get("text")
        language = row.get("language", "Auto")
        if not isinstance(text_value, str) or not text_value:
            raise QwenEngineError(
                f"prefill warmup row for length {length} must contain text"
            )
        result[length] = {
            "text": text_value,
            "language": str(language or "Auto"),
            "speaker": str(row.get("speaker") or default_speaker),
            "instruction": str(row.get("instruction") or ""),
        }

    missing = [length for length in lengths if length not in result]
    if missing:
        raise QwenEngineError(
            f"prefill warmup manifest missing allowlisted lengths: {missing}"
        )
    return result


def _prefill_warmup_instruction(model: Any, entry: dict[str, object]) -> str | None:
    instruction = str(entry.get("instruction") or "")
    model_size = str(_nested_attr(model, ("model", "model", "tts_model_size")) or "")
    if model_size.lower() in {"0b6", "0.6b", "0.6"}:
        return None
    return instruction or None


def _call_prefill_for_warmup(
    prefill_call: Any,
    talker: Any,
    tie: Any,
    tam: Any,
    tth: Any,
    tpe: Any,
    metadata: dict[str, Any],
    *,
    backend: str,
    mask_mode: str,
    config: QwenEngineConfig,
) -> tuple[Any, dict[str, object]]:
    torch = importlib.import_module("torch")
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    with torch.inference_mode():
        out, profile = prefill_call(
            talker,
            tie,
            tam,
            tth,
            tpe,
            prefill_backend=backend,
            prefill_mask_mode=mask_mode,
            prefill_compile_compat_mode=(
                "none" if backend == "eager" else config.prefill_compile_compat_mode
            ),
            prefill_compile_lengths=config.prefill_compile_lengths,
            prefill_compile_on_miss=config.prefill_compile_on_miss,
            prefill_unknown_shape_policy=config.prefill_unknown_shape_policy,
            input_metadata=metadata,
        )
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    return out, cast(dict[str, object], profile)


def _run_prefill_decode_state_warmup(
    model: Any,
    talker: Any,
    attention_mask: Any,
    prefill_out: Any,
    metadata: dict[str, Any],
) -> dict[str, object]:
    talker_graph = getattr(model, "talker_graph", None)
    if talker_graph is None:
        raise QwenEngineError("loaded faster model does not expose talker_graph")

    torch = importlib.import_module("torch")
    started_at = monotonic_seconds()
    with torch.inference_mode():
        prefill_kv_started = monotonic_seconds()
        prefill_len = int(talker_graph.prefill_kv(prefill_out.past_key_values))
        prefill_kv_ms = elapsed_milliseconds(prefill_kv_started)

        generation_state_started = monotonic_seconds()
        attention_mask_all_valid = (
            metadata.get("prefill_attention_mask_all_valid") is True
        )
        generation_attention_mask = None if attention_mask_all_valid else attention_mask
        talker_graph.set_generation_state(
            generation_attention_mask,
            getattr(talker, "rope_deltas", None),
            attention_mask_all_valid=attention_mask_all_valid,
        )
        generation_state_ms = elapsed_milliseconds(generation_state_started)

        replay_started = monotonic_seconds()
        if prefill_len >= int(talker_graph.max_seq_len) - 1:
            raise QwenEngineError(
                "prefill decode-state warmup length exceeds talker graph capacity: "
                f"prefill_len={prefill_len}, max_seq_len={talker_graph.max_seq_len}"
            )
        input_embeds = prefill_out.past_hidden[:, -1:, :]
        talker_graph.run(input_embeds, position=prefill_len)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        replay_ms = elapsed_milliseconds(replay_started)

        reset_started = monotonic_seconds()
        talker_graph.reset(prefill_len)
        reset_ms = elapsed_milliseconds(reset_started)

    profile = getattr(talker_graph, "last_generation_state_profile", None)
    profile_fields = dict(profile) if isinstance(profile, dict) else {}
    if profile_fields.get("generation_state_mask_cache_hit") is not True:
        raise QwenEngineError(
            "prefill decode-state warmup did not hit the generation mask cache: "
            f"{profile_fields}"
        )
    if profile_fields.get("generation_state_masks_built") != 0:
        raise QwenEngineError(
            f"prefill decode-state warmup rebuilt generation masks: {profile_fields}"
        )

    return {
        "prefill_decode_state_warmup": True,
        "prefill_decode_state_ready": True,
        "prefill_decode_state_length": prefill_len,
        "prefill_decode_state_warmup_duration_ms": elapsed_milliseconds(started_at),
        "prefill_decode_state_prefill_kv_ms": prefill_kv_ms,
        "prefill_decode_state_generation_state_ms": generation_state_ms,
        "prefill_decode_state_replay_ms": replay_ms,
        "prefill_decode_state_reset_ms": reset_ms,
        **{
            f"prefill_decode_state_{key}": value
            for key, value in profile_fields.items()
        },
    }


def _snapshot_prefill_output(out: Any) -> dict[str, Any]:
    return {
        "logits": _snapshot_value(getattr(out, "logits", None)),
        "past_hidden": _snapshot_value(getattr(out, "past_hidden", None)),
        "past_key_values": _snapshot_value(getattr(out, "past_key_values", None)),
    }


def _snapshot_value(value: Any) -> Any:
    if hasattr(value, "detach"):
        return value.detach().float().cpu().clone()
    if isinstance(value, tuple):
        return tuple(_snapshot_value(item) for item in value)
    if isinstance(value, list):
        return [_snapshot_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _snapshot_value(item) for key, item in value.items()}
    return value


def _prefill_snapshot_max_abs(left: Any, right: Any) -> float:
    if type(left) is not type(right):
        raise QwenEngineError(
            "prefill warmup output type mismatch: "
            f"{type(left).__name__} != {type(right).__name__}"
        )
    if hasattr(left, "shape") and hasattr(right, "shape"):
        if tuple(left.shape) != tuple(right.shape):
            raise QwenEngineError(
                "prefill warmup output shape mismatch: "
                f"{tuple(left.shape)} != {tuple(right.shape)}"
            )
        if getattr(left, "dtype", None) != getattr(right, "dtype", None):
            raise QwenEngineError(
                "prefill warmup output dtype mismatch: "
                f"{getattr(left, 'dtype', None)} != {getattr(right, 'dtype', None)}"
            )
        return float((left - right).abs().max().item()) if left.numel() else 0.0
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            raise QwenEngineError(
                "prefill warmup output dictionary keys mismatch: "
                f"{sorted(map(str, left))} != {sorted(map(str, right))}"
            )
        return max(
            (_prefill_snapshot_max_abs(left[key], right[key]) for key in left),
            default=0.0,
        )
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if len(left) != len(right):
            raise QwenEngineError(
                "prefill warmup output sequence length mismatch: "
                f"{len(left)} != {len(right)}"
            )
        return max(
            (
                _prefill_snapshot_max_abs(left_item, right_item)
                for left_item, right_item in zip(left, right, strict=True)
            ),
            default=0.0,
        )
    return 0.0


def _set_prefill_require_precompiled(model: Any, enabled: bool) -> None:
    if not hasattr(model, "prefill_require_precompiled"):
        raise QwenEngineError(
            "loaded faster model does not support prefill_require_precompiled; "
            "reinstall the bridge-patched faster-qwen3-tts wheel"
        )
    model.prefill_require_precompiled = bool(enabled)


def _profile_int(profile: dict[str, object], key: str) -> int:
    value = profile.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return int(value)
    return 0


def _request_seed(
    config: QwenEngineConfig,
    request: SynthesisRequest,
) -> int | None:
    if request.seed is not None:
        return int(request.seed)
    request_id = request.request_id
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


def _seed_runtime(
    seed: int | None,
    *,
    strict: bool = False,
    require_cuda: bool = False,
) -> None:
    if seed is None:
        return
    failures: list[str] = []
    try:
        random.seed(seed)
    except Exception as exc:
        failures.append(f"Python RNG: {exc}")
    try:
        numpy = importlib.import_module("numpy")
        numpy.random.seed(seed % (2**32))
    except Exception as exc:
        failures.append(f"NumPy RNG: {exc}")
    try:
        torch = importlib.import_module("torch")
        torch.manual_seed(seed)
        cuda = getattr(torch, "cuda", None)
        manual_seed_all = getattr(cuda, "manual_seed_all", None)
        if require_cuda and not callable(manual_seed_all):
            raise RuntimeError("torch.cuda.manual_seed_all is unavailable")
        if require_cuda:
            assert callable(manual_seed_all)
            manual_seed_all(seed)
    except Exception as exc:
        failures.append(f"Torch RNG: {exc}")

    if strict and failures:
        raise EngineRequestValidationError(
            "seed_application_failed",
            "could not apply explicit seed to all required RNGs: "
            + "; ".join(failures),
        )


def _reset_after_partial_generation(model: Any) -> dict[str, object]:
    reset = getattr(model, "reset_after_partial_generation", None)
    if not callable(reset):
        raise QwenEngineError(
            "loaded faster model does not expose reset_after_partial_generation()"
        )
    try:
        metadata = reset()
    except Exception as exc:
        raise QwenEngineError("failed to reset partial faster generation") from exc
    if not isinstance(metadata, dict):
        raise QwenEngineError("partial faster generation reset returned no metadata")
    if metadata.get("reset_api_version") != 1:
        raise QwenEngineError("partial faster generation reset API version mismatch")
    if metadata.get("talker_graph_reset") is not True:
        raise QwenEngineError("partial faster generation did not reset TalkerGraph")
    predictor_count = metadata.get("predictor_graphs_reset")
    if not isinstance(predictor_count, int) or predictor_count <= 0:
        raise QwenEngineError("partial faster generation did not reset PredictorGraph")
    for name in (
        "compiled_prefill_cache_preserved",
        "cuda_graphs_preserved",
        "generation_mask_cache_preserved",
    ):
        if metadata.get(name) is not True:
            raise QwenEngineError(
                f"partial faster generation reset did not preserve {name}"
            )
    return metadata


def _rng_state_fingerprint(*, require_cuda: bool = True) -> dict[str, str]:
    """Return stable hashes for every RNG state guarded by warmup passes."""

    try:
        numpy = importlib.import_module("numpy")
        torch = importlib.import_module("torch")
        cuda_available = bool(torch.cuda.is_available())
        if require_cuda and not cuda_available:
            raise QwenEngineError("strict generation prime requires CUDA RNG state")
        numpy_state = numpy.random.get_state()
        torch_cpu_state = torch.get_rng_state().cpu().numpy().tobytes()
        cuda_states = torch.cuda.get_rng_state_all() if cuda_available else ()
    except QwenEngineError:
        raise
    except Exception as exc:
        raise QwenEngineError(
            "failed to fingerprint generation-prime RNG state"
        ) from exc

    def digest(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    numpy_bytes = b"".join(
        (
            str(numpy_state[0]).encode("ascii"),
            numpy_state[1].tobytes(),
            str(numpy_state[2:]).encode("ascii"),
        )
    )
    return {
        "python_sha256": digest(repr(random.getstate()).encode("utf-8")),
        "numpy_sha256": digest(numpy_bytes),
        "torch_cpu_sha256": digest(torch_cpu_state),
        "torch_cuda_sha256": digest(
            b"".join(state.cpu().numpy().tobytes() for state in cuda_states)
        ),
    }


@contextmanager
def _preserved_rng_state(*, require_cuda: bool = True) -> Iterator[None]:
    python_state = random.getstate()
    try:
        numpy = importlib.import_module("numpy")
        numpy_state = numpy.random.get_state()
    except Exception as exc:
        raise QwenEngineError("failed to capture NumPy RNG state") from exc
    try:
        torch = importlib.import_module("torch")
        torch_cpu_state = torch.get_rng_state()
        cuda_available = bool(torch.cuda.is_available())
        if require_cuda and not cuda_available:
            raise QwenEngineError("strict first-chunk warmup requires CUDA RNG state")
        torch_cuda_states = torch.cuda.get_rng_state_all() if cuda_available else None
    except QwenEngineError:
        raise
    except Exception as exc:
        raise QwenEngineError("failed to capture torch RNG state") from exc
    try:
        yield
    finally:
        try:
            random.setstate(python_state)
            numpy.random.set_state(numpy_state)
            torch.set_rng_state(torch_cpu_state)
            if torch_cuda_states is not None:
                torch.cuda.set_rng_state_all(torch_cuda_states)
        except Exception as exc:
            raise QwenEngineError("failed to restore strict warmup RNG state") from exc


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

    if model_type == "base":
        return _supports_base_voice_clone_streaming(model)

    return False


def _supports_base_voice_clone_streaming(model: Any) -> bool:
    return callable(getattr(model, "stream_generate_voice_clone", None)) or callable(
        getattr(model, "generate_voice_clone_streaming", None)
    )


def _supports_qwen_instructions(model: Any, config: QwenEngineConfig) -> bool:
    model_type = _qwen_model_type(model)
    if model_type == "custom_voice":
        return _supports_custom_voice_instructions(model, config)
    return model_type == "voice_design"


def _validate_voice_clone_request(
    request: SynthesisRequest,
    profiles: VoiceProfileRegistry | None,
) -> None:
    """Validate local Base voice-clone inputs before model inference."""

    if request.speaker:
        raise EngineRequestValidationError(
            "unsupported_feature",
            "qwen base voice-clone requests do not accept speaker",
        )
    if request.instruction:
        raise EngineRequestValidationError(
            "unsupported_feature",
            "qwen base voice-clone requests do not accept instruction",
        )
    if request.voice_id:
        if (
            request.reference_audio_path
            or request.reference_text
            or request.x_vector_only
        ):
            raise EngineRequestValidationError(
                "invalid_field_type",
                "voice_id cannot be combined with direct reference-audio fields",
            )
        if profiles is None:
            raise EngineRequestValidationError(
                "unsupported_feature",
                "qwen base voice profiles require a configured voice registry",
            )
        if not profiles.has_voice(request.voice_id):
            raise EngineRequestValidationError(
                "invalid_field_type",
                f"unknown qwen base voice profile: {request.voice_id}",
            )
        return
    if not request.reference_audio_path:
        raise EngineRequestValidationError(
            "missing_required_field",
            "qwen base voice-clone requests require reference_audio_path",
        )
    try:
        preflight_reference_audio(
            request.reference_audio_path,
            request.reference_text,
            request.x_vector_only,
        )
    except VoiceProfileError as exc:
        raise EngineRequestValidationError(
            "invalid_field_type",
            str(exc),
        ) from exc


def _reject_voice_clone_fields_for_non_base_model(request: SynthesisRequest) -> None:
    """Reject Base-only clone inputs instead of silently ignoring them."""

    if (
        request.voice_id
        or request.reference_audio_path
        or request.reference_text
        or request.x_vector_only
    ):
        raise EngineRequestValidationError(
            "unsupported_feature",
            "voice cloning and registered voice profiles are supported only by "
            "qwen base models",
        )


def _supports_custom_voice_instructions(
    model: Any,
    config: QwenEngineConfig,
) -> bool:
    if config.runtime_backend != "faster":
        return True
    return bool(getattr(model, "supports_custom_voice_instructions", False))


def _supports_qwen_stream_generate_pcm(model: Any) -> bool:
    inner_model = getattr(model, "model", None)
    return callable(
        getattr(inner_model, "stream_generate_pcm", None)
    ) and _has_qwen_stream_helpers(model)


def _qwen_stream_generate_audio(
    model: Any,
    config: QwenEngineConfig,
    request: SynthesisRequest,
    cancel_event: threading.Event,
    voice_clone_prompt: Any | None = None,
) -> Iterable[tuple[Any, int]] | None:
    model_type = _qwen_model_type(model)
    language = _qwen_language(request.language)
    sampling = _resolve_faster_sampling(config, request)

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
                    "chunk_schedule": config.emit_chunk_schedule or None,
                    "overlap_samples": config.overlap_samples,
                    **sampling,
                    "prefill_backend": config.prefill_backend,
                    "prefill_compile_compat_mode": (config.prefill_compile_compat_mode),
                    "cancel_check": cancel_event.is_set,
                }
                if config.compiled_emit_chunk_schedule:
                    stream_kwargs["compiled_chunk_schedule"] = (
                        config.compiled_emit_chunk_schedule
                    )
                if config.eager_emit_chunk_schedule:
                    stream_kwargs["eager_chunk_schedule"] = (
                        config.eager_emit_chunk_schedule
                    )
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
            instruction=_custom_voice_instruction(model, config, request),
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
                    "chunk_schedule": config.emit_chunk_schedule or None,
                    **sampling,
                    "prefill_backend": config.prefill_backend,
                    "prefill_compile_compat_mode": (config.prefill_compile_compat_mode),
                    "cancel_check": cancel_event.is_set,
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

    if model_type == "base":
        if config.runtime_backend == "faster":
            public_stream = getattr(model, "generate_voice_clone_streaming", None)
            if callable(public_stream):
                stream_kwargs = {
                    "text": request.text,
                    "language": _qwen_runtime_language(request.language),
                    "ref_audio": (
                        None
                        if voice_clone_prompt is not None
                        else request.reference_audio_path
                    ),
                    "ref_text": (
                        "" if voice_clone_prompt is not None else request.reference_text
                    ),
                    "xvec_only": (
                        False
                        if voice_clone_prompt is not None
                        else request.x_vector_only
                    ),
                    "voice_clone_prompt": voice_clone_prompt,
                    "chunk_size": config.emit_every_frames,
                    **sampling,
                }
                return _faster_voice_clone_stream(
                    cast(
                        Iterable[tuple[Any, int, dict[str, Any]]],
                        public_stream(**stream_kwargs),
                    ),
                    cancel_event,
                )
            return None

        public_stream = getattr(model, "stream_generate_voice_clone", None)
        if callable(public_stream):
            return cast(
                Iterable[tuple[Any, int]],
                public_stream(
                    text=request.text,
                    language=language,
                    ref_audio=(
                        None
                        if voice_clone_prompt is not None
                        else request.reference_audio_path
                    ),
                    ref_text=(
                        None
                        if voice_clone_prompt is not None
                        else request.reference_text or None
                    ),
                    x_vector_only_mode=(
                        False
                        if voice_clone_prompt is not None
                        else request.x_vector_only
                    ),
                    voice_clone_prompt=voice_clone_prompt,
                    emit_every_frames=config.emit_every_frames,
                    decode_window_frames=config.decode_window_frames,
                    overlap_samples=config.overlap_samples,
                ),
            )

    return None


def _faster_voice_clone_stream(
    stream: Iterable[tuple[Any, int, dict[str, Any]]],
    cancel_event: threading.Event,
) -> Iterator[tuple[Any, int]]:
    """Adapt FasterQwen Base's timing-bearing stream to bridge PCM tuples."""

    close = getattr(stream, "close", None)
    try:
        for item in stream:
            if cancel_event.is_set():
                return
            if not isinstance(item, tuple) or len(item) != 3:
                raise QwenEngineError(
                    "FasterQwen Base streaming yielded an invalid chunk"
                )
            audio, sample_rate, _timing = item
            if not isinstance(sample_rate, int) or sample_rate <= 0:
                raise QwenEngineError(
                    "FasterQwen Base streaming yielded an invalid sample rate"
                )
            yield audio, sample_rate
    finally:
        if callable(close):
            close()


def _sampling_vocab_size(model: Any) -> int | None:
    """Return the loaded codec vocabulary size when the adapter exposes it."""

    for path in (
        ("model", "config", "vocab_size"),
        ("model", "model", "config", "vocab_size"),
        ("model", "model", "talker", "config", "vocab_size"),
        ("model", "model", "talker", "model", "config", "vocab_size"),
        ("config", "vocab_size"),
    ):
        value = _nested_attr(model, path)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def _validate_sampling_top_k_for_model(model: Any, top_k: int) -> None:
    """Reject top-k settings outside the loaded codec vocabulary."""

    vocabulary_size = _sampling_vocab_size(model)
    if vocabulary_size is not None and top_k > vocabulary_size:
        raise EngineRequestValidationError(
            "invalid_field_type",
            "sampling.top_k must not exceed the loaded codec vocabulary size "
            f"({vocabulary_size})",
        )


def _resolve_faster_sampling(
    config: QwenEngineConfig,
    request: SynthesisRequest,
) -> dict[str, float | int | bool]:
    """Resolve and validate request overrides against runtime sampling defaults."""

    options = request.sampling
    temperature = (
        config.temperature if options.temperature is None else options.temperature
    )
    top_k = config.top_k if options.top_k is None else options.top_k
    top_p = config.top_p if options.top_p is None else options.top_p
    repetition_penalty = (
        config.repetition_penalty
        if options.repetition_penalty is None
        else options.repetition_penalty
    )
    do_sample = config.do_sample if options.do_sample is None else options.do_sample

    if not math.isfinite(temperature) or not 0.0 < temperature <= 2.0:
        raise EngineRequestValidationError(
            "invalid_field_type",
            "sampling.temperature must be finite and in the interval (0, 2]",
        )
    if top_k <= 0:
        raise EngineRequestValidationError(
            "invalid_field_type",
            "sampling.top_k must be greater than zero",
        )
    if not math.isfinite(top_p) or not 0.0 < top_p <= 1.0:
        raise EngineRequestValidationError(
            "invalid_field_type",
            "sampling.top_p must be finite and in the interval (0, 1]",
        )
    if not math.isfinite(repetition_penalty) or not 1.0 <= repetition_penalty <= 2.0:
        raise EngineRequestValidationError(
            "invalid_field_type",
            "sampling.repetition_penalty must be finite and in the interval [1, 2]",
        )
    return {
        "temperature": temperature,
        "top_k": top_k,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
        "do_sample": do_sample,
    }


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
    if not callable(stream_generate_pcm) or not _supports_qwen_stream_generate_pcm(
        model
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
        "emit_chunk_schedule": list(config.emit_chunk_schedule),
        "compiled_emit_chunk_schedule": list(config.compiled_emit_chunk_schedule),
        "eager_emit_chunk_schedule": list(config.eager_emit_chunk_schedule),
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
    instruction_token_count = _sequence_length(instruct_ids[0]) if instruct_ids else 0
    metadata: dict[str, object] = {}
    if text_token_count is not None:
        metadata["text_token_count"] = text_token_count
    if instruction_token_count is not None:
        metadata["instruction_token_count"] = instruction_token_count
    if text_token_count is not None and instruction_token_count is not None:
        metadata["prefill_sequence_length"] = text_token_count + instruction_token_count
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
    decode_ms = _number_field(chunk_timing, "ar_decode_ms") or _number_field(
        chunk_timing, "decode_ms"
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
        "generation_state_masks_built",
        "prefill_compile_cache_entries",
        "prefill_compile_cache_entries_before",
        "prefill_compile_cache_entries_after",
        "prefill_compile_cache_entries_delta",
        "prefill_compile_cache_talker_entries",
        "prefill_compile_cache_talker_entries_before",
        "prefill_compile_cache_talker_entries_after",
        "prefill_compile_cache_talker_entries_delta",
        "prefill_compile_cache_max_entries",
        "prefill_compile_cache_evictions",
        "prefill_compile_cache_evictions_before",
        "prefill_compile_cache_evictions_after",
        "prefill_compile_cache_evictions_delta",
        "prefill_compile_attempt_count",
        "prefill_dynamo_unique_graphs_before",
        "prefill_dynamo_unique_graphs_after",
        "prefill_dynamo_unique_graphs_delta",
        "prefill_shape_call_ordinal",
        "prefill_shape_length",
        "chunk_target_steps",
        "chunk_schedule_index",
        "prefill_cuda_memory_before_allocated_bytes",
        "prefill_cuda_memory_before_reserved_bytes",
        "prefill_cuda_memory_before_max_reserved_bytes",
        "prefill_cuda_memory_after_allocated_bytes",
        "prefill_cuda_memory_after_reserved_bytes",
        "prefill_cuda_memory_after_max_reserved_bytes",
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
        "prefill_compile_cache_kind",
        "prefill_shape_policy",
        "chunk_schedule_decision",
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
        "prefill_compile_attempted",
        "prefill_compile_compat_applied",
        "prefill_compile_compat_reused",
        "prefill_compile_cache_hit",
        "prefill_shape_allowlist_hit",
        "prefill_compile_on_miss",
        "prefill_require_precompiled",
        "prefill_dynamo_counter_available",
        "generation_state_mask_cache_hit",
        "generation_state_attention_mask_all_valid",
        "is_final",
    ):
        value = chunk_timing.get(key)
        if isinstance(value, bool):
            fields[key] = value
    value = chunk_timing.get("prefill_compile_compat_patched_modules")
    if isinstance(value, dict):
        fields["prefill_compile_compat_patched_modules"] = dict(value)
    for key in (
        "selected_chunk_schedule",
        "prefill_shape_talker_input_embeds",
        "prefill_shape_attention_mask",
        "prefill_shape_trailing_text_hiddens",
        "prefill_shape_tts_pad_embed",
    ):
        value = chunk_timing.get(key)
        if isinstance(value, (list, tuple)):
            fields[key] = value
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
        "generation_state_total_ms",
        "generation_state_mask_key_ms",
        "generation_state_mask_table_build_ms",
        "generation_state_rope_copy_ms",
        "generation_state_gpu_ms",
        "prefill_to_sync_gpu_ms",
        "prefill_sync_wait_ms",
        "prefill_gpu_component_sum_ms",
        "prefill_gpu_partition_error_ms",
        "prefill_gpu_accounting_error_ms",
        "prefill_compile_wall_ms",
        "prefill_compile_wrapper_create_ms",
        "prefill_compile_wrapper_create_host_ms",
        "prefill_compiled_call_ms",
        "prefill_compiled_call_host_ms",
        "prefill_compiled_first_call_ms",
        "prefill_compiled_warm_call_ms",
        "prefill_compiled_call_1_host_ms",
        "prefill_compiled_call_2_host_ms",
        "prefill_compiled_call_3plus_host_ms",
        "codec_context_assembly_ms",
        "speech_tokenizer_decode_wall_ms",
        "speech_tokenizer_decode_gpu_ms",
        "d2h_ms",
        "numpy_ms",
        "audio_flatten_ms",
        "audio_slice_ms",
        "codec_wrapper_wall_ms",
        "codec_wrapper_other_ms",
        "first_sample_setup_gpu_ms",
        "first_sample_logits_prepare_gpu_ms",
        "first_sample_clone_suppress_gpu_ms",
        "first_sample_temperature_gpu_ms",
        "first_sample_top_k_gpu_ms",
        "first_sample_top_p_gpu_ms",
        "first_sample_softmax_gpu_ms",
        "first_sample_multinomial_gpu_ms",
        "first_sample_argmax_gpu_ms",
        "ar_predictor_graph_gpu_ms",
        "ar_history_update_gpu_ms",
        "ar_codebook_embed_gather_gpu_ms",
        "ar_talker_graph_replay_gpu_ms",
        "ar_logits_prepare_gpu_ms",
        "ar_sample_clone_suppress_gpu_ms",
        "ar_sample_temperature_gpu_ms",
        "ar_sample_top_k_gpu_ms",
        "ar_sample_top_p_gpu_ms",
        "ar_sample_softmax_gpu_ms",
        "ar_sample_multinomial_gpu_ms",
        "ar_sample_argmax_gpu_ms",
        "ar_state_update_gpu_ms",
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

    for key in (
        "generation_state_mask_key",
        "generation_state_previous_mask_key",
    ):
        if key in chunk_timing:
            value = chunk_timing.get(key)
            if value is None or isinstance(value, (list, tuple)):
                fields[key] = value

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
    config: QwenEngineConfig,
    request: SynthesisRequest,
) -> str | None:
    if not request.instruction or not _supports_custom_voice_instructions(
        model,
        config,
    ):
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
