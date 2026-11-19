"""Behavioral checks for native model-profile fail-closed rules."""

from __future__ import annotations

import hashlib
import json
import os
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

    def run_relocated_bundle(
        self, *extra: str, corrupt_model: str = "", exit_code: int = 0
    ) -> tuple[subprocess.CompletedProcess[str], list[str] | None]:
        temporary_root = _ROOT / ".tmp" / "native-launcher-tests"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="bundle with spaces ", dir=temporary_root
        ) as temporary_directory:
            bundle = Path(temporary_directory)
            for name in ("scripts", "bin", "config", "models"):
                (bundle / name).mkdir()
            for name in ("start-native-play.ps1", "ensure-native-models.ps1"):
                shutil.copyfile(_ROOT / "scripts" / name, bundle / "scripts" / name)
            config = json.loads(
                (_ROOT / "config" / "native-package.example.json").read_text(
                    encoding="utf-8"
                )
            )
            config["player"] = "bin/capture.ps1"
            config["save_wav"] = "bin/capture.ps1"
            for profile in config["model_profiles"].values():
                for kind in ("talker", "codec"):
                    model = bundle / "models" / profile[f"{kind}_model"]
                    model.parent.mkdir(parents=True, exist_ok=True)
                    model.write_bytes(kind.encode("ascii"))
                    profile["model_download"][f"{kind}_sha256"] = hashlib.sha256(
                        kind.encode("ascii")
                    ).hexdigest()
            if corrupt_model:
                profile = config["model_profiles"]["ru-stress"]
                (bundle / "models" / profile[f"{corrupt_model}_model"]).write_bytes(
                    b"corrupt"
                )
            (bundle / "config" / "native-package.example.json").write_text(
                json.dumps(config, ensure_ascii=False), encoding="utf-8"
            )
            capture = bundle / "arguments.json"
            (bundle / "bin" / "capture.ps1").write_text(
                "[IO.File]::WriteAllText($env:QTB_LAUNCH_ARGS, "
                "(ConvertTo-Json -InputObject @($args)), "
                "[Text.UTF8Encoding]::new($false))\n"
                f"exit {exit_code}\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(bundle / "scripts" / "start-native-play.ps1"),
                    *extra,
                ],
                # The launch must not depend on the caller's checkout or cwd.
                cwd=bundle / "bin",
                env={**os.environ, "QTB_LAUNCH_ARGS": str(capture)},
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            arguments = (
                json.loads(capture.read_text(encoding="utf-8"))
                if capture.exists()
                else None
            )
            if arguments is not None:
                # Strip the disposable root to make portable-path expectations clear.
                arguments = [
                    value.replace(str(bundle), "<bundle>").replace("\\", "/")
                    for value in arguments
                ]
            return completed, arguments

    def test_relocated_package_defaults_and_unicode_wav_receipt(self) -> None:
        text = "За́мок у двери́. Вчера купил 2 книги."
        result, arguments = self.run_relocated_bundle(
            "-Offline", "-Text", text, "-Language", "russian", "-VoiceId", "robot",
            "-OutputWav", "speech.wav",
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIsNotNone(arguments)
        assert arguments is not None
        self.assertEqual(text, arguments[arguments.index("--text") + 1])
        self.assertEqual("russian", arguments[arguments.index("--language") + 1])
        self.assertIn("--tts-front-explicit-stress", arguments)
        self.assertIn("--require-natural-eos", arguments)
        self.assertIn("speech.wav.result.json", arguments)
        self.assertIn("robot", arguments)
        self.assertIn("<bundle>/bin/qwen_tts_native_worker.exe", arguments)
        self.assertIn(
            "<bundle>/models/ru-stress/qwen-talker-1.7b-ru-stress-Q8_0.gguf",
            arguments,
        )
        self.assertNotIn("--no-playback", arguments)

    def test_relocated_package_base_and_raw_opt_out(self) -> None:
        for profile, no_front in (("base", False), ("ru-stress", True)):
            with self.subTest(profile=profile, no_front=no_front):
                extra = ["-NoTtsFront"] if no_front else []
                result, arguments = self.run_relocated_bundle(
                    "-Offline", "-ModelProfile", profile, "-Text", "2 книги",
                    "-NoPlayback", *extra,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                assert arguments is not None
                self.assertNotIn("--tts-front-explicit-stress", arguments)
                self.assertEqual(no_front, "--no-tts-front" in arguments)
                self.assertEqual("2 книги", arguments[arguments.index("--text") + 1])
                self.assertIn("--no-playback", arguments)

    def test_relocated_package_rejects_wrong_hash_even_with_no_download(self) -> None:
        for kind in ("talker", "codec"):
            with self.subTest(model=kind):
                result, arguments = self.run_relocated_bundle(
                    "-NoDownload", "-Text", "test", corrupt_model=kind,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIsNone(arguments)
                self.assertIn("SHA-256 does not match", result.stdout + result.stderr)

    def test_relocated_package_base_rejects_explicit_stress(self) -> None:
        result, arguments = self.run_relocated_bundle(
            "-Offline", "-ModelProfile", "base", "-Text", "За́мок",
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIsNone(arguments)
        self.assertIn("Explicit U+0301 stress requires", result.stdout + result.stderr)

    def test_relocated_package_propagates_executable_failure(self) -> None:
        result, _ = self.run_relocated_bundle(
            "-Offline", "-Text", "test", exit_code=17,
        )
        self.assertEqual(17, result.returncode)


if __name__ == "__main__":
    unittest.main()
