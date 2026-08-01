"""Worker engine DTOs."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class EngineCapabilities:
    """Feature flags supported by an engine."""

    streaming: bool
    cancellation: bool
    instructions: bool
    voice_clone: bool


@dataclass(frozen=True, slots=True)
class AudioFormat:
    """PCM audio format used for worker output."""

    sample_format: str = "s16le"
    sample_rate: int = 24000
    channels: int = 1

    @staticmethod
    def default() -> "AudioFormat":
        """Return the protocol v1 default audio format."""

        return AudioFormat()

    def to_payload(self) -> dict[str, Any]:
        """Convert the format to protocol JSON fields."""

        return {
            "sample_format": self.sample_format,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
        }

    @staticmethod
    def from_payload(payload: Mapping[str, Any] | None) -> "AudioFormat":
        """Parse an optional protocol output-format object."""

        if payload is None:
            return AudioFormat.default()
        return AudioFormat(
            sample_format=str(payload.get("sample_format", "s16le")),
            sample_rate=int(payload.get("sample_rate", 24000)),
            channels=int(payload.get("channels", 1)),
        )


class EngineRequestValidationError(ValueError):
    """Raised when an engine rejects a client synthesis request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class UnsupportedAudioFormatError(EngineRequestValidationError):
    """Raised when an engine cannot produce a requested audio format."""

    def __init__(self, message: str) -> None:
        super().__init__("unsupported_audio_format", message)


@dataclass(frozen=True, slots=True)
class SamplingOptions:
    """Optional per-request decoding controls."""

    temperature: float | None = None
    top_k: int | None = None
    top_p: float | None = None
    repetition_penalty: float | None = None
    do_sample: bool | None = None

    def __post_init__(self) -> None:
        """Validate values that are present on this individual request."""

        if self.temperature is not None and (
            not math.isfinite(self.temperature)
            or not 0.0 < self.temperature <= 2.0
        ):
            raise ValueError("sampling.temperature must be finite and in the interval (0, 2]")
        if self.top_k is not None and self.top_k <= 0:
            raise ValueError("sampling.top_k must be greater than zero")
        if self.top_p is not None and (
            not math.isfinite(self.top_p) or not 0.0 < self.top_p <= 1.0
        ):
            raise ValueError("sampling.top_p must be finite and in the interval (0, 1]")
        if self.repetition_penalty is not None and (
            not math.isfinite(self.repetition_penalty)
            or not 1.0 <= self.repetition_penalty <= 2.0
        ):
            raise ValueError(
                "sampling.repetition_penalty must be finite and in the interval [1, 2]"
            )

    def is_default(self) -> bool:
        """Return whether no request-level setting overrides the runtime profile."""

        return (
            self.temperature is None
            and self.top_k is None
            and self.top_p is None
            and self.repetition_penalty is None
            and self.do_sample is None
        )


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    """Normalized synthesis request passed from server to engine."""

    request_id: int
    text: str
    language: str = "auto"
    speaker: str = ""
    instruction: str = ""
    seed: int | None = None
    sampling: SamplingOptions = field(default_factory=SamplingOptions)
    output: AudioFormat = field(default_factory=AudioFormat.default)
