"""Regression tests for the speech-animation PowerShell runner."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPOSITORY_ROOT / "scripts" / "run-speech-animation-qwen-e2e.ps1"


class SpeechAnimationE2eRunnerTests(unittest.TestCase):
    def test_utf8_text_file_round_trip(self) -> None:
        """The runner must preserve Cyrillic text in its generated summary."""
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is required for the runner integration check")

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            probe = temporary_root / "fake_probe.cmd"
            probe_script = temporary_root / "fake_probe.ps1"
            worker = temporary_root / "fake_worker.exe"
            text_file = temporary_root / "utterance.txt"
            output_root = temporary_root / "receipt"
            spoken_text = "Сегодня голос говорит спокойно.\n"

            probe_script.write_text(
                """
$outputIndex = [Array]::IndexOf($args, '--output-json')
$textIndex = [Array]::IndexOf($args, '--text-file')
if ($outputIndex -lt 0 -or $textIndex -lt 0) { exit 2 }
$outputPath = $args[$outputIndex + 1]
$textPath = $args[$textIndex + 1]
$text = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($textPath))
[ordered]@{
    success = $true
    text = $text
    text_source = 'utf8_file'
    text_file = $textPath
    first_pcm_ms = 100.0
    first_downstream_pcm_ms = 100.0
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $outputPath -Encoding UTF8
""".lstrip(),
                encoding="utf-8",
            )
            probe.write_text(
                '@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass '
                '-File "%~dp0fake_probe.ps1" %*\r\nexit /b %ERRORLEVEL%\r\n',
                encoding="ascii",
            )
            worker.write_bytes(b"mock worker")
            text_file.write_text(spoken_text, encoding="utf-8", newline="")

            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(RUNNER),
                    "-ProbePath",
                    str(probe),
                    "-WorkerPath",
                    str(worker),
                    "-TextFile",
                    str(text_file),
                    "-OutputRoot",
                    str(output_root),
                ],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode(errors="replace")
                self.fail(f"PowerShell runner failed: {stderr}")

            summary = json.loads(
                (output_root / "ab-summary.json").read_text(encoding="utf-8-sig")
            )
            self.assertEqual(summary["text"], spoken_text)
            self.assertEqual(summary["adapter_off"]["success"], True)
            self.assertEqual(summary["adapter_on"]["success"], True)


if __name__ == "__main__":
    unittest.main()
