#!/usr/bin/env python3
"""Validate the predictor Philox schedule recorded by a native probe.

The validator is deliberately independent of NumPy and PyTorch so that a
sanitized diagnostic artifact can be checked in a small CI or review
environment.  It mirrors the qwentts.cpp Philox4x32-10 implementation and
compares the serialized float32 uniforms with a bounded tolerance.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path
from typing import Any

_MASK32 = 0xFFFFFFFF
_M0 = 0xD2511F53
_M1 = 0xCD9E8D57
_W0 = 0x9E3779B9
_W1 = 0xBB67AE85
_TWO_POW32_INV = 2.3283064365386963e-10


def _load_probe(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("probe must contain a JSON object")
    return value


def _float32(value: float) -> float:
    """Round a Python float to the float32 value emitted by qwentts."""

    return struct.unpack("<f", struct.pack("<f", value))[0]


def _mul_hi_lo(left: int, right: int) -> tuple[int, int]:
    product = (left * right) & 0xFFFFFFFFFFFFFFFF
    return (product >> 32) & _MASK32, product & _MASK32


def _philox_round(
    counter: tuple[int, int, int, int], key0: int, key1: int
) -> tuple[int, int, int, int]:
    hi0, lo0 = _mul_hi_lo(_M0, counter[0])
    hi1, lo1 = _mul_hi_lo(_M1, counter[2])
    return (
        (hi1 ^ counter[1] ^ key0) & _MASK32,
        lo1,
        (hi0 ^ counter[3] ^ key1) & _MASK32,
        lo0,
    )


def philox_uniform(seed: int, subsequence: int) -> float:
    """Return the qwentts float32 uniform for counter zero."""

    key0 = seed & _MASK32
    key1 = (seed >> 32) & _MASK32
    counter = (0, 0, subsequence & _MASK32, (subsequence >> 32) & _MASK32)
    for _ in range(9):
        counter = _philox_round(counter, key0, key1)
        key0 = (key0 + _W0) & _MASK32
        key1 = (key1 + _W1) & _MASK32
    counter = _philox_round(counter, key0, key1)
    return _float32((_float32(counter[0]) + _float32(0.5)) * _TWO_POW32_INV)


def validate_probe(probe: dict[str, Any], *, tolerance: float = 1e-7) -> dict[str, Any]:
    """Validate schedule shape and every recorded uniform.

    The native trace passes ``step * 16`` as the predictor base; predictor
    codebooks then consume ``base + 1`` through ``base + 15``. The Talker
    draw itself is source-derived context and is not present in this trace.
    """

    seed = probe.get("seed")
    if not isinstance(seed, int):
        raise ValueError("probe.seed must be an integer")
    records = probe.get("predictor_philox_trace")
    if not isinstance(records, list) or not records:
        raise ValueError("probe.predictor_philox_trace must be a non-empty array")

    checked_draws = 0
    max_error = 0.0
    steps: list[int] = []
    for expected_step, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"predictor trace record {expected_step} is not an object")
        step = record.get("step")
        base = record.get("base")
        draws = record.get("draws")
        if step != expected_step:
            raise ValueError(f"predictor trace step {step!r} is not {expected_step}")
        if base != step * 16:
            raise ValueError(f"step {step} base {base!r} is not {step * 16}")
        if not isinstance(draws, list) or len(draws) != 15:
            raise ValueError(f"step {step} must contain exactly 15 predictor draws")
        for offset, draw in enumerate(draws, start=1):
            if not isinstance(draw, list) or len(draw) != 2:
                raise ValueError(f"step {step} contains a malformed draw")
            subsequence, observed = draw
            expected_subsequence = base + offset
            if subsequence != expected_subsequence:
                raise ValueError(
                    f"step {step} subsequence {subsequence!r} is not "
                    f"{expected_subsequence}"
                )
            if not isinstance(observed, (int, float)) or not math.isfinite(observed):
                raise ValueError(f"step {step} has a non-finite uniform")
            if not 0.0 <= float(observed) < 1.0:
                raise ValueError(f"step {step} uniform is outside [0, 1)")
            expected = philox_uniform(seed, subsequence)
            error = abs(float(observed) - expected)
            max_error = max(max_error, error)
            if error > tolerance:
                raise ValueError(
                    f"step {step} subsequence {subsequence} uniform mismatch: "
                    f"observed={observed!r} expected={expected!r} error={error:g}"
                )
            checked_draws += 1
        steps.append(step)

    return {
        "seed": seed,
        "records": len(records),
        "draws": checked_draws,
        "steps": steps,
        "max_abs_error": max_error,
        "tolerance": tolerance,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=1e-7)
    args = parser.parse_args()
    try:
        result = validate_probe(_load_probe(args.probe), tolerance=args.tolerance)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
