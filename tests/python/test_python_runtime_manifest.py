"""Tests for the installed-distribution runtime manifest helper."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts import python_runtime_manifest as manifest


class PythonRuntimeManifestTests(unittest.TestCase):
    def test_manifest_hash_and_verification_are_content_sensitive(self) -> None:
        distributions = [{"name": "example", "version": "1", "files": []}]
        with patch.object(
            manifest,
            "_installed_distributions",
            return_value=distributions,
        ):
            result = manifest.build_manifest()
            manifest.verify_manifest(result)

            changed = dict(result)
            changed["distributions"] = [
                {"name": "example", "version": "2", "files": []}
            ]
            with self.assertRaisesRegex(ValueError, "SHA is invalid"):
                manifest.verify_manifest(changed)

    def test_verification_rejects_changed_installed_content(self) -> None:
        expected = [{"name": "example", "version": "1", "files": []}]
        actual = [
            {
                "name": "example",
                "version": "1",
                "files": [{"path": "x", "sha256": "a"}],
            }
        ]
        with patch.object(manifest, "_installed_distributions", return_value=expected):
            result = manifest.build_manifest()
        with patch.object(manifest, "_installed_distributions", return_value=actual):
            with self.assertRaisesRegex(ValueError, "do not match"):
                manifest.verify_manifest(result)


if __name__ == "__main__":
    unittest.main()
