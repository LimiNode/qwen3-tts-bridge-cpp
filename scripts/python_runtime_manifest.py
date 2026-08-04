"""Build and verify actual-content manifests for the active Python runtime."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import platform
import sys
import sysconfig
from pathlib import Path
from typing import Iterable

_SCHEMA_VERSION = 2
_TRANSIENT_DIRECTORY_NAMES = {"__pycache__"}
_TRANSIENT_FILE_SUFFIXES = {".pyc", ".pyo"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--output", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "build":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(_json_bytes(build_manifest()))
        return 0

    verify_manifest(_load_manifest(args.manifest))
    return 0


def build_manifest() -> dict[str, object]:
    """Return a deterministic actual-content manifest for this Python runtime."""

    file_hasher = _FileHasher()
    distributions = _installed_distributions(file_hasher)
    if not distributions:
        raise ValueError("Python environment has no installed distributions")
    payload: dict[str, object] = {
        "python_runtime_manifest_schema_version": _SCHEMA_VERSION,
        "python": {
            "implementation": platform.python_implementation(),
            "version_info": list(sys.version_info[:3]),
        },
        "distributions": distributions,
        "runtime_files": _runtime_files(file_hasher),
    }
    payload["python_runtime_manifest_sha256"] = _sha256(_json_bytes(payload))
    return payload


def verify_manifest(manifest: dict[str, object]) -> None:
    """Raise ``ValueError`` unless the active runtime matches ``manifest``."""

    if manifest.get("python_runtime_manifest_schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported Python runtime manifest schema")
    expected_hash = manifest.get("python_runtime_manifest_sha256")
    unsigned = dict(manifest)
    unsigned.pop("python_runtime_manifest_sha256", None)
    if (
        not isinstance(expected_hash, str)
        or _sha256(_json_bytes(unsigned)) != expected_hash
    ):
        raise ValueError("Python runtime manifest SHA is invalid")
    if manifest != build_manifest():
        raise ValueError("active Python runtime does not match manifest")


class _FileHasher:
    """Avoid reading the same runtime file twice while building one manifest."""

    def __init__(self) -> None:
        self._cache: dict[Path, str] = {}

    def sha256(self, path: Path) -> str:
        resolved = path.resolve()
        cached = self._cache.get(resolved)
        if cached is not None:
            return cached
        digest = hashlib.sha256()
        with resolved.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        result = digest.hexdigest()
        self._cache[resolved] = result
        return result


def _installed_distributions(file_hasher: _FileHasher) -> list[dict[str, object]]:
    entries = [
        _distribution_entry(distribution, file_hasher)
        for distribution in importlib.metadata.distributions()
        if _is_installed_in_active_environment(distribution)
    ]
    names = [str(entry["name"]) for entry in entries]
    if len(names) != len(set(names)):
        raise ValueError(
            "installed Python distributions have duplicate normalized names"
        )
    return sorted(entries, key=lambda entry: str(entry["name"]))


def _is_installed_in_active_environment(
    distribution: importlib.metadata.Distribution,
) -> bool:
    metadata_path = getattr(distribution, "_path", None)
    if metadata_path is None:
        raise ValueError("installed Python distribution has no metadata location")
    try:
        Path(str(metadata_path)).resolve().relative_to(Path(sys.prefix).resolve())
    except ValueError:
        return False
    return True


def _distribution_entry(
    distribution: importlib.metadata.Distribution,
    file_hasher: _FileHasher,
) -> dict[str, object]:
    try:
        raw_name = distribution.metadata["Name"]
    except KeyError as exc:
        raise ValueError("installed Python distribution has no name") from exc
    if not isinstance(raw_name, str) or not raw_name:
        raise ValueError("installed Python distribution has no name")
    files = distribution.files
    if files is None:
        raise ValueError(
            f"installed Python distribution has no file record: {raw_name}"
        )
    return {
        "name": _normalize_name(raw_name),
        "version": distribution.version,
        "files": [
            _distribution_file_entry(distribution, path, file_hasher)
            for path in sorted(
                _regular_files(distribution, files),
                key=lambda item: item.as_posix(),
            )
        ],
    }


def _distribution_file_entry(
    distribution: importlib.metadata.Distribution,
    path: importlib.metadata.PackagePath,
    file_hasher: _FileHasher,
) -> dict[str, object]:
    resolved = Path(str(distribution.locate_file(path)))
    return {
        "path": path.as_posix(),
        "recorded_sha256": _recorded_file_sha256(path),
        "actual_sha256": file_hasher.sha256(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _regular_files(
    distribution: importlib.metadata.Distribution,
    files: Iterable[importlib.metadata.PackagePath],
) -> Iterable[importlib.metadata.PackagePath]:
    for path in files:
        resolved = Path(str(distribution.locate_file(path)))
        if resolved.is_file() and not _is_transient_path(Path(str(path))):
            yield path


def _recorded_file_sha256(path: importlib.metadata.PackagePath) -> str | None:
    file_hash = path.hash
    if file_hash is None:
        return None
    if file_hash.mode != "sha256":
        raise ValueError(
            f"installed Python distribution file has unsupported RECORD hash: {path}"
        )
    encoded = file_hash.value.encode("ascii")
    return base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4)).hex()


def _runtime_files(file_hasher: _FileHasher) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for root_name, root in _runtime_file_roots():
        if root.is_file():
            entries.append(
                {
                    "root": root_name,
                    "path": root.name,
                    "sha256": file_hasher.sha256(root),
                    "size_bytes": root.stat().st_size,
                }
            )
            continue
        for path in _files_under_root(root, root_name):
            entries.append(
                {
                    "root": root_name,
                    "path": path.relative_to(root).as_posix(),
                    "sha256": file_hasher.sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    if not entries:
        raise ValueError("Python runtime has no manifestable files")
    return entries


def _runtime_file_roots() -> list[tuple[str, Path]]:
    paths = sysconfig.get_paths()
    candidates = [
        ("executable", Path(sys.executable)),
        ("stdlib", Path(paths["stdlib"])),
        ("platstdlib", Path(paths["platstdlib"])),
        ("purelib", Path(paths["purelib"])),
        ("platlib", Path(paths["platlib"])),
    ]
    roots: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for root_name, root in candidates:
        resolved = root.resolve()
        if resolved in seen:
            continue
        if not resolved.exists():
            raise ValueError(f"Python runtime root is missing: {resolved}")
        seen.add(resolved)
        roots.append((root_name, resolved))
    return roots


def _files_under_root(root: Path, root_name: str) -> list[Path]:
    if not root.is_dir():
        raise ValueError(f"Python runtime root is not a directory: {root}")
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and not _is_transient_path(path.relative_to(root))
        and not (
            root_name == "stdlib"
            and path.relative_to(root).parts[0] == "site-packages"
        )
    ]
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _is_transient_path(relative_path: Path) -> bool:
    return bool(
        set(relative_path.parts).intersection(_TRANSIENT_DIRECTORY_NAMES)
    ) or relative_path.name.endswith(tuple(_TRANSIENT_FILE_SUFFIXES))


def _normalize_name(value: str) -> str:
    return value.lower().replace("_", "-").replace(".", "-")


def _load_manifest(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Python runtime manifest is not an object")
    return value


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
