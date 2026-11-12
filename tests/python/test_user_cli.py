from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, BinaryIO, cast
from unittest import mock

from qwen_tts_bridge_worker import user_cli


class UserCliTests(unittest.TestCase):
    def test_synthesis_commands_forward_cmp50hx_dtype_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="voice_design")
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_synthesis,
            ) as run:
                self.assertEqual(
                    0,
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
                            str(root / "default.wav"),
                        ]
                    ),
                )
            worker_args = _worker_argument_values(run.call_args.args[0])
            self.assertEqual("float16", worker_args[worker_args.index("--dtype") + 1])

            config = root / "config.json"
            config.write_text(
                json.dumps({"schema_version": 1, "runtime": {"dtype": "bfloat16"}}),
                encoding="utf-8",
            )
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_synthesis,
            ) as run:
                self.assertEqual(
                    0,
                    user_cli.main(
                        [
                            "--config",
                            str(config),
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
                            str(root / "configured.wav"),
                        ]
                    ),
                )
            worker_args = _worker_argument_values(run.call_args.args[0])
            self.assertEqual("bfloat16", worker_args[worker_args.index("--dtype") + 1])

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_synthesis,
            ) as run:
                self.assertEqual(
                    0,
                    user_cli.main(
                        [
                            "--config",
                            str(config),
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
                            "--dtype",
                            "float32",
                            "--out",
                            str(root / "explicit.wav"),
                        ]
                    ),
                )
            worker_args = _worker_argument_values(run.call_args.args[0])
            self.assertEqual("float32", worker_args[worker_args.index("--dtype") + 1])

    def test_synthesis_rejects_unsupported_dtype(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model")
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            with redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as error:
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
                            "--dtype",
                            "int8",
                            "--out",
                            str(root / "voice.wav"),
                        ]
                    )
            self.assertEqual(2, error.exception.code)
            self.assertIn("--dtype", stderr.getvalue())

    def test_voices_create_generates_and_registers_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="voice_design")
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "voice_library": {"registry_path": "voices/registry.json"},
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_voice_creation,
            ) as run, redirect_stdout(io.StringIO()) as stdout:
                result = user_cli.main(
                    [
                        "--config",
                        str(config),
                        "voices",
                        "create",
                        "--id",
                        "calm",
                        "--instruction",
                        "A calm warm voice.",
                        "--sample-text",
                        "This is the reference.",
                        "--acceptance-mock-worker",
                        "--model",
                        str(model),
                        "--save-wav-executable",
                        str(save_wav),
                        "--worker",
                        str(worker),
                    ]
                )

            self.assertEqual(0, result)
            self.assertEqual(1, run.call_count)
            worker_arguments = _worker_argument_values(run.call_args.args[0])
            self.assertEqual(
                "75", worker_arguments[worker_arguments.index("--chunks") + 1]
            )
            registry = root / "voices" / "registry.json"
            rows = json.loads(registry.read_text(encoding="utf-8"))["voices"]
            self.assertEqual("calm", rows[0]["voice_id"])
            self.assertEqual("voices create", rows[0]["provenance"]["operation"])
            self.assertEqual("A calm warm voice.", rows[0]["provenance"]["instruction"])
            self.assertEqual(
                "This is the reference.", rows[0]["provenance"]["reference_text"]
            )
            self.assertNotIn("source_reference_audio_path", rows[0])
            self.assertEqual("Russian", rows[0]["provenance"]["language"])
            self.assertIsNone(rows[0]["provenance"]["model_revision"])
            self.assertEqual(
                rows[0]["reference_audio_sha256"],
                rows[0]["provenance"]["reference_audio_sha256"],
            )
            self.assertEqual(
                "eos", rows[0]["provenance"]["generation"]["termination_reason"]
            )
            self.assertNotIn("Wrote VoiceDesign WAV:", stdout.getvalue())

            verify = user_cli.main(
                [
                    "--config",
                    str(config),
                    "voices",
                    "verify",
                    "calm",
                    "--backend",
                    "python",
                ]
            )
            self.assertEqual(0, verify)

            base_model = _write_model(root / "base-model", model_type="base")
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_synthesis,
            ):
                self.assertEqual(
                    0,
                    user_cli.main(
                        [
                            "--config",
                            str(config),
                            "synth",
                            "--model",
                            str(base_model),
                            "--voice-id",
                            "calm",
                            "--save-wav-executable",
                            str(save_wav),
                            "--worker",
                            str(worker),
                            "--text",
                            "Reuse this voice.",
                            "--out",
                            str(root / "reused.wav"),
                        ]
                    ),
                )

    def test_voices_create_rejects_duplicate_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _ = _write_voice_library(root, voice_id="calm")
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run"
            ) as run, redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    user_cli.main(
                        [
                            "--config",
                            str(config),
                            "voices",
                            "create",
                            "--id",
                            "calm",
                            "--instruction",
                            "A calm voice.",
                            "--sample-text",
                            "Reference",
                            "--model",
                            str(root / "missing-model"),
                        ]
                    )
            self.assertEqual(2, raised.exception.code)
            self.assertIn("voice_id already exists", stderr.getvalue())
            run.assert_not_called()

    def test_voices_create_rejects_log_file_registry_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, registry = _write_voice_library(root, voice_id="existing")
            model = _write_model(root / "model", model_type="voice_design")
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            (root / "logs").mkdir()
            aliased_registry = root / "logs" / ".." / "voices" / "registry.json"
            original_registry = registry.read_bytes()
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run"
            ) as run, redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    user_cli.main(
                        [
                            "--config",
                            str(config),
                            "voices",
                            "create",
                            "--id",
                            "new-voice",
                            "--instruction",
                            "A new voice.",
                            "--sample-text",
                            "Reference",
                            "--model",
                            str(model),
                            "--save-wav-executable",
                            str(save_wav),
                            "--worker",
                            str(worker),
                            "--log-file",
                            str(aliased_registry),
                        ]
                    )
            self.assertEqual(2, raised.exception.code)
            self.assertIn("voice registry", stderr.getvalue())
            self.assertEqual(original_registry, registry.read_bytes())
            run.assert_not_called()

    def test_voices_create_generation_failure_does_not_publish_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="voice_design")
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "voice_library": {"registry_path": "voices/registry.json"},
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                return_value=mock.Mock(returncode=17),
            ) as run:
                result = user_cli.main(
                    [
                        "--config",
                        str(config),
                        "voices",
                        "create",
                        "--id",
                        "failed",
                        "--instruction",
                        "A failed voice.",
                        "--sample-text",
                        "Reference",
                        "--model",
                        str(model),
                        "--save-wav-executable",
                        str(save_wav),
                        "--worker",
                        str(worker),
                    ]
                )
            self.assertEqual(17, result)
            self.assertFalse((root / "voices" / "registry.json").exists())
            run.assert_called_once()

    def test_voices_create_invalid_reference_does_not_publish_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="voice_design")
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "voice_library": {"registry_path": "voices/registry.json"},
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_invalid_voice_creation,
            ):
                with self.assertRaises(SystemExit) as raised:
                    user_cli.main(
                        [
                            "--config",
                            str(config),
                            "voices",
                            "create",
                            "--id",
                            "invalid",
                            "--instruction",
                            "An invalid voice.",
                            "--sample-text",
                            "Reference",
                            "--model",
                            str(model),
                            "--save-wav-executable",
                            str(save_wav),
                            "--worker",
                            str(worker),
                        ]
                    )
            self.assertEqual(2, raised.exception.code)
            self.assertFalse((root / "voices" / "registry.json").exists())

    def test_voices_create_rejects_non_natural_eos_opt_out(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="voice_design")
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "voice_library": {"registry_path": "voices/registry.json"},
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run"
            ) as run, redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    user_cli.main(
                        [
                            "--config",
                            str(config),
                            "voices",
                            "create",
                            "--id",
                            "diagnostic-only",
                            "--instruction",
                            "A diagnostic voice.",
                            "--sample-text",
                            "Reference",
                            "--allow-non-natural-eos",
                            "--model",
                            str(model),
                            "--save-wav-executable",
                            str(save_wav),
                            "--worker",
                            str(worker),
                        ]
                    )
            self.assertEqual(2, raised.exception.code)
            self.assertIn("strict natural-EOS", stderr.getvalue())
            run.assert_not_called()

    def test_voices_create_publication_failure_does_not_leave_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="voice_design")
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "voice_library": {"registry_path": "voices/registry.json"},
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_voice_creation,
            ), mock.patch(
                "qwen_tts_bridge_worker.user_cli.add_voice",
                side_effect=user_cli.VoiceLibraryError("publication failed"),
            ):
                with self.assertRaises(SystemExit) as raised:
                    user_cli.main(
                        [
                            "--config",
                            str(config),
                            "voices",
                            "create",
                            "--id",
                            "publication-failure",
                            "--instruction",
                            "A publication failure voice.",
                            "--sample-text",
                            "Reference",
                            "--model",
                            str(model),
                            "--save-wav-executable",
                            str(save_wav),
                            "--worker",
                            str(worker),
                        ]
                    )
            self.assertEqual(2, raised.exception.code)
            self.assertFalse((root / "voices" / "registry.json").exists())

    def test_play_uses_existing_streaming_player_and_is_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            player = _write_executable(root / "bin" / "qwen_tts_play.exe")
            worker = _write_executable(root / "bin" / "worker.exe")
            config, registry = _write_voice_library(
                root,
                voice_id="voice",
                extra_config={"runtime": {"device": "cuda:0"}},
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                return_value=mock.Mock(returncode=0),
            ) as run:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = user_cli.main(
                        [
                            "--config",
                            str(config),
                            "play",
                            "--voice-id",
                            "voice",
                            "--text",
                            "Test playback",
                            "--model",
                            str(model),
                            "--play-executable",
                            str(player),
                            "--worker",
                            str(worker),
                            "--request-timeout-ms",
                            "12345",
                            "--device",
                            "cuda:1",
                        ]
                    )

            self.assertEqual(0, result)
            self.assertEqual("", stdout.getvalue())
            self.assertEqual("", stderr.getvalue())
            command = run.call_args.args[0]
            self.assertEqual(str(player.resolve()), command[0])
            self.assertEqual("voice", command[command.index("--voice-id") + 1])
            self.assertEqual(
                "12345", command[command.index("--request-timeout-ms") + 1]
            )
            self.assertNotIn("--allow-non-natural-eos", command)
            worker_args = _worker_argument_values(command)
            self.assertEqual("qwen", worker_args[0])
            self.assertIn("--collect-generation-trace", worker_args)
            self.assertEqual("cuda:1", worker_args[worker_args.index("--device") + 1])
            self.assertEqual(
                str(registry.resolve()),
                worker_args[worker_args.index("--voice-registry-path") + 1],
            )

    def test_play_failure_preserves_bounded_diagnostics_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            player = _write_executable(root / "player.exe")
            worker = _write_executable(root / "worker.exe")
            config, _ = _write_voice_library(root, voice_id="voice")

            def failed_play(command: list[str], **kwargs: object) -> mock.Mock:
                stream = cast(BinaryIO, kwargs["stdout"])
                stream.write(b"player failure\\n")
                return mock.Mock(returncode=19)

            stderr = io.StringIO()
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=failed_play,
            ):
                with redirect_stderr(stderr):
                    result = user_cli.main(
                        [
                            "--config",
                            str(config),
                            "play",
                            "--voice-id",
                            "voice",
                            "--text",
                            "Test playback",
                            "--model",
                            str(model),
                            "--play-executable",
                            str(player),
                            "--worker",
                            str(worker),
                        ]
                    )
            self.assertEqual(19, result)
            self.assertIn("Playback failed", stderr.getvalue())
            self.assertIn("player failure", stderr.getvalue())

    def test_play_allows_explicit_non_natural_eos_diagnostic_opt_out(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            player = _write_executable(root / "player.exe")
            worker = _write_executable(root / "worker.exe")
            config, _ = _write_voice_library(root, voice_id="voice")
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                return_value=mock.Mock(returncode=0),
            ) as run:
                self.assertEqual(
                    0,
                    user_cli.main(
                        [
                            "--config",
                            str(config),
                            "play",
                            "--voice-id",
                            "voice",
                            "--text",
                            "Test",
                            "--model",
                            str(model),
                            "--play-executable",
                            str(player),
                            "--worker",
                            str(worker),
                            "--allow-non-natural-eos",
                        ]
                    ),
                )
            self.assertIn("--allow-non-natural-eos", run.call_args.args[0])

    def test_synth_uses_base_model_registered_voice_and_authoritative_registry(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "модель Base", model_type="base")
            save_wav = _write_executable(root / "bin" / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "bin" / "qwen_tts_worker.exe")
            config, registry = _write_voice_library(root, voice_id="крафтверк-ru")
            registry_before = registry.read_bytes()
            output = root / "результат" / "речь.wav"

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_synthesis,
            ) as run:
                result = user_cli.main(
                    [
                        "--config",
                        str(config),
                        "synth",
                        "--voice-id",
                        "крафтверк-ru",
                        "--text",
                        "Привет! Это проверка синтеза речи.",
                        "--language",
                        "Russian",
                        "--model",
                        str(model),
                        "--save-wav-executable",
                        str(save_wav),
                        "--worker",
                        str(worker),
                        "--out",
                        str(output),
                    ]
                )

            self.assertEqual(0, result)
            command = run.call_args.args[0]
            self.assertEqual(
                "крафтверк-ru", command[command.index("--voice-id") + 1]
            )
            worker_args = _worker_argument_values(command)
            self.assertEqual("qwen", worker_args[0])
            self.assertEqual(
                str(model.resolve()), worker_args[worker_args.index("--model-path") + 1]
            )
            self.assertEqual(
                str(registry.resolve()),
                worker_args[worker_args.index("--voice-registry-path") + 1],
            )
            self.assertIn("--collect-generation-trace", worker_args)
            self.assertIn("--require-natural-eos", command)
            self.assertEqual(registry_before, registry.read_bytes())

    def test_synth_uses_configured_base_model_and_timeout_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "models" / "base", model_type="base")
            save_wav = _write_executable(root / "bin" / "save.exe")
            worker = _write_executable(root / "bin" / "worker.exe")
            config, _ = _write_voice_library(
                root,
                voice_id="voice",
                extra_config={
                    "models": {"base-1.7b": {"path": "models/base"}},
                    "runtime": {
                        "save_wav_executable": str(save_wav),
                        "worker": str(worker),
                        "device": "cuda:1",
                        "startup_timeout_ms": 180000,
                        "request_timeout_ms": 600000,
                    },
                },
            )
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_synthesis,
            ) as run:
                result = user_cli.main(
                    [
                        "--config",
                        str(config),
                        "synth",
                        "--voice-id",
                        "voice",
                        "--text",
                        "Test",
                        "--out",
                        str(root / "speech.wav"),
                        "--request-timeout-ms",
                        "720000",
                    ]
                )

            self.assertEqual(0, result)
            command = run.call_args.args[0]
            self.assertEqual(
                "180000", command[command.index("--startup-timeout-ms") + 1]
            )
            self.assertEqual(
                "720000", command[command.index("--request-timeout-ms") + 1]
            )
            self.assertIn(str(model.resolve()), _worker_argument_values(command))
            worker_args = _worker_argument_values(command)
            self.assertEqual("cuda:1", worker_args[worker_args.index("--device") + 1])

    def test_synth_cli_device_overrides_configured_device(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_model(root / "models" / "base", model_type="base")
            save_wav = _write_executable(root / "bin" / "save.exe")
            worker = _write_executable(root / "bin" / "worker.exe")
            config, _ = _write_voice_library(
                root,
                voice_id="voice",
                extra_config={
                    "models": {"base-1.7b": {"path": "models/base"}},
                    "runtime": {
                        "save_wav_executable": str(save_wav),
                        "worker": str(worker),
                        "device": "cuda:0",
                    },
                },
            )
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_synthesis,
            ) as run:
                result = user_cli.main(
                    [
                        "--config",
                        str(config),
                        "synth",
                        "--voice-id",
                        "voice",
                        "--text",
                        "Test",
                        "--out",
                        str(root / "speech.wav"),
                        "--device",
                        "cuda:1",
                    ]
                )

            self.assertEqual(0, result)
            worker_args = _worker_argument_values(run.call_args.args[0])
            self.assertEqual("cuda:1", worker_args[worker_args.index("--device") + 1])

    def test_design_forwards_explicit_device(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model")
            save_wav = _write_executable(root / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "worker.exe")
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
                        "Test",
                        "--instruction",
                        "Voice",
                        "--out",
                        str(root / "voice.wav"),
                        "--device",
                        "cuda:1",
                    ]
                )

            self.assertEqual(0, result)
            worker_args = _worker_argument_values(run.call_args.args[0])
            self.assertEqual("cuda:1", worker_args[worker_args.index("--device") + 1])

    def test_design_uses_configured_device_when_cli_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model")
            save_wav = _write_executable(root / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "worker.exe")
            config, _ = _write_voice_library(
                root,
                voice_id="voice",
                extra_config={"runtime": {"device": "cuda:2"}},
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
                        str(root / "voice.wav"),
                    ]
                )

            self.assertEqual(0, result)
            worker_args = _worker_argument_values(run.call_args.args[0])
            self.assertEqual("cuda:2", worker_args[worker_args.index("--device") + 1])

    def test_device_rejects_blank_cli_and_config_values(self) -> None:
        with self.assertRaisesRegex(ValueError, r"--device must be a non-empty"):
            user_cli._resolve_device("  ", None)
        with self.assertRaisesRegex(
            ValueError, r"runtime\.device must be a non-empty"
        ):
            user_cli._resolve_device(None, "")

    def test_synth_resolves_base_model_from_portable_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "portable package"
            model = _write_model(
                package / "models" / "Qwen3-TTS-12Hz-1.7B-Base", model_type="base"
            )
            save_wav = _write_executable(package / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "worker.exe")
            config, _ = _write_voice_library(root, voice_id="voice")
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_synthesis,
            ) as run:
                result = user_cli.main(
                    [
                        "--config",
                        str(config),
                        "--portable-root",
                        str(package),
                        "synth",
                        "--voice-id",
                        "voice",
                        "--text",
                        "Test",
                        "--worker",
                        str(worker),
                        "--out",
                        str(root / "speech.wav"),
                    ]
                )
            self.assertEqual(0, result)
            self.assertEqual(str(save_wav.resolve()), run.call_args.args[0][0])
            self.assertIn(
                str(model.resolve()), _worker_argument_values(run.call_args.args[0])
            )

    def test_synth_rejects_missing_and_python_incompatible_voices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            save_wav = _write_executable(root / "save.exe")
            worker = _write_executable(root / "worker.exe")
            config, registry = _write_voice_library(root, voice_id="voice")
            common = [
                "--config",
                str(config),
                "synth",
                "--text",
                "Test",
                "--model",
                str(model),
                "--save-wav-executable",
                str(save_wav),
                "--worker",
                str(worker),
                "--out",
                str(root / "speech.wav"),
            ]
            with self.assertRaises(SystemExit) as missing:
                user_cli.main(common + ["--voice-id", "missing"])
            self.assertEqual(2, missing.exception.code)

            row = json.loads(registry.read_text(encoding="utf-8"))["voices"][0]
            managed_wav = registry.parent / row["reference_audio_path"]
            managed_wav.write_bytes(b"corrupt")
            with self.assertRaises(SystemExit) as incompatible:
                user_cli.main(common + ["--voice-id", "voice"])
            self.assertEqual(2, incompatible.exception.code)

    def test_synth_rejects_missing_or_invalid_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "voice_library": {"registry_path": "voices/registry.json"},
                    }
                ),
                encoding="utf-8",
            )
            arguments = [
                "--config",
                str(config),
                "synth",
                "--voice-id",
                "voice",
                "--text",
                "Test",
                "--out",
                str(root / "speech.wav"),
            ]
            with self.assertRaises(SystemExit) as missing:
                user_cli.main(arguments)
            self.assertEqual(2, missing.exception.code)

            registry = root / "voices" / "registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text("not json", encoding="utf-8")
            with self.assertRaises(SystemExit) as invalid:
                user_cli.main(arguments)
            self.assertEqual(2, invalid.exception.code)

    def test_all_output_routes_preserve_protected_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, registry = _write_voice_library(root, voice_id="voice")
            row = json.loads(registry.read_text(encoding="utf-8"))["voices"][0]
            managed = registry.parent / row["reference_audio_path"]
            model = _write_model(root / "model", model_type="voice_design")
            executable = _write_executable(root / "client.exe")
            worker = _write_executable(root / "worker.exe")
            output = root / "previous.wav"
            output.write_bytes(b"preserve previous output")
            nested = root / "aliases"
            nested.mkdir()
            common = [
                "--model", str(model), "--worker", str(worker),
            ]
            routes = {
                "synth": [
                    "synth", "--model-family", "voice-design",
                    "--instruction", "Voice", "--text", "Test",
                    "--out", str(output), "--save-wav-executable",
                    str(executable), *common,
                ],
                "design": [
                    "design", "--instruction", "Voice", "--text", "Test",
                    "--out", str(output), "--save-wav-executable",
                    str(executable), *common,
                ],
                "play": [
                    "play", "--model-family", "voice-design",
                    "--instruction", "Voice", "--text", "Test",
                    "--out", str(output), "--play-executable",
                    str(executable), *common,
                ],
                "create": [
                    "voices", "create", "--id", "new",
                    "--instruction", "Voice", "--sample-text", "Test",
                    "--save-wav-executable", str(executable), *common,
                ],
            }
            expected = {
                path: path.read_bytes()
                for path in root.rglob("*") if path.is_file()
            }
            for route, arguments in routes.items():
                flags = ["--log-file"]
                if route != "create":
                    flags.append("--out")
                if route in {"synth", "design"}:
                    flags.append("--result-json")
                for flag in flags:
                    for target in (config, registry, managed):
                        with self.subTest(route=route, flag=flag, target=target):
                            # Existing intermediate directory, canonical .. alias.
                            alias = target.parent / "alias-dir"
                            alias.mkdir(exist_ok=True)
                            spelling = alias / ".." / target.name
                            command = list(arguments)
                            if flag in command:
                                command[command.index(flag) + 1] = str(spelling)
                            else:
                                command.extend((flag, str(spelling)))
                            with mock.patch.object(
                                user_cli.subprocess, "run"
                            ) as run, redirect_stderr(io.StringIO()) as stderr:
                                with self.assertRaises(SystemExit) as raised:
                                    user_cli.main(
                                        ["--config", str(config), *command]
                                    )
                            self.assertEqual(2, raised.exception.code)
                            self.assertIn("protected file", stderr.getvalue())
                            run.assert_not_called()
                            self.assertEqual(
                                expected,
                                {
                                    path: path.read_bytes()
                                    for path in root.rglob("*") if path.is_file()
                                },
                            )

    def test_voices_add_preserves_config_registry_and_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, registry = _write_voice_library(root, voice_id="voice")
            source = root / "reference.wav"
            source.write_bytes(b"source must not be overwritten")
            for target in ("config.json", "reference.wav"):
                payload = json.loads(config.read_text(encoding="utf-8"))
                payload["voice_library"]["registry_path"] = target
                config.write_text(json.dumps(payload), encoding="utf-8")
                expected = {
                    path: path.read_bytes()
                    for path in root.rglob("*") if path.is_file()
                }
                with self.subTest(target=target), mock.patch.object(
                    user_cli, "add_voice"
                ) as add, mock.patch.object(
                    user_cli.subprocess, "run"
                ) as run, redirect_stderr(io.StringIO()) as stderr:
                    with self.assertRaises(SystemExit) as raised:
                        user_cli.main([
                            "--config", str(config), "voices", "add",
                            "--id", "new", "--wav", str(source), "--text", "Test",
                        ])
                self.assertEqual(2, raised.exception.code)
                self.assertIn("protected file", stderr.getvalue())
                add.assert_not_called()
                run.assert_not_called()
                self.assertEqual(
                    expected,
                    {
                        path: path.read_bytes()
                        for path in root.rglob("*") if path.is_file()
                    },
                )

    def test_output_routes_fail_closed_for_invalid_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, registry = _write_voice_library(root, voice_id="voice")
            model = _write_model(root / "model", model_type="voice_design")
            executable = _write_executable(root / "client.exe")
            worker = _write_executable(root / "worker.exe")
            output = root / "previous.wav"
            output.write_bytes(b"previous output")
            routes = (
                ["design", "--instruction", "Voice",
                 "--save-wav-executable", str(executable)],
                ["synth", "--model-family", "voice-design",
                 "--instruction", "Voice",
                 "--save-wav-executable", str(executable)],
                ["play", "--model-family", "voice-design",
                 "--instruction", "Voice",
                 "--play-executable", str(executable)],
            )
            registry.write_bytes(b"not a valid registry")
            expected = {
                path: path.read_bytes()
                for path in root.rglob("*") if path.is_file()
            }
            for arguments in routes:
                with self.subTest(route=arguments[0]), mock.patch.object(
                    user_cli.subprocess, "run"
                ) as run, redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        user_cli.main([
                            "--config", str(config), *arguments,
                            "--model", str(model), "--worker", str(worker),
                            "--text", "Test", "--out", str(output),
                        ])
                self.assertEqual(2, raised.exception.code)
                run.assert_not_called()
                self.assertEqual(
                    expected,
                    {
                        path: path.read_bytes()
                        for path in root.rglob("*") if path.is_file()
                    },
                )
            with mock.patch.object(
                user_cli, "load_voice_rows", side_effect=PermissionError("denied")
            ), self.assertRaises(PermissionError):
                user_cli._managed_reference_paths(registry)

    def test_voices_create_rejects_config_registry_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            config.write_text(
                json.dumps({
                    "schema_version": 1,
                    "voice_library": {"registry_path": "config.json"},
                    "voices": [],
                }), encoding="utf-8",
            )
            before = config.read_bytes()
            with mock.patch.object(
                user_cli.subprocess, "run"
            ) as run, mock.patch.object(
                user_cli, "add_voice"
            ) as add, redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    user_cli.main([
                        "--config", str(config), "voices", "create",
                        "--id", "voice", "--instruction", "Voice",
                        "--sample-text", "Test",
                    ])
            self.assertEqual(2, raised.exception.code)
            self.assertIn("protected file", stderr.getvalue())
            self.assertEqual(before, config.read_bytes())
            run.assert_not_called()
            add.assert_not_called()

    def test_synth_explicit_model_executable_and_worker_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            save_wav = _write_executable(root / "save.exe")
            worker = _write_executable(root / "worker.exe")
            config, _ = _write_voice_library(root, voice_id="voice")
            common = [
                "--config",
                str(config),
                "synth",
                "--voice-id",
                "voice",
                "--text",
                "Test",
                "--out",
                str(root / "speech.wav"),
            ]
            cases = (
                ("--model", root / "missing-model"),
                ("--save-wav-executable", root / "missing-save.exe"),
                ("--worker", root / "missing-worker.exe"),
            )
            required = {
                "--model": [
                    "--save-wav-executable",
                    str(save_wav),
                    "--worker",
                    str(worker),
                ],
                "--save-wav-executable": [
                    "--model",
                    str(model),
                    "--worker",
                    str(worker),
                ],
                "--worker": [
                    "--model",
                    str(model),
                    "--save-wav-executable",
                    str(save_wav),
                ],
            }
            for option, missing_path in cases:
                with self.subTest(option=option):
                    with self.assertRaises(SystemExit) as raised:
                        user_cli.main(
                            common
                            + required[option]
                            + [option, str(missing_path)]
                        )
                    self.assertEqual(2, raised.exception.code)

    def test_synth_natural_eos_is_default_and_opt_out_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            save_wav = _write_executable(root / "save.exe")
            worker = _write_executable(root / "worker.exe")
            config, _ = _write_voice_library(root, voice_id="voice")
            arguments = [
                "--config",
                str(config),
                "synth",
                "--voice-id",
                "voice",
                "--text",
                "Test",
                "--model",
                str(model),
                "--save-wav-executable",
                str(save_wav),
                "--worker",
                str(worker),
                "--out",
                str(root / "speech.wav"),
            ]
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_non_natural_synthesis,
            ):
                with self.assertRaises(SystemExit) as natural_eos:
                    user_cli.main(arguments)
            self.assertEqual(2, natural_eos.exception.code)

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_non_natural_synthesis,
            ) as run:
                result = user_cli.main(arguments + ["--allow-non-natural-eos"])
            self.assertEqual(0, result)
            self.assertNotIn("--require-natural-eos", run.call_args.args[0])

    def test_synth_failure_preserves_existing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            save_wav = _write_executable(root / "save.exe")
            worker = _write_executable(root / "worker.exe")
            config, _ = _write_voice_library(root, voice_id="voice")
            output = root / "speech.wav"
            receipt = root / "speech.json"
            output.write_bytes(b"previous wav")
            receipt.write_text('{"previous": true}', encoding="utf-8")
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                return_value=mock.Mock(returncode=23),
            ):
                result = user_cli.main(
                    [
                        "--config",
                        str(config),
                        "synth",
                        "--voice-id",
                        "voice",
                        "--text",
                        "Test",
                        "--model",
                        str(model),
                        "--save-wav-executable",
                        str(save_wav),
                        "--worker",
                        str(worker),
                        "--out",
                        str(output),
                        "--result-json",
                        str(receipt),
                    ]
                )
            self.assertEqual(23, result)
            self.assertEqual(b"previous wav", output.read_bytes())
            self.assertEqual('{"previous": true}', receipt.read_text())

    def test_synthesis_is_quiet_by_default_and_writes_complete_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            save_wav = _write_executable(root / "save.exe")
            worker = _write_executable(root / "worker.exe")
            config, _ = _write_voice_library(root, voice_id="voice")
            log_file = root / "logs" / "synth.log"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_diagnostic_success,
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = user_cli.main(
                        [
                            "--config",
                            str(config),
                            "synth",
                            "--voice-id",
                            "voice",
                            "--text",
                            "Test",
                            "--model",
                            str(model),
                            "--save-wav-executable",
                            str(save_wav),
                            "--worker",
                            str(worker),
                            "--out",
                            str(root / "speech.wav"),
                            "--log-file",
                            str(log_file),
                        ]
                    )

            self.assertEqual(0, result)
            self.assertIn("Wrote Base voice WAV:", stdout.getvalue())
            self.assertEqual("", stderr.getvalue())
            log_text = log_file.read_text(encoding="utf-8")
            self.assertIn('qtb_metric {"event":"worker_loaded"}', log_text)
            self.assertIn("worker предупреждение", log_text)

    def test_verbose_replays_diagnostics_and_failure_hides_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            save_wav = _write_executable(root / "save.exe")
            worker = _write_executable(root / "worker.exe")
            config, _ = _write_voice_library(root, voice_id="voice")
            common = [
                "--config",
                str(config),
                "synth",
                "--voice-id",
                "voice",
                "--text",
                "Test",
                "--model",
                str(model),
                "--save-wav-executable",
                str(save_wav),
                "--worker",
                str(worker),
                "--out",
                str(root / "speech.wav"),
            ]
            verbose_stderr = io.StringIO()
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_diagnostic_success,
            ):
                with redirect_stderr(verbose_stderr):
                    self.assertEqual(0, user_cli.main(common + ["--verbose"]))
            self.assertIn("qtb_metric", verbose_stderr.getvalue())
            self.assertIn("worker предупреждение", verbose_stderr.getvalue())

            failure_stderr = io.StringIO()
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_diagnostic_failure,
            ):
                with redirect_stderr(failure_stderr):
                    self.assertEqual(17, user_cli.main(common))
            self.assertIn("exit code 17", failure_stderr.getvalue())
            self.assertIn("worker failure", failure_stderr.getvalue())
            self.assertNotIn("qtb_metric", failure_stderr.getvalue())

    def test_verbose_diagnostics_stream_in_bounded_utf8_chunks(self) -> None:
        payload = b"a" * 4095 + "Живой поток\n".encode("utf-8")
        stream = _BoundedReadStream(payload)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            user_cli._emit_diagnostics(stream)
        self.assertEqual(payload.decode("utf-8"), stderr.getvalue())
        self.assertTrue(stream.read_sizes)
        self.assertTrue(all(size == 4096 for size in stream.read_sizes[:-1]))

    def test_failure_tail_keeps_errors_after_many_metrics_with_bounded_memory(
        self,
    ) -> None:
        payload = (
            b"model_error: CUDA allocation failed\n"
            + b'qtb_metric {"event":"cleanup"}\n' * 2000
            + b"ordinary qtb_metric marker\n"
            + b"warning: invalid byte \xff\n"
        )
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            user_cli._emit_failure_diagnostics(23, _BoundedReadStream(payload))
        output = stderr.getvalue()
        self.assertIn("exit code 23", output)
        self.assertIn("model_error: CUDA allocation failed", output)
        self.assertIn("ordinary qtb_metric marker", output)
        self.assertIn("warning: invalid byte �", output)
        self.assertNotIn('qtb_metric {"event":"cleanup"}', output)
        self.assertLess(len(output.encode("utf-8")), 9 * 1024)

    def test_failure_tail_bounds_long_invalid_utf8_line_in_bytes(self) -> None:
        payload = b"\xff" * (user_cli._DIAGNOSTIC_LINE_BYTES + 1024) + b"\n"
        text = user_cli._collect_failure_diagnostics(_BoundedReadStream(payload))

        self.assertLessEqual(
            len(text.encode("utf-8")) + 1,
            user_cli._DIAGNOSTIC_TAIL_BYTES,
        )
        self.assertIn("tail truncated", text)

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
            self.assertIn("--collect-generation-trace", command)
            self.assertIn("Мягкий женский голос", command)

    def test_design_forwards_explicit_timeouts_and_requires_natural_eos(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model")
            save_wav = _write_executable(root / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "worker.exe")
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
                        "Test",
                        "--instruction",
                        "Voice",
                        "--out",
                        str(root / "voice.wav"),
                        "--startup-timeout-ms",
                        "240000",
                        "--request-timeout-ms",
                        "900000",
                    ]
                )

            self.assertEqual(0, result)
            command = run.call_args.args[0]
            self.assertEqual(
                "240000", command[command.index("--startup-timeout-ms") + 1]
            )
            self.assertEqual(
                "900000", command[command.index("--request-timeout-ms") + 1]
            )
            self.assertIn("--require-natural-eos", command)
            self.assertIn("--collect-generation-trace", command)

    def test_design_timeout_config_is_overridden_by_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_model(root / "model")
            save_wav = _write_executable(root / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "worker.exe")
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "models": {"voice-design": {"path": "model"}},
                        "runtime": {
                            "save_wav_executable": str(save_wav),
                            "worker": str(worker),
                            "startup_timeout_ms": 180000,
                            "request_timeout_ms": 600000,
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
                        "Test",
                        "--instruction",
                        "Voice",
                        "--out",
                        str(root / "voice.wav"),
                        "--request-timeout-ms",
                        "720000",
                    ]
                )

            self.assertEqual(0, result)
            command = run.call_args.args[0]
            self.assertEqual(
                "180000", command[command.index("--startup-timeout-ms") + 1]
            )
            self.assertEqual(
                "720000", command[command.index("--request-timeout-ms") + 1]
            )

    def test_design_failure_preserves_previous_outputs_and_cleans_temporary_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model")
            save_wav = _write_executable(root / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "worker.exe")
            output = root / "voice.wav"
            result_json = root / "voice.json"
            output.write_bytes(b"previous wav")
            result_json.write_text('{"previous": true}', encoding="utf-8")
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                return_value=mock.Mock(returncode=17),
            ):
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
                        "Test",
                        "--instruction",
                        "Voice",
                        "--out",
                        str(output),
                        "--result-json",
                        str(result_json),
                    ]
                )

            self.assertEqual(17, result)
            self.assertEqual(b"previous wav", output.read_bytes())
            self.assertEqual('{"previous": true}', result_json.read_text())
            self.assertEqual([], list(root.glob(".*.qtb-tmp")))

    def test_child_output_reservations_are_absent_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = user_cli._temporary_output_paths(
                root / "voice.wav", root / "voice.json"
            )
            self.assertTrue(all(not path.exists() for path in paths))
            self.assertEqual([], list(root.glob(".*.qtb-tmp")))

    def test_design_success_replaces_previous_outputs_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model")
            save_wav = _write_executable(root / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "worker.exe")
            output = root / "voice.wav"
            result_json = root / "voice.json"
            output.write_bytes(b"previous wav")
            result_json.write_text('{"previous": true}', encoding="utf-8")
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_synthesis,
            ):
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
                        "Test",
                        "--instruction",
                        "Voice",
                        "--out",
                        str(output),
                        "--result-json",
                        str(result_json),
                    ]
                )

            self.assertEqual(0, result)
            with wave.open(str(output), "rb") as wav:
                self.assertEqual(16, wav.getnframes())
            self.assertEqual(1, json.loads(result_json.read_text())["audio_chunks"])
            self.assertEqual([], list(root.glob(".*.qtb-tmp")))

    def test_design_invalid_result_preserves_previous_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model")
            save_wav = _write_executable(root / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "worker.exe")
            output = root / "voice.wav"
            result_json = root / "voice.json"
            output.write_bytes(b"previous wav")
            result_json.write_text('{"previous": true}', encoding="utf-8")

            def invalid_synthesis(command: list[str], **_kwargs: object) -> mock.Mock:
                Path(command[command.index("--output") + 1]).write_bytes(b"bad wav")
                Path(command[command.index("--result-json") + 1]).write_text(
                    "{}", encoding="utf-8"
                )
                return mock.Mock(returncode=0)

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=invalid_synthesis,
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
                            str(output),
                            "--result-json",
                            str(result_json),
                        ]
                    )

            self.assertEqual(2, raised.exception.code)
            self.assertEqual(b"previous wav", output.read_bytes())
            self.assertEqual('{"previous": true}', result_json.read_text())
            self.assertEqual([], list(root.glob(".*.qtb-tmp")))

    def test_design_rejects_invalid_timeout_values(self) -> None:
        for value in ("0", "-1", "4294967296", "not-a-number"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    user_cli._parse_timeout_argument(value)

    def test_design_can_explicitly_allow_non_natural_eos(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model")
            save_wav = _write_executable(root / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "worker.exe")

            def truncated_synthesis(
                command: list[str], **_kwargs: object
            ) -> mock.Mock:
                output = Path(command[command.index("--output") + 1])
                result = Path(command[command.index("--result-json") + 1])
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
                            "termination_reason": "max_new_tokens",
                            "hit_eos": False,
                            "hit_max_seq_len": False,
                            "hit_max_new_tokens": True,
                        }
                    ),
                    encoding="utf-8",
                )
                return mock.Mock(returncode=0)

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=truncated_synthesis,
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
                        "Test",
                        "--instruction",
                        "Voice",
                        "--out",
                        str(root / "voice.wav"),
                        "--allow-non-natural-eos",
                    ]
                )

            self.assertEqual(0, result)
            self.assertNotIn("--require-natural-eos", run.call_args.args[0])
            self.assertIn("--collect-generation-trace", run.call_args.args[0])

    def test_upstream_diagnostic_does_not_receive_faster_trace_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model")
            save_wav = _write_executable(root / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "worker.exe")
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_non_natural_synthesis,
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
                        "--runtime-backend",
                        "upstream",
                        "--allow-non-natural-eos",
                        "--text",
                        "Test",
                        "--instruction",
                        "Voice",
                        "--out",
                        str(root / "voice.wav"),
                    ]
                )

            self.assertEqual(0, result)
            self.assertNotIn("--collect-generation-trace", run.call_args.args[0])

    def test_strict_natural_eos_requires_generation_trace_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wav_path, receipt_path = _write_valid_design_outputs(
                Path(temporary),
                generation_trace_available=False,
                termination_reason="",
                hit_eos=False,
            )

            with self.assertRaisesRegex(ValueError, "natural EOS"):
                user_cli._validate_design_outputs(wav_path, receipt_path, True)

    def test_strict_natural_eos_accepts_generation_trace_eos(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wav_path, receipt_path = _write_valid_design_outputs(
                Path(temporary),
                generation_trace_available=True,
                termination_reason="eos",
                hit_eos=True,
            )

            user_cli._validate_design_outputs(wav_path, receipt_path, True)

    def test_strict_natural_eos_rejects_generation_limits(self) -> None:
        for reason, max_seq_len, max_new_tokens in (
            ("max_new_tokens", False, True),
            ("max_seq_len", True, False),
        ):
            with (
                self.subTest(reason=reason),
                tempfile.TemporaryDirectory() as temporary,
            ):
                wav_path, receipt_path = _write_valid_design_outputs(
                    Path(temporary),
                    generation_trace_available=True,
                    termination_reason=reason,
                    hit_eos=False,
                    hit_max_seq_len=max_seq_len,
                    hit_max_new_tokens=max_new_tokens,
                )

                with self.assertRaisesRegex(ValueError, "natural EOS"):
                    user_cli._validate_design_outputs(wav_path, receipt_path, True)

    def test_strict_natural_eos_failure_preserves_previous_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model")
            save_wav = _write_executable(root / "qwen_tts_save_wav.exe")
            worker = _write_executable(root / "worker.exe")
            output = root / "voice.wav"
            result_json = root / "voice.json"
            output.write_bytes(b"previous wav")
            result_json.write_text('{"previous": true}', encoding="utf-8")
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_non_natural_synthesis,
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
                            str(output),
                            "--result-json",
                            str(result_json),
                        ]
                    )

            self.assertEqual(2, raised.exception.code)
            self.assertEqual(b"previous wav", output.read_bytes())
            self.assertEqual('{"previous": true}', result_json.read_text())

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
            config.parent.mkdir(exist_ok=True)
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

    def test_publication_failure_backing_up_second_target_restores_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _publication_fixture(Path(temporary))
            original_replace = user_cli.os.replace
            calls = 0

            def fail_second_backup(source: str, destination: str) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected second-backup failure")
                original_replace(source, destination)

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.os.replace",
                side_effect=fail_second_backup,
            ):
                with self.assertRaisesRegex(ValueError, "publish"):
                    user_cli._publish_design_outputs(*paths)

            self.assertEqual(b"old wav", paths[2].read_bytes())
            self.assertEqual(b"old json", paths[3].read_bytes())
            self.assertEqual([], list(Path(temporary).glob("*.qtb-backup")))

    def test_publication_failure_before_wav_publish_restores_both_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _publication_fixture(Path(temporary))
            original_replace = user_cli.os.replace
            calls = 0

            def fail_wav_publish(source: str, destination: str) -> None:
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("injected wav-publish failure")
                original_replace(source, destination)

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.os.replace",
                side_effect=fail_wav_publish,
            ):
                with self.assertRaisesRegex(ValueError, "publish"):
                    user_cli._publish_design_outputs(*paths)

            self.assertEqual(b"old wav", paths[2].read_bytes())
            self.assertEqual(b"old json", paths[3].read_bytes())
            self.assertEqual([], list(Path(temporary).glob("*.qtb-backup")))

    def test_publication_failure_after_wav_publish_restores_both_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _publication_fixture(Path(temporary))
            original_replace = user_cli.os.replace
            calls = 0

            def fail_json_publish(source: str, destination: str) -> None:
                nonlocal calls
                calls += 1
                if calls == 4:
                    raise OSError("injected json-publish failure")
                original_replace(source, destination)

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.os.replace",
                side_effect=fail_json_publish,
            ):
                with self.assertRaisesRegex(ValueError, "publish"):
                    user_cli._publish_design_outputs(*paths)

            self.assertEqual(b"old wav", paths[2].read_bytes())
            self.assertEqual(b"old json", paths[3].read_bytes())
            self.assertEqual([], list(Path(temporary).glob("*.qtb-backup")))

    def test_publication_reports_and_preserves_backup_when_rollback_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _publication_fixture(Path(temporary))
            original_replace = user_cli.os.replace
            calls = 0

            def fail_publish_and_json_restore(source: str, destination: str) -> None:
                nonlocal calls
                calls += 1
                if calls in (4, 5):
                    raise OSError(f"injected failure {calls}")
                original_replace(source, destination)

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.os.replace",
                side_effect=fail_publish_and_json_restore,
            ):
                with self.assertRaisesRegex(
                    ValueError, "rollback was incomplete.*backup"
                ) as raised:
                    user_cli._publish_design_outputs(*paths)

            json_backups = list(
                Path(temporary).glob(".voice.json.*.qtb-backup")
            )
            self.assertEqual(1, len(json_backups))
            self.assertIn(str(json_backups[0]), str(raised.exception))
            self.assertEqual(b"old wav", paths[2].read_bytes())
            self.assertFalse(paths[3].exists())
            json_backups[0].unlink()
            paths[0].unlink(missing_ok=True)
            paths[1].unlink(missing_ok=True)

    def test_successful_publication_cleans_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _publication_fixture(Path(temporary))
            user_cli._publish_design_outputs(*paths)

            self.assertEqual(b"new wav", paths[2].read_bytes())
            self.assertEqual(b"new json", paths[3].read_bytes())
            self.assertEqual([], list(Path(temporary).glob("*.qtb-backup")))
            self.assertFalse(paths[0].exists())
            self.assertFalse(paths[1].exists())

    def test_publication_rejects_symlink_before_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _publication_fixture(Path(temporary))
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.Path.is_symlink",
                return_value=True,
            ), mock.patch("qwen_tts_bridge_worker.user_cli.os.replace") as replace:
                with self.assertRaisesRegex(ValueError, "symlink"):
                    user_cli._publish_design_outputs(*paths)
            replace.assert_not_called()
            paths[0].unlink(missing_ok=True)
            paths[1].unlink(missing_ok=True)

    def test_publication_rejects_wav_directory_and_preserves_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            temporary_wav = root / ".voice.wav.qtb-tmp"
            temporary_result = root / ".voice.json.qtb-tmp"
            output = root / "voice.wav"
            result_json = root / "voice.json"
            temporary_wav.write_bytes(b"new wav")
            temporary_result.write_bytes(b"new json")
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.os.replace"
            ) as replace:
                with self.assertRaisesRegex(ValueError, "non-file output"):
                    user_cli._publish_design_outputs(
                        temporary_wav, temporary_result, output, result_json
                    )

            replace.assert_not_called()
            self.assertTrue(output.is_dir())
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))
            self.assertEqual(b"new wav", temporary_wav.read_bytes())
            self.assertEqual(b"new json", temporary_result.read_bytes())

    def test_publication_rejects_receipt_directory_and_preserves_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            temporary_wav = root / ".voice.wav.qtb-tmp"
            temporary_result = root / ".voice.json.qtb-tmp"
            output = root / "voice.wav"
            result_json = root / "voice.json"
            temporary_wav.write_bytes(b"new wav")
            temporary_result.write_bytes(b"new json")
            output.write_bytes(b"old wav")
            result_json.mkdir()
            sentinel = result_json / "sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.os.replace"
            ) as replace:
                with self.assertRaisesRegex(ValueError, "non-file output"):
                    user_cli._publish_design_outputs(
                        temporary_wav, temporary_result, output, result_json
                    )

            replace.assert_not_called()
            self.assertEqual(b"old wav", output.read_bytes())
            self.assertTrue(result_json.is_dir())
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))
            self.assertEqual(b"new wav", temporary_wav.read_bytes())
            self.assertEqual(b"new json", temporary_result.read_bytes())

    def test_target_preflight_rejects_canonical_output_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "voice.wav"
            result = root / "nested" / ".." / "voice.wav"
            with self.assertRaisesRegex(ValueError, "different files"):
                user_cli._validate_cli_targets(
                    outputs=(output, result), protected=(), operation="synthesis"
                )

    def test_target_preflight_rejects_protected_config_and_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            registry = root / "voices" / "registry.json"
            config.parent.mkdir(exist_ok=True)
            registry.parent.mkdir()
            config.write_text("{}", encoding="utf-8")
            registry.write_text("{}", encoding="utf-8")
            for target in (config, registry):
                with self.subTest(target=target):
                    with self.assertRaisesRegex(ValueError, "protected file"):
                        user_cli._validate_cli_targets(
                            outputs=(target,),
                            protected=(config, registry),
                            operation="synthesis",
                        )

    def test_target_preflight_rejects_hardlink_alias_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            protected = root / "protected.wav"
            alias = root / "alias.wav"
            protected.write_bytes(b"immutable")
            try:
                os.link(protected, alias)
            except (AttributeError, OSError) as exc:
                self.skipTest(f"hardlinks unavailable: {exc}")
            with self.assertRaisesRegex(ValueError, "protected file"):
                user_cli._validate_cli_targets(
                    outputs=(alias,), protected=(protected,), operation="playback"
                )


    def test_synth_supports_custom_voice_family_and_speaker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(
                root / "model", model_type="custom_voice", model_size="0b6"
            )
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            output = root / "custom.wav"

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_synthesis,
            ) as run:
                result = user_cli.main(
                    [
                        "synth",
                        "--model-family",
                        "custom-0.6b",
                        "--speaker",
                        "Alice",
                        "--instruction",
                        "Speak warmly.",
                        "--model",
                        str(model),
                        "--save-wav-executable",
                        str(save_wav),
                        "--worker",
                        str(worker),
                        "--text",
                        "Hello",
                        "--out",
                        str(output),
                    ]
                )

            self.assertEqual(0, result)
            command = run.call_args.args[0]
            self.assertIn("--speaker", command)
            self.assertEqual("Alice", command[command.index("--speaker") + 1])
            self.assertIn("--instruction", command)
            self.assertNotIn("--voice-id", command)
            worker_args = _worker_argument_values(command)
            self.assertEqual(
                str(model.resolve()),
                worker_args[worker_args.index("--model-path") + 1],
            )


    def test_synth_supports_custom_voice_1_7b_family(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(
                root / "model", model_type="custom_voice", model_size="1b7"
            )
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_synthesis,
            ) as run:
                self.assertEqual(
                    0,
                    user_cli.main(
                        [
                            "synth",
                            "--model-family",
                            "custom-1.7b",
                            "--speaker",
                            "Ryan",
                            "--model",
                            str(model),
                            "--save-wav-executable",
                            str(save_wav),
                            "--worker",
                            str(worker),
                            "--text",
                            "Hello",
                            "--out",
                            str(root / "custom.wav"),
                        ]
                    ),
                )
            command = run.call_args.args[0]
            self.assertEqual("Ryan", command[command.index("--speaker") + 1])
            self.assertNotIn("--voice-id", command)


    def test_synth_rejects_incompatible_voice_sources_without_starting_worker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(
                root / "model", model_type="custom_voice", model_size="1b7"
            )
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            common = [
                "synth",
                "--model-family",
                "custom-1.7b",
                "--model",
                str(model),
                "--save-wav-executable",
                str(save_wav),
                "--worker",
                str(worker),
                "--text",
                "Hello",
                "--out",
                str(root / "custom.wav"),
            ]
            for extra, message in (
                (["--voice-id", "voice", "--speaker", "Ryan"], "--voice-id"),
                (["--instruction", "Speak warmly."], "--speaker"),
            ):
                with self.subTest(message=message):
                    with mock.patch(
                        "qwen_tts_bridge_worker.user_cli.subprocess.run"
                    ) as run, redirect_stderr(io.StringIO()) as stderr:
                        with self.assertRaises(SystemExit) as raised:
                            user_cli.main(common + extra)
                    self.assertEqual(2, raised.exception.code)
                    self.assertIn(message, stderr.getvalue())
                    run.assert_not_called()


    def test_synth_rejects_family_checkpoint_mismatch_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run"
            ) as run, redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    user_cli.main(
                        [
                            "synth",
                            "--model-family",
                            "custom-1.7b",
                            "--speaker",
                            "Ryan",
                            "--model",
                            str(model),
                            "--save-wav-executable",
                            str(save_wav),
                            "--worker",
                            str(worker),
                            "--text",
                            "Hello",
                            "--out",
                            str(root / "custom.wav"),
                        ]
                    )
            self.assertEqual(2, raised.exception.code)
            self.assertIn("model family mismatch", stderr.getvalue())
            run.assert_not_called()


    def test_synth_supports_voice_design_family(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="voice_design")
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_synthesis,
            ) as run:
                result = user_cli.main(
                    [
                        "synth",
                        "--model-family",
                        "voice-design",
                        "--instruction",
                        "A calm voice.",
                        "--model",
                        str(model),
                        "--save-wav-executable",
                        str(save_wav),
                        "--worker",
                        str(worker),
                        "--text",
                        "Hello",
                        "--out",
                        str(root / "design.wav"),
                    ]
                )

            self.assertEqual(0, result)
            command = run.call_args.args[0]
            self.assertEqual(
                "A calm voice.", command[command.index("--instruction") + 1]
            )
            self.assertNotIn("--voice-id", command)


    def test_play_out_captures_and_publishes_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            player = _write_executable(root / "player.exe")
            worker = _write_executable(root / "worker.exe")
            config, _ = _write_voice_library(root, voice_id="voice")
            output = root / "nested" / "speech.wav"

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                side_effect=_successful_play,
            ) as run:
                result = user_cli.main(
                    [
                        "--config",
                        str(config),
                        "play",
                        "--voice-id",
                        "voice",
                        "--text",
                        "Test playback",
                        "--model",
                        str(model),
                        "--play-executable",
                        str(player),
                        "--worker",
                        str(worker),
                        "--out",
                        str(output),
                    ]
                )

            self.assertEqual(0, result)
            command = run.call_args.args[0]
            capture = Path(command[command.index("--wav-capture-file") + 1])
            self.assertFalse(capture.exists())
            with wave.open(str(output), "rb") as wav:
                self.assertEqual(1, wav.getnchannels())
                self.assertEqual(16, wav.getnframes())

    def test_play_routes_families_with_and_without_wav_capture(self) -> None:
        # Command forwarding only; actual speakers/styles require model acceptance.
        families = (
            ("base-0.6b", "base", "0b6", ["--voice-id", "voice"]),
            ("base-1.7b", "base", "1b7", ["--voice-id", "voice"]),
            ("custom-0.6b", "custom_voice", "0b6", ["--speaker", "Ryan"]),
            (
                "custom-1.7b", "custom_voice", "1b7",
                ["--speaker", "Ryan", "--instruction", "Speak warmly."],
            ),
            ("voice-design", "voice_design", "1b7", ["--instruction", "Calm voice."]),
        )
        for family, model_type, size, voice_arguments in families:
            for backend, capture in (
                ("faster", False), ("faster", True),
                ("upstream", False), ("upstream", True),
            ):
                with self.subTest(family=family, backend=backend, capture=capture):
                    with tempfile.TemporaryDirectory() as temporary:
                        root = Path(temporary)
                        model = _write_model(
                            root / "model", model_type=model_type, model_size=size
                        )
                        player = _write_executable(root / "player.exe")
                        worker = _write_executable(root / "worker.exe")
                        config, registry = _write_voice_library(root, voice_id="voice")
                        output = root / "speech.wav"
                        invocation = [
                            "--config", str(config), "play", "--model-family", family,
                            "--runtime-backend", backend, "--text", "Test playback",
                            "--model", str(model), "--play-executable", str(player),
                            "--worker", str(worker), *voice_arguments,
                        ]
                        if capture:
                            invocation += ["--out", str(output)]
                        with mock.patch(
                            "qwen_tts_bridge_worker.user_cli.subprocess.run",
                            side_effect=_successful_play if capture else None,
                            return_value=mock.Mock(returncode=0),
                        ) as run:
                            self.assertEqual(0, user_cli.main(invocation))
                        command = run.call_args.args[0]
                        worker_arguments = _worker_argument_values(command)
                        model_path = Path(
                            worker_arguments[worker_arguments.index("--model-path") + 1]
                        )
                        self.assertEqual(
                            user_cli._canonical_path(model),
                            user_cli._canonical_path(model_path),
                        )
                        self.assertEqual(
                            backend,
                            worker_arguments[
                                worker_arguments.index("--runtime-backend") + 1
                            ],
                        )
                        self.assertEqual(
                            backend == "faster",
                            "--collect-generation-trace" in worker_arguments,
                        )
                        for flag, value in zip(
                            voice_arguments[::2], voice_arguments[1::2], strict=True
                        ):
                            self.assertEqual(value, command[command.index(flag) + 1])
                        if family.startswith("base-"):
                            self.assertIn(str(registry.resolve()), worker_arguments)
                        else:
                            self.assertNotIn("--voice-id", command)
                            self.assertNotIn("--voice-registry-path", worker_arguments)
                        self.assertEqual(capture, "--wav-capture-file" in command)
                        self.assertEqual(capture, output.exists())
                        if capture:
                            user_cli._validate_wav_output(output)


    def test_play_out_failure_preserves_previous_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            player = _write_executable(root / "player.exe")
            worker = _write_executable(root / "worker.exe")
            config, _ = _write_voice_library(root, voice_id="voice")
            output = root / "speech.wav"
            output.write_bytes(b"previous wav")

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run",
                return_value=mock.Mock(returncode=19),
            ):
                result = user_cli.main(
                    [
                        "--config",
                        str(config),
                        "play",
                        "--voice-id",
                        "voice",
                        "--text",
                        "Test playback",
                        "--model",
                        str(model),
                        "--play-executable",
                        str(player),
                        "--worker",
                        str(worker),
                        "--out",
                        str(output),
                    ]
                )

            self.assertEqual(19, result)
            self.assertEqual(b"previous wav", output.read_bytes())


    def test_play_rejects_output_and_log_file_collision_before_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="base")
            player = _write_executable(root / "player.exe")
            worker = _write_executable(root / "worker.exe")
            config, _ = _write_voice_library(root, voice_id="voice")
            output = root / "speech.wav"
            (root / "temp").mkdir()
            aliased_output = root / "temp" / ".." / "speech.wav"
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run"
            ) as run, redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    user_cli.main(
                        [
                            "--config",
                            str(config),
                            "play",
                            "--voice-id",
                            "voice",
                            "--text",
                            "Test playback",
                            "--model",
                            str(model),
                            "--play-executable",
                            str(player),
                            "--worker",
                            str(worker),
                            "--out",
                            str(output),
                            "--log-file",
                            str(aliased_output),
                        ]
                    )
            self.assertEqual(2, raised.exception.code)
            self.assertIn("different files", stderr.getvalue())
            run.assert_not_called()

    def test_synth_rejects_result_alias_before_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = _write_model(root / "model", model_type="voice_design")
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            output = root / "voice.wav"
            (root / "nested").mkdir()
            aliased_result = root / "nested" / ".." / "voice.wav"
            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.subprocess.run"
            ) as run, redirect_stderr(io.StringIO()) as stderr:
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
                            str(output),
                            "--result-json",
                            str(aliased_result),
                        ]
                    )
            self.assertEqual(2, raised.exception.code)
            self.assertIn("different files", stderr.getvalue())
            run.assert_not_called()

    def test_synth_rejects_registry_and_managed_reference_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, registry = _write_voice_library(root, voice_id="voice")
            model = _write_model(root / "model", model_type="base")
            save_wav = _write_executable(root / "save-wav.exe")
            worker = _write_executable(root / "worker.exe")
            row = json.loads(registry.read_text(encoding="utf-8"))["voices"][0]
            managed = registry.parent / row["reference_audio_path"]
            for target in (registry, managed, config):
                with self.subTest(target=target):
                    with mock.patch(
                        "qwen_tts_bridge_worker.user_cli.subprocess.run"
                    ) as run, redirect_stderr(io.StringIO()) as stderr:
                        with self.assertRaises(SystemExit) as raised:
                            user_cli.main(
                                [
                                    "--config",
                                    str(config),
                                    "synth",
                                    "--model-family",
                                    "base-1.7b",
                                    "--voice-id",
                                    "voice",
                                    "--model",
                                    str(model),
                                    "--save-wav-executable",
                                    str(save_wav),
                                    "--worker",
                                    str(worker),
                                    "--text",
                                    "Test",
                                    "--out",
                                    str(target),
                                ]
                            )
                    self.assertEqual(2, raised.exception.code)
                    self.assertIn("protected file", stderr.getvalue())
                    run.assert_not_called()


    def test_play_path_collision_through_symlink_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target_dir = root / "audio"
            target_dir.mkdir()
            alias_dir = root / "alias"
            try:
                alias_dir.symlink_to(target_dir, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            self.assertEqual(
                user_cli._canonical_path(target_dir / "speech.wav"),
                user_cli._canonical_path(alias_dir / "speech.wav"),
            )
            output_link = root / "output.wav"
            output_link.symlink_to(target_dir / "speech.wav")
            with self.assertRaisesRegex(ValueError, "symlink output"):
                user_cli._reject_output_target(output_link)


    def test_wav_validation_reads_bounded_chunks_and_rejects_truncated_pcm(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "capture.wav"
            frames = 2 * user_cli._WAV_VALIDATION_CHUNK_FRAMES + 17
            with wave.open(str(path), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(24000)
                writer.writeframes(b"\x00\x10" * frames)
            real_readframes = wave.Wave_read.readframes

            def bounded_readframes(reader: wave.Wave_read, count: int) -> bytes:
                self.assertLessEqual(count, user_cli._WAV_VALIDATION_CHUNK_FRAMES)
                return real_readframes(reader, count)

            with mock.patch.object(
                wave.Wave_read, "readframes", autospec=True,
                side_effect=bounded_readframes,
            ) as readframes:
                user_cli._validate_wav_output(path)
                self.assertEqual(3, readframes.call_count)
                path.write_bytes(path.read_bytes()[:-2])
                with self.assertRaisesRegex(ValueError, "audio frames"):
                    user_cli._validate_wav_output(path)


    def test_publish_output_backup_failure_preserves_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "speech.wav"
            temporary_output = root / ".speech.wav.qtb-tmp"
            target.write_bytes(b"previous wav")
            temporary_output.write_bytes(b"new wav")
            real_replace = user_cli.os.replace

            def fail_backup(
                source: str | os.PathLike[str], destination: str | os.PathLike[str]
            ) -> None:
                if Path(source) == target:
                    raise OSError("backup failure")
                real_replace(source, destination)

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.os.replace", side_effect=fail_backup
            ):
                with self.assertRaises(ValueError):
                    user_cli._publish_output(temporary_output, target)
            self.assertEqual(b"previous wav", target.read_bytes())
            self.assertEqual(b"new wav", temporary_output.read_bytes())


    def test_publish_output_publish_failure_restores_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "speech.wav"
            temporary_output = root / ".speech.wav.qtb-tmp"
            target.write_bytes(b"previous wav")
            temporary_output.write_bytes(b"new wav")
            real_replace = user_cli.os.replace

            def fail_publish(
                source: str | os.PathLike[str], destination: str | os.PathLike[str]
            ) -> None:
                if Path(source) == temporary_output:
                    raise OSError("publish failure")
                real_replace(source, destination)

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.os.replace", side_effect=fail_publish
            ):
                with self.assertRaises(ValueError):
                    user_cli._publish_output(temporary_output, target)
            self.assertEqual(b"previous wav", target.read_bytes())
            self.assertEqual(b"new wav", temporary_output.read_bytes())


    def test_publish_output_rollback_failure_retains_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "speech.wav"
            temporary_output = root / ".speech.wav.qtb-tmp"
            target.write_bytes(b"previous wav")
            temporary_output.write_bytes(b"new wav")
            real_replace = user_cli.os.replace
            calls = 0

            def fail_rollback(
                source: str | os.PathLike[str], destination: str | os.PathLike[str]
            ) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("publish failure")
                if calls == 3:
                    raise OSError("rollback failure")
                real_replace(source, destination)

            with mock.patch(
                "qwen_tts_bridge_worker.user_cli.os.replace", side_effect=fail_rollback
            ):
                with self.assertRaisesRegex(ValueError, "backup retained"):
                    user_cli._publish_output(temporary_output, target)
            self.assertFalse(target.exists())
            backups = list(root.glob(".speech.wav.*.qtb-backup"))
            self.assertEqual(1, len(backups))
            self.assertEqual(b"previous wav", backups[0].read_bytes())


class _BoundedReadStream(io.BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        if size < 0 or size > user_cli._DIAGNOSTIC_READ_CHUNK_BYTES:
            raise AssertionError(f"unbounded diagnostic read: {size}")
        self.read_sizes.append(size)
        return super().read(size)


def _write_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"exe")
    return path


def _successful_play(command: list[str], **_kwargs: object) -> mock.Mock:
    output = Path(command[command.index("--wav-capture-file") + 1])
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x00\x00" * 16)
    return mock.Mock(returncode=0)

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
                "generation_trace_available": True,
                "termination_reason": "eos",
                "hit_eos": True,
                "hit_max_seq_len": False,
                "hit_max_new_tokens": False,
            }
        ),
        encoding="utf-8",
    )
    return mock.Mock(returncode=0)


def _successful_voice_creation(command: list[str], **_kwargs: object) -> mock.Mock:
    return _write_voice_creation_result(command, frames=48_000)


def _invalid_voice_creation(command: list[str], **_kwargs: object) -> mock.Mock:
    return _write_voice_creation_result(command, frames=24_000)


def _write_voice_creation_result(command: list[str], *, frames: int) -> mock.Mock:
    output = Path(command[command.index("--output") + 1])
    result = Path(command[command.index("--result-json") + 1])
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x00\x10" * frames)
    result.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "terminal_state": "completed",
                "audio_chunks": 1,
                "audio_bytes": frames * 2,
                "completion_metadata_received": True,
                "generation_trace_available": True,
                "termination_reason": "eos",
                "hit_eos": True,
                "hit_max_seq_len": False,
                "hit_max_new_tokens": False,
            }
        ),
        encoding="utf-8",
    )
    return mock.Mock(returncode=0)


def _diagnostic_success(command: list[str], **kwargs: object) -> mock.Mock:
    stream = cast(Any, kwargs.get("stdout"))
    if stream is not None:
        stream.write(b'qtb_metric {"event":"worker_loaded"}\n')
        stream.write("worker предупреждение\n".encode("utf-8"))
    _successful_synthesis(command, **kwargs)
    return mock.Mock(returncode=0)


def _diagnostic_failure(command: list[str], **kwargs: object) -> mock.Mock:
    stream = cast(Any, kwargs.get("stdout"))
    if stream is not None:
        stream.write(b'qtb_metric {"event":"worker_failed"}\n')
        stream.write(b"worker failure\n")
    return mock.Mock(returncode=17)


def _non_natural_synthesis(command: list[str], **_kwargs: object) -> mock.Mock:
    output = Path(command[command.index("--output") + 1])
    result = Path(command[command.index("--result-json") + 1])
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
                "generation_trace_available": True,
                "termination_reason": "max_new_tokens",
                "hit_eos": False,
                "hit_max_seq_len": False,
                "hit_max_new_tokens": True,
            }
        ),
        encoding="utf-8",
    )
    return mock.Mock(returncode=0)


def _write_valid_design_outputs(
    root: Path,
    *,
    generation_trace_available: bool,
    termination_reason: str,
    hit_eos: bool,
    hit_max_seq_len: bool = False,
    hit_max_new_tokens: bool = False,
) -> tuple[Path, Path]:
    output = root / "voice.wav"
    result = root / "voice.json"
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
                "generation_trace_available": generation_trace_available,
                "termination_reason": termination_reason,
                "hit_eos": hit_eos,
                "hit_max_seq_len": hit_max_seq_len,
                "hit_max_new_tokens": hit_max_new_tokens,
            }
        ),
        encoding="utf-8",
    )
    return output, result


def _write_model(
    root: Path, *, model_type: str = "voice_design", model_size: str = "1b7"
) -> Path:
    root.mkdir(parents=True)
    (root / "speech_tokenizer").mkdir()
    (root / "config.json").write_text(
        json.dumps(
            {
                "model_type": "qwen3_tts",
                "tts_model_type": model_type,
                "tts_model_size": model_size,
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


def _write_voice_library(
    root: Path,
    *,
    voice_id: str,
    extra_config: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    config = root / "config.json"
    payload: dict[str, object] = {
        "schema_version": 1,
        "voice_library": {"registry_path": "voices/registry.json"},
    }
    if extra_config:
        payload.update(extra_config)
    config.write_text(json.dumps(payload), encoding="utf-8")
    source = root / "source" / "reference.wav"
    source.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x00\x20\x00\xe0" * 36_000)
    registry = root / "voices" / "registry.json"
    user_cli.add_voice(
        registry,
        voice_id=voice_id,
        wav_path=source,
        reference_text="Reference text",
        x_vector_only=False,
        preserve_reference_text_whitespace=False,
    )
    return config, registry


def _worker_argument_values(command: list[str]) -> list[str]:
    return [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--worker-arg"
    ]


def _publication_fixture(
    root: Path,
) -> tuple[Path, Path, Path, Path]:
    temporary_wav = root / ".voice.wav.qtb-tmp"
    temporary_result = root / ".voice.json.qtb-tmp"
    output = root / "voice.wav"
    result_json = root / "voice.json"
    temporary_wav.write_bytes(b"new wav")
    temporary_result.write_bytes(b"new json")
    output.write_bytes(b"old wav")
    result_json.write_bytes(b"old json")
    return temporary_wav, temporary_result, output, result_json


if __name__ == "__main__":
    unittest.main()
