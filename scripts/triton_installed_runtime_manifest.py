"""Build and verify a content manifest for an installed Triton distribution."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

_SCHEMA_VERSION = 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--distribution", required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--distribution", required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "build":
        manifest = build_manifest(args.distribution)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(_json_bytes(manifest))
        return 0

    verify_manifest(args.distribution, _load_manifest(args.manifest))
    return 0


def build_manifest(distribution_name: str) -> dict[str, object]:
    """Return a manifest for every installed package file owned by a distribution."""

    distribution = importlib.metadata.distribution(distribution_name)
    files = _installed_files(distribution)
    payload: dict[str, object] = {
        "triton_installed_runtime_manifest_schema_version": _SCHEMA_VERSION,
        "distribution_name": distribution.metadata["Name"],
        "distribution_version": distribution.version,
        "record_sha256": _sha256(_record_bytes(distribution)),
        "installed_files": [
            {
                "path": relative_path,
                "sha256": _sha256(path.read_bytes()),
                "size_bytes": path.stat().st_size,
            }
            for relative_path, path in files
        ],
    }
    payload["installed_manifest_sha256"] = _sha256(_json_bytes(payload))
    return payload


def verify_manifest(distribution_name: str, manifest: dict[str, object]) -> None:
    """Raise ``ValueError`` unless installed files match a Triton manifest."""

    if (
        manifest.get("triton_installed_runtime_manifest_schema_version")
        != _SCHEMA_VERSION
    ):
        raise ValueError("unsupported Triton installed runtime manifest schema")
    distribution = importlib.metadata.distribution(distribution_name)
    if manifest.get("distribution_name") != distribution.metadata["Name"]:
        raise ValueError("Triton distribution name does not match manifest")
    if manifest.get("distribution_version") != distribution.version:
        raise ValueError("Triton distribution version does not match manifest")
    if manifest.get("record_sha256") != _sha256(_record_bytes(distribution)):
        raise ValueError("Triton RECORD SHA does not match manifest")
    expected_files = manifest.get("installed_files")
    if not isinstance(expected_files, list) or not expected_files:
        raise ValueError("Triton installed runtime manifest has no files")
    unsigned = dict(manifest)
    expected_manifest_sha256 = unsigned.pop("installed_manifest_sha256", None)
    if not isinstance(expected_manifest_sha256, str) or (
        _sha256(_json_bytes(unsigned)) != expected_manifest_sha256
    ):
        raise ValueError("Triton installed runtime manifest SHA is invalid")

    actual_paths = dict(_installed_files(distribution))
    expected_paths: set[str] = set()
    for entry in expected_files:
        if not isinstance(entry, dict):
            raise ValueError("Triton installed runtime manifest file entry is invalid")
        relative_path = entry.get("path")
        expected_sha256 = entry.get("sha256")
        expected_size = entry.get("size_bytes")
        if not isinstance(relative_path, str) or not isinstance(expected_sha256, str):
            raise ValueError("Triton installed runtime manifest file entry is invalid")
        if not isinstance(expected_size, int) or expected_size < 0:
            raise ValueError("Triton installed runtime manifest file size is invalid")
        if relative_path in expected_paths:
            raise ValueError(
                "Triton installed runtime manifest has duplicate file paths"
            )
        expected_paths.add(relative_path)
        path = actual_paths.get(relative_path)
        if path is None:
            raise ValueError(f"Triton installed file is missing: {relative_path}")
        if path.stat().st_size != expected_size:
            raise ValueError(
                f"Triton installed file size does not match: {relative_path}"
            )
        if _sha256(path.read_bytes()) != expected_sha256:
            raise ValueError(
                f"Triton installed file SHA does not match: {relative_path}"
            )
    if set(actual_paths) != expected_paths:
        raise ValueError("Triton installed file set does not match manifest")


def _installed_files(
    distribution: importlib.metadata.Distribution,
) -> list[tuple[str, Path]]:
    files = distribution.files or []
    record_paths = [
        Path(str(path)) for path in files if str(path).endswith(".dist-info/RECORD")
    ]
    if len(record_paths) != 1:
        raise ValueError("Triton distribution has no unique RECORD file")

    root = distribution.locate_file("")
    package_roots = {
        Path(str(path)).parts[0]
        for path in files
        if Path(str(path)).parts
        and not Path(str(path)).parts[0].endswith(".dist-info")
        and not Path(str(path)).parts[0].endswith(".data")
    }
    paths = {Path(str(path)) for path in files}
    for package_root in package_roots:
        directory = root / package_root
        if directory.is_dir():
            paths.update(
                path.relative_to(root)
                for path in directory.rglob("*")
                if path.is_file()
            )

    resolved: list[tuple[str, Path]] = []
    for relative_path in sorted(paths, key=lambda path: path.as_posix()):
        path = distribution.locate_file(relative_path)
        if not path.is_file():
            raise ValueError(
                f"Triton installed file is missing: {relative_path.as_posix()}"
            )
        resolved.append((relative_path.as_posix(), path))
    if not resolved:
        raise ValueError("Triton distribution has no installed files")
    return resolved


def _record_bytes(distribution: importlib.metadata.Distribution) -> bytes:
    record = next(
        (
            Path(str(path))
            for path in distribution.files or []
            if str(path).endswith(".dist-info/RECORD")
        ),
        None,
    )
    if record is None:
        raise ValueError("Triton distribution has no RECORD file")
    return distribution.locate_file(record).read_bytes()


def _load_manifest(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Triton installed runtime manifest is not an object")
    return value


def _json_bytes(value: dict[str, object]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
