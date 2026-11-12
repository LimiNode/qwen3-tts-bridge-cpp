"""Exercise portable acceptance preflight/failure receipts without a runtime."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("powershell.exe")


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "Windows PowerShell required")
class PortableCliRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_root = ROOT / ".tmp/portable-cli-runner-tests"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "package"
        self.package.mkdir()
        (self.package / ".qtb-portable-release-root").touch()
        (self.package / "sentinel.bin").write_bytes(b"preserve original package")
        (self.package / "qwen-tts.cmd").write_text("@echo off\r\n", encoding="ascii")
        (self.package / "release-manifest.json").write_text(
            '{"release_manifest_schema_version": 1}', encoding="utf-8"
        )
        (self.package / "bin").mkdir()
        (self.package / "bin/qwen_tts_play.exe").write_bytes(b"not an executable")
        (self.package / "worker-python/python").mkdir(parents=True)
        shutil.copy2(
            os.environ["ComSpec"], self.package / "worker-python/python/python.exe"
        )

    def run_runner(self, output: Path) -> subprocess.CompletedProcess[str]:
        assert POWERSHELL
        return subprocess.run(
            [
                POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(ROOT / "scripts/test-portable-user-cli.ps1"),
                "-PackageRoot", str(self.package), "-OutputRoot", str(output),
                "-CommandTimeoutSeconds", "1",
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )

    def test_failed_package_preserves_a_machine_readable_failure(self) -> None:
        output = self.root / "acceptance"
        result = self.run_runner(output)
        self.assertNotEqual(0, result.returncode)
        if not (output / "cli-acceptance-summary.json").is_file():
            self.fail(
                "runner did not write failure receipt; stdout/stderr:\n"
                f"{result.stdout}\n{result.stderr}"
            )
        summary = json.loads((output / "cli-acceptance-summary.json").read_text())
        self.assertEqual("fail", summary["case_result"]["status"])
        self.assertTrue(summary["case_result"]["reason"])
        self.assertEqual("not_assessed", summary["listening_result"]["status"])
        self.assertEqual("blocked", summary["release_disposition"]["status"])
        self.assertEqual("portable_cli_mock", summary["evidence_kind"])
        self.assertTrue(summary["package_manifest_sha256"])
        self.assertEqual(
            b"preserve original package", (self.package / "sentinel.bin").read_bytes()
        )

    def test_output_must_not_overlap_the_package(self) -> None:
        result = self.run_runner(self.package)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.package / ".qtb-portable-cli-test-root").exists())
        self.assertEqual(
            b"preserve original package", (self.package / "sentinel.bin").read_bytes()
        )


if __name__ == "__main__":
    unittest.main()
