"""Runtime configuration DTOs for the Python worker."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, TypeAlias


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
    emit_every_frames: int = 8
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
    seed: int | None = None
    warmup_synthesis_enabled: bool = False
    warmup_synthesis_passes: int = 1
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
        if not self.device:
            raise ValueError("qwen.device must not be empty")
        if not self.dtype:
            raise ValueError("qwen.dtype must not be empty")
        if self.emit_every_frames <= 0:
            raise ValueError("qwen.emit_every_frames must be greater than zero")
        if self.decode_window_frames <= 0:
            raise ValueError("qwen.decode_window_frames must be greater than zero")
        if self.max_seq_len <= 0:
            raise ValueError("qwen.max_seq_len must be greater than zero")
        if self.overlap_samples < 0:
            raise ValueError("qwen.overlap_samples must be non-negative")
        if not self.compile_mode:
            raise ValueError("qwen.compile_mode must not be empty")
        if self.matmul_precision not in {"", "highest", "high", "medium"}:
            raise ValueError("qwen.matmul_precision must be highest, high, or medium")
        if self.warmup_synthesis_enabled and not self.warmup_text:
            raise ValueError("qwen.warmup_text must not be empty")
        if self.warmup_synthesis_passes <= 0:
            raise ValueError("qwen.warmup_synthesis_passes must be greater than zero")
        if (
            self.warmup_max_output_chunks is not None
            and self.warmup_max_output_chunks <= 0
        ):
            raise ValueError("qwen.warmup_max_output_chunks must be greater than zero")
        if not self.warmup_language:
            raise ValueError("qwen.warmup_language must not be empty")


EngineConfig: TypeAlias = MockEngineConfig | QwenEngineConfig


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Top-level worker runtime configuration."""

    worker_version: str = "0.2.0"
    output_queue_size: int = 128
    engine: EngineConfig = field(default_factory=MockEngineConfig)

    def __post_init__(self) -> None:
        """Validate worker-level settings when the DTO is created."""

        if not self.worker_version:
            raise ValueError("worker_version must not be empty")
        if self.output_queue_size <= 0:
            raise ValueError("output_queue_size must be greater than zero")
        if not isinstance(self.engine, (MockEngineConfig, QwenEngineConfig)):
            raise TypeError("engine must be a known engine configuration")
