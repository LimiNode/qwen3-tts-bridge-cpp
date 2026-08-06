"""Build and verify the exact file set of a portable technical-beta package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 3
_LEGACY_SCHEMA_VERSION = 2
_FORBIDDEN_FILE_SUFFIXES = {".pyc", ".pyo"}
_MUTABLE_EMPTY_DIRECTORY_NAMES = {"__pycache__"}
_PACKAGE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_MARKER_NAME = ".qtb-technical-beta-root"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--root", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--package-id", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--root", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "build":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(build_manifest(args.root, args.output, args.package_id))
        return 0

    verify_manifest(args.root, args.manifest)
    return 0


def build_manifest(root: Path, output: Path, package_id: str) -> bytes:
    """Return a canonical manifest for the sealed package tree except itself."""

    root = root.resolve()
    output = output.resolve()
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise ValueError("package manifest output must be inside package root") from exc
    _validate_package_id(package_id)
    payload: dict[str, object] = {
        "package_tree_manifest_schema_version": _SCHEMA_VERSION,
        "package_id": package_id,
        "manifest_path": output.relative_to(root).as_posix(),
        "mutable_empty_directory_names": sorted(_MUTABLE_EMPTY_DIRECTORY_NAMES),
        "package_directories": [
            path.relative_to(root).as_posix()
            for path in _package_directories(root)
        ],
        "package_files": [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in _package_files(root, output)
        ],
    }
    payload["package_tree_manifest_sha256"] = _sha256(_canonical_json_bytes(payload))
    return _canonical_json_bytes(payload)


def verify_manifest(root: Path, manifest_path: Path) -> None:
    """Raise ``ValueError`` unless the package has its sealed tree and files."""

    root = root.resolve()
    manifest_path = manifest_path.resolve()
    manifest = _load_json(manifest_path)
    schema_version = manifest.get("package_tree_manifest_schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version not in {_LEGACY_SCHEMA_VERSION, _SCHEMA_VERSION}
    ):
        raise ValueError("unsupported package tree manifest schema")
    recorded_path = manifest.get("manifest_path")
    if (
        not isinstance(recorded_path, str)
        or recorded_path != manifest_path.relative_to(root).as_posix()
    ):
        raise ValueError("package tree manifest path is invalid")
    expected_hash = manifest.get("package_tree_manifest_sha256")
    unsigned = dict(manifest)
    unsigned.pop("package_tree_manifest_sha256", None)
    if (
        not isinstance(expected_hash, str)
        or _sha256(_canonical_json_bytes(unsigned)) != expected_hash
    ):
        raise ValueError("package tree manifest SHA is invalid")
    _verify_forbidden_bytecode(root)
    _verify_directories(root, manifest)
    package_id = manifest.get("package_id")
    if schema_version == _SCHEMA_VERSION:
        if not isinstance(package_id, str):
            raise ValueError("package tree manifest package_id is invalid")
        _validate_package_id(package_id)
        _verify_package_marker(root, package_id)
        actual = build_manifest(root, manifest_path, package_id)
    else:
        actual = _build_legacy_manifest(root, manifest_path)
    if _canonical_json_bytes(manifest) != actual:
        raise ValueError("package tree does not match manifest")


def _build_legacy_manifest(root: Path, output: Path) -> bytes:
    """Build the schema-2 form so previously published R3 can be verified."""

    payload: dict[str, object] = {
        "package_tree_manifest_schema_version": _LEGACY_SCHEMA_VERSION,
        "manifest_path": output.relative_to(root).as_posix(),
        "mutable_empty_directory_names": sorted(_MUTABLE_EMPTY_DIRECTORY_NAMES),
        "package_directories": [
            path.relative_to(root).as_posix() for path in _package_directories(root)
        ],
        "package_files": [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in _package_files(root, output)
        ],
    }
    payload["package_tree_manifest_sha256"] = _sha256(_canonical_json_bytes(payload))
    return _canonical_json_bytes(payload)


def _package_files(root: Path, manifest_path: Path) -> list[Path]:
    if not root.is_dir():
        raise ValueError(f"package root is not a directory: {root}")
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_file() and path.suffix in _FORBIDDEN_FILE_SUFFIXES:
            raise ValueError(
                f"package contains forbidden bytecode: {relative.as_posix()}"
            )
        if path.is_file() and path.resolve() != manifest_path:
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _package_directories(root: Path) -> list[Path]:
    """Return every sealed directory below the package root."""

    if not root.is_dir():
        raise ValueError(f"package root is not a directory: {root}")
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_dir() and path.name not in _MUTABLE_EMPTY_DIRECTORY_NAMES
        ),
        key=lambda item: item.relative_to(root).as_posix(),
    )


def _verify_forbidden_bytecode(root: Path) -> None:
    """Reject bytecode before checking permitted empty transient directories."""

    for path in root.rglob("*"):
        if path.is_file() and path.suffix in _FORBIDDEN_FILE_SUFFIXES:
            relative = path.relative_to(root).as_posix()
            raise ValueError(f"package contains forbidden bytecode: {relative}")


def _all_package_directories(root: Path) -> list[Path]:
    """Return every directory, including explicitly mutable cache directories."""

    return sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda item: item.relative_to(root).as_posix(),
    )


def _verify_directories(root: Path, manifest: dict[str, Any]) -> None:
    """Reject missing or unexpected directories outside explicit empty cache roots."""

    expected = manifest.get("package_directories")
    mutable_names = manifest.get("mutable_empty_directory_names")
    if (
        not isinstance(expected, list)
        or not all(isinstance(path, str) for path in expected)
        or not isinstance(mutable_names, list)
        or not all(isinstance(name, str) for name in mutable_names)
    ):
        raise ValueError("package tree directory policy is invalid")

    expected_paths = set(expected)
    actual_paths: set[str] = set()
    for directory in _all_package_directories(root):
        relative = directory.relative_to(root).as_posix()
        if relative in expected_paths:
            actual_paths.add(relative)
            continue
        if directory.name not in mutable_names:
            raise ValueError(f"package contains unexpected directory: {relative}")
        if any(path.is_file() for path in directory.rglob("*")):
            raise ValueError(
                "package mutable cache directory must remain empty: "
                f"{relative}"
            )

    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        raise ValueError(
            "package is missing sealed directories: " + ", ".join(missing)
        )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"package manifest is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError("package manifest root is not an object")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate object keys instead of accepting JSON's last-key wins rule."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _validate_package_id(package_id: str) -> None:
    if _PACKAGE_ID_PATTERN.fullmatch(package_id) is None:
        raise ValueError(
            "package_id must contain only letters, digits, '.', '_' or '-'"
        )


def _verify_package_marker(root: Path, package_id: str) -> None:
    marker = _load_json(root / _MARKER_NAME)
    if (
        marker.get("marker_schema_version") != 1
        or marker.get("package_id") != package_id
    ):
        raise ValueError("package marker does not match package_id")


def _canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
