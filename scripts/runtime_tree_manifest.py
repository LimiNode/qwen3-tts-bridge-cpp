"""Build and verify an actual-content manifest for a runtime directory tree."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

_SCHEMA_VERSION = 1
_TRANSIENT_DIRECTORY_NAMES = {"__pycache__"}
_TRANSIENT_FILE_SUFFIXES = {".pyc", ".pyo"}


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
        args.output.write_bytes(_json_bytes(build_manifest(args.root)))
        return 0

    verify_manifest(args.root, _load_manifest(args.manifest))
    return 0


def build_manifest(root: Path) -> dict[str, object]:
    """Return a deterministic actual-content manifest of ``root``."""

    files = _runtime_files(root)
    payload: dict[str, object] = {
        "runtime_tree_manifest_schema_version": _SCHEMA_VERSION,
        "runtime_files": [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in files
        ],
    }
    payload["runtime_tree_manifest_sha256"] = _sha256(_json_bytes(payload))
    return payload


def verify_manifest(root: Path, manifest: dict[str, object]) -> None:
    """Raise ``ValueError`` unless ``root`` matches ``manifest`` exactly."""

    if manifest.get("runtime_tree_manifest_schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported runtime tree manifest schema")
    expected_hash = manifest.get("runtime_tree_manifest_sha256")
    unsigned = dict(manifest)
    unsigned.pop("runtime_tree_manifest_sha256", None)
    if (
        not isinstance(expected_hash, str)
        or _sha256(_json_bytes(unsigned)) != expected_hash
    ):
        raise ValueError("runtime tree manifest SHA is invalid")
    if manifest != build_manifest(root):
        raise ValueError("runtime tree does not match manifest")


def _runtime_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise ValueError(f"runtime tree root is not a directory: {root}")
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and not _is_transient_path(path.relative_to(root))
    ]
    if not files:
        raise ValueError("runtime tree has no files")
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _is_transient_path(relative_path: Path) -> bool:
    return bool(
        set(relative_path.parts).intersection(_TRANSIENT_DIRECTORY_NAMES)
    ) or relative_path.name.endswith(tuple(_TRANSIENT_FILE_SUFFIXES))


def _load_manifest(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("runtime tree manifest is not an object")
    return value


def _json_bytes(value: object) -> bytes:
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
