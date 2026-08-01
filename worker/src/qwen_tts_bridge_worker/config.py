"""Runtime configuration DTOs for the Python worker."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Mapping, TypeAlias

MAX_EMIT_CHUNK_SCHEDULE_FRAMES = 64


def _validate_sampling_values(
    *,
    temperature: float,
    top_k: int,
    top_p: float,
    repetition_penalty: float,
) -> None:
    if not math.isfinite(temperature) or not 0.0 < temperature <= 2.0:
        raise ValueError("qwen.temperature must be finite and in the interval (0, 2]")
    if top_k <= 0:
        raise ValueError("qwen.top_k must be greater than zero")
    if not math.isfinite(top_p) or not 0.0 < top_p <= 1.0:
        raise ValueError("qwen.top_p must be finite and in the interval (0, 1]")
    if not math.isfinite(repetition_penalty) or not 1.0 <= repetition_penalty <= 2.0:
        raise ValueError(
            "qwen.repetition_penalty must be finite and in the interval [1, 2]"
        )


@dataclass(frozen=True, slots=True)
class CanaryRuntimeProvenance:
    """Pinned runtime identity emitted with local canary diagnostics."""

    runtime_profile_id: str
    bridge_commit: str
    faster_wheel_sha256: str
    compiled_allowlist_manifest_sha256: str
    compiled_lengths: tuple[int, ...]

    @classmethod
    def from_manifests(
        cls,
        runtime_profile: Mapping[str, object],
        allowlist: Mapping[str, object],
        allowlist_sha256: str,
    ) -> "CanaryRuntimeProvenance":
        """Create a provenance record after validating paired manifests."""

        required = {
            "runtime_profile_id",
            "bridge_commit",
            "faster_wheel_sha256",
            "compiled_allowlist_manifest_sha256",
        }
        missing = sorted(required.difference(runtime_profile))
        if missing:
            raise ValueError(
                "runtime profile manifest is missing " + ", ".join(missing)
            )
        if runtime_profile["compiled_allowlist_manifest_sha256"] != allowlist_sha256:
            raise ValueError("runtime profile manifest does not pin the allowlist SHA")
        if allowlist.get("runtime_profile_id") != runtime_profile["runtime_profile_id"]:
            raise ValueError("allowlist manifest does not match runtime profile")
        lengths = allowlist.get("compiled_lengths")
        if not isinstance(lengths, list) or not all(
            isinstance(length, int) and not isinstance(length, bool) and length > 0
            for length in lengths
        ):
            raise ValueError("allowlist manifest has invalid compiled_lengths")
        values = {
            key: runtime_profile[key]
            for key in required - {"compiled_allowlist_manifest_sha256"}
        }
        if not all(isinstance(value, str) and value for value in values.values()):
            raise ValueError("runtime profile manifest has invalid identity fields")
        return cls(
            runtime_profile_id=str(runtime_profile["runtime_profile_id"]),
            bridge_commit=str(runtime_profile["bridge_commit"]),
            faster_wheel_sha256=str(runtime_profile["faster_wheel_sha256"]),
            compiled_allowlist_manifest_sha256=allowlist_sha256,
            compiled_lengths=tuple(sorted(lengths)),
        )


@dataclass(frozen=True, slots=True)
class MockEngineConfig:
    """Configuration for the deterministic mock engine."""

    chunk_count: int = 3
    chunk_duration_ms: int = 100
    chunk_delay_seconds: float = 0.0
    kind: Literal["mock"] = field(default="mock", init=False)

    def __post_init__(self) -> None:
        """Validate mock-engine settings when the DTO is created."""

        if self.chunk_count <= 0:
            raise ValueError("mock.chunk_count must be greater than zero")
        if self.chunk_duration_ms < 20:
            raise ValueError("mock.chunk_duration_ms must be at least 20")
        if (
            not math.isfinite(self.chunk_delay_seconds)
            or self.chunk_delay_seconds < 0.0
        ):
            raise ValueError("mock.chunk_delay_seconds must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class QwenEngineConfig:
    """Configuration for the Qwen3-TTS engine adapter."""

    model_path: str
    runtime_backend: Literal["upstream", "faster"] = "upstream"
    device: str = "cuda"
    dtype: str = "auto"
    attn_implementation: str = ""
    max_seq_len: int = 2048
    max_audio_seconds_per_utterance: float | None = None
    emit_every_frames: int = 8
    emit_chunk_schedule: tuple[int, ...] = ()
    compiled_emit_chunk_schedule: tuple[int, ...] = ()
    eager_emit_chunk_schedule: tuple[int, ...] = ()
    decode_window_frames: int = 80
    overlap_samples: int = 0
    enable_streaming_optimizations: bool = False
    use_compile: bool = True
    use_cuda_graphs: bool = True
    compile_mode: str = "reduce-overhead"
    use_fast_codebook: bool = False
    compile_codebook_predictor: bool = True
    compile_talker: bool = True
    matmul_precision: str = ""
    profile_prefill: bool = False
    profile_nvtx: bool = False
    collect_generation_trace: bool = False
    prefill_backend: Literal[
        "eager",
        "compile_backend_eager",
        "compile_backend_aot_eager",
        "compile_default",
        "compile_inductor_default",
        "compile_reduce_overhead",
    ] = "eager"
    prefill_compile_compat_mode: Literal["none", "strict_bf16_sdpa_v1"] = "none"
    prefill_compile_lengths: tuple[int, ...] = ()
    prefill_compile_on_miss: bool = True
    prefill_unknown_shape_policy: Literal["eager", "error"] = "eager"
    prefill_compile_policy: Literal["diagnostic_dynamic", "exact_allowlist"] = (
        "diagnostic_dynamic"
    )
    prefill_allowlist_warmup_manifest: str = ""
    prefill_allowlist_warmup_repeats: int = 3
    prefill_allowlist_max_entries: int = 6
    prefill_allowlist_max_abs_threshold: float = 0.0
    prefill_require_precompiled: bool = False
    prefill_first_chunk_warmup_enabled: bool = False
    prefill_first_chunk_warmup_length: int | None = None
    prefill_generation_prime_enabled: bool = False
    allow_request_sampling_overrides: bool = False
    do_sample: bool = True
    temperature: float = 0.9
    top_k: int = 50
    top_p: float = 1.0
    repetition_penalty: float = 1.05
    seed: int | None = None
    seed_mode: Literal["request_id", "fixed"] = "request_id"
    warmup_seed: int | None = None
    warmup_synthesis_enabled: bool = False
    warmup_synthesis_passes: int = 1
    warmup_unbounded_passes: int = 0
    warmup_max_output_chunks: int | None = None
    warmup_text: str = "Warmup."
    warmup_language: str = "auto"
    warmup_speaker: str = ""
    warmup_instruction: str = ""
    kind: Literal["qwen"] = field(default="qwen", init=False)

    def __post_init__(self) -> None:
        """Validate Qwen engine adapter settings."""

        if not self.model_path:
            raise ValueError("qwen.model_path must not be empty")
        if self.runtime_backend not in {"upstream", "faster"}:
            raise ValueError("qwen.runtime_backend must be upstream or faster")
        if self.collect_generation_trace and self.runtime_backend != "faster":
            raise ValueError(
                "qwen.collect_generation_trace requires runtime_backend=faster"
            )
        if not self.device:
            raise ValueError("qwen.device must not be empty")
        if not self.dtype:
            raise ValueError("qwen.dtype must not be empty")
        if self.emit_every_frames <= 0:
            raise ValueError("qwen.emit_every_frames must be greater than zero")
        schedules = {
            "emit_chunk_schedule": self.emit_chunk_schedule,
            "compiled_emit_chunk_schedule": self.compiled_emit_chunk_schedule,
            "eager_emit_chunk_schedule": self.eager_emit_chunk_schedule,
        }
        if any(frames <= 0 for schedule in schedules.values() for frames in schedule):
            raise ValueError("qwen chunk schedule values must be positive")
        if any(
            frames > MAX_EMIT_CHUNK_SCHEDULE_FRAMES
            for schedule in schedules.values()
            for frames in schedule
        ):
            raise ValueError(
                "qwen.emit_chunk_schedule values must not exceed "
                f"{MAX_EMIT_CHUNK_SCHEDULE_FRAMES}"
            )
        if any(schedules.values()) and self.runtime_backend != "faster":
            raise ValueError("qwen chunk schedules require runtime_backend=faster")
        if self.decode_window_frames <= 0:
            raise ValueError("qwen.decode_window_frames must be greater than zero")
        if self.max_seq_len <= 0:
            raise ValueError("qwen.max_seq_len must be greater than zero")
        if self.max_audio_seconds_per_utterance is not None and (
            not math.isfinite(self.max_audio_seconds_per_utterance)
            or self.max_audio_seconds_per_utterance <= 0.0
        ):
            raise ValueError(
                "qwen.max_audio_seconds_per_utterance must be finite and positive"
            )
        if self.overlap_samples < 0:
            raise ValueError("qwen.overlap_samples must be non-negative")
        if not self.compile_mode:
            raise ValueError("qwen.compile_mode must not be empty")
        if self.matmul_precision not in {"", "highest", "high", "medium"}:
            raise ValueError("qwen.matmul_precision must be highest, high, or medium")
        if self.prefill_backend not in {
            "eager",
            "compile_backend_eager",
            "compile_backend_aot_eager",
            "compile_default",
            "compile_inductor_default",
            "compile_reduce_overhead",
        }:
            raise ValueError(
                "qwen.prefill_backend must be eager, a supported diagnostic "
                "compile backend, or compile_reduce_overhead"
            )
        if self.prefill_compile_compat_mode not in {
            "none",
            "strict_bf16_sdpa_v1",
        }:
            raise ValueError(
                "qwen.prefill_compile_compat_mode must be none or "
                "strict_bf16_sdpa_v1"
            )
        if self.prefill_unknown_shape_policy not in {"eager", "error"}:
            raise ValueError(
                "qwen.prefill_unknown_shape_policy must be eager or error"
            )
        if self.prefill_compile_policy not in {
            "diagnostic_dynamic",
            "exact_allowlist",
        }:
            raise ValueError(
                "qwen.prefill_compile_policy must be diagnostic_dynamic or "
                "exact_allowlist"
            )
        if any(length <= 0 for length in self.prefill_compile_lengths):
            raise ValueError("qwen.prefill_compile_lengths must be positive")
        if len(set(self.prefill_compile_lengths)) != len(
            self.prefill_compile_lengths
        ):
            raise ValueError("qwen.prefill_compile_lengths must be unique")
        if self.prefill_allowlist_warmup_repeats < 3:
            raise ValueError(
                "qwen.prefill_allowlist_warmup_repeats must be at least 3"
            )
        if self.prefill_allowlist_max_entries <= 0:
            raise ValueError("qwen.prefill_allowlist_max_entries must be positive")
        if (
            not math.isfinite(self.prefill_allowlist_max_abs_threshold)
            or self.prefill_allowlist_max_abs_threshold < 0.0
        ):
            raise ValueError(
                "qwen.prefill_allowlist_max_abs_threshold must be finite and "
                "non-negative"
            )
        self._validate_exact_allowlist_contract()
        self._validate_route_aware_schedule_contract()
        if (
            self.prefill_first_chunk_warmup_enabled
            and self.prefill_compile_policy != "exact_allowlist"
        ):
            raise ValueError(
                "qwen.prefill_first_chunk_warmup_enabled requires "
                "prefill_compile_policy=exact_allowlist"
            )
        if self.prefill_first_chunk_warmup_enabled:
            if self.prefill_first_chunk_warmup_length is None:
                raise ValueError(
                    "qwen.prefill_first_chunk_warmup_length is required when "
                    "prefill_first_chunk_warmup_enabled=true"
                )
            if (
                self.prefill_first_chunk_warmup_length
                not in self.prefill_compile_lengths
            ):
                raise ValueError(
                    "qwen.prefill_first_chunk_warmup_length must be in "
                    "prefill_compile_lengths"
                )
        elif self.prefill_first_chunk_warmup_length is not None:
            raise ValueError(
                "qwen.prefill_first_chunk_warmup_length requires "
                "prefill_first_chunk_warmup_enabled=true"
            )
        if (
            self.prefill_generation_prime_enabled
            and not self.prefill_first_chunk_warmup_enabled
        ):
            raise ValueError(
                "qwen.prefill_generation_prime_enabled requires "
                "prefill_first_chunk_warmup_enabled=true"
            )
        if self.prefill_generation_prime_enabled and not self.collect_generation_trace:
            raise ValueError(
                "qwen.prefill_generation_prime_enabled requires "
                "collect_generation_trace=true"
            )
        if (
            self.prefill_generation_prime_enabled
            and self.max_audio_seconds_per_utterance is None
        ):
            raise ValueError(
                "qwen.prefill_generation_prime_enabled requires a finite "
                "max_audio_seconds_per_utterance safety limit"
            )
        if (
            self.prefill_first_chunk_warmup_enabled
            and self.warmup_synthesis_enabled
        ):
            raise ValueError(
                "qwen.prefill_first_chunk_warmup_enabled and "
                "warmup_synthesis_enabled cannot both be true"
            )
        self._validate_prefill_compile_compat_contract()
        _validate_sampling_values(
            temperature=self.temperature,
            top_k=self.top_k,
            top_p=self.top_p,
            repetition_penalty=self.repetition_penalty,
        )
        if self.seed_mode not in {"request_id", "fixed"}:
            raise ValueError("qwen.seed_mode must be request_id or fixed")
        if self.warmup_synthesis_enabled and not self.warmup_text:
            raise ValueError("qwen.warmup_text must not be empty")
        if self.warmup_synthesis_passes <= 0:
            raise ValueError("qwen.warmup_synthesis_passes must be greater than zero")
        if (
            self.warmup_max_output_chunks is not None
            and self.warmup_max_output_chunks <= 0
        ):
            raise ValueError("qwen.warmup_max_output_chunks must be greater than zero")
        if self.warmup_unbounded_passes < 0:
            raise ValueError("qwen.warmup_unbounded_passes must be non-negative")
        if not self.warmup_language:
            raise ValueError("qwen.warmup_language must not be empty")

    def _validate_prefill_compile_compat_contract(self) -> None:
        if self.prefill_compile_compat_mode == "none":
            return
        if self.runtime_backend != "faster":
            raise ValueError(
                "qwen.prefill_compile_compat_mode requires runtime_backend=faster"
            )
        if self.dtype not in {"bfloat16", "bf16"}:
            raise ValueError(
                "qwen.prefill_compile_compat_mode=strict_bf16_sdpa_v1 "
                "requires dtype=bfloat16"
            )
        if self.attn_implementation != "sdpa":
            raise ValueError(
                "qwen.prefill_compile_compat_mode=strict_bf16_sdpa_v1 "
                "requires attn_implementation=sdpa"
            )
        if self.prefill_backend not in {
            "compile_inductor_default",
            "compile_reduce_overhead",
        }:
            raise ValueError(
                "qwen.prefill_compile_compat_mode=strict_bf16_sdpa_v1 "
                "requires prefill_backend=compile_inductor_default or "
                "compile_reduce_overhead"
            )
        if (
            not self.warmup_synthesis_enabled
            and self.prefill_compile_policy != "exact_allowlist"
        ):
            raise ValueError(
                "qwen.prefill_compile_compat_mode=strict_bf16_sdpa_v1 "
                "requires warmup_synthesis_enabled=true or "
                "prefill_compile_policy=exact_allowlist"
            )

    def _validate_exact_allowlist_contract(self) -> None:
        if self.prefill_compile_policy != "exact_allowlist":
            return
        if self.runtime_backend != "faster":
            raise ValueError(
                "qwen.prefill_compile_policy=exact_allowlist requires "
                "runtime_backend=faster"
            )
        if self.prefill_compile_compat_mode != "strict_bf16_sdpa_v1":
            raise ValueError(
                "qwen.prefill_compile_policy=exact_allowlist requires "
                "prefill_compile_compat_mode=strict_bf16_sdpa_v1"
            )
        if self.prefill_backend not in {
            "compile_inductor_default",
            "compile_reduce_overhead",
        }:
            raise ValueError(
                "qwen.prefill_compile_policy=exact_allowlist requires "
                "prefill_backend=compile_inductor_default or compile_reduce_overhead"
            )
        if not self.prefill_compile_lengths:
            raise ValueError(
                "qwen.prefill_compile_policy=exact_allowlist requires "
                "prefill_compile_lengths"
            )
        if len(self.prefill_compile_lengths) > self.prefill_allowlist_max_entries:
            raise ValueError(
                "qwen.prefill_compile_lengths exceeds "
                "qwen.prefill_allowlist_max_entries"
            )
        if self.prefill_compile_on_miss:
            raise ValueError(
                "qwen.prefill_compile_policy=exact_allowlist requires "
                "prefill_compile_on_miss=false"
            )
        if self.prefill_unknown_shape_policy != "eager":
            raise ValueError(
                "qwen.prefill_compile_policy=exact_allowlist requires "
                "prefill_unknown_shape_policy=eager"
            )
        if not self.prefill_allowlist_warmup_manifest:
            raise ValueError(
                "qwen.prefill_compile_policy=exact_allowlist requires "
                "prefill_allowlist_warmup_manifest"
            )
        if not self.prefill_require_precompiled:
            raise ValueError(
                "qwen.prefill_compile_policy=exact_allowlist requires "
                "prefill_require_precompiled=true"
            )
        if self.prefill_allowlist_max_abs_threshold != 0.0:
            raise ValueError(
                "qwen.prefill_compile_policy=exact_allowlist with "
                "strict_bf16_sdpa_v1 requires "
                "prefill_allowlist_max_abs_threshold=0.0"
            )

    def _validate_route_aware_schedule_contract(self) -> None:
        route_aware_enabled = bool(
            self.compiled_emit_chunk_schedule or self.eager_emit_chunk_schedule
        )
        if not route_aware_enabled:
            return
        if self.emit_chunk_schedule:
            raise ValueError(
                "qwen.emit_chunk_schedule cannot be combined with route-aware "
                "chunk schedules"
            )
        if self.prefill_compile_policy != "exact_allowlist":
            raise ValueError(
                "route-aware chunk schedules require "
                "prefill_compile_policy=exact_allowlist"
            )
        if self.prefill_unknown_shape_policy != "eager":
            raise ValueError(
                "route-aware chunk schedules require "
                "prefill_unknown_shape_policy=eager"
            )
        if self.prefill_compile_on_miss:
            raise ValueError(
                "route-aware chunk schedules require "
                "prefill_compile_on_miss=false"
            )
        if not self.prefill_require_precompiled:
            raise ValueError(
                "route-aware chunk schedules require "
                "prefill_require_precompiled=true"
            )


EngineConfig: TypeAlias = MockEngineConfig | QwenEngineConfig


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Top-level worker runtime configuration."""

    worker_version: str = "0.2.0"
    output_queue_size: int = 128
    engine_startup_mode: Literal["main", "engine_warmup", "engine_load_warmup"] = (
        "main"
    )
    engine: EngineConfig = field(default_factory=MockEngineConfig)
    canary_runtime_provenance: CanaryRuntimeProvenance | None = None

    def __post_init__(self) -> None:
        """Validate worker-level settings when the DTO is created."""

        if not self.worker_version:
            raise ValueError("worker_version must not be empty")
        if self.output_queue_size <= 0:
            raise ValueError("output_queue_size must be greater than zero")
        if self.engine_startup_mode not in {
            "main",
            "engine_warmup",
            "engine_load_warmup",
        }:
            raise ValueError("engine_startup_mode must be a supported value")
        if not isinstance(self.engine, (MockEngineConfig, QwenEngineConfig)):
            raise TypeError("engine must be a known engine configuration")
        if self.canary_runtime_provenance is not None and not isinstance(
            self.canary_runtime_provenance, CanaryRuntimeProvenance
        ):
            raise TypeError("canary_runtime_provenance must be valid when provided")
