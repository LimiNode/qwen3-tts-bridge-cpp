"""Tests for the portable runtime tree manifest helper."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import runtime_tree_manifest as manifest


class RuntimeTreeManifestTests(unittest.TestCase):
    def test_verification_rejects_changed_or_extra_runtime_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "python.exe"
            target.write_bytes(b"before")
            expected = manifest.build_manifest(root)
            manifest.verify_manifest(root, expected)

            target.write_bytes(b"after")
            with self.assertRaisesRegex(ValueError, "does not match"):
                manifest.verify_manifest(root, expected)

            target.write_bytes(b"before")
            (root / "added.dll").write_bytes(b"added")
            with self.assertRaisesRegex(ValueError, "does not match"):
                manifest.verify_manifest(root, expected)

    def test_transient_bytecode_does_not_change_runtime_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "module.py").write_text("value = 1\n", encoding="utf-8")
            expected = manifest.build_manifest(root)
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "module.cpython-311.pyc").write_bytes(b"transient")
            manifest.verify_manifest(root, expected)


if __name__ == "__main__":
    unittest.main()
