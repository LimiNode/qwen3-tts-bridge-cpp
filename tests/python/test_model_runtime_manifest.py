"""Tests for pinned local model runtime manifests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import cast

from scripts.model_runtime_manifest import (
    _load_manifest,
    build_manifest,
    compare_manifests,
    verify_manifest,
)


class ModelRuntimeManifestTests(unittest.TestCase):
    def test_round_trip_accepts_complete_runtime_file_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            model = Path(temporary_name)
            _write_runtime_files(model)

            manifest = build_manifest(model, "Qwen/example", "revision")

            verify_manifest(model, manifest)

    def test_rejects_changed_or_extra_model_directory_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            model = Path(temporary_name)
            _write_runtime_files(model)
            manifest = build_manifest(model, "Qwen/example", "revision")

            (model / "config.json").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                verify_manifest(model, manifest)

            (model / "config.json").write_text("config", encoding="utf-8")
            (model / "tokenizer.json").write_text("extra", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file set"):
                verify_manifest(model, manifest)

    def test_compare_reports_precise_file_level_manifest_difference(self) -> None:
        with (
            tempfile.TemporaryDirectory() as left_name,
            tempfile.TemporaryDirectory() as right_name,
        ):
            left = Path(left_name)
            right = Path(right_name)
            _write_runtime_files(left)
            _write_runtime_files(right)
            (right / "config.json").write_text("changed", encoding="utf-8")
            (right / "added.json").write_text("added", encoding="utf-8")
            (right / "speech_tokenizer" / "configuration.json").unlink()

            comparison = compare_manifests(
                build_manifest(left, "Qwen/example", "pinned"),
                build_manifest(right, "Qwen/example", "pinned"),
            )

            self.assertTrue(comparison["same_repository"])
            self.assertTrue(comparison["same_revision"])
            self.assertFalse(comparison["same_directory_manifest"])
            self.assertFalse(comparison["manifests_equal"])
            self.assertEqual(["added.json"], comparison["added_paths"])
            self.assertEqual(
                ["speech_tokenizer/configuration.json"], comparison["removed_paths"]
            )
            changed_files = cast(
                list[dict[str, object]], comparison["changed_files"]
            )
            self.assertEqual("config.json", changed_files[0]["path"])

    def test_rejects_duplicate_json_keys_and_invalid_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            manifest_path = Path(temporary_name) / "manifest.json"
            manifest_path.write_text(
                '{"repository":"first","repository":"second"}', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "invalid model runtime manifest"):
                _load_manifest(manifest_path)

            model = Path(temporary_name) / "model"
            _write_runtime_files(model)
            manifest = build_manifest(model, "Qwen/example", "revision")
            manifest["repository"] = ""
            with self.assertRaisesRegex(ValueError, "repository is invalid"):
                verify_manifest(model, manifest)

            manifest = build_manifest(model, "Qwen/example", "revision")
            runtime_files = manifest["runtime_files"]
            assert isinstance(runtime_files, list)
            first = runtime_files[0]
            assert isinstance(first, dict)
            first["sha256"] = "z" * 64
            with self.assertRaisesRegex(ValueError, "SHA is invalid"):
                verify_manifest(model, manifest)


def _write_runtime_files(model: Path) -> None:
    (model / "speech_tokenizer").mkdir(parents=True)
    (model / "config.json").write_text("config", encoding="utf-8")
    (model / "model.safetensors").write_text("weights", encoding="utf-8")
    (model / "speech_tokenizer" / "configuration.json").write_text(
        "speech config", encoding="utf-8"
    )
    (model / ".cache").mkdir()
    (model / ".cache" / "ignored.json").write_text("cache", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
