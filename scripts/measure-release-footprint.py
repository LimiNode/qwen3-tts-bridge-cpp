"""Measure a release directory or ZIP without modifying the candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable


def _entries_for_directory(root: Path) -> Iterable[tuple[str, int]]:
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        yield path.relative_to(root).as_posix(), path.stat().st_size


def _entries_for_zip(path: Path) -> Iterable[tuple[str, int]]:
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            if not entry.is_dir():
                yield entry.filename, entry.file_size


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def measure(path: Path) -> dict[str, object]:
    path = path.resolve()
    if path.is_dir():
        entries = list(_entries_for_directory(path))
        archive_bytes = None
        kind = "directory"
    elif path.is_file() and path.suffix.lower() == ".zip":
        entries = list(_entries_for_zip(path))
        archive_bytes = path.stat().st_size
        kind = "zip"
    else:
        raise ValueError("input must be a directory or .zip archive")

    top_level: dict[str, int] = defaultdict(int)
    extensions: dict[str, int] = defaultdict(int)
    for name, size in entries:
        top_level[name.split("/", 1)[0]] += size
        suffix = Path(name).suffix.lower() or "<none>"
        extensions[suffix] += size

    result: dict[str, object] = {
        "schema_version": 1,
        "input": str(path),
        "input_kind": kind,
        "input_sha256": _sha256(path) if path.is_file() else None,
        "archive_bytes": archive_bytes,
        "unpacked_bytes": sum(size for _, size in entries),
        "file_count": len(entries),
        "top_level_bytes": dict(sorted(top_level.items())),
        "extension_bytes": dict(sorted(extensions.items())),
        "largest_files": [
            {"path": name, "bytes": size}
            for name, size in sorted(
                entries, key=lambda item: item[1], reverse=True
            )[:20]
        ],
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = measure(args.input)
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, args.output)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
