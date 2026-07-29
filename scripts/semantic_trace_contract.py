"""Fail-closed validation for complete FasterQwen generation traces."""

from __future__ import annotations

from numbers import Integral
from typing import Any


TERMINATION_FLAGS = {
    "eos": "hit_eos",
    "max_new_tokens": "hit_max_new_tokens",
    "max_seq_len": "hit_max_seq_len",
}


def validate_generation_trace(trace: dict[str, Any]) -> None:
    """Raise ``RuntimeError`` unless a completed trace is internally coherent.

    ``generated_steps`` and ``emitted_steps`` count non-EOS codec frames in a
    fully consumed stream. The raw EOS candidate is represented by
    ``terminal_step_index`` but is excluded from both counters.
    """

    required = (
        "codec_sha256",
        "codec_frame_count",
        "termination_reason",
        "terminal_step_index",
        "generated_steps",
        "emitted_steps",
        *TERMINATION_FLAGS.values(),
    )
    for key in required:
        if key not in trace or trace[key] is None:
            raise RuntimeError(f"incomplete generation trace: {key}")

    reason = trace["termination_reason"]
    expected_flag = TERMINATION_FLAGS.get(reason)
    if expected_flag is None:
        raise RuntimeError(f"unsupported generation termination reason: {reason!r}")

    flags = {name: trace[key] for name, key in TERMINATION_FLAGS.items()}
    if any(not isinstance(value, bool) for value in flags.values()):
        raise RuntimeError("generation trace terminal flags must be bool")
    if sum(value is True for value in flags.values()) != 1:
        raise RuntimeError("generation trace must contain exactly one terminal flag")
    if flags[reason] is not True:
        raise RuntimeError(
            "generation trace terminal reason does not match its terminal flag"
        )

    codec_frames = _non_negative_int(trace["codec_frame_count"], "codec_frame_count")
    generated_steps = _non_negative_int(trace["generated_steps"], "generated_steps")
    emitted_steps = _non_negative_int(trace["emitted_steps"], "emitted_steps")
    if codec_frames != emitted_steps:
        raise RuntimeError(
            "generation trace codec_frame_count must equal emitted_steps"
        )
    if generated_steps != emitted_steps:
        raise RuntimeError(
            "completed generation trace generated_steps must equal emitted_steps"
        )

    terminal_step = _non_negative_int(
        trace["terminal_step_index"], "terminal_step_index"
    )
    if reason == "eos":
        _non_negative_int(trace["terminal_token_id"], "terminal_token_id")
        if terminal_step != generated_steps:
            raise RuntimeError(
                "eos terminal_step_index must identify the rejected EOS candidate"
            )
        return

    if trace["terminal_token_id"] is not None:
        raise RuntimeError(f"{reason} terminal trace must not contain an EOS token")
    if generated_steps == 0 or terminal_step != generated_steps - 1:
        raise RuntimeError(
            f"{reason} terminal_step_index must identify the last emitted codec frame"
        )


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise RuntimeError(f"generation trace {name} must be an integer")
    result = int(value)
    if result < 0:
        raise RuntimeError(f"generation trace {name} must be non-negative")
    return result
