"""Inventory a sealed model-free release without changing its contents."""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--forbidden-root", action="append", default=[])
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = root / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    files = sorted(path for path in root.rglob("*") if path.is_file())
    components: dict[str, int] = defaultdict(int)
    packages: dict[str, int] = defaultdict(int)
    python_core_bytes = 0
    torch_library_bytes = 0
    largest = []
    weights = []
    caches = []
    leaks = []
    needles = [
        str(Path(value).resolve()).replace("\\", "/").casefold()
        for value in args.forbidden_root
    ]
    site_prefix = "worker-python/python/Lib/site-packages/"
    text_suffixes = {".py", ".json", ".txt", ".pth", ".cmd", ".cfg", ".ini"}
    for path in files:
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        components[relative.split("/")[0]] += size
        largest.append({"path": relative, "bytes": size})
        if relative.startswith(site_prefix):
            packages[relative[len(site_prefix) :].split("/")[0]] += size
            if relative.startswith(site_prefix + "torch/lib/"):
                torch_library_bytes += size
        elif relative.startswith("worker-python/python/"):
            python_core_bytes += size
        if path.suffix.lower() in {".safetensors", ".gguf", ".ckpt", ".pt", ".bin"}:
            weights.append({"path": relative, "bytes": size})
        if set(path.relative_to(root).parts) & {
            "__pycache__",
            ".cache",
            ".pytest_cache",
            ".git",
        }:
            caches.append(relative)
        if needles and path.suffix.lower() in text_suffixes:
            content = path.read_text(encoding="utf-8", errors="replace")
            content = content.replace("\\\\", "/").replace("\\", "/").casefold()
            if any(needle in content for needle in needles):
                leaks.append(relative)

    # Hashes come from the release manifest; verify that manifest separately
    # before interpreting these as byte-identical duplicate candidates.
    groups: dict[tuple[int, str], list[str]] = defaultdict(list)
    for entry in manifest["release_files"]:
        if entry["size_bytes"] >= 1024 * 1024:
            groups[(entry["size_bytes"], entry["sha256"])].append(entry["path"])
    duplicates = [
        {"bytes_each": size, "sha256": digest, "paths": paths}
        for (size, digest), paths in groups.items()
        if len(paths) > 1
    ]
    site_bytes = sum(packages.values())
    result = {
        "source_git_revision": manifest["source_git_revision"],
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "total_bytes": sum(components.values()),
        "file_count": len(files),
        "manifest_file_count": len(manifest["release_files"]),
        "top_level_bytes": dict(sorted(components.items())),
        "site_packages_bytes": site_bytes,
        "python_core_bytes": python_core_bytes,
        "torch_library_bytes": torch_library_bytes,
        "largest_site_packages": dict(
            sorted(packages.items(), key=lambda item: item[1], reverse=True)[:15]
        ),
        "ten_largest_files": sorted(
            largest, key=lambda item: item["bytes"], reverse=True
        )[:10],
        "duplicate_candidates_at_least_1_mib": sorted(
            duplicates, key=lambda item: item["bytes_each"], reverse=True
        ),
        "weight_file_candidates": weights,
        "cache_files": caches,
        "checkout_path_text_matches": leaks,
        "path_scan_scope": (
            "UTF-8 py/json/txt/pth/cmd/cfg/ini files; not binary debug strings"
        ),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
