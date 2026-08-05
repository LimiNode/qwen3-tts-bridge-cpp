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
            build_manifest = _build_manifest(root, tree_manifest_path)
            (root / "build-manifest.json").write_text(
                json.dumps(build_manifest),
                encoding="utf-8",
            )

            report = doctor.inspect_portable_runtime(portable_root=root)
            self.assertTrue(report["acceptance_pass"])

            runtime_file.write_bytes(b"runtime after")
            with self.assertRaisesRegex(ValueError, "does not match"):
                doctor.inspect_portable_runtime(portable_root=root)

    def test_rejects_runtime_bytecode_and_invalid_build_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "worker-python"
            python_root = root / "python"
            python_root.mkdir(parents=True)
            (root / ".qtb-portable-worker-root").write_text(
                "marker\n",
                encoding="utf-8",
            )
            (python_root / "python.exe").write_bytes(b"runtime")
            tree_manifest = doctor._runtime_tree_manifest(python_root)
            tree_manifest_path = root / "portable-python-tree-manifest.json"
            tree_manifest_path.write_bytes(doctor._canonical_json_bytes(tree_manifest))
            (root / "build-manifest.json").write_text(
                json.dumps(_build_manifest(root, tree_manifest_path)),
                encoding="utf-8",
            )

            cache = python_root / "Lib" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "doctor.cpython-311.pyc").write_bytes(b"bytecode")
            with self.assertRaisesRegex(ValueError, "forbidden bytecode"):
                doctor.inspect_portable_runtime(portable_root=root)

            for path in sorted(cache.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
            cache.rmdir()
            manifest = _build_manifest(root, tree_manifest_path)
            manifest["build_manifest_schema_version"] = 99
            (root / "build-manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "build manifest schema"):
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


def _build_manifest(root: Path, tree_manifest_path: Path) -> dict[str, object]:
    wheel_path = root / "wheels" / "worker.whl"
    wheel_path.parent.mkdir(exist_ok=True)
    wheel_path.write_bytes(b"worker wheel")
    return {
        "build_manifest_schema_version": 1,
        "generated_at_utc": "2026-08-05T00:00:00Z",
        "python": {
            "base_prefix": {"kind": "external_name", "path": "python"},
            "implementation": "CPython",
            "version": "3.11.0",
            "version_info": [3, 11, 0],
            "purelib": {"kind": "external_name", "path": "site-packages"},
            "platlib": {"kind": "external_name", "path": "site-packages"},
        },
        "python_tools": {
            "pip": "24.0",
            "setuptools": "80.0",
            "wheel": "0.45",
            "torch": "2.11",
            "transformers": "4.57",
            "torch_cuda": "12.6",
            "torch_cuda_available": "true",
        },
        "pip_freeze": ["example==1.0"],
        "wheels": [
            {
                "label": "worker",
                "requirement": "worker==1.0",
                "wheel": wheel_path.name,
                "wheel_sha256": _sha256_file(wheel_path),
                "wheel_artifact": "wheels/worker.whl",
                "source": {
                    "path": "worker",
                    "path_kind": "repo_relative",
                    "git_commit": "0" * 40,
                    "git_dirty": False,
                    "git_status": [],
                },
            }
        ],
        "portable_runtime_tree_manifest": {
            "path": tree_manifest_path.name,
            "sha256": _sha256_file(tree_manifest_path),
        },
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
