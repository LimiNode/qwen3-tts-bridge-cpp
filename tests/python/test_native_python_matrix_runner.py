"""Static contract checks for the cross-backend matrix runner."""

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-native-python-matrix.ps1"
BENCHMARK = ROOT / "examples" / "qwen_tts_latency_benchmark.cpp"
FULL_TEMPLATE = ROOT / "docs" / "acceptance" / "native-python-full.template.jsonl"


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
        self.assertIn("Get-ReferenceAudioProvenance", source)
        self.assertIn("Get-PythonPackageProvenance", source)
        self.assertIn("python_sources", source)
        self.assertIn("reference_audio", source)
        self.assertIn("effective-request-manifest.jsonl", source)
        self.assertIn("--canary-runtime-profile-manifest", source)
        self.assertIn("--canary-compiled-allowlist-manifest", source)
        self.assertIn("talker_model", source)
        self.assertIn("codec_model", source)

    def test_runner_preserves_defaults_and_negative_outcome_contract(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            '$runtimeManifest = Join-Path $NativeWorkerArgument[$index + 1] '
            '"manifest.json"',
            source,
        )
        self.assertIn('Add-OptionalPlaybackArgument $command "--seed" $Seed', source)

    def test_benchmark_accepts_explicit_negative_outcomes(self) -> None:
        source = BENCHMARK.read_text(encoding="utf-8")
        template = FULL_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("allowed_terminal_outcomes", source)
        self.assertIn("allowed_errors", source)
        self.assertIn("cancel_after_first_pcm", source)
        self.assertIn("completion_metadata", source)
        self.assertIn("natural_eos", source)
        self.assertIn("late_audio_after_terminal_count", source)
        self.assertIn("terminal_quiet", source)
        self.assertIn('"request_error"', template)
        self.assertIn('"resource_error"', template)
        self.assertIn("allowed_errors", template)


if __name__ == "__main__":
    unittest.main()
