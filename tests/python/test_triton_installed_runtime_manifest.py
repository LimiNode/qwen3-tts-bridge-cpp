"""Tests for installed Triton content manifests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from scripts.triton_installed_runtime_manifest import build_manifest, verify_manifest


class _FakeDistribution:
    def __init__(self, root: Path) -> None:
        self._root = root
        self.metadata = {"Name": "triton-windows"}
        self.version = "3.6.0.post26"
        self.files = [
            PurePosixPath("triton/__init__.py"),
            PurePosixPath("triton/runtime.dll"),
            PurePosixPath("triton_windows-3.6.0.post26.dist-info/METADATA"),
            PurePosixPath("triton_windows-3.6.0.post26.dist-info/RECORD"),
        ]

    def locate_file(self, path: object) -> Path:
        return self._root / Path(str(path))


class TritonInstalledRuntimeManifestTests(unittest.TestCase):
    def test_round_trip_captures_every_owned_package_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            distribution = _write_distribution(Path(temporary_name))
            with patch(
                "scripts.triton_installed_runtime_manifest.importlib.metadata.distribution",
                return_value=distribution,
            ):
                manifest = build_manifest("triton-windows")
                verify_manifest("triton-windows", manifest)

    def test_rejects_changed_or_unrecorded_installed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            distribution = _write_distribution(root)
            with patch(
                "scripts.triton_installed_runtime_manifest.importlib.metadata.distribution",
                return_value=distribution,
            ):
                manifest = build_manifest("triton-windows")

                (root / "triton" / "runtime.dll").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "SHA does not match"):
                    verify_manifest("triton-windows", manifest)

                (root / "triton" / "runtime.dll").write_bytes(b"runtime")
                (root / "triton" / "injected.py").write_text(
                    "print('unexpected')", encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, "file set does not match"):
                    verify_manifest("triton-windows", manifest)


def _write_distribution(root: Path) -> _FakeDistribution:
    package = root / "triton"
    metadata = root / "triton_windows-3.6.0.post26.dist-info"
    package.mkdir()
    metadata.mkdir()
    (package / "__init__.py").write_text("__version__ = 'test'", encoding="utf-8")
    (package / "runtime.dll").write_bytes(b"runtime")
    (metadata / "METADATA").write_text("Name: triton-windows", encoding="utf-8")
    (metadata / "RECORD").write_text(
        "triton/__init__.py,,\ntriton/runtime.dll,,\n", encoding="utf-8"
    )
    return _FakeDistribution(root)


if __name__ == "__main__":
    unittest.main()
