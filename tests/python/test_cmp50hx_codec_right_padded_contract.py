"""Regression checks for the right-padded codec decode input contract."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LAUNCHER = _ROOT / "scripts" / "run-cmp50hx-playback-etw-soak.ps1"
_FASTER_MODEL = (
    _ROOT
    / "external"
    / "python"
    / "faster-qwen3-tts"
    / "faster_qwen3_tts"
    / "model.py"
)


class Cmp50hxCodecRightPaddedContractTest(unittest.TestCase):
    def test_launcher_and_submodule_fail_closed_on_context_contract_drift(
        self,
    ) -> None:
        launcher = _LAUNCHER.read_text(encoding="utf-8")
        faster_model = _FASTER_MODEL.read_text(encoding="utf-8")

        self.assertIn("$CodecRightPaddedHistoryFrames = 25", launcher)
        self.assertIn("external\\python\\faster-qwen3-tts", launcher)
        self.assertIn(
            "QTB_FASTER_CODEC_RIGHT_PADDED_MAX_DECODE_INPUT_FRAMES", launcher
        )
        self.assertIn(
            "$CodecRightPaddedHistoryFrames + $EmitEveryFrames", launcher
        )
        self.assertIn(
            "_codec_right_padded_max_decode_input_frames", faster_model
        )
        self.assertIn("original_frames > max_decode_input_frames", faster_model)
        self.assertNotIn("prepare-cmp50hx-faster", launcher)
        self.assertNotIn("$CodecStreamingDecode", launcher)

    def test_launcher_revision_matches_faster_submodule_gitlink(self) -> None:
        launcher = _LAUNCHER.read_text(encoding="utf-8")
        revision = re.search(
            r"\$FasterCmp50hxSubmoduleCommit = '([0-9a-f]{40})'", launcher
        )
        assert revision is not None
        gitlink = subprocess.check_output(
            [
                "git",
                "ls-files",
                "--stage",
                "external/python/faster-qwen3-tts",
            ],
            cwd=_ROOT,
            text=True,
        ).split()[1]
        self.assertEqual(revision.group(1), gitlink)


if __name__ == "__main__":
    unittest.main()
