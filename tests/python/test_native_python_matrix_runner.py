"""Static contract checks for the cross-backend matrix runner."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-native-python-matrix.ps1"


class NativePythonMatrixRunnerTests(unittest.TestCase):
    def test_playback_selects_and_replays_exact_manifest_fields(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("[string] $PlaybackManifestLabel", source)
        self.assertIn("Get-ManifestPlaybackSpec", source)
        for argument in (
            '"--speaker"',
            '"--voice-id"',
            '"--instruction"',
            '"--reference-audio"',
            '"--reference-text"',
            '"--x-vector-only"',
            '"--seed"',
        ):
            self.assertIn(argument, source)

    def test_runner_snapshots_manifest_and_native_hashes(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn('"request-manifest.jsonl"', source)
        self.assertIn("Get-FileHash -Algorithm SHA256", source)
        self.assertIn("native_dll", source)
        self.assertIn("native_runtime_manifest", source)


if __name__ == "__main__":
    unittest.main()
