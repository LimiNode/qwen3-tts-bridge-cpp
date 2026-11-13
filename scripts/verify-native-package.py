"""Verify a native package directory and its ZIP representation."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

MARKER = ".qtb-native-release-root"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_names(root: Path) -> set[str]:
    names = set()
    for path in root.rglob("*"):
        if path.is_file() and path.name != MARKER:
            names.add(path.relative_to(root).as_posix())
    return names


def verify_directory(root: Path) -> set[str]:
    manifest_path = root / "release-manifest.json"
    checksums_path = root / "SHA256SUMS.txt"
    if not manifest_path.is_file() or not checksums_path.is_file():
        raise ValueError(
            "native package is missing release-manifest.json or SHA256SUMS.txt"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("native_release_manifest_schema_version") != 1:
        raise ValueError("unsupported native release manifest schema")
    names = _safe_names(root)
    manifest_names = {
        str(item["path"]).replace("\\", "/") for item in manifest.get("files", [])
    }
    expected_manifest_names = names - {"release-manifest.json", "SHA256SUMS.txt"}
    if manifest_names != expected_manifest_names:
        raise ValueError("release manifest does not match package files")
    for item in manifest.get("files", []):
        path = root / str(item["path"])
        if _sha256(path).lower() != str(item["sha256"]).lower():
            raise ValueError(f"release manifest hash mismatch: {item['path']}")
    checksum_names: set[str] = set()
    for line in checksums_path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", 1)
        relative = relative.replace("\\", "/")
        checksum_names.add(relative)
        path = root / relative
        if not path.is_file() or _sha256(path).lower() != digest.lower():
            raise ValueError(f"checksum mismatch: {relative}")
    if checksum_names != names - {"SHA256SUMS.txt"}:
        raise ValueError("SHA256SUMS.txt does not cover the complete package")
    return names


def verify_archive(root: Path, archive: Path, extract_check: bool) -> None:
    expected = verify_directory(root)
    with zipfile.ZipFile(archive) as zipped:
        entries = [entry.filename for entry in zipped.infolist() if not entry.is_dir()]
        if len(entries) != len(set(entries)):
            raise ValueError("ZIP contains duplicate entries")
        if set(entries) != expected:
            raise ValueError("ZIP entries do not match the release directory")
        if any(
            ".." in Path(name).parts or Path(name).is_absolute() for name in entries
        ):
            raise ValueError("ZIP contains an unsafe path")
        for name in entries:
            if _sha256(root / name) != hashlib.sha256(zipped.read(name)).hexdigest():
                raise ValueError(f"ZIP content differs from release directory: {name}")
        if extract_check:
            with tempfile.TemporaryDirectory(prefix="qtb-native-verify-") as temporary:
                extracted = Path(temporary)
                zipped.extractall(extracted)
                verify_directory(extracted)


def create_archive(root: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    names = sorted(_safe_names(root))
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name in names:
            zipped.write(root / name, arcname=name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--extract-check", action="store_true")
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    archive = args.archive.resolve()
    if args.create:
        create_archive(root, archive)
    verify_archive(root, archive, args.extract_check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
