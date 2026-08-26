"""Regression checks for the right-padded codec decode input contract."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LAUNCHER = _ROOT / "scripts" / "run-cmp50hx-playback-etw-soak.ps1"
_PATCH = (
    _ROOT
    / "scripts"
    / "patches"
    / "cmp50hx-faster-codec-right-padded-decode.patch"
)


class Cmp50hxCodecRightPaddedContractTest(unittest.TestCase):
    def test_launcher_and_patch_fail_closed_on_context_contract_drift(self) -> None:
        launcher = _LAUNCHER.read_text(encoding="utf-8")
        patch = _PATCH.read_text(encoding="utf-8")

        self.assertIn("$CodecRightPaddedHistoryFrames = 25", launcher)
        self.assertIn(
            "QTB_FASTER_CODEC_RIGHT_PADDED_MAX_DECODE_INPUT_FRAMES", launcher
        )
        self.assertIn(
            "$CodecRightPaddedHistoryFrames + $EmitEveryFrames", launcher
        )
        self.assertIn("_codec_right_padded_max_decode_input_frames", patch)
        self.assertIn("original_frames > max_decode_input_frames", patch)


if __name__ == "__main__":
    unittest.main()
