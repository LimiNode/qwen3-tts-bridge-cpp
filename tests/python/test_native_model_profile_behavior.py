"""Behavioral checks for native model-profile fail-closed rules."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LAUNCHER = _ROOT / "scripts" / "start-native-play.ps1"


class NativeModelProfileBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("powershell") is None:
            raise unittest.SkipTest("Windows PowerShell is required")

    def run_launcher(
        self, config: dict[str, object], *extra: str
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "native-worker.local.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            command = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(_LAUNCHER),
                "-ConfigPath",
                str(config_path),
                *extra,
            ]
            return subprocess.run(
                command,
                cwd=_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

    @staticmethod
    def base_config() -> dict[str, object]:
        return {
            "player": "qwen_tts_play.exe",
            "worker": "qwen_tts_native_worker.exe",
            "runtime_dir": "runtime/qwentts-sm75",
        }

    def test_selected_profile_requires_each_native_model_field(self) -> None:
        config = self.base_config()
        config["model_profiles"] = {
            "ru-stress": {"codec_model": "common/codec.gguf"},
        }
        result = self.run_launcher(
            config,
            "-ModelProfile",
            "ru-stress",
            "-NoDownload",
            "-NoPlayback",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must define talker_model", result.stdout + result.stderr)

    def test_selected_profile_does_not_inherit_global_download_metadata(self) -> None:
        config = self.base_config()
        config["model_profiles"] = {
            "ru-stress": {
                "talker_model": "ru-stress/talker.gguf",
                "codec_model": "common/codec.gguf",
            },
        }
        config["model_download"] = {
            "talker_url": "https://example.invalid/base.gguf",
            "talker_sha256": "BASE",
            "codec_url": "https://example.invalid/base-codec.gguf",
            "codec_sha256": "BASE-CODEC",
        }
        result = self.run_launcher(config, "-ModelProfile", "ru-stress")

        self.assertNotEqual(0, result.returncode)
        output = result.stdout + result.stderr
        self.assertIn("no download URL was supplied", output)
        self.assertNotIn("example.invalid", output)


if __name__ == "__main__":
    unittest.main()
