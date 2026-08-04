"""Validate a staged portable worker before starting a real Qwen workload."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from qwen_tts_bridge_worker.engine.voice_profiles import VoiceProfileRegistry

_PORTABLE_MARKER = ".qtb-portable-worker-root"
_RUNTIME_TREE_SCHEMA = 1
_MODEL_MANIFEST_SCHEMA = 2
_TRANSIENT_RUNTIME_DIRECTORIES = {"__pycache__"}
_TRANSIENT_RUNTIME_SUFFIXES = {".pyc", ".pyo"}
_TRANSIENT_MODEL_DIRECTORIES = {".cache"}
_TRANSIENT_MODEL_SUFFIXES = {".incomplete", ".lock", ".partial", ".tmp"}


def main(argv: Sequence[str] | None = None) -> int:
    """Run portable-runtime checks and write a machine-readable result."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        report = inspect_portable_runtime(
            portable_root=args.portable_root,
            model_path=args.model_path,
            model_manifest=args.model_manifest,
            voice_registry=args.voice_registry,
            require_cuda=args.require_cuda,
            minimum_compute_capability=args.minimum_compute_capability,
            minimum_driver_version=args.minimum_driver_version,
        )
    except ValueError as exc:
        print(json.dumps({"acceptance_pass": False, "failures": [str(exc)]}))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


def inspect_portable_runtime(
    *,
    portable_root: Path,
    model_path: Path | None = None,
    model_manifest: Path | None = None,
    voice_registry: Path | None = None,
    require_cuda: bool = False,
    minimum_compute_capability: str | None = None,
    minimum_driver_version: str | None = None,
) -> dict[str, object]:
    """Return a report or raise ``ValueError`` when a required check fails."""

    root = portable_root.resolve()
    runtime = _verify_portable_runtime(root)
    report: dict[str, object] = {
        "acceptance_pass": True,
        "portable_root": str(root),
        "runtime": runtime,
    }
    if (model_path is None) != (model_manifest is None):
        raise ValueError("model_path and model_manifest must be supplied together")
    if model_path is not None and model_manifest is not None:
        report["model"] = _verify_model_runtime(
            model_path.resolve(),
            _load_json_object(model_manifest.resolve()),
        )
    if voice_registry is not None:
        registry = VoiceProfileRegistry.from_json_file(voice_registry.resolve(), 1)
        report["voice_profiles"] = {
            "registry": str(voice_registry.resolve()),
            "count": len(registry.voice_ids),
            "voice_ids": list(registry.voice_ids),
        }
    report["gpu"] = _gpu_report(
        require_cuda=require_cuda,
        minimum_compute_capability=minimum_compute_capability,
        minimum_driver_version=minimum_driver_version,
    )
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--portable-root",
        type=Path,
        default=Path(sys.executable).resolve().parent.parent,
    )
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--model-manifest", type=Path)
    parser.add_argument("--voice-registry", type=Path)
    parser.add_argument("--require-cuda", action="store_true")
    parser.add_argument("--minimum-compute-capability")
    parser.add_argument("--minimum-driver-version")
    return parser


def _verify_portable_runtime(root: Path) -> dict[str, object]:
    if not (root / _PORTABLE_MARKER).is_file():
        raise ValueError(f"portable worker marker is missing: {root}")
    python_root = root / "python"
    build_manifest_path = root / "build-manifest.json"
    build_manifest = _load_json_object(build_manifest_path)
    tree_entry = build_manifest.get("portable_runtime_tree_manifest")
    if not isinstance(tree_entry, dict):
        raise ValueError("portable build manifest has no runtime tree entry")
    tree_name = tree_entry.get("path")
    expected_tree_sha256 = tree_entry.get("sha256")
    if (
        not isinstance(tree_name, str)
        or Path(tree_name).name != tree_name
        or not isinstance(expected_tree_sha256, str)
        or len(expected_tree_sha256) != 64
    ):
        raise ValueError("portable build manifest has an invalid runtime tree entry")
    tree_manifest_path = root / tree_name
    if not tree_manifest_path.is_file():
        raise ValueError(
            f"portable runtime tree manifest is missing: {tree_manifest_path}"
        )
    if _sha256_file(tree_manifest_path) != expected_tree_sha256:
        raise ValueError("portable build manifest runtime tree SHA does not match")
    tree_manifest = _load_json_object(tree_manifest_path)
    _verify_runtime_tree_manifest(python_root, tree_manifest)
    return {
        "build_manifest": str(build_manifest_path),
        "runtime_tree_manifest": str(tree_manifest_path),
        "runtime_tree_manifest_sha256": expected_tree_sha256,
    }


def _verify_runtime_tree_manifest(root: Path, manifest: dict[str, object]) -> None:
    if manifest.get("runtime_tree_manifest_schema_version") != _RUNTIME_TREE_SCHEMA:
        raise ValueError("unsupported portable runtime tree manifest schema")
    expected_hash = manifest.get("runtime_tree_manifest_sha256")
    unsigned = dict(manifest)
    unsigned.pop("runtime_tree_manifest_sha256", None)
    if (
        not isinstance(expected_hash, str)
        or _sha256(_canonical_json_bytes(unsigned)) != expected_hash
    ):
        raise ValueError("portable runtime tree manifest SHA is invalid")
    if manifest != _runtime_tree_manifest(root):
        raise ValueError("portable runtime tree does not match manifest")


def _runtime_tree_manifest(root: Path) -> dict[str, object]:
    files = _runtime_files(root)
    payload: dict[str, object] = {
        "runtime_tree_manifest_schema_version": _RUNTIME_TREE_SCHEMA,
        "runtime_files": [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in files
        ],
    }
    payload["runtime_tree_manifest_sha256"] = _sha256(_canonical_json_bytes(payload))
    return payload


def _verify_model_runtime(
    model_path: Path,
    manifest: dict[str, object],
) -> dict[str, object]:
    if manifest.get("model_runtime_manifest_schema_version") != _MODEL_MANIFEST_SCHEMA:
        raise ValueError("unsupported model runtime manifest schema")
    expected_hash = manifest.get("directory_manifest_sha256")
    unsigned = dict(manifest)
    unsigned.pop("directory_manifest_sha256", None)
    if (
        not isinstance(expected_hash, str)
        or _sha256(_canonical_json_bytes(unsigned)) != expected_hash
    ):
        raise ValueError("model runtime manifest SHA is invalid")
    expected_files = manifest.get("runtime_files")
    if not isinstance(expected_files, list) or not expected_files:
        raise ValueError("model runtime manifest has no runtime files")
    actual_files = {
        path.relative_to(model_path).as_posix(): path
        for path in _model_files(model_path)
    }
    expected_paths: set[str] = set()
    for entry in expected_files:
        if not isinstance(entry, dict):
            raise ValueError("model runtime manifest file entry is invalid")
        relative_path = entry.get("path")
        expected_sha256 = entry.get("sha256")
        expected_size = entry.get("size_bytes")
        if (
            not isinstance(relative_path, str)
            or Path(relative_path).is_absolute()
            or ".." in Path(relative_path).parts
            or not isinstance(expected_sha256, str)
            or not isinstance(expected_size, int)
            or expected_size < 0
            or relative_path in expected_paths
        ):
            raise ValueError("model runtime manifest file entry is invalid")
        expected_paths.add(relative_path)
        actual_path = actual_files.get(relative_path)
        if actual_path is None:
            raise ValueError(f"model runtime file is missing: {relative_path}")
        if actual_path.stat().st_size != expected_size:
            raise ValueError(f"model runtime file size does not match: {relative_path}")
        if _sha256_file(actual_path) != expected_sha256:
            raise ValueError(f"model runtime file SHA does not match: {relative_path}")
    if set(actual_files) != expected_paths:
        raise ValueError("model runtime file set does not match manifest")
    return {
        "path": str(model_path),
        "repository": manifest.get("repository"),
        "revision": manifest.get("revision"),
        "directory_manifest_sha256": expected_hash,
    }


def _gpu_report(
    *,
    require_cuda: bool,
    minimum_compute_capability: str | None,
    minimum_driver_version: str | None,
) -> dict[str, object]:
    try:
        import torch
    except ModuleNotFoundError as exc:
        if require_cuda:
            raise ValueError(
                "PyTorch is unavailable for the required CUDA check"
            ) from exc
        return {"cuda_available": False, "torch": None}
    cuda_available = bool(torch.cuda.is_available())
    if require_cuda and not cuda_available:
        raise ValueError("CUDA is required but unavailable")
    report: dict[str, object] = {
        "cuda_available": cuda_available,
        "torch": str(torch.__version__),
        "cuda_runtime": str(torch.version.cuda),
    }
    if not cuda_available:
        return report
    capability = tuple(int(value) for value in torch.cuda.get_device_capability(0))
    report.update(
        {
            "gpu_name": str(torch.cuda.get_device_name(0)),
            "gpu_capability": list(capability),
            "gpu_total_memory_bytes": int(
                torch.cuda.get_device_properties(0).total_memory
            ),
        }
    )
    if minimum_compute_capability is not None:
        minimum_capability = _parse_version(minimum_compute_capability)
        if capability < minimum_capability:
            raise ValueError(
                "GPU compute capability is below the required minimum: "
                f"{capability[0]}.{capability[1]} < {minimum_compute_capability}"
            )
        report["minimum_compute_capability"] = minimum_compute_capability
    driver_version = _nvidia_driver_version()
    report["nvidia_driver_version"] = driver_version
    if minimum_driver_version is not None:
        if not driver_version:
            raise ValueError("NVIDIA driver version is unavailable")
        if _parse_version(driver_version) < _parse_version(minimum_driver_version):
            raise ValueError(
                "NVIDIA driver version is below the required minimum: "
                f"{driver_version} < {minimum_driver_version}"
            )
        report["minimum_driver_version"] = minimum_driver_version
    return report


def _runtime_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise ValueError(f"portable runtime root is not a directory: {root}")
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and not _is_transient_runtime_path(path.relative_to(root))
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _model_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise ValueError(f"model path is not a directory: {root}")
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and not _is_transient_model_path(path.relative_to(root))
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _is_transient_runtime_path(path: Path) -> bool:
    return bool(set(path.parts).intersection(_TRANSIENT_RUNTIME_DIRECTORIES)) or (
        path.suffix in _TRANSIENT_RUNTIME_SUFFIXES
    )


def _is_transient_model_path(path: Path) -> bool:
    return bool(set(path.parts).intersection(_TRANSIENT_MODEL_DIRECTORIES)) or (
        path.suffix in _TRANSIENT_MODEL_SUFFIXES
    )


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"manifest is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"manifest is not an object: {path}")
    return value


def _nvidia_driver_version() -> str:
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""


def _parse_version(value: str) -> tuple[int, ...]:
    parts = value.split(".")
    if not parts or any(not part.isdecimal() for part in parts):
        raise ValueError(f"version must contain decimal components: {value}")
    return tuple(int(part) for part in parts)


def _canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
