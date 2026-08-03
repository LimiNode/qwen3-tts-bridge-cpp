"""Local Base-model voice profiles and reference-audio preflight checks."""

from __future__ import annotations

import hashlib
import json
import math
import wave
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

_VOICE_PROFILE_SCHEMA_VERSION = 1
_MAX_REFERENCE_AUDIO_BYTES = 16 * 1024 * 1024
_MIN_REFERENCE_SECONDS = 2.0
_MAX_REFERENCE_SECONDS = 20.0
_MIN_SAMPLE_RATE = 8_000
_MAX_SAMPLE_RATE = 96_000
_MAX_REFERENCE_TEXT_CHARACTERS = 1_024
_MAX_CLIPPED_SAMPLE_FRACTION = 0.05
_MIN_RMS_RATIO = 0.003
_ICL_TRAILING_SILENCE_SECONDS = 0.5

VoicePromptPolicy = Literal[
    "shared", "clone_per_request", "rebuild_per_request", "direct_reference"
]


class VoiceProfileError(ValueError):
    """Raised when a local voice profile or reference recording is invalid."""


@dataclass(frozen=True, slots=True)
class ReferenceAudioInfo:
    """Validated metadata for a PCM WAV reference recording."""

    path: Path
    sha256: str
    duration_seconds: float
    sample_rate: int
    channels: int
    sample_width_bytes: int
    rms_ratio: float
    clipped_sample_fraction: float


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """Durable metadata for one locally registered Base voice."""

    voice_id: str
    reference_audio_path: Path
    reference_text: str
    preserve_reference_text_whitespace: bool
    x_vector_only: bool
    reference_audio: ReferenceAudioInfo


@dataclass(slots=True)
class _PreparedVoiceProfile:
    """In-memory prompt kept by the persistent worker only."""

    profile: VoiceProfile
    prompt: Any


def preflight_reference_audio(
    reference_audio_path: str | Path,
    reference_text: str,
    x_vector_only: bool,
) -> ReferenceAudioInfo:
    """Validate a short PCM WAV reference before model-side prompt creation."""

    path = Path(reference_audio_path).expanduser()
    if not path.is_file():
        raise VoiceProfileError("reference audio must identify an existing local file")
    if path.suffix.lower() != ".wav":
        raise VoiceProfileError("reference audio must be a .wav file")

    size = path.stat().st_size
    if size <= 44 or size > _MAX_REFERENCE_AUDIO_BYTES:
        raise VoiceProfileError(
            "reference audio size must be between 45 bytes and "
            f"{_MAX_REFERENCE_AUDIO_BYTES} bytes"
        )
    _validate_reference_text(reference_text, x_vector_only)

    try:
        with wave.open(str(path), "rb") as reader:
            channels = reader.getnchannels()
            sample_width_bytes = reader.getsampwidth()
            sample_rate = reader.getframerate()
            frame_count = reader.getnframes()
            compression = reader.getcomptype()
            if compression != "NONE":
                raise VoiceProfileError("reference audio must be uncompressed PCM WAV")
            _validate_wav_format(channels, sample_width_bytes, sample_rate, frame_count)
            rms_ratio, clipped_sample_fraction = _scan_pcm_levels(
                reader,
                sample_width_bytes,
            )
    except wave.Error as exc:
        raise VoiceProfileError("reference audio is not a decodable PCM WAV") from exc

    duration_seconds = frame_count / sample_rate
    if not _MIN_REFERENCE_SECONDS <= duration_seconds <= _MAX_REFERENCE_SECONDS:
        raise VoiceProfileError(
            "reference audio duration must be between "
            f"{_MIN_REFERENCE_SECONDS:g} and {_MAX_REFERENCE_SECONDS:g} seconds"
        )
    if rms_ratio < _MIN_RMS_RATIO:
        raise VoiceProfileError("reference audio is effectively silent")
    if clipped_sample_fraction > _MAX_CLIPPED_SAMPLE_FRACTION:
        raise VoiceProfileError("reference audio contains excessive clipping")

    return ReferenceAudioInfo(
        path=path.resolve(),
        sha256=_sha256_file(path),
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width_bytes,
        rms_ratio=rms_ratio,
        clipped_sample_fraction=clipped_sample_fraction,
    )


class VoiceProfileRegistry:
    """Immutable profile definitions plus an LRU cache of model-ready prompts."""

    def __init__(
        self, profiles: dict[str, VoiceProfile], max_cached_prompts: int
    ) -> None:
        if max_cached_prompts <= 0:
            raise VoiceProfileError(
                "voice prompt cache limit must be greater than zero"
            )
        self._profiles = profiles
        self._max_cached_prompts = max_cached_prompts
        self._prepared: OrderedDict[str, _PreparedVoiceProfile] = OrderedDict()

    @classmethod
    def from_json_file(
        cls,
        registry_path: str | Path,
        max_cached_prompts: int,
    ) -> "VoiceProfileRegistry":
        """Load and validate a local voice-profile manifest."""

        path = Path(registry_path).expanduser()
        if not path.is_file():
            raise VoiceProfileError(
                "voice profile registry must identify an existing file"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VoiceProfileError(
                "voice profile registry must be valid UTF-8 JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise VoiceProfileError("voice profile registry root must be an object")
        if payload.get("schema_version") != _VOICE_PROFILE_SCHEMA_VERSION:
            raise VoiceProfileError(
                "voice profile registry schema_version must be "
                f"{_VOICE_PROFILE_SCHEMA_VERSION}"
            )
        rows = payload.get("voices")
        if not isinstance(rows, list):
            raise VoiceProfileError("voice profile registry voices must be an array")

        profiles: dict[str, VoiceProfile] = {}
        for row in rows:
            profile = _parse_voice_profile(path.parent, row)
            if profile.voice_id in profiles:
                raise VoiceProfileError(
                    f"voice profile registry has duplicate voice_id: {profile.voice_id}"
                )
            profiles[profile.voice_id] = profile
        return cls(profiles, max_cached_prompts)

    @property
    def voice_ids(self) -> tuple[str, ...]:
        """Return stable registered voice IDs."""

        return tuple(self._profiles)

    def has_voice(self, voice_id: str) -> bool:
        """Return whether a profile is registered under the supplied ID."""

        return voice_id in self._profiles

    def profile_for(self, voice_id: str) -> VoiceProfile:
        """Return the immutable metadata for one registered voice."""

        profile = self._profiles.get(voice_id)
        if profile is None:
            raise VoiceProfileError(f"unknown voice profile: {voice_id}")
        return profile

    def prompt_for(
        self,
        model: Any,
        voice_id: str,
        *,
        policy: VoicePromptPolicy = "shared",
    ) -> Any:
        """Return a prepared prompt according to an explicit diagnostic policy."""

        if policy == "direct_reference":
            raise VoiceProfileError(
                "direct_reference does not prepare a reusable voice prompt"
            )
        profile = self.profile_for(voice_id)
        if policy == "rebuild_per_request":
            return self._build_prompt(model, profile)

        prepared = self._prepared.get(voice_id)
        if prepared is not None:
            self._prepared.move_to_end(voice_id)
            return (
                _clone_prompt(prepared.prompt)
                if policy == "clone_per_request"
                else prepared.prompt
            )

        prompt = self._build_prompt(model, profile)
        self._prepared[voice_id] = _PreparedVoiceProfile(profile=profile, prompt=prompt)
        self._prepared.move_to_end(voice_id)
        while len(self._prepared) > self._max_cached_prompts:
            self._prepared.popitem(last=False)
        return _clone_prompt(prompt) if policy == "clone_per_request" else prompt

    def _build_prompt(self, model: Any, profile: VoiceProfile) -> Any:
        """Create one model-owned prompt after revalidating its source WAV."""

        # Re-check the source hash only when creating a new GPU prompt.
        audio = preflight_reference_audio(
            profile.reference_audio_path,
            profile.reference_text,
            profile.x_vector_only,
        )
        if audio.sha256 != profile.reference_audio.sha256:
            raise VoiceProfileError(
                "reference audio changed after registry load for voice_id: "
                f"{profile.voice_id}"
            )
        create_prompt = _voice_clone_prompt_builder(model)
        if not callable(create_prompt):
            raise VoiceProfileError(
                "loaded Base model cannot create voice clone prompts"
            )
        prompt = create_prompt(
            ref_audio=_prompt_reference_audio(profile),
            ref_text=profile.reference_text or None,
            x_vector_only_mode=profile.x_vector_only,
        )
        return prompt


def _clone_prompt(prompt: Any) -> Any:
    """Deep-copy a model prompt for the clone-per-request diagnostic policy."""

    try:
        return deepcopy(prompt)
    except Exception as exc:
        raise VoiceProfileError(
            "voice prompt cannot be copied for clone_per_request diagnostics"
        ) from exc


def _voice_clone_prompt_builder(model: Any) -> Any:
    """Find the public builder or FasterQwen's wrapped upstream builder."""

    create_prompt = getattr(model, "create_voice_clone_prompt", None)
    if callable(create_prompt):
        return create_prompt
    return getattr(getattr(model, "model", None), "create_voice_clone_prompt", None)


def _prompt_reference_audio(profile: VoiceProfile) -> str | tuple[Any, int]:
    """Prepare reference audio with the silence expected by ICL generation."""

    if profile.x_vector_only:
        return str(profile.reference_audio_path)

    # FasterQwen's direct ICL path appends this pause to prevent the last
    # reference phoneme from being continued into the first generated word.
    try:
        import numpy as np
    except ModuleNotFoundError as exc:
        raise VoiceProfileError(
            "ICL voice profiles require NumPy in the model runtime"
        ) from exc

    with wave.open(str(profile.reference_audio_path), "rb") as reader:
        raw_frames = reader.readframes(reader.getnframes())
    samples = _pcm_bytes_to_float32(
        raw_frames,
        profile.reference_audio.sample_width_bytes,
        np,
    )
    if profile.reference_audio.channels > 1:
        samples = samples.reshape(-1, profile.reference_audio.channels).mean(axis=1)
    silence = np.zeros(
        round(profile.reference_audio.sample_rate * _ICL_TRAILING_SILENCE_SECONDS),
        dtype=np.float32,
    )
    return np.concatenate((samples, silence)), profile.reference_audio.sample_rate


def _pcm_bytes_to_float32(
    data: bytes,
    sample_width_bytes: int,
    np: Any,
) -> Any:
    """Decode validated little-endian PCM data into normalized mono-ready samples."""

    if sample_width_bytes == 1:
        return (np.frombuffer(data, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    if sample_width_bytes == 2:
        return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    if sample_width_bytes == 4:
        return np.frombuffer(data, dtype="<i4").astype(np.float32) / 2147483648.0
    if sample_width_bytes == 3:
        triples = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3)
        values = (
            triples[:, 0].astype(np.int32)
            | (triples[:, 1].astype(np.int32) << 8)
            | (triples[:, 2].astype(np.int32) << 16)
        )
        values[values & 0x800000 != 0] -= 1 << 24
        return values.astype(np.float32) / 8388608.0
    raise VoiceProfileError("reference audio uses an unsupported PCM width")


def _parse_voice_profile(registry_directory: Path, row: object) -> VoiceProfile:
    if not isinstance(row, dict):
        raise VoiceProfileError("each voice profile must be an object")
    voice_id = row.get("voice_id")
    reference_audio_path = row.get("reference_audio_path")
    reference_text = row.get("reference_text", "")
    preserve_reference_text_whitespace = row.get(
        "preserve_reference_text_whitespace",
        False,
    )
    x_vector_only = row.get("x_vector_only", False)
    if not isinstance(voice_id, str) or not voice_id.strip():
        raise VoiceProfileError("voice profile voice_id must be a non-empty string")
    if not isinstance(reference_audio_path, str) or not reference_audio_path.strip():
        raise VoiceProfileError(
            f"voice profile {voice_id} reference_audio_path must be a non-empty string"
        )
    if (
        not isinstance(reference_text, str)
        or not isinstance(preserve_reference_text_whitespace, bool)
        or not isinstance(x_vector_only, bool)
    ):
        raise VoiceProfileError(
            f"voice profile {voice_id} has invalid reference_text, "
            "preserve_reference_text_whitespace, or x_vector_only"
        )
    audio_path = Path(reference_audio_path).expanduser()
    if not audio_path.is_absolute():
        audio_path = registry_directory / audio_path
    audio = preflight_reference_audio(audio_path, reference_text, x_vector_only)
    return VoiceProfile(
        voice_id=voice_id.strip(),
        reference_audio_path=audio.path,
        reference_text=(
            reference_text
            if preserve_reference_text_whitespace
            else reference_text.strip()
        ),
        preserve_reference_text_whitespace=preserve_reference_text_whitespace,
        x_vector_only=x_vector_only,
        reference_audio=audio,
    )


def _validate_reference_text(reference_text: str, x_vector_only: bool) -> None:
    if not isinstance(reference_text, str):
        raise VoiceProfileError("reference text must be a string")
    text = reference_text.strip()
    if not x_vector_only and not text:
        raise VoiceProfileError(
            "reference text is required unless x_vector_only is true"
        )
    if len(text) > _MAX_REFERENCE_TEXT_CHARACTERS:
        raise VoiceProfileError(
            "reference text must not exceed "
            f"{_MAX_REFERENCE_TEXT_CHARACTERS} characters"
        )


def _validate_wav_format(
    channels: int,
    sample_width_bytes: int,
    sample_rate: int,
    frame_count: int,
) -> None:
    if channels not in {1, 2}:
        raise VoiceProfileError("reference audio must be mono or stereo")
    if sample_width_bytes not in {1, 2, 3, 4}:
        raise VoiceProfileError("reference audio must use 8-, 16-, 24-, or 32-bit PCM")
    if not _MIN_SAMPLE_RATE <= sample_rate <= _MAX_SAMPLE_RATE:
        raise VoiceProfileError(
            "reference audio sample rate must be between "
            f"{_MIN_SAMPLE_RATE} and {_MAX_SAMPLE_RATE} Hz"
        )
    if frame_count <= 0:
        raise VoiceProfileError("reference audio must contain at least one frame")


def _scan_pcm_levels(
    reader: wave.Wave_read, sample_width_bytes: int
) -> tuple[float, float]:
    maximum = float((1 << (sample_width_bytes * 8 - 1)) - 1)
    clipped_threshold = maximum * 0.999
    sum_squares = 0.0
    sample_count = 0
    clipped_count = 0
    while True:
        frames = reader.readframes(16_384)
        if not frames:
            break
        for sample in _iter_pcm_samples(frames, sample_width_bytes):
            normalized = sample / maximum
            sum_squares += normalized * normalized
            sample_count += 1
            if abs(sample) >= clipped_threshold:
                clipped_count += 1
    if sample_count == 0:
        raise VoiceProfileError("reference audio contains no PCM samples")
    return (
        math.sqrt(sum_squares / sample_count),
        clipped_count / sample_count,
    )


def _iter_pcm_samples(data: bytes, sample_width_bytes: int):
    if sample_width_bytes == 1:
        for value in data:
            yield value - 128
        return
    for offset in range(0, len(data), sample_width_bytes):
        sample = data[offset : offset + sample_width_bytes]
        if len(sample) != sample_width_bytes:
            raise VoiceProfileError("reference audio has an incomplete PCM sample")
        if sample_width_bytes == 3:
            sign_extension = b"\xff" if sample[2] & 0x80 else b"\x00"
            yield int.from_bytes(sample + sign_extension, "little", signed=True)
        else:
            yield int.from_bytes(sample, "little", signed=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
