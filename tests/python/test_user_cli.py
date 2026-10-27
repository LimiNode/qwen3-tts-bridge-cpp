from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
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
                side_effect=_successful_synthesis,
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
                side_effect=_successful_synthesis,
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
            environment["PYTHONIOENCODING"] = "cp1252"
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
            self.assertIn(str(package.resolve()), completed.stdout)
            self.assertNotIn(str(source_package), completed.stdout + completed.stderr)

    def test_explicit_runtime_paths_fail_closed_before_portable_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fallback = _write_executable(root / "qwen_tts_save_wav.exe")
            missing = root / "missing.exe"
            with self.assertRaisesRegex(ValueError, "explicit.*was not found"):
                user_cli._resolve_executable(
                    missing, None, root, "qwen_tts_save_wav.exe"
                )
            with self.assertRaisesRegex(ValueError, "configured.*was not found"):
                user_cli._resolve_executable(
                    None, missing, root, "qwen_tts_save_wav.exe"
                )
            self.assertTrue(fallback.is_file())

            worker = root / "worker-python" / "python" / "python.exe"
            _write_executable(worker)
            with self.assertRaisesRegex(ValueError, "explicit worker.*was not found"):
                user_cli._resolve_worker(missing, None, root)
            with self.assertRaisesRegex(ValueError, "configured worker.*was not found"):
                user_cli._resolve_worker(None, missing, root)

    def test_portable_worker_does_not_fall_back_to_developer_python(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "portable worker.*was not found"):
                user_cli._resolve_worker(None, None, Path(temporary))

    def test_successful_subprocess_must_create_valid_wav_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model")
            save_wav = _write_executable(root / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "worker.exe")
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                return_value=mock.Mock(returncode=0),
            ):
                with self.assertRaises(SystemExit) as raised:
                    user_cli.main(
                        [
                            "design",
                            "--model",
                            str(model),
                            "--save-wav-executable",
                            str(save_wav),
                            "--worker",
                            str(worker),
                            "--text",
                            "Test",
                            "--instruction",
                            "Voice",
                            "--out",
                            str(root / "missing.wav"),
                        ]
                    )
            self.assertEqual(2, raised.exception.code)

    def test_play_help_names_default_application_not_native_playback(self) -> None:
        with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            with self.assertRaises(SystemExit) as raised:
                user_cli._build_parser().parse_args(["design", "--help"])
        self.assertEqual(0, raised.exception.code)
        self.assertIn("default application", output.getvalue())
        self.assertNotIn("--acceptance-mock-worker", output.getvalue())


def _write_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"exe")
    return path


def _successful_synthesis(command: list[str], **_kwargs: object) -> mock.Mock:
    output = Path(command[command.index("--output") + 1])
    result = Path(command[command.index("--result-json") + 1])
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x00\x00" * 16)
    result.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "terminal_state": "completed",
                "audio_chunks": 1,
                "audio_bytes": 32,
                "completion_metadata_received": True,
                "termination_reason": "eos",
                "hit_eos": True,
                "hit_max_seq_len": False,
                "hit_max_new_tokens": False,
            }
        ),
        encoding="utf-8",
    )
    return mock.Mock(returncode=0)


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
