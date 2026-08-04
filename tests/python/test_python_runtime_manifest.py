"""Tests for the installed-runtime manifest helper."""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import python_runtime_manifest as manifest


class PythonRuntimeManifestTests(unittest.TestCase):
    def test_manifest_hash_and_verification_are_content_sensitive(self) -> None:
        distributions = [{"name": "example", "version": "1", "files": []}]
        runtime_files = [
            {"root": "executable", "path": "python.exe", "sha256": "a", "size_bytes": 1}
        ]
        with (
            patch.object(
                manifest,
                "_installed_distributions",
                return_value=distributions,
            ),
            patch.object(manifest, "_runtime_files", return_value=runtime_files),
        ):
            result = manifest.build_manifest()
            manifest.verify_manifest(result)

            changed = dict(result)
            changed["distributions"] = [
                {"name": "example", "version": "2", "files": []}
            ]
            with self.assertRaisesRegex(ValueError, "SHA is invalid"):
                manifest.verify_manifest(changed)

    def test_verification_rejects_file_changed_without_record_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            package = root / "example.py"
            package.write_text("value = 'before'\n", encoding="utf-8")
            metadata = root / "example-1.0.dist-info"
            metadata.mkdir()
            (metadata / "METADATA").write_text(
                "Name: example\nVersion: 1.0\n", encoding="utf-8"
            )
            package_hash = _record_hash(package.read_bytes())
            (metadata / "RECORD").write_text(
                "example.py,sha256=" + package_hash + ",17\n"
                "example-1.0.dist-info/METADATA,,\n"
                "example-1.0.dist-info/RECORD,,\n",
                encoding="utf-8",
            )
            distribution = importlib.metadata.PathDistribution(metadata)
            with (
                patch.object(
                    importlib.metadata,
                    "distributions",
                    return_value=[distribution],
                ),
                patch.object(manifest.sys, "prefix", str(root)),
                patch.object(
                    manifest,
                    "_runtime_file_roots",
                    return_value=[("purelib", root)],
                ),
            ):
                expected = manifest.build_manifest()
                manifest.verify_manifest(expected)

                package.write_text("value = 'after'\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "does not match"):
                    manifest.verify_manifest(expected)

    def test_runtime_tree_records_untracked_package_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "declared.py").write_text("declared\n", encoding="utf-8")
            with patch.object(
                manifest,
                "_runtime_file_roots",
                return_value=[("purelib", root)],
            ):
                entries = manifest._runtime_files(manifest._FileHasher())
            self.assertEqual(["declared.py"], [entry["path"] for entry in entries])

            (root / "extra_module.py").write_text("extra\n", encoding="utf-8")
            with patch.object(
                manifest,
                "_runtime_file_roots",
                return_value=[("purelib", root)],
            ):
                changed_entries = manifest._runtime_files(manifest._FileHasher())
            self.assertEqual(
                ["declared.py", "extra_module.py"],
                [entry["path"] for entry in changed_entries],
            )


def _record_hash(value: bytes) -> str:
    digest = hashlib.sha256(value).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


if __name__ == "__main__":
    unittest.main()
