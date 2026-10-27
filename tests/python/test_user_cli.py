from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qwen_tts_bridge_worker import user_cli


class UserCliTests(unittest.TestCase):
    def test_design_resolves_explicit_model_and_invokes_existing_wav_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "модель")
            save_wav = _write_executable(root / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "qwen_tts_worker.exe")
            output = root / "голос.wav"

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                return_value=mock.Mock(returncode=0),
            ) as run:
                result = user_cli.main(
                    [
                        "design",
                        "--model",
                        str(model),
                        "--save-wav-executable",
                        str(save_wav),
                        "--worker",
                        str(worker),
                        "--text",
                        "Привет",
                        "--instruction",
                        "Мягкий женский голос",
                        "--out",
                        str(output),
                    ]
                )

            self.assertEqual(0, result)
            command = run.call_args.args[0]
            self.assertEqual(str(save_wav.resolve()), command[0])
            self.assertIn(str(model.resolve()), command)
            self.assertIn("Мягкий женский голос", command)

    def test_models_list_finds_portable_model_without_init(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            _write_model(package / "models" / "Qwen3-TTS-12Hz-1.7B-VoiceDesign")
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(package / "user")}):
                with mock.patch("builtins.print") as output:
                    result = user_cli.main(
                        ["--portable-root", str(package), "models", "list"]
                    )
            self.assertEqual(0, result)
            self.assertIn("voice-design", str(output.call_args_list))
            self.assertIn("portable", str(output.call_args_list))

    def test_design_resolves_relative_runtime_paths_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_directory = root / "настройки"
            config_directory.mkdir()
            model = _write_model(root / "models" / "voice-design")
            save_wav = _write_executable(root / "bin" / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "runtime" / "qwen_tts_worker.exe")
            config = config_directory / "qwen-tts.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "models": {"voice-design": {"path": "../models/voice-design"}},
                        "runtime": {
                            "save_wav_executable": "../bin/qwen_tts_save_wav.exe",
                            "worker": "../runtime/qwen_tts_worker.exe",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                return_value=mock.Mock(returncode=0),
            ) as run:
                result = user_cli.main(
                    [
                        "--config",
                        str(config),
                        "design",
                        "--text",
                        "Привет",
                        "--instruction",
                        "Спокойный голос",
                        "--out",
                        str(root / "voice.wav"),
                    ]
                )
            self.assertEqual(0, result)
            command = run.call_args.args[0]
            self.assertEqual(str(save_wav.resolve()), command[0])
            self.assertIn(str(worker.resolve()), command)
            self.assertIn(str(model.resolve()), command)

    def test_default_user_config_resolves_native_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "QwenTTSBridge" / "config.json"
            config.parent.mkdir()
            runtime = config.parent / "runtime"
            runtime.mkdir()
            (runtime / "qwen.dll").write_bytes(b"dll")
            models = config.parent / "models"
            models.mkdir()
            (models / "talker.gguf").write_bytes(b"talker")
            (models / "codec.gguf").write_bytes(b"codec")
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "native_profiles": {
                            "ru": {
                                "runtime_dir": "runtime",
                                "talker_model": "models/talker.gguf",
                                "codec_model": "models/codec.gguf",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(root)}):
                with mock.patch("builtins.print") as output:
                    result = user_cli.main(
                        ["models", "verify", "--native-profile", "ru"]
                    )
            self.assertEqual(0, result)
            self.assertIn('"valid": true', str(output.call_args_list))

    def test_relocated_package_discovers_model_without_repository_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "перенесённый пакет"
            site_packages = (
                package / "worker-python" / "python" / "Lib" / "site-packages"
            )
            source_package = (
                Path(__file__).resolve().parents[2]
                / "worker"
                / "src"
                / "qwen_tts_bridge_worker"
            )
            shutil.copytree(source_package, site_packages / source_package.name)
            _write_model(package / "models" / "Qwen3-TTS-12Hz-1.7B-VoiceDesign")
            elsewhere = root / "other-cwd"
            elsewhere.mkdir()
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(site_packages)
            environment["PYTHONIOENCODING"] = "utf-8"
            environment["PYTHONNOUSERSITE"] = "1"
            environment["QTB_PACKAGE_ROOT"] = str(package)
            environment["LOCALAPPDATA"] = str(root / "empty-user-config")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-P",
                    "-s",
                    "-m",
                    "qwen_tts_bridge_worker.user_cli",
                    "models",
                    "list",
                ],
                cwd=elsewhere,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("voice-design\tportable", completed.stdout)
            self.assertIn(str(package), completed.stdout)
            self.assertNotIn(str(source_package), completed.stdout + completed.stderr)


def _write_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"exe")
    return path


def _write_model(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "speech_tokenizer").mkdir()
    (root / "config.json").write_text(
        json.dumps(
            {
                "model_type": "qwen3_tts",
                "tts_model_type": "voice_design",
                "tts_model_size": "1b7",
            }
        ),
        encoding="utf-8",
    )
    for name in (
        "model.safetensors",
        "generation_config.json",
        "merges.txt",
        "preprocessor_config.json",
        "tokenizer_config.json",
        "vocab.json",
        "speech_tokenizer/config.json",
        "speech_tokenizer/model.safetensors",
        "speech_tokenizer/preprocessor_config.json",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"model")
    return root


if __name__ == "__main__":
    unittest.main()
