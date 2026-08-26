"""Regression checks for CMP50HX launcher process-environment restoration."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LAUNCHER = _ROOT / "scripts" / "run-cmp50hx-playback-etw-soak.ps1"


class Cmp50hxPlaybackLauncherEnvironmentTest(unittest.TestCase):
    def test_compile_environment_is_snapshotted_and_restored(self) -> None:
        launcher = _LAUNCHER.read_text(encoding="utf-8")

        self.assertIn("'QTB_FASTER_CODEC_RIGHT_PADDED_COMPILE'", launcher)
        self.assertIn("'QTB_FASTER_CODEC_RIGHT_PADDED_COMPILE_MODE'", launcher)
        self.assertIn("$previousEnvironment[$name]", launcher)
        expected_restore = (
            "[Environment]::SetEnvironmentVariable("
            "$name, $previousEnvironment[$name], 'Process')"
        )
        self.assertIn(
            expected_restore,
            launcher,
        )


if __name__ == "__main__":
    unittest.main()
