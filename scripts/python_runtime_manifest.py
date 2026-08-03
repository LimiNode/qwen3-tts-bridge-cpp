"""Build and verify content manifests for installed Python distributions."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from typing import Iterable

_SCHEMA_VERSION = 1


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
    """Return a deterministic content manifest for this Python environment."""

    distributions = _installed_distributions()
    if not distributions:
        raise ValueError("Python environment has no installed distributions")
    payload: dict[str, object] = {
        "python_runtime_manifest_schema_version": _SCHEMA_VERSION,
        "python": {
            "implementation": platform.python_implementation(),
            "version_info": list(sys.version_info[:3]),
        },
        "distributions": distributions,
    }
    payload["installed_distributions_manifest_sha256"] = _sha256(
        _json_bytes(payload)
    )
    return payload


def verify_manifest(manifest: dict[str, object]) -> None:
    """Raise ``ValueError`` unless this environment matches ``manifest``."""

    if manifest.get("python_runtime_manifest_schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported Python runtime manifest schema")
    expected_hash = manifest.get("installed_distributions_manifest_sha256")
    unsigned = dict(manifest)
    unsigned.pop("installed_distributions_manifest_sha256", None)
    if (
        not isinstance(expected_hash, str)
        or _sha256(_json_bytes(unsigned)) != expected_hash
    ):
        raise ValueError("Python runtime manifest SHA is invalid")
    if manifest != build_manifest():
        raise ValueError("installed Python distributions do not match manifest")


def _installed_distributions() -> list[dict[str, object]]:
    entries = [
        _distribution_entry(distribution)
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
            {
                "path": path.as_posix(),
                "sha256": _recorded_file_sha256(distribution, path),
            }
            for path in sorted(
                _regular_files(distribution, files),
                key=lambda item: item.as_posix(),
            )
        ],
    }


def _regular_files(
    distribution: importlib.metadata.Distribution,
    files: Iterable[importlib.metadata.PackagePath],
) -> Iterable[importlib.metadata.PackagePath]:
    for path in files:
        resolved = Path(str(distribution.locate_file(path)))
        if resolved.is_file():
            yield path


def _recorded_file_sha256(
    distribution: importlib.metadata.Distribution,
    path: importlib.metadata.PackagePath,
) -> str:
    file_hash = path.hash
    if file_hash is None:
        return _sha256(Path(str(distribution.locate_file(path))).read_bytes())
    if file_hash.mode != "sha256":
        raise ValueError(
            f"installed Python distribution file has unsupported RECORD hash: {path}"
        )
    encoded = file_hash.value.encode("ascii")
    return base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4)).hex()


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
