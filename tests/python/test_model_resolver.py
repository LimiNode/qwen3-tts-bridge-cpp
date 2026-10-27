from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qwen_tts_bridge_worker.model_resolver import (
    MODEL_CATALOG,
    download_model,
    hugging_face_cache_root,
    list_models,
    resolve_hf_snapshot,
    resolve_model,
    resolve_native_profile,
    validate_python_model,
)


class ModelResolverTests(unittest.TestCase):
    def test_explicit_path_has_precedence_over_config_portable_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            explicit = _write_model(root / "явная модель", "voice_design", "1b7")
            configured = _write_model(root / "configured", "voice_design", "1b7")
            portable = _write_model(
                root
                / "package"
                / "models"
                / MODEL_CATALOG["voice-design"].directory_name,
                "voice_design",
                "1b7",
            )
            _write_hf_model(root / "hub", "voice-design", "cache-revision")
            config = root / "config.json"
            _write_config(config, {"voice-design": {"path": str(configured)}})

            result = resolve_model(
                "voice-design",
                explicit_path=explicit,
                config_path=config,
                portable_root=portable.parents[1],
                environ={"HF_HUB_CACHE": str(root / "hub")},
            )

            self.assertEqual("explicit", result.source)
            self.assertEqual(explicit.resolve(), result.path)

    def test_config_precedes_portable_and_hf_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configured = _write_model(root / "configured", "voice_design", "1b7")
            _write_model(
                root
                / "package"
                / "models"
                / MODEL_CATALOG["voice-design"].directory_name,
                "voice_design",
                "1b7",
            )
            _write_hf_model(root / "hub", "voice-design", "cache-revision")
            config = root / "config.json"
            _write_config(config, {"voice-design": {"path": str(configured)}})

            result = resolve_model(
                "voice-design",
                config_path=config,
                portable_root=root / "package",
                environ={"HF_HUB_CACHE": str(root / "hub")},
            )

            self.assertEqual("config", result.source)

    def test_incompatible_explicit_model_does_not_fall_back_to_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            explicit = _write_model(root / "wrong", "base", "1b7")
            _write_hf_model(root / "hub", "voice-design", "cache-revision")
            with self.assertRaisesRegex(ValueError, "family mismatch"):
                resolve_model(
                    "voice-design",
                    explicit_path=explicit,
                    environ={"HF_HUB_CACHE": str(root / "hub")},
                )

    def test_configured_relative_model_path_is_relative_to_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = _write_model(root / "models" / "voice", "voice_design", "1b7")
            config = root / "config" / "qwen-tts.json"
            config.parent.mkdir()
            _write_config(
                config,
                {"voice-design": {"path": "../models/voice"}},
            )
            result = resolve_model("voice-design", config_path=config)
            self.assertEqual(expected.resolve(), result.path)

    def test_portable_precedes_hf_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            portable = _write_model(
                root
                / "package"
                / "models"
                / MODEL_CATALOG["voice-design"].directory_name,
                "voice_design",
                "1b7",
            )
            _write_hf_model(root / "hub", "voice-design", "cache-revision")
            result = resolve_model(
                "voice-design",
                portable_root=root / "package",
                environ={"HF_HUB_CACHE": str(root / "hub")},
            )
            self.assertEqual("portable", result.source)
            self.assertEqual(portable.resolve(), result.path)

    def test_hf_cache_honors_environment_precedence(self) -> None:
        env = {"HF_HOME": "C:/hf-home", "HF_HUB_CACHE": "D:/hub-cache"}
        self.assertEqual(Path("D:/hub-cache"), hugging_face_cache_root(env))
        self.assertEqual(
            Path("C:/hf-home/hub"), hugging_face_cache_root({"HF_HOME": "C:/hf-home"})
        )

    def test_hf_ref_resolves_exact_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            hub = Path(temporary)
            expected = _write_hf_model(hub, "voice-design", "abc123")
            repo = hub / "models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign"
            (repo / "refs").mkdir(parents=True)
            (repo / "refs" / "main").write_text("abc123\n", encoding="utf-8")
            path, revision = resolve_hf_snapshot(
                hub, MODEL_CATALOG["voice-design"].repository
            )
            self.assertEqual(expected.resolve(), path)
            self.assertEqual("abc123", revision)

    def test_multiple_unreferenced_hf_revisions_are_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            hub = Path(temporary)
            _write_hf_model(hub, "voice-design", "first")
            _write_hf_model(hub, "voice-design", "second")
            with self.assertRaisesRegex(ValueError, "multiple cached revisions"):
                resolve_hf_snapshot(hub, MODEL_CATALOG["voice-design"].repository)

    def test_incomplete_and_incompatible_models_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incomplete = _write_model(root / "incomplete", "voice_design", "1b7")
            (incomplete / "download.incomplete").write_bytes(b"pending")
            with self.assertRaisesRegex(ValueError, "incomplete download"):
                validate_python_model(incomplete, MODEL_CATALOG["voice-design"])
            wrong = _write_model(root / "wrong", "base", "1b7")
            with self.assertRaisesRegex(ValueError, "family mismatch"):
                validate_python_model(wrong, MODEL_CATALOG["voice-design"])

    def test_base_sizes_are_not_interchangeable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = _write_model(Path(temporary), "base", "0b6")
            with self.assertRaisesRegex(ValueError, "size mismatch"):
                validate_python_model(model, MODEL_CATALOG["base-1.7b"])

    def test_optional_model_manifest_is_content_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = _write_model(Path(temporary), "voice_design", "1b7")
            weights = model / "model.safetensors"
            (model / "model-runtime-manifest.json").write_text(
                json.dumps(
                    {
                        "runtime_files": [
                            {
                                "path": "model.safetensors",
                                "sha256": hashlib.sha256(
                                    weights.read_bytes()
                                ).hexdigest(),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            validate_python_model(model, MODEL_CATALOG["voice-design"])
            weights.write_bytes(b"mutated")
            with self.assertRaisesRegex(ValueError, "manifest integrity failed"):
                validate_python_model(model, MODEL_CATALOG["voice-design"])

    def test_missing_model_error_names_explicit_download_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(
                ValueError, "qwen-tts models download voice-design"
            ):
                resolve_model(
                    "voice-design",
                    config_path=root / "missing-config.json",
                    portable_root=root / "package",
                    environ={"HF_HUB_CACHE": str(root / "hub")},
                )

    def test_portable_download_is_staged_then_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "package"

            def fake_download(**kwargs: object) -> str:
                local = Path(str(kwargs["local_dir"]))
                self.assertTrue(local.name.endswith(".incomplete"))
                _write_model(local, "voice_design", "1b7")
                return str(local)

            result = download_model(
                "voice-design",
                portable_root=package,
                downloader=fake_download,
            )
            self.assertTrue(result.path.is_dir())
            self.assertFalse(
                (result.path.parent / f".{result.path.name}.incomplete").exists()
            )

    def test_hf_local_dir_metadata_is_not_model_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "package"

            def fake_download(**kwargs: object) -> str:
                local = _write_model(
                    Path(str(kwargs["local_dir"])), "voice_design", "1b7"
                )
                metadata = local / ".cache" / "huggingface" / "download"
                metadata.mkdir(parents=True)
                (metadata / "model.safetensors.lock").write_bytes(b"metadata")
                (metadata / "config.json.metadata").write_bytes(b"metadata")
                return str(local)

            result = download_model(
                "voice-design",
                portable_root=package,
                revision="0123456789abcdef",
                downloader=fake_download,
            )
            self.assertEqual("0123456789abcdef", result.revision)
            self.assertFalse((result.path / ".cache" / "huggingface").exists())
            validate_python_model(result.path, MODEL_CATALOG["voice-design"])

    def test_failed_download_removes_staging_and_keeps_target_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "package"

            def fake_download(**kwargs: object) -> str:
                local = Path(str(kwargs["local_dir"]))
                _write_model(local, "voice_design", "1b7")
                (local / "model.safetensors").unlink()
                return str(local)

            with self.assertRaisesRegex(ValueError, "missing: model.safetensors"):
                download_model(
                    "voice-design", portable_root=package, downloader=fake_download
                )
            target = package / "models" / MODEL_CATALOG["voice-design"].directory_name
            self.assertFalse(target.exists())
            self.assertFalse((target.parent / f".{target.name}.incomplete").exists())

    def test_existing_download_target_is_not_modified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "package"
            target = package / "models" / MODEL_CATALOG["voice-design"].directory_name
            target.mkdir(parents=True)
            sentinel = target / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already exists"):
                download_model(
                    "voice-design",
                    portable_root=package,
                    downloader=lambda **_kwargs: "unused",
                )
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

    def test_models_list_reports_invalid_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "package"
            invalid = _write_model(
                package / "models" / MODEL_CATALOG["voice-design"].directory_name,
                "base",
                "1b7",
            )
            rows = list_models(
                config_path=Path(temporary) / "missing.json",
                portable_root=package,
                environ={"HF_HUB_CACHE": str(Path(temporary) / "hub")},
            )
            self.assertEqual(1, len(rows))
            self.assertFalse(rows[0].structurally_valid)
            self.assertEqual(invalid.resolve(), rows[0].path)
            self.assertIn("family mismatch", rows[0].error or "")

    def test_integrity_status_requires_complete_signed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = _write_model(Path(temporary) / "model", "voice_design", "1b7")
            self.assertFalse(
                validate_python_model(model, MODEL_CATALOG["voice-design"])
            )

            runtime_files = []
            for path in sorted(item for item in model.rglob("*") if item.is_file()):
                runtime_files.append(
                    {
                        "path": path.relative_to(model).as_posix(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "size_bytes": path.stat().st_size,
                    }
                )
            manifest: dict[str, object] = {
                "model_runtime_manifest_schema_version": 1,
                "runtime_files": runtime_files,
            }
            canonical = (
                json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            manifest["directory_manifest_sha256"] = hashlib.sha256(
                canonical
            ).hexdigest()
            (model / "model-runtime-manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            self.assertTrue(
                validate_python_model(model, MODEL_CATALOG["voice-design"])
            )

    def test_unwritable_portable_destination_fails_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            called = False

            def fake_download(**_kwargs: object) -> str:
                nonlocal called
                called = True
                return ""

            with mock.patch(
                "qwen_tts_bridge_worker.model_resolver._assert_writable_parent",
                side_effect=ValueError("download destination is not writable"),
            ):
                with self.assertRaisesRegex(ValueError, "not writable"):
                    download_model(
                        "voice-design",
                        portable_root=Path(temporary),
                        downloader=fake_download,
                    )
            self.assertFalse(called)

    def test_custom_download_directory_receives_catalog_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "models"

            def fake_download(**kwargs: object) -> str:
                local = Path(str(kwargs["local_dir"]))
                _write_model(local, "voice_design", "1b7")
                return str(local)

            result = download_model(
                "voice-design",
                destination=destination,
                downloader=fake_download,
            )
            self.assertEqual(
                destination.resolve() / MODEL_CATALOG["voice-design"].directory_name,
                result.path,
            )

    def test_native_profile_keeps_gguf_and_dll_contract_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "qwen.dll").write_bytes(b"dll")
            talker = root / "models" / "talker.gguf"
            codec = root / "models" / "codec.gguf"
            talker.parent.mkdir()
            talker.write_bytes(b"talker")
            codec.write_bytes(b"codec")
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "native_profiles": {
                            "ru": {
                                "runtime_dir": "runtime",
                                "talker_model": "models/talker.gguf",
                                "codec_model": "models/codec.gguf",
                                "talker_sha256": hashlib.sha256(b"talker").hexdigest(),
                                "codec_sha256": hashlib.sha256(b"codec").hexdigest(),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            profile = resolve_native_profile("ru", config_path=config)
            self.assertEqual(talker.resolve(), profile.talker_model)
            self.assertEqual(codec.resolve(), profile.codec_model)


def _write_config(path: Path, models: dict[str, object]) -> None:
    path.write_text(
        json.dumps({"schema_version": 1, "models": models}),
        encoding="utf-8",
    )


def _write_hf_model(hub: Path, family: str, revision: str) -> Path:
    spec = MODEL_CATALOG[family]
    root = (
        hub / ("models--" + spec.repository.replace("/", "--")) / "snapshots" / revision
    )
    return _write_model(root, spec.model_type, spec.model_size)


def _write_model(root: Path, model_type: str, model_size: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
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


if __name__ == "__main__":
    unittest.main()
