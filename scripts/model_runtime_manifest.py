"""Build and verify a content manifest for local Qwen runtime model files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

_SCHEMA_VERSION = 1
_RUNTIME_FILE_NAMES = {
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "vocab.json",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--model-path", type=Path, required=True)
    build_parser.add_argument("--repository", required=True)
    build_parser.add_argument("--revision", required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--model-path", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "build":
        manifest = build_manifest(args.model_path, args.repository, args.revision)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(_json_bytes(manifest))
        return 0

    verify_manifest(args.model_path, _load_manifest(args.manifest))
    return 0


def build_manifest(
    model_path: Path,
    repository: str,
    revision: str,
) -> dict[str, object]:
    """Return a deterministic manifest of all model files loaded at runtime."""

    if not repository or not revision:
        raise ValueError("repository and revision must be non-empty")
    files = _runtime_files(model_path)
    payload: dict[str, object] = {
        "model_runtime_manifest_schema_version": _SCHEMA_VERSION,
        "repository": repository,
        "revision": revision,
        "runtime_files": [
            {
                "path": path.relative_to(model_path).as_posix(),
                "sha256": _sha256(path.read_bytes()),
                "size_bytes": path.stat().st_size,
            }
            for path in files
        ],
    }
    payload["directory_manifest_sha256"] = _sha256(_json_bytes(payload))
    return payload


def verify_manifest(model_path: Path, manifest: dict[str, object]) -> None:
    """Raise ``ValueError`` unless a model directory matches its manifest."""

    if manifest.get("model_runtime_manifest_schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported model runtime manifest schema")
    expected_files = manifest.get("runtime_files")
    if not isinstance(expected_files, list) or not expected_files:
        raise ValueError("model runtime manifest has no runtime files")
    unsigned = dict(manifest)
    expected_directory_sha256 = unsigned.pop("directory_manifest_sha256", None)
    if not isinstance(expected_directory_sha256, str) or (
        _sha256(_json_bytes(unsigned)) != expected_directory_sha256
    ):
        raise ValueError("model runtime manifest SHA is invalid")

    actual_paths = {
        path.relative_to(model_path).as_posix(): path
        for path in _runtime_files(model_path)
    }
    expected_paths: set[str] = set()
    for entry in expected_files:
        if not isinstance(entry, dict):
            raise ValueError("model runtime manifest file entry is invalid")
        relative_path = entry.get("path")
        expected_sha256 = entry.get("sha256")
        expected_size = entry.get("size_bytes")
        if not isinstance(relative_path, str) or not isinstance(expected_sha256, str):
            raise ValueError("model runtime manifest file entry is invalid")
        if not isinstance(expected_size, int) or expected_size < 0:
            raise ValueError("model runtime manifest file size is invalid")
        if relative_path in expected_paths:
            raise ValueError("model runtime manifest has duplicate file paths")
        expected_paths.add(relative_path)
        path = actual_paths.get(relative_path)
        if path is None:
            raise ValueError(f"model runtime file is missing: {relative_path}")
        if path.stat().st_size != expected_size:
            raise ValueError(f"model runtime file size does not match: {relative_path}")
        if _sha256(path.read_bytes()) != expected_sha256:
            raise ValueError(f"model runtime file SHA does not match: {relative_path}")
    if set(actual_paths) != expected_paths:
        raise ValueError("model runtime file set does not match manifest")


def _runtime_files(model_path: Path) -> list[Path]:
    if not model_path.is_dir():
        raise ValueError(f"model path is not a directory: {model_path}")
    files = [
        path
        for path in model_path.rglob("*")
        if path.is_file()
        and ".cache" not in path.relative_to(model_path).parts
        and path.name in _RUNTIME_FILE_NAMES
    ]
    if not files:
        raise ValueError("model path has no runtime files")
    return sorted(files, key=lambda path: path.relative_to(model_path).as_posix())


def _load_manifest(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("model runtime manifest is not an object")
    return value


def _json_bytes(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
