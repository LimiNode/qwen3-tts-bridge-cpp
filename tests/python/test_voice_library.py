from __future__ import annotations

import hashlib
import json
import math
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from qwen_tts_bridge_worker import user_cli
from qwen_tts_bridge_worker.voice_library import (
    VoiceLibraryError,
    _cleanup_orphaned_entries,
    _internal_id,
    _registry_lock,
    _run_native_prepare,
    _verify_prepared_artifacts,
    add_voice,
    list_voices,
    load_voice_rows,
    prepare_voice,
    show_voice,
    verify_voice,
)


class VoiceLibraryTests(unittest.TestCase):
    def test_add_list_show_and_python_verify_use_managed_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _write_wav(root / "source.wav")
            registry = root / "voices" / "registry.json"

            row = add_voice(
                registry,
                voice_id="русский голос",
                wav_path=source,
                reference_text="  Пример текста.  ",
                x_vector_only=False,
                preserve_reference_text_whitespace=False,
            )

            managed = registry.parent / row["reference_audio_path"]
            self.assertTrue(managed.is_file())
            self.assertNotEqual(source.resolve(), managed.resolve())
            self.assertEqual("Пример текста.", row["reference_text"])
            self.assertEqual("compatible", list_voices(registry)[0]["python_status"])
            self.assertEqual(
                "compatible",
                verify_voice(registry, "русский голос", backend="python")["status"],
            )
            self.assertEqual(
                "русский голос", show_voice(registry, "русский голос")["voice_id"]
            )

            source.write_bytes(b"source remains untouched")
            self.assertEqual(b"source remains untouched", source.read_bytes())
            self.assertEqual(1, len(load_voice_rows(registry)))

    def test_add_preserves_reference_whitespace_and_rejects_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wav = _write_wav(root / "source.wav")
            registry = root / "registry.json"
            add_voice(
                registry,
                voice_id="voice",
                wav_path=wav,
                reference_text="  exact  ",
                x_vector_only=False,
                preserve_reference_text_whitespace=True,
            )
            self.assertEqual(
                "  exact  ", load_voice_rows(registry)[0]["reference_text"]
            )
            with self.assertRaisesRegex(VoiceLibraryError, "already exists"):
                add_voice(
                    registry,
                    voice_id="voice",
                    wav_path=wav,
                    reference_text="again",
                    x_vector_only=False,
                    preserve_reference_text_whitespace=False,
                )

    def test_x_vector_only_accepts_empty_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            add_voice(
                registry,
                voice_id="xvector",
                wav_path=_write_wav(root / "source.wav"),
                reference_text="",
                x_vector_only=True,
                preserve_reference_text_whitespace=False,
            )
            self.assertEqual(
                "compatible",
                verify_voice(registry, "xvector", backend="python")["status"],
            )

    def test_list_is_stable_for_several_voices_and_empty_library(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            self.assertEqual([], list_voices(registry))
            wav = _write_wav(root / "source.wav")
            for voice_id in ("zeta", "альфа"):
                add_voice(
                    registry,
                    voice_id=voice_id,
                    wav_path=wav,
                    reference_text="text",
                    x_vector_only=False,
                    preserve_reference_text_whitespace=False,
                )
            self.assertEqual(
                ["zeta", "альфа"],
                [row["voice_id"] for row in list_voices(registry)],
            )

    def test_malformed_registry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry.json"
            registry.write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(VoiceLibraryError, "valid UTF-8 JSON"):
                load_voice_rows(registry)

    def test_silent_wav_is_rejected_without_publishing_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            wav = root / "silent.wav"
            with wave.open(str(wav), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(24_000)
                output.writeframes(b"\0\0" * (24_000 * 2))
            with self.assertRaisesRegex(VoiceLibraryError, "silent"):
                add_voice(
                    registry,
                    voice_id="silent",
                    wav_path=wav,
                    reference_text="text",
                    x_vector_only=False,
                    preserve_reference_text_whitespace=False,
                )
            self.assertFalse(registry.exists())

    def test_registry_write_failure_does_not_publish_managed_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "voices" / "registry.json"
            with mock.patch(
                "qwen_tts_bridge_worker.voice_library._atomic_write_registry",
                side_effect=OSError("injected"),
            ):
                with self.assertRaisesRegex(OSError, "injected"):
                    add_voice(
                        registry,
                        voice_id="voice",
                        wav_path=_write_wav(root / "source.wav"),
                        reference_text="text",
                        x_vector_only=False,
                        preserve_reference_text_whitespace=False,
                    )
            self.assertFalse(registry.exists())
            self.assertEqual([], list((registry.parent / "entries").glob("*")))

    def test_add_quarantines_marked_orphan_without_deleting_nested_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "voices" / "registry.json"
            entries = registry.parent / "entries"
            orphan = entries / _internal_id("orphan")
            orphan.mkdir(parents=True)
            (orphan / ".qtb-managed-entry").write_text(
                json.dumps({"schema_version": 1, "voice_id": "orphan"}),
                encoding="utf-8",
            )
            (orphan / "reference.wav").write_bytes(b"orphan")
            (orphan / "native").mkdir()
            (orphan / "native" / "user-sentinel.txt").write_text(
                "keep", encoding="utf-8"
            )
            (orphan / "unexpected").mkdir()
            (orphan / "unexpected" / "nested.txt").write_text(
                "keep", encoding="utf-8"
            )
            user_dir = entries / "user-owned"
            user_dir.mkdir(parents=True)
            (user_dir / "sentinel").write_text("keep", encoding="utf-8")
            add_voice(
                registry,
                voice_id="voice",
                wav_path=_write_wav(root / "source.wav"),
                reference_text="text",
                x_vector_only=False,
                preserve_reference_text_whitespace=False,
            )
            quarantined = list((entries / ".qtb-orphans").glob("*"))
            self.assertEqual(1, len(quarantined))
            self.assertTrue(
                (quarantined[0] / "native" / "user-sentinel.txt").is_file()
            )
            self.assertTrue(
                (quarantined[0] / "unexpected" / "nested.txt").is_file()
            )
            self.assertTrue((user_dir / "sentinel").is_file())

    def test_orphan_quarantine_conflict_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            entries = root / "entries"
            orphan = entries / _internal_id("orphan")
            orphan.mkdir(parents=True)
            (orphan / ".qtb-managed-entry").write_text(
                json.dumps({"schema_version": 1, "voice_id": "orphan"}),
                encoding="utf-8",
            )
            quarantine = entries / ".qtb-orphans"
            (quarantine / f"{orphan.name}-fixed").mkdir(parents=True)
            with mock.patch(
                "qwen_tts_bridge_worker.voice_library.uuid.uuid4",
                return_value=mock.Mock(hex="fixed"),
            ):
                with self.assertRaisesRegex(VoiceLibraryError, "quarantine target"):
                    _cleanup_orphaned_entries(registry, [])
            self.assertTrue(orphan.is_dir())

    def test_orphan_quarantine_interruption_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            orphan = root / "entries" / _internal_id("orphan")
            orphan.mkdir(parents=True)
            (orphan / ".qtb-managed-entry").write_text(
                json.dumps({"schema_version": 1, "voice_id": "orphan"}),
                encoding="utf-8",
            )
            with mock.patch.object(Path, "replace", side_effect=OSError("injected")):
                _cleanup_orphaned_entries(registry, [])
            self.assertTrue(orphan.is_dir())

    def test_changed_managed_audio_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            row = add_voice(
                registry,
                voice_id="voice",
                wav_path=_write_wav(root / "source.wav"),
                reference_text="text",
                x_vector_only=False,
                preserve_reference_text_whitespace=False,
            )
            (registry.parent / row["reference_audio_path"]).write_bytes(b"changed")
            result = verify_voice(registry, "voice", backend="python")
            self.assertEqual("incompatible", result["status"])

    def test_registry_lock_conflict_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            registry.write_text(
                '{"schema_version": 1, "voices": []}\n', encoding="utf-8"
            )
            with _registry_lock(registry):
                with self.assertRaisesRegex(VoiceLibraryError, "being modified"):
                    add_voice(
                        registry,
                        voice_id="voice",
                        wav_path=_write_wav(root / "source.wav"),
                        reference_text="text",
                        x_vector_only=False,
                        preserve_reference_text_whitespace=False,
                    )

    def test_registry_lock_file_is_reusable_after_owner_termination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry.json"
            script = (
                "import sys,time; "
                "from pathlib import Path; "
                "from qwen_tts_bridge_worker.voice_library import _registry_lock; "
                "path=Path(sys.argv[1]); "
                "lock=_registry_lock(path); lock.__enter__(); "
                "print('ready', flush=True); time.sleep(30)"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(registry)],
                stdout=subprocess.PIPE,
                text=True,
            )
            assert process.stdout is not None
            try:
                self.assertEqual("ready\n", process.stdout.readline())
                with self.assertRaisesRegex(VoiceLibraryError, "being modified"):
                    with _registry_lock(registry):
                        pass
            finally:
                process.terminate()
                process.wait(timeout=5)
            with _registry_lock(registry):
                pass

    def test_native_manifest_path_traversal_is_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            row = {
                "voice_id": "voice",
                "reference_audio_path": "reference.wav",
                "reference_text": "text",
                "x_vector_only": False,
                "reference_audio_sha256": "0" * 64,
                "native_reference": {"manifest_path": "../outside.json"},
            }
            registry.write_text(
                json.dumps({"schema_version": 1, "voices": [row]}),
                encoding="utf-8",
            )
            result = verify_voice(
                registry,
                "voice",
                backend="native",
                native_profile="profile",
            )
            self.assertEqual("prepared_corrupt", result["status"])

    def test_native_verifier_rejects_non_finite_speaker_with_matching_hash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "native" / "manifest.json"
            row = {"reference_text": "text", "x_vector_only": False}
            wav = _write_wav(root / "reference.wav")
            talker = root / "talker.gguf"
            codec = root / "codec.gguf"
            talker.write_bytes(b"talker")
            codec.write_bytes(b"codec")
            _write_native_manifest(manifest_path, wav, row, talker, codec)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            speaker_path = manifest_path.parent / manifest["speaker"]["path"]
            for value in (float("nan"), float("inf"), float("-inf")):
                speaker_path.write_bytes(struct.pack("<f", value))
                manifest["speaker"]["sha256"] = _sha256(speaker_path)
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "NaN or Inf"):
                    _verify_prepared_artifacts(
                        manifest_path,
                        manifest,
                        False,
                    )

    def test_native_verifier_requires_explicit_null_rvq_for_x_vector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "native" / "manifest.json"
            row = {"reference_text": "", "x_vector_only": True}
            wav = _write_wav(root / "reference.wav")
            talker = root / "talker.gguf"
            codec = root / "codec.gguf"
            talker.write_bytes(b"talker")
            codec.write_bytes(b"codec")
            _write_native_manifest(manifest_path, wav, row, talker, codec)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["rvq"] = None
            _verify_prepared_artifacts(manifest_path, manifest, True)
            del manifest["rvq"]
            with self.assertRaisesRegex(ValueError, "requires rvq"):
                _verify_prepared_artifacts(manifest_path, manifest, True)

    def test_native_verifier_rejects_uppercase_artifact_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "native" / "manifest.json"
            row = {"reference_text": "text", "x_vector_only": False}
            wav = _write_wav(root / "reference.wav")
            talker = root / "talker.gguf"
            codec = root / "codec.gguf"
            talker.write_bytes(b"talker")
            codec.write_bytes(b"codec")
            _write_native_manifest(manifest_path, wav, row, talker, codec)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["speaker"]["sha256"] = manifest["speaker"]["sha256"].upper()
            with self.assertRaisesRegex(ValueError, "speaker artifact"):
                _verify_prepared_artifacts(manifest_path, manifest, False)

    def test_native_unsupported_runtime_abi_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _write_native_config(root)
            runtime_manifest = root / "runtime" / "manifest.json"
            payload = json.loads(runtime_manifest.read_text(encoding="utf-8"))
            payload["qt_abi_version"] = 7
            runtime_manifest.write_text(json.dumps(payload), encoding="utf-8")
            registry = root / "registry.json"
            add_voice(
                registry,
                voice_id="voice",
                wav_path=_write_wav(root / "source.wav"),
                reference_text="text",
                x_vector_only=False,
                preserve_reference_text_whitespace=False,
            )
            result = verify_voice(
                registry,
                "voice",
                backend="native",
                native_profile="native",
                config_path=config,
            )
            self.assertEqual("model_unavailable", result["status"])

    def test_malformed_nested_native_manifest_is_prepared_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            row = add_voice(
                registry,
                voice_id="voice",
                wav_path=_write_wav(root / "source.wav"),
                reference_text="text",
                x_vector_only=False,
                preserve_reference_text_whitespace=False,
            )
            config = _write_native_config(root)
            manifest_path = registry.parent / "native" / "manifest.json"
            _write_native_manifest(
                manifest_path,
                registry.parent / row["reference_audio_path"],
                row,
                root / "talker.gguf",
                root / "codec.gguf",
            )
            row["native_reference"] = {"manifest_path": "native/manifest.json"}
            registry.write_text(
                json.dumps({"schema_version": 1, "voices": [row]}),
                encoding="utf-8",
            )
            for field in ("engine", "models", "preprocessing"):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest[field] = []
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                result = verify_voice(
                    registry,
                    "voice",
                    backend="native",
                    native_profile="native",
                    config_path=config,
                )
                self.assertEqual("prepared_corrupt", result["status"])

    def test_cli_add_and_list_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "voice_library": {"registry_path": "registry.json"},
                    }
                ),
                encoding="utf-8",
            )
            wav = _write_wav(root / "source.wav")
            self.assertEqual(
                0,
                user_cli.main(
                    [
                        "--config",
                        str(config),
                        "voices",
                        "add",
                        "--id",
                        "voice",
                        "--wav",
                        str(wav),
                        "--text",
                        "text",
                    ]
                ),
            )
            with mock.patch("builtins.print") as printer:
                self.assertEqual(
                    0,
                    user_cli.main(
                        [
                            "--config",
                            str(config),
                            "voices",
                            "list",
                            "--json",
                        ]
                    ),
                )
            rows = json.loads(printer.call_args.args[0])
            self.assertEqual("voice", rows[0]["voice_id"])

    def test_native_prepare_protocol_uses_one_bounded_reader(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = _write_fake_worker(Path(temporary) / "worker.py", "ready")
            _run_native_prepare(
                [sys.executable, str(script)], "voice", timeout_seconds=2.0
            )

    def test_native_prepare_timeout_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = _write_fake_worker(Path(temporary) / "worker.py", "hang")
            with self.assertRaisesRegex(VoiceLibraryError, "before timeout"):
                _run_native_prepare(
                    [sys.executable, str(script)], "voice", timeout_seconds=0.1
                )

    def test_native_prepare_rejects_unadvertised_voice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = _write_fake_worker(Path(temporary) / "worker.py", "other")
            with self.assertRaisesRegex(VoiceLibraryError, "did not advertise"):
                _run_native_prepare(
                    [sys.executable, str(script)], "voice", timeout_seconds=2.0
                )

    def test_native_prepare_requires_structured_metric(self) -> None:
        for behavior, expected in (
            ("no_metric", "did not report voice preparation evidence"),
            ("wrong_voice_metric", "did not report voice preparation evidence"),
            ("invalid_source", "did not report voice preparation evidence"),
            ("bad_metric", "malformed qtb_metric JSON"),
        ):
            with (
                self.subTest(behavior=behavior),
                tempfile.TemporaryDirectory() as temporary,
            ):
                script = _write_fake_worker(Path(temporary) / "worker.py", behavior)
                with self.assertRaisesRegex(VoiceLibraryError, expected):
                    _run_native_prepare(
                        [sys.executable, str(script)], "voice", timeout_seconds=2.0
                    )

    def test_native_prepare_rejects_excessive_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = _write_fake_worker(Path(temporary) / "worker.py", "verbose")
            with self.assertRaisesRegex(VoiceLibraryError, "stderr exceeded"):
                _run_native_prepare(
                    [sys.executable, str(script)], "voice", timeout_seconds=2.0
                )

    def test_prepare_publishes_row_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "voices" / "registry.json"
            add_voice(
                registry,
                voice_id="voice",
                wav_path=_write_wav(root / "source.wav"),
                reference_text="text",
                x_vector_only=False,
                preserve_reference_text_whitespace=False,
            )
            config = _write_native_config(root)

            def publish(command: list[str], voice_id: str, _timeout: float) -> None:
                temp_registry = Path(
                    command[command.index("--voice-registry-path") + 1]
                )
                row = load_voice_rows(temp_registry, allow_missing=False)[0]
                relative = row["native_reference"]["manifest_path"]
                manifest_path = temp_registry.parent / relative
                _write_native_manifest(
                    manifest_path,
                    temp_registry.parent / row["reference_audio_path"],
                    row,
                    root / "talker.gguf",
                    root / "codec.gguf",
                )
                self.assertEqual("voice", voice_id)

            with mock.patch(
                "qwen_tts_bridge_worker.voice_library._run_native_prepare",
                side_effect=publish,
            ) as runner:
                first = prepare_voice(
                    registry,
                    "voice",
                    native_profile="native",
                    config_path=config,
                )
                second = prepare_voice(
                    registry,
                    "voice",
                    native_profile="native",
                    config_path=config,
                )

            self.assertEqual("prepared_valid", first["status"])
            self.assertFalse(first["idempotent"])
            self.assertTrue(second["idempotent"])
            self.assertEqual(1, runner.call_count)
            native = next(
                iter(load_voice_rows(registry)[0]["native_references"].values())
            )
            self.assertFalse(native["prepare_if_missing"])

            (root / "talker.gguf").write_bytes(b"changed")
            stale = verify_voice(
                registry,
                "voice",
                backend="native",
                native_profile="native",
                config_path=config,
            )
            self.assertEqual("prepared_stale", stale["status"])
            self.assertEqual("model_binding_changed", stale["reason"])
            with mock.patch(
                "qwen_tts_bridge_worker.voice_library._run_native_prepare",
                side_effect=publish,
            ):
                replacement = prepare_voice(
                    registry,
                    "voice",
                    native_profile="native",
                    config_path=config,
                )
            self.assertEqual("prepared_valid", replacement["status"])
            references = load_voice_rows(registry)[0]["native_references"]
            self.assertEqual(2, len(references))

    def test_python_compatible_16khz_voice_is_not_native_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "voices" / "registry.json"
            add_voice(
                registry,
                voice_id="voice",
                wav_path=_write_wav(root / "source.wav", sample_rate=16_000),
                reference_text="text",
                x_vector_only=False,
                preserve_reference_text_whitespace=False,
            )
            self.assertEqual(
                "compatible",
                verify_voice(registry, "voice", backend="python")["status"],
            )
            with self.assertRaisesRegex(VoiceLibraryError, "24000 Hz"):
                prepare_voice(
                    registry,
                    "voice",
                    native_profile="native",
                    config_path=_write_native_config(root),
                )


def _write_wav(path: Path, *, sample_rate: int = 24_000) -> Path:
    frames = bytearray()
    for index in range(int(sample_rate * 2.1)):
        sample = int(7_000 * math.sin(2 * math.pi * 220 * index / sample_rate))
        frames.extend(sample.to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)
    return path


def _write_fake_worker(path: Path, behavior: str) -> Path:
    path.write_text(
        """
import json
import struct
import sys
import time

header = struct.Struct("<4sHHHHIQ")
raw = sys.stdin.buffer.read(header.size)
if len(raw) != header.size:
    raise SystemExit(2)
_magic, _version, _size, _type, _flags, payload_size, _request = header.unpack(raw)
sys.stdin.buffer.read(payload_size)
behavior = %r
if behavior == "hang":
    time.sleep(5)
    raise SystemExit(0)
voice_ids = ["other"] if behavior == "other" else ["voice"]
if behavior == "bad_metric":
    sys.stderr.write("qtb_metric {not-json}\\n")
elif behavior == "verbose":
    sys.stderr.write("x" * (2 * 1024 * 1024))
elif behavior != "no_metric":
    metric = {
        "event": "native_voice_reference_ready",
        "voice_id": "other" if behavior == "wrong_voice_metric" else "voice",
        "source": "invalid" if behavior == "invalid_source" else "persisted",
    }
    sys.stderr.write("qtb_metric " + json.dumps(metric) + "\\n")
sys.stderr.flush()
payload = json.dumps({"message_type": "ready", "voice_ids": voice_ids}).encode()
sys.stdout.buffer.write(header.pack(b"QTB1", 1, 24, 1, 0, len(payload), 0) + payload)
sys.stdout.buffer.flush()
raw = sys.stdin.buffer.read(header.size)
if raw:
    payload_size = header.unpack(raw)[5]
    sys.stdin.buffer.read(payload_size)
    payload = json.dumps({"message_type": "shutdown_ack"}).encode()
    sys.stdout.buffer.write(
        header.pack(b"QTB1", 1, 24, 1, 0, len(payload), 0) + payload
    )
    sys.stdout.buffer.flush()
"""
        % behavior,
        encoding="utf-8",
    )
    return path


def _write_native_config(root: Path) -> Path:
    runtime = root / "runtime"
    runtime.mkdir()
    (runtime / "qwen.dll").write_bytes(b"dll")
    (runtime / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "engine": "qwentts.cpp",
                "engine_commit": "commit",
                "qt_abi_version": 6,
                "architecture": "x64",
                "backend": "cuda",
                "files": [
                    {
                        "path": "qwen.dll",
                        "sha256": _sha256(runtime / "qwen.dll"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "talker.gguf").write_bytes(b"talker")
    (root / "codec.gguf").write_bytes(b"codec")
    (root / "worker.exe").write_bytes(b"worker")
    config = root / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "native_profiles": {
                    "native": {
                        "runtime_dir": "runtime",
                        "talker_model": "talker.gguf",
                        "codec_model": "codec.gguf",
                        "worker": "worker.exe",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return config


def _write_native_manifest(
    path: Path,
    wav: Path,
    row: dict[str, object],
    talker: Path,
    codec: Path,
) -> None:
    path.parent.mkdir(parents=True)
    speaker = path.parent / "reference.spk"
    rvq = path.parent / "reference.rvq"
    speaker.write_bytes(b"\0\0\0\0")
    rvq.write_bytes(b"\0\0")
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "format": "qwen3-tts-native-voice-reference",
                "source_wav_sha256": _sha256(wav),
                "reference_text": row["reference_text"],
                "x_vector_only": row["x_vector_only"],
                "engine": {
                    "name": "qwentts.cpp",
                    "commit": "commit",
                    "abi_version": 6,
                },
                "models": {
                    "talker_sha256": _sha256(talker),
                    "codec_sha256": _sha256(codec),
                },
                "preprocessing": {
                    "version": 1,
                    "sample_rate": 24_000,
                    "channels": 1,
                    "sample_format": "float32",
                    "icl_trailing_silence_samples": 12_000,
                },
                "speaker": {
                    "path": speaker.name,
                    "sha256": _sha256(speaker),
                    "dimension": 1,
                    "size_bytes": 4,
                    "scalar": "float32-le",
                },
                "rvq": {
                    "path": rvq.name,
                    "sha256": _sha256(rvq),
                    "codebooks": 1,
                    "frames": 1,
                    "bits_per_code": 11,
                    "layout": "codebook-major-frame-fastest",
                    "size_bytes": 2,
                },
            }
        ),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
