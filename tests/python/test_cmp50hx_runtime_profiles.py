"""Contract tests for the explicit CMP 50HX playback profiles."""

from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_LAUNCHER = _ROOT / "scripts" / "start-qwen-tts-clone-play.ps1"
_DOC = _ROOT / "docs" / "voice-clone.md"


class Cmp50hxRuntimeProfilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.launcher = _LAUNCHER.read_text(encoding="utf-8")
        self.documentation = _DOC.read_text(encoding="utf-8")

    def test_profiles_are_explicit_and_default_is_preserved(self) -> None:
        self.assertIn(
            '[ValidateSet("default", "cmp50hx-low-latency", "cmp50hx-safe")]',
            self.launcher,
        )
        self.assertIn('[string]$RuntimeProfile = "default"', self.launcher)
        self.assertIn('$emitEveryFrames = 8', self.launcher)
        self.assertIn('$decodeWindowFrames = 80', self.launcher)
        self.assertIn('$maxSeqLen = 2048', self.launcher)
        self.assertIn('$dtype = "bfloat16"', self.launcher)

    def test_low_latency_profile_maps_to_bounded_e4_w33_graph(self) -> None:
        block = self.launcher.split('switch ($RuntimeProfile)', 1)[1].split(
            '"cmp50hx-safe"', 1
        )[0]
        block = block.split('"cmp50hx-low-latency"', 1)[1]
        self.assertIn('$emitEveryFrames = 4', block)
        self.assertIn('$decodeWindowFrames = 33', block)
        self.assertIn('$maxSeqLen = 768', block)
        self.assertIn('$dtype = "float16"', block)

    def test_safe_profile_maps_to_e8_w33_graph(self) -> None:
        block = self.launcher.split('"cmp50hx-safe"', 1)[1]
        self.assertIn('$emitEveryFrames = 8', block)
        self.assertIn('$decodeWindowFrames = 33', block)
        self.assertIn('$maxSeqLen = 2048', block)
        self.assertIn('$dtype = "float16"', block)

    def test_launcher_passes_selected_values_and_one_chunk_prebuffer(self) -> None:
        self.assertIn('"--max-seq-len", $maxSeqLen', self.launcher)
        self.assertIn('"--emit-every-frames", $emitEveryFrames', self.launcher)
        self.assertIn('"--decode-window-frames", $decodeWindowFrames', self.launcher)
        self.assertIn(
            '$workerArguments += @("--runtime-profile", $RuntimeProfile)',
            self.launcher,
        )
        self.assertIn(
            '$arguments += @("--playback-prebuffer-chunks", "1")',
            self.launcher,
        )
        self.assertIn('$env:QTB_FASTER_CODEC_RIGHT_PADDED_DECODE = "1"', self.launcher)
        self.assertIn(
            '$env:QTB_FASTER_CODEC_RIGHT_PADDED_CUDA_GRAPH = "1"',
            self.launcher,
        )
        self.assertIn(
            '$env:QTB_FASTER_BASE_REFERENCE_CONTEXT_BOOTSTRAP = "1"',
            self.launcher,
        )

    def test_documentation_describes_request_boundary_switching(self) -> None:
        self.assertIn("cmp50hx-low-latency", self.documentation)
        self.assertIn("cmp50hx-safe", self.documentation)
        self.assertIn("request boundary", self.documentation)
        self.assertIn("max_seq_len=768", self.documentation)


if __name__ == "__main__":
    unittest.main()
