"""Exercise installed real-model runner receipts without GPU inference."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
POWERSHELLS = [
    candidate
    for candidate in (shutil.which("powershell.exe"), shutil.which("pwsh.exe"))
    if candidate
]


FAKE_CLI_PS1 = r"""
$arguments = @($args)
$outIndex = [Array]::IndexOf([array]$arguments, '--out')
if ($outIndex -ge 0 -and $outIndex + 1 -lt $arguments.Count) {
    $output = [string]$arguments[$outIndex + 1]
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $output) | Out-Null
    $stream = [IO.File]::Create($output)
    $writer = [IO.BinaryWriter]::new($stream, [Text.Encoding]::ASCII, $false)
    try {
        $writer.Write([Text.Encoding]::ASCII.GetBytes('RIFF'))
        $writer.Write([int]38)
        $writer.Write([Text.Encoding]::ASCII.GetBytes('WAVEfmt '))
        $writer.Write([int]16)
        $writer.Write([int16]1)
        $writer.Write([int16]1)
        $writer.Write([int]24000)
        $writer.Write([int]48000)
        $writer.Write([int16]2)
        $writer.Write([int16]16)
        $writer.Write([Text.Encoding]::ASCII.GetBytes('data'))
        $writer.Write([int]2)
        $writer.Write([int16]4096)
    }
    finally { $writer.Dispose() }
}
if ($env:QTB_TEST_REAL_MODEL_CLI_FAIL -eq '1') {
    [Console]::Error.WriteLine('synthetic model failure')
    exit 23
}
Write-Output '{"status":"ok"}'
exit 0
""".strip()


FAKE_CLI_CMD = """@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0fake-cli.ps1" %*
exit /b %ERRORLEVEL%
"""


@unittest.skipUnless(os.name == "nt" and POWERSHELLS, "Windows PowerShell required")
class InstalledRealModelCliRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.cli_script = self.root / "fake-cli.ps1"
        self.cli_launcher = self.root / "fake-cli.cmd"
        self.cli_script.write_text(FAKE_CLI_PS1 + "\n", encoding="utf-8")
        self.cli_launcher.write_text(FAKE_CLI_CMD, encoding="ascii")
        self.model = self.root / "model"
        self.model.mkdir()
        (self.model / "config.json").write_text("{}", encoding="utf-8")
        self.config = self.root / "cli-config.json"
        self.config.write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_runner(
        self,
        shell: str,
        output: Path,
        *,
        fail: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        if fail:
            environment["QTB_TEST_REAL_MODEL_CLI_FAIL"] = "1"
        else:
            environment.pop("QTB_TEST_REAL_MODEL_CLI_FAIL", None)
        return subprocess.run(
            [
                shell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts/run-installed-real-model-cli-acceptance.ps1"),
                "-CliPath",
                str(self.cli_launcher),
                "-PythonPath",
                sys.executable,
                "-ModelPath",
                str(self.model),
                "-ConfigPath",
                str(self.config),
                "-OutputRoot",
                str(output),
                "-SkipPlay",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=30,
            check=False,
        )

    @staticmethod
    def find_summary(output: Path) -> dict[str, Any]:
        summaries = list(output.glob("*/summary.json"))
        if len(summaries) != 1:
            raise AssertionError(
                f"expected one summary under {output}, got {summaries}"
            )
        return json.loads(summaries[0].read_text(encoding="utf-8"))

    def test_failed_command_preserves_structured_receipt_and_artifacts(self) -> None:
        for index, shell in enumerate(POWERSHELLS):
            with self.subTest(shell=shell):
                output = self.root / f"failure-{index}"
                result = self.run_runner(shell, output, fail=True)
                self.assertNotEqual(0, result.returncode)
                summary = self.find_summary(output)
                self.assertEqual("fail", summary["case_result"]["status"])
                self.assertEqual("blocked", summary["release_disposition"]["status"])
                self.assertEqual(23, summary["failure"]["exit_code"])
                self.assertEqual("qwen-tts synth", summary["failure"]["stage"])
                self.assertIn("synthetic model failure", summary["failure"]["reason"])
                self.assertEqual(
                    str(self.cli_launcher), summary["provenance"]["cli_path"]
                )
                artifact_paths = {item["path"] for item in summary["artifacts"]}
                self.assertIn("synth.log", artifact_paths)
                self.assertIn("synth.wav", artifact_paths)

    def test_successful_runner_writes_structured_summary_without_gpu(self) -> None:
        for index, shell in enumerate(POWERSHELLS):
            with self.subTest(shell=shell):
                output = self.root / f"success-{index}"
                result = self.run_runner(shell, output)
                if result.returncode != 0:
                    self.fail(
                        "runner failed:\n"
                        f"stdout={result.stdout}\nstderr={result.stderr}"
                    )
                summary = self.find_summary(output)
                self.assertEqual("pass", summary["case_result"]["status"])
                self.assertEqual(
                    "conditional", summary["release_disposition"]["status"]
                )
                self.assertEqual(
                    "repository_checkout",
                    summary["verification_harness"]["wav_verifier_source"],
                )
                self.assertEqual(
                    "not_proven",
                    summary["verification_harness"]["clean_package_independence"],
                )
                self.assertTrue(summary["verification_harness"]["installed_cli_pythonpath_removed"])
                self.assertEqual(0, summary["synth"]["exit_code"])


if __name__ == "__main__":
    unittest.main()
