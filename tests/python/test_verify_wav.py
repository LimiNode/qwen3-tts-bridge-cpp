from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path


class VerifyWavTests(unittest.TestCase):
    def test_unicode_path_is_reported_with_legacy_stdout_encoding(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        verifier = repository / "tests" / "python" / "verify_wav.py"
        with tempfile.TemporaryDirectory() as temporary:
            wav_path = Path(temporary) / "русский голос.wav"
            with wave.open(str(wav_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(b"\x00\x00" * 16)

            environment = os.environ.copy()
            environment["PYTHONIOENCODING"] = "ascii"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(verifier),
                    str(wav_path),
                    "--sample-rate",
                    "24000",
                    "--channels",
                    "1",
                    "--bits-per-sample",
                    "16",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn(str(wav_path), completed.stdout)


if __name__ == "__main__":
    unittest.main()
