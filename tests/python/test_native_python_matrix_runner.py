"""Contract checks for the cross-backend matrix runner."""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-native-python-matrix.ps1"
BENCHMARK = ROOT / "examples" / "qwen_tts_latency_benchmark.cpp"
FULL_TEMPLATE = ROOT / "docs" / "acceptance" / "native-python-full.template.jsonl"


class NativePythonMatrixRunnerTests(unittest.TestCase):
    def test_failed_playback_gate_returns_nonzero(self) -> None:
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell is required for the runner integration check")

        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            benchmark = root / "mock-benchmark.ps1"
            playback = root / "mock-playback.ps1"
            python_worker = root / "python-worker.exe"
            native_worker = root / "native-worker.exe"
            output = root / "matrix.json"

            benchmark.write_text(
                """
$resultIndex = [Array]::IndexOf($args, "--result-json")
if ($resultIndex -lt 0) { exit 2 }
@{ startup_ms = 0; requests = @(); contract_failures = @() } |
    ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath $args[$resultIndex + 1] -Encoding UTF8
exit 0
""".strip(),
                encoding="utf-8",
            )
            playback.write_text(
                """
$metricsIndex = [Array]::IndexOf($args, "--playback-metrics-file")
if ($metricsIndex -lt 0) { exit 2 }
@{ playback_completed = $false; queue_empty_before_later_chunk_count = 0 } |
    ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath $args[$metricsIndex + 1] -Encoding UTF8
exit 0
""".strip(),
                encoding="utf-8",
            )
            python_worker.touch()
            native_worker.touch()

            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-File",
                    str(RUNNER),
                    "-BenchmarkExecutable",
                    str(benchmark),
                    "-PythonWorkerExecutable",
                    str(python_worker),
                    "-PythonWorkerArgument",
                    "mock",
                    "-NativeWorkerExecutable",
                    str(native_worker),
                    "-NativeWorkerArgument",
                    "mock",
                    "-PlaybackExecutable",
                    str(playback),
                    "-Warmups",
                    "0",
                    "-Requests",
                    "1",
                    "-SkipGpuSampling",
                    "-Output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(
                completed.returncode,
                0,
                completed.stdout + completed.stderr,
            )
            self.assertTrue(output.is_file())
            matrix = json.loads(output.read_text(encoding="utf-8-sig"))
            self.assertFalse(matrix["playback"]["python"]["gate_passed"])
            self.assertFalse(matrix["playback"]["native"]["gate_passed"])

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
        self.assertIn("Get-BenchmarkGateFailures", source)
        self.assertIn("starvation_proxy_count", source)
        self.assertIn("provenance_mismatch_count", source)
        self.assertIn(
            "selected acceptance case has an invalid manifest contract",
            source,
        )

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
        self.assertIn("warmup_reference_audio", source)
        self.assertIn("warmup_reference_text", source)
        self.assertIn("self-test-eos-contract", source)
        self.assertIn('"request_error"', template)
        self.assertIn('"resource_error"', template)
        self.assertIn("allowed_errors", template)


if __name__ == "__main__":
    unittest.main()
