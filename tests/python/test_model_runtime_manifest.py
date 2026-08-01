"""Tests for pinned local model runtime manifests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.model_runtime_manifest import build_manifest, verify_manifest


class ModelRuntimeManifestTests(unittest.TestCase):
    def test_round_trip_accepts_complete_runtime_file_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            model = Path(temporary_name)
            _write_runtime_files(model)

            manifest = build_manifest(model, "Qwen/example", "revision")

            verify_manifest(model, manifest)

    def test_rejects_changed_or_extra_runtime_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            model = Path(temporary_name)
            _write_runtime_files(model)
            manifest = build_manifest(model, "Qwen/example", "revision")

            (model / "config.json").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                verify_manifest(model, manifest)

            (model / "config.json").write_text("config", encoding="utf-8")
            (model / "speech_tokenizer" / "vocab.json").write_text(
                "extra", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "file set"):
                verify_manifest(model, manifest)


def _write_runtime_files(model: Path) -> None:
    (model / "speech_tokenizer").mkdir()
    (model / "config.json").write_text("config", encoding="utf-8")
    (model / "model.safetensors").write_text("weights", encoding="utf-8")
    (model / "speech_tokenizer" / "configuration.json").write_text(
        "speech config", encoding="utf-8"
    )
    (model / ".cache").mkdir()
    (model / ".cache" / "ignored.json").write_text("cache", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
