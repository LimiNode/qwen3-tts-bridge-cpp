"""Contract checks for the native CMP 50HX timing measurement."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MEASUREMENT = _ROOT / "scripts" / "measure-cmp50hx-ggml-playback.ps1"


class Cmp50hxNativeMeasurementContractTests(unittest.TestCase):
    def test_incomplete_physical_playback_fails_the_attempt(self) -> None:
        measurement = _MEASUREMENT.read_text(encoding="utf-8")

        self.assertIn(
            "if (-not [bool]$playback.playback_completed)", measurement
        )
        self.assertIn(
            "did not complete physical playback", measurement
        )


if __name__ == "__main__":
    unittest.main()
