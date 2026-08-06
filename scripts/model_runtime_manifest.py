"""Build and verify a content manifest for local Qwen runtime model files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

_SCHEMA_VERSION = 2
_TRANSIENT_DIRECTORY_NAMES = {".cache"}
_TRANSIENT_FILE_SUFFIXES = {".incomplete", ".lock", ".partial", ".tmp"}


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
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--left-manifest", type=Path, required=True)
    compare_parser.add_argument("--right-manifest", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.command == "build":
        manifest = build_manifest(args.model_path, args.repository, args.revision)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(_json_bytes(manifest))
        return 0

    if args.command == "compare":
        comparison = compare_manifests(
            _load_manifest(args.left_manifest),
            _load_manifest(args.right_manifest),
        )
        output = _json_bytes(comparison)
        if args.output is None:
            print(output.decode("utf-8"), end="")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(output)
        return 0

    verify_manifest(args.model_path, _load_manifest(args.manifest))
    return 0


def build_manifest(
    model_path: Path,
    repository: str,
    revision: str,
) -> dict[str, object]:
    """Return a deterministic manifest of a complete pinned model directory."""

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


def compare_manifests(
    left: dict[str, object],
    right: dict[str, object],
) -> dict[str, object]:
    """Return a deterministic, file-level explanation of manifest differences."""

    left_files = _validated_manifest_files(left)
    right_files = _validated_manifest_files(right)
    left_paths = set(left_files)
    right_paths = set(right_files)
    changed_paths = sorted(
        path
        for path in left_paths.intersection(right_paths)
        if left_files[path] != right_files[path]
    )
    return {
        "comparison_schema_version": 1,
        "report_kind": "model_runtime_manifest_comparison",
        "left": _manifest_summary(left, len(left_files)),
        "right": _manifest_summary(right, len(right_files)),
        "same_repository": left.get("repository") == right.get("repository"),
        "same_revision": left.get("revision") == right.get("revision"),
        "same_directory_manifest": (
            left.get("directory_manifest_sha256")
            == right.get("directory_manifest_sha256")
        ),
        "added_paths": sorted(right_paths.difference(left_paths)),
        "removed_paths": sorted(left_paths.difference(right_paths)),
        "changed_files": [
            {
                "path": path,
                "left": left_files[path],
                "right": right_files[path],
            }
            for path in changed_paths
        ],
    }


def _runtime_files(model_path: Path) -> list[Path]:
    if not model_path.is_dir():
        raise ValueError(f"model path is not a directory: {model_path}")
    files = [
        path
        for path in model_path.rglob("*")
        if path.is_file() and not _is_transient_model_path(path.relative_to(model_path))
    ]
    if not files:
        raise ValueError("model path has no runtime files")
    return sorted(files, key=lambda path: path.relative_to(model_path).as_posix())


def _is_transient_model_path(relative_path: Path) -> bool:
    return bool(
        set(relative_path.parts).intersection(_TRANSIENT_DIRECTORY_NAMES)
    ) or relative_path.name.endswith(tuple(_TRANSIENT_FILE_SUFFIXES))


def _load_manifest(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("model runtime manifest is not an object")
    return value


def _validated_manifest_files(
    manifest: dict[str, object],
) -> dict[str, dict[str, object]]:
    if manifest.get("model_runtime_manifest_schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported model runtime manifest schema")
    unsigned = dict(manifest)
    expected_directory_sha256 = unsigned.pop("directory_manifest_sha256", None)
    if not isinstance(expected_directory_sha256, str) or (
        _sha256(_json_bytes(unsigned)) != expected_directory_sha256
    ):
        raise ValueError("model runtime manifest SHA is invalid")
    runtime_files = manifest.get("runtime_files")
    if not isinstance(runtime_files, list) or not runtime_files:
        raise ValueError("model runtime manifest has no runtime files")
    files: dict[str, dict[str, object]] = {}
    for entry in runtime_files:
        if not isinstance(entry, dict):
            raise ValueError("model runtime manifest file entry is invalid")
        path = entry.get("path")
        sha256 = entry.get("sha256")
        size_bytes = entry.get("size_bytes")
        if (
            not isinstance(path, str)
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or not isinstance(size_bytes, int)
            or size_bytes < 0
            or path in files
        ):
            raise ValueError("model runtime manifest file entry is invalid")
        files[path] = {"sha256": sha256, "size_bytes": size_bytes}
    return files


def _manifest_summary(
    manifest: dict[str, object],
    file_count: int,
) -> dict[str, object]:
    return {
        "repository": manifest.get("repository"),
        "revision": manifest.get("revision"),
        "directory_manifest_sha256": manifest.get("directory_manifest_sha256"),
        "file_count": file_count,
    }


def _json_bytes(value: dict[str, object]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
