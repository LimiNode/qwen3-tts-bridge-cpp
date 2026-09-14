"""Tests for the dependency-free CMP 50HX Philox trace validator."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_cmp50hx_philox_trace",
    ROOT / "scripts" / "validate-cmp50hx-philox-trace.py",
)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def _probe() -> dict[str, object]:
    records = []
    for step in range(2):
        base = step * 16
        records.append(
            {
                "step": step,
                "base": base,
                "draws": [
                    [subsequence, validator.philox_uniform(1006, subsequence)]
                    for subsequence in range(base + 1, base + 16)
                ],
            }
        )
    return {"seed": 1006, "predictor_philox_trace": records}


class ValidateCmp50HxPhiloxTraceTests(unittest.TestCase):
    def test_accepts_python_mirror_schedule(self) -> None:
        result = validator.validate_probe(_probe())

        self.assertEqual(2, result["records"])
        self.assertEqual(30, result["draws"])
        self.assertEqual([0, 1], result["steps"])
        self.assertLessEqual(result["max_abs_error"], 1e-12)

    def test_rejects_uniform_mismatch(self) -> None:
        probe = _probe()
        probe["predictor_philox_trace"][0]["draws"][0][1] = 0.5  # type: ignore[index]

        with self.assertRaisesRegex(ValueError, "uniform mismatch"):
            validator.validate_probe(probe)

    def test_rejects_non_contiguous_base(self) -> None:
        probe = _probe()
        probe["predictor_philox_trace"][1]["base"] = 15  # type: ignore[index]

        with self.assertRaisesRegex(ValueError, "base"):
            validator.validate_probe(probe)

    def test_rejects_subsequence_gap(self) -> None:
        probe = _probe()
        probe["predictor_philox_trace"][0]["draws"][4][0] = 99  # type: ignore[index]

        with self.assertRaisesRegex(ValueError, "subsequence"):
            validator.validate_probe(probe)


if __name__ == "__main__":
    unittest.main()
