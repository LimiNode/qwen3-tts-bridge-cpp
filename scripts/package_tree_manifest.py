"""Build and verify the exact file set of a portable technical-beta package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1
_FORBIDDEN_DIRECTORY_NAMES = {"__pycache__"}
_FORBIDDEN_FILE_SUFFIXES = {".pyc", ".pyo"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--root", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--root", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "build":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(build_manifest(args.root, args.output))
        return 0

    verify_manifest(args.root, args.manifest)
    return 0


def build_manifest(root: Path, output: Path) -> bytes:
    """Return a canonical manifest for every package file except itself."""

    root = root.resolve()
    output = output.resolve()
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise ValueError("package manifest output must be inside package root") from exc
    payload: dict[str, object] = {
        "package_tree_manifest_schema_version": _SCHEMA_VERSION,
        "manifest_path": output.relative_to(root).as_posix(),
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
    """Raise ``ValueError`` unless the package has exactly its sealed file set."""

    root = root.resolve()
    manifest_path = manifest_path.resolve()
    manifest = _load_json(manifest_path)
    if manifest.get("package_tree_manifest_schema_version") != _SCHEMA_VERSION:
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
    actual = build_manifest(root, manifest_path)
    if _canonical_json_bytes(manifest) != actual:
        raise ValueError("package tree does not match manifest")


def _package_files(root: Path, manifest_path: Path) -> list[Path]:
    if not root.is_dir():
        raise ValueError(f"package root is not a directory: {root}")
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if set(relative.parts).intersection(_FORBIDDEN_DIRECTORY_NAMES) or (
            path.suffix in _FORBIDDEN_FILE_SUFFIXES
        ):
            raise ValueError(
                f"package contains forbidden bytecode: {relative.as_posix()}"
            )
        if path.is_file() and path.resolve() != manifest_path:
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"package manifest is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError("package manifest root is not an object")
    return value


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
