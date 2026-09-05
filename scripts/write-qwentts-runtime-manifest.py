"""Write a qwentts.cpp runtime manifest with SHA-256 file hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--engine-commit", required=True)
    parser.add_argument("--backend", default="cuda")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime_dir = args.runtime_dir.resolve()
    if not runtime_dir.is_dir():
        raise SystemExit(f"runtime directory does not exist: {runtime_dir}")
    dll = runtime_dir / "qwen.dll"
    if not dll.is_file():
        raise SystemExit(f"runtime directory must contain qwen.dll: {dll}")

    output = (args.output or runtime_dir / "manifest.json").resolve()
    files = []
    for path in sorted(runtime_dir.rglob("*")):
        if not path.is_file() or path.name.lower() == "manifest.json" or path.resolve() == output:
            continue
        relative = path.relative_to(runtime_dir).as_posix()
        files.append({"path": relative, "sha256": sha256(path)})

    manifest = {
        "schema_version": 1,
        "engine": "qwentts.cpp",
        "engine_commit": args.engine_commit,
        "qt_abi_version": 5,
        "architecture": "x64",
        "backend": args.backend,
        "files": files,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
