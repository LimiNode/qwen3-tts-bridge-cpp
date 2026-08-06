"""Static contracts for the packaged playback launcher."""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LAUNCHER = _REPO_ROOT / "scripts" / "start-packaged-qwen-tts.ps1"
_PACKAGE_SCRIPT = _REPO_ROOT / "scripts" / "package-technical-beta.ps1"
_TEMPLATE = _REPO_ROOT / "config" / "packaged-runtime.local.example.json"


class PackagedLauncherContractTests(unittest.TestCase):
    def test_launcher_uses_private_runtime_and_external_user_config(self) -> None:
        script = _LAUNCHER.read_text(encoding="utf-8")

        self.assertIn(".qtb-technical-beta-root", script)
        self.assertIn("QwenTTSBridge\\runtime.local.json", script)
        self.assertIn("python\\python.exe", script)
        self.assertIn("qwen_tts_play.exe", script)
        self.assertIn("PYTHONHOME", script)
        self.assertIn("PYTHONPATH", script)
        self.assertIn("Assert-UserConfigPath", script)
        self.assertIn("Read-StrictConfig", script)
        self.assertIn("startup_timeout_ms", script)
        self.assertIn("--prefill-backend", script)
        self.assertIn('"eager"', script)
        self.assertNotIn("qwen_tts_worker.cmd", script)

    def test_package_stages_launcher_and_template(self) -> None:
        script = _PACKAGE_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("scripts/start-packaged-qwen-tts.ps1", script)
        self.assertIn("start-qwen-tts.ps1", script)
        self.assertIn("config/packaged-runtime.local.example.json", script)
        self.assertIn("config/runtime.local.example.json", script)

    def test_template_has_defaults_for_both_model_families(self) -> None:
        template = _TEMPLATE.read_text(encoding="utf-8")

        self.assertIn('"custom_voice_model_path"', template)
        self.assertIn('"base_model_path"', template)
        self.assertIn('"base_voice_id"', template)
        self.assertIn('"startup_timeout_ms": 180000', template)


if __name__ == "__main__":
    unittest.main()
