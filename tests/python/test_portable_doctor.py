"""Tests for portable-worker runtime validation."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from qwen_tts_bridge_worker import doctor


class PortableDoctorTests(unittest.TestCase):
    def test_verifies_staged_runtime_and_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "worker-python"
            python_root = root / "python"
            python_root.mkdir(parents=True)
            (root / ".qtb-portable-worker-root").write_text(
                "marker\n",
                encoding="utf-8",
            )
            runtime_file = python_root / "python.exe"
            runtime_file.write_bytes(b"runtime before")
            tree_manifest = doctor._runtime_tree_manifest(python_root)
            tree_manifest_path = root / "portable-python-tree-manifest.json"
            tree_manifest_path.write_bytes(doctor._canonical_json_bytes(tree_manifest))
            build_manifest = {
                "portable_runtime_tree_manifest": {
                    "path": tree_manifest_path.name,
                    "sha256": _sha256_file(tree_manifest_path),
                }
            }
            (root / "build-manifest.json").write_text(
                json.dumps(build_manifest),
                encoding="utf-8",
            )

            report = doctor.inspect_portable_runtime(portable_root=root)
            self.assertTrue(report["acceptance_pass"])

            runtime_file.write_bytes(b"runtime after")
            with self.assertRaisesRegex(ValueError, "does not match"):
                doctor.inspect_portable_runtime(portable_root=root)

    def test_verifies_model_manifest_and_rejects_changed_model_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            model = root / "model"
            model.mkdir()
            weights = model / "weights.safetensors"
            weights.write_bytes(b"weights before")
            manifest = _model_manifest(model)

            report = doctor._verify_model_runtime(model, manifest)
            self.assertEqual("example/model", report["repository"])

            weights.write_bytes(b"changed before")
            with self.assertRaisesRegex(ValueError, "SHA does not match"):
                doctor._verify_model_runtime(model, manifest)


def _model_manifest(model: Path) -> dict[str, object]:
    files = doctor._model_files(model)
    payload: dict[str, object] = {
        "model_runtime_manifest_schema_version": 2,
        "repository": "example/model",
        "revision": "deadbeef",
        "runtime_files": [
            {
                "path": path.relative_to(model).as_posix(),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in files
        ],
    }
    payload["directory_manifest_sha256"] = doctor._sha256(
        doctor._canonical_json_bytes(payload)
    )
    return payload


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
