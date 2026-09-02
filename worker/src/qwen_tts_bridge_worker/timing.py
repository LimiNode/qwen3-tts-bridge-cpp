"""Small timing helpers shared across worker layers."""

from __future__ import annotations

import time


def monotonic_seconds() -> float:
    """Return a monotonic timestamp suitable for duration measurements."""

    return time.perf_counter()


def elapsed_milliseconds(started_at: float, ended_at: float | None = None) -> float:
    """Return elapsed milliseconds rounded for diagnostic output."""

    if ended_at is None:
        ended_at = monotonic_seconds()
    return round((ended_at - started_at) * 1000.0, 3)
