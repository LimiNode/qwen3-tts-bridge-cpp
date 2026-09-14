"""Executable tests for the stochastic parity evidence contract."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_cmp50hx_stochastic_parity",
    ROOT / "scripts" / "validate-cmp50hx-stochastic-parity.py",
)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def _evidence() -> dict[str, object]:
    return {
        "schema_version": 1,
        "sampling_mode": "stochastic",
        "same_conditioning": True,
        "sampling_parameters": {
            "seed": 1006,
            "temperature": 0.9,
            "top_k": 50,
            "top_p": 1.0,
            "repetition_penalty": 1.05,
        },
        "talker_c0_draws": [
            {
                "subsequence": 0,
                "native_u": 0.25,
                "python_u": 0.25,
                "native_token": 1721,
                "python_token": 1721,
            },
            {
                "subsequence": 16,
                "native_u": 0.75,
                "python_u": 0.75,
                "native_token": 1687,
                "python_token": 1687,
            },
        ],
        "predictor_first_frame": {
            "native_codes": [27, *range(1, 16)],
            "python_codes": [27, *range(1, 16)],
        },
        "conclusion": {
            "stochastic_sampler_parity_closed": True,
            "long_horizon_ar_kv_parity_closed": False,
        },
    }


class ValidateCmp50HxStochasticParityTests(unittest.TestCase):
    def test_accepts_exact_same_conditioning_contract(self) -> None:
        result = validator.validate(_evidence())
        self.assertEqual(2, result["draws"])
        self.assertEqual(16, result["predictor_codebooks"])

    def test_rejects_uniform_mismatch(self) -> None:
        evidence = _evidence()
        evidence["talker_c0_draws"][1]["python_u"] = 0.5  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "uniform mismatch"):
            validator.validate(evidence)

    def test_rejects_predictor_token_mismatch(self) -> None:
        evidence = _evidence()
        evidence["predictor_first_frame"]["native_codes"][3] = 99  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "first-frame codes"):
            validator.validate(evidence)

    def test_keeps_long_horizon_gate_open(self) -> None:
        evidence = _evidence()
        evidence["conclusion"]["long_horizon_ar_kv_parity_closed"] = True  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "long-horizon"):
            validator.validate(evidence)


if __name__ == "__main__":
    unittest.main()
