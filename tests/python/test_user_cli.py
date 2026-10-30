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
from typing import Any, cast
from unittest import mock

from qwen_tts_bridge_worker import user_cli


class UserCliTests(unittest.TestCase):
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
