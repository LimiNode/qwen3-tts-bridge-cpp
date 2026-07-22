"""Pure accounting helpers for faster-qwen benchmark scripts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class PlaybackChunk:
    arrival_ms: float
    audio_ms: float


@dataclass(frozen=True, slots=True)
class PlaybackSimulation:
    minimum_buffer_ms: float
    minimum_reserve_margin_ms: float
    underrun_count: int
    reserve_violation_count: int
    second_arrival_margin_ms: float | None
    second_arrival_reserve_margin_ms: float | None


def validate_reported_steps(*, reported_steps: int, actual_steps: int) -> None:
    if reported_steps != actual_steps:
        raise ValueError(
            f"producer chunk step mismatch: reported={reported_steps}, actual={actual_steps}"
        )


def validate_pending_steps(*, pending_steps: int, combined_steps: int) -> None:
    if pending_steps != combined_steps:
        raise ValueError(
            f"pending chunk step mismatch: pending={pending_steps}, combined={combined_steps}"
        )


def validate_emitted_steps(*, generated_steps: int, emitted_steps: int) -> None:
    if generated_steps != emitted_steps:
        raise ValueError(
            f"adaptive chunk accounting mismatch: generated={generated_steps}, "
            f"emitted={emitted_steps}"
        )


def simulate_playback(
    chunks: Iterable[PlaybackChunk],
    *,
    transport_reserve_ms: float = 50.0,
) -> PlaybackSimulation:
    sorted_chunks = sorted(chunks, key=lambda chunk: chunk.arrival_ms)
    if not sorted_chunks:
        return PlaybackSimulation(
            minimum_buffer_ms=0.0,
            minimum_reserve_margin_ms=0.0,
            underrun_count=0,
            reserve_violation_count=0,
            second_arrival_margin_ms=None,
            second_arrival_reserve_margin_ms=None,
        )

    playback_start_ms = sorted_chunks[0].arrival_ms
    buffered_until_ms = playback_start_ms + sorted_chunks[0].audio_ms
    minimum_buffer_ms = sorted_chunks[0].audio_ms
    minimum_reserve_margin_ms = sorted_chunks[0].audio_ms - transport_reserve_ms
    underrun_count = 0
    reserve_violation_count = 0
    second_arrival_margin_ms: float | None = None
    second_arrival_reserve_margin_ms: float | None = None

    for index, chunk in enumerate(sorted_chunks[1:], start=1):
        margin_ms = buffered_until_ms - chunk.arrival_ms
        reserve_margin_ms = margin_ms - transport_reserve_ms
        if index == 1:
            second_arrival_margin_ms = margin_ms
            second_arrival_reserve_margin_ms = reserve_margin_ms
        minimum_buffer_ms = min(minimum_buffer_ms, margin_ms)
        minimum_reserve_margin_ms = min(minimum_reserve_margin_ms, reserve_margin_ms)
        if margin_ms < 0.0:
            underrun_count += 1
        if reserve_margin_ms < 0.0:
            reserve_violation_count += 1
        if margin_ms < 0.0:
            buffered_until_ms = chunk.arrival_ms
        buffered_until_ms += chunk.audio_ms

    return PlaybackSimulation(
        minimum_buffer_ms=minimum_buffer_ms,
        minimum_reserve_margin_ms=minimum_reserve_margin_ms,
        underrun_count=underrun_count,
        reserve_violation_count=reserve_violation_count,
        second_arrival_margin_ms=second_arrival_margin_ms,
        second_arrival_reserve_margin_ms=second_arrival_reserve_margin_ms,
    )
