"""Regression tests for the sealed internal runtime launcher."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LAUNCHER = _ROOT / "scripts" / "start-rtx4090-faster-customvoice.ps1"
_INTERNAL_PROFILE = (
    "config/rtx4090-48gb-faster-customvoice-frequency-exact-allowlist-r10-"
    "internal-opt-in.json"
)


@unittest.skipUnless(os.name == "nt", "PowerShell launcher is Windows-only")
class InternalRuntimeLauncherTests(unittest.TestCase):
    def test_internal_profile_accepts_an_absolute_profile_path(self) -> None:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(_LAUNCHER),
                "-ProfilePath",
                str(_ROOT / _INTERNAL_PROFILE),
                "-Python",
                "not-used-because-argument-is-rejected.exe",
                "-AdditionalArguments",
                "--dtype",
                "float16",
            ],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "Internal runtime profiles do not accept AdditionalArguments.",
            completed.stderr,
        )

    def test_internal_profile_rejects_runtime_overrides_before_preflight(self) -> None:
        override_attempts = (
            ("--model-path", "models/other-model"),
            ("--prefill-compile-lengths", "1,2,3"),
            ("--max-audio-seconds-per-utterance", "0"),
            ("--runtime-backend", "upstream"),
            ("--dtype", "float16"),
            ("--attn-implementation", "eager"),
            ("--compiled-emit-chunk-schedule", "5,8,12"),
            ("--prefill-generation-prime",),
            ("--prefill-compile-on-miss",),
        )
        for override in override_attempts:
            with self.subTest(override=override):
                completed = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(_LAUNCHER),
                        "-ProfilePath",
                        _INTERNAL_PROFILE,
                        "-Python",
                        "not-used-because-argument-is-rejected.exe",
                        "-AdditionalArguments",
                        *override,
                    ],
                    cwd=_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(
                    "Internal runtime profiles do not accept AdditionalArguments.",
                    completed.stderr,
                )


if __name__ == "__main__":
    unittest.main()
