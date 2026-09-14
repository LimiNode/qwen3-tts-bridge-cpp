#!/usr/bin/env python3
"""Validate a sanitized same-conditioning stochastic parity artifact.

The validator is intentionally model-free.  It checks that the artifact
records one shared sampling configuration, equal Philox uniforms and exact
Talker/predictor token selections.  It does not treat this first-frame gate as
evidence for long-horizon AR/KV parity.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("evidence must be a JSON object")
    return value


def validate(
    evidence: dict[str, Any], *, uniform_tolerance: float = 1e-9
) -> dict[str, Any]:
    if evidence.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    if evidence.get("sampling_mode") != "stochastic":
        raise ValueError("sampling_mode must be stochastic")
    if evidence.get("same_conditioning") is not True:
        raise ValueError("same_conditioning must be true")

    parameters = evidence.get("sampling_parameters")
    if not isinstance(parameters, dict):
        raise ValueError("sampling_parameters are required")
    for field in ("seed", "temperature", "top_k", "top_p", "repetition_penalty"):
        if field not in parameters:
            raise ValueError(f"sampling parameter is missing: {field}")

    draws = evidence.get("talker_c0_draws")
    if not isinstance(draws, list) or not draws:
        raise ValueError("talker_c0_draws must be a non-empty array")
    for index, draw in enumerate(draws):
        if not isinstance(draw, dict):
            raise ValueError(f"draw {index} is not an object")
        subseq = draw.get("subsequence")
        if not isinstance(subseq, int) or subseq != index * 16:
            raise ValueError(f"draw {index} has a non-contiguous subsequence")
        native_u = draw.get("native_u")
        python_u = draw.get("python_u")
        if not all(
            isinstance(value, (int, float)) and math.isfinite(value)
            for value in (native_u, python_u)
        ):
            raise ValueError(f"draw {index} has a non-finite uniform")
        if not all(0.0 <= float(value) < 1.0 for value in (native_u, python_u)):
            raise ValueError(f"draw {index} uniform is outside [0, 1)")
        if abs(float(native_u) - float(python_u)) > uniform_tolerance:
            raise ValueError(f"draw {index} Philox uniform mismatch")
        if draw.get("native_token") != draw.get("python_token"):
            raise ValueError(f"draw {index} selected token mismatch")
        if not isinstance(draw.get("native_token"), int):
            raise ValueError(f"draw {index} selected token is not an integer")

    predictor = evidence.get("predictor_first_frame")
    if not isinstance(predictor, dict):
        raise ValueError("predictor_first_frame is required")
    native_codes = predictor.get("native_codes")
    python_codes = predictor.get("python_codes")
    if not isinstance(native_codes, list) or not isinstance(python_codes, list):
        raise ValueError("predictor code arrays are required")
    if len(native_codes) != 16 or len(python_codes) != 16:
        raise ValueError("predictor first frame must contain 16 codebooks")
    if native_codes != python_codes:
        raise ValueError("predictor first-frame codes differ")

    conclusion = evidence.get("conclusion")
    if (
        not isinstance(conclusion, dict)
        or conclusion.get("stochastic_sampler_parity_closed") is not True
    ):
        raise ValueError("stochastic sampler parity must be explicitly closed")
    if conclusion.get("long_horizon_ar_kv_parity_closed") is not False:
        raise ValueError("long-horizon AR/KV parity must remain open")

    return {
        "draws": len(draws),
        "predictor_codebooks": 16,
        "uniform_tolerance": uniform_tolerance,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--uniform-tolerance", type=float, default=1e-9)
    args = parser.parse_args()
    try:
        result = validate(
            _load(args.evidence), uniform_tolerance=args.uniform_tolerance
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
