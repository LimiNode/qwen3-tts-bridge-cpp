"""Audit Windows PE imports for a native release directory.

The auditor intentionally uses only the Python standard library.  It walks
imports from the supplied entry points, records whether each DLL is bundled,
and classifies known Windows/driver imports separately from unresolved third
party dependencies.  It does not load or execute any binary.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import struct
from collections import deque
from pathlib import Path


class PeFormatError(ValueError):
    """Raised when a file is not a readable PE image."""


def _u16(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        raise PeFormatError("truncated PE header")
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise PeFormatError("truncated PE header")
    return struct.unpack_from("<I", data, offset)[0]


def _imports(path: Path) -> list[dict[str, str]]:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise PeFormatError(f"{path.name} is not a PE image")
    pe_offset = _u32(data, 0x3C)
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise PeFormatError(f"{path.name} has an invalid PE signature")
    coff = pe_offset + 4
    section_count = _u16(data, coff + 2)
    optional_size = _u16(data, coff + 16)
    optional = coff + 20
    magic = _u16(data, optional)
    if magic == 0x20B:
        data_directory = optional + 112
    elif magic == 0x10B:
        data_directory = optional + 96
    else:
        raise PeFormatError(f"{path.name} has an unsupported PE optional header")
    directories = [
        ("normal", _u32(data, data_directory + 8), 20, 12),
        ("delay", _u32(data, data_directory + 13 * 8), 32, 4),
    ]
    section_table = optional + optional_size
    sections: list[tuple[int, int, int, int]] = []
    for index in range(section_count):
        section = section_table + index * 40
        virtual_size = _u32(data, section + 8)
        virtual_address = _u32(data, section + 12)
        raw_size = _u32(data, section + 16)
        raw_pointer = _u32(data, section + 20)
        sections.append(
            (virtual_address, max(virtual_size, raw_size), raw_pointer, raw_size)
        )

    def rva_to_file_offset(rva: int) -> int:
        for virtual_address, span, raw_pointer, raw_size in sections:
            if virtual_address <= rva < virtual_address + span:
                delta = rva - virtual_address
                if delta >= raw_size:
                    raise PeFormatError(f"RVA outside raw section in {path.name}")
                return raw_pointer + delta
        raise PeFormatError(f"RVA not mapped by a section in {path.name}")

    imports: list[dict[str, str]] = []
    for kind, import_rva, descriptor_size, _name_offset in directories:
        if not import_rva:
            continue
        descriptor = rva_to_file_offset(import_rva)
        for index in range(65536):
            entry = descriptor + index * descriptor_size
            if entry + descriptor_size > len(data):
                raise PeFormatError(f"truncated {kind} import table in {path.name}")
            if kind == "normal":
                original_first_thunk, _, _, name_rva, _ = struct.unpack_from(
                    "<5I", data, entry
                )
                if not (original_first_thunk or name_rva):
                    break
            else:
                attributes, name_rva = struct.unpack_from("<2I", data, entry)
                if not (attributes or name_rva):
                    break
            name_offset = rva_to_file_offset(name_rva)
            end = data.find(b"\0", name_offset)
            if end < 0:
                raise PeFormatError(f"unterminated import name in {path.name}")
            imports.append(
                {"name": data[name_offset:end].decode("ascii"), "kind": kind}
            )
        else:
            raise PeFormatError(f"{kind} import table is unbounded in {path.name}")
    return imports


def _exports(path: Path) -> set[str]:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise PeFormatError(f"{path.name} is not a PE image")
    pe_offset = _u32(data, 0x3C)
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise PeFormatError(f"{path.name} has an invalid PE signature")
    coff = pe_offset + 4
    section_count = _u16(data, coff + 2)
    optional_size = _u16(data, coff + 16)
    optional = coff + 20
    magic = _u16(data, optional)
    data_directory = optional + (112 if magic == 0x20B else 96)
    export_rva = _u32(data, data_directory)
    if not export_rva:
        return set()
    section_table = optional + optional_size
    sections = []
    for index in range(section_count):
        section = section_table + index * 40
        sections.append(
            (
                _u32(data, section + 12),
                max(_u32(data, section + 8), _u32(data, section + 16)),
                _u32(data, section + 20),
                _u32(data, section + 16),
            )
        )

    def rva_to_file_offset(rva: int) -> int:
        for virtual_address, span, raw_pointer, raw_size in sections:
            if virtual_address <= rva < virtual_address + span:
                delta = rva - virtual_address
                if delta >= raw_size:
                    raise PeFormatError(
                        f"export RVA outside raw section in {path.name}"
                    )
                return raw_pointer + delta
        raise PeFormatError(f"export RVA not mapped in {path.name}")

    directory = rva_to_file_offset(export_rva)
    number_of_names = _u32(data, directory + 24)
    names_rva = _u32(data, directory + 32)
    names_offset = rva_to_file_offset(names_rva)
    names: set[str] = set()
    for index in range(number_of_names):
        name_rva = _u32(data, names_offset + index * 4)
        name_offset = rva_to_file_offset(name_rva)
        end = data.find(b"\0", name_offset)
        if end < 0:
            raise PeFormatError(f"unterminated export name in {path.name}")
        names.add(data[name_offset:end].decode("ascii"))
    return names


_DEFAULT_SYSTEM_PREFIXES = (
    "api-ms-win-",
    "ext-ms-win-",
)
_DEFAULT_SYSTEM_NAMES = {
    "advapi32.dll",
    "bcrypt.dll",
    "combase.dll",
    "gdi32.dll",
    "kernel32.dll",
    "ntdll.dll",
    "ole32.dll",
    "oleaut32.dll",
    "psapi.dll",
    "rpcrt4.dll",
    "shell32.dll",
    "shlwapi.dll",
    "user32.dll",
    "version.dll",
    "winmm.dll",
    "ws2_32.dll",
}


def _load_policy(path: Path | None) -> dict[str, object]:
    if path is None:
        return {
            "guaranteed_system": sorted(_DEFAULT_SYSTEM_NAMES),
            "guaranteed_system_prefixes": list(_DEFAULT_SYSTEM_PREFIXES),
            "declared_prerequisites": [],
            "dynamic_dependencies": [],
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("dependency policy must use schema_version 1")
    return payload


def _policy_external(name: str, policy: dict[str, object]) -> dict[str, str] | None:
    lower = name.lower()
    system = {str(item).lower() for item in policy.get("guaranteed_system", [])}
    prefixes = tuple(
        str(item).lower()
        for item in policy.get("guaranteed_system_prefixes", [])
    )
    if lower in system or any(
        fnmatch.fnmatchcase(lower, prefix) for prefix in prefixes
    ):
        return {"status": "guaranteed_system", "kind": "windows"}
    for item in policy.get("declared_prerequisites", []):
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("name", "")).lower()
        if pattern and fnmatch.fnmatchcase(lower, pattern):
            return {
                "status": "declared_prerequisite",
                "kind": str(item.get("kind", "external")),
            }
    return None


def audit(
    root: Path,
    entries: list[str],
    policy: dict[str, object] | None = None,
    dynamic_dependencies: list[str] | None = None,
    required_exports: list[str] | None = None,
) -> dict[str, object]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"package root does not exist: {root}")
    policy = policy or _load_policy(None)
    candidates: dict[str, list[Path]] = {}
    for path in (*root.rglob("*.dll"), *root.rglob("*.exe")):
        candidates.setdefault(path.name.lower(), []).append(path)
    duplicate_names = {
        name: sorted(path.relative_to(root).as_posix() for path in paths)
        for name, paths in candidates.items()
        if len(paths) > 1
    }
    by_name = {
        name: paths[0]
        for name, paths in candidates.items()
        if len(paths) == 1
    }
    queue: deque[tuple[str, Path]] = deque()
    for entry in entries:
        path = (root / entry).resolve()
        if not path.is_file() or root not in path.parents:
            raise ValueError(f"entry is not a package file: {entry}")
        queue.append((entry.replace("\\", "/"), path))
    visited: set[Path] = set()
    imports: list[dict[str, object]] = []
    missing: list[str] = []
    non_pe: list[str] = []
    export_failures: list[dict[str, object]] = []
    while queue:
        relative, path = queue.popleft()
        if path in visited:
            continue
        visited.add(path)
        try:
            names = _imports(path)
        except PeFormatError as error:
            imports.append({"path": relative, "status": "not_pe", "error": str(error)})
            non_pe.append(relative)
            continue
        if path.name.lower() == "qwen.dll" and required_exports:
            try:
                exports = _exports(path)
                absent = sorted(set(required_exports) - exports)
                if absent:
                    export_failures.append({"path": relative, "missing": absent})
            except PeFormatError as error:
                non_pe.append(relative)
                imports.append(
                    {
                        "path": relative,
                        "status": "invalid_exports",
                        "error": str(error),
                    }
                )
                continue
        for imported in names:
            name = imported["name"]
            kind = imported["kind"]
            bundled = by_name.get(name.lower())
            if bundled is not None and bundled.parent != path.parent:
                bundled = None
            if bundled is not None:
                status = "bundled"
                bundled_relative = bundled.relative_to(root).as_posix()
                queue.append((bundled_relative, bundled))
            else:
                external = _policy_external(name, policy)
                status = external["status"] if external else "missing"
                external_kind = external["kind"] if external else "unknown"
                if status == "missing":
                    missing.append(name.lower())
                bundled_relative = None
            imports.append({
                "importer": relative,
                "name": name,
                "kind": kind,
                "status": status,
                "external_kind": external_kind if bundled is None else None,
                "bundled_path": bundled_relative,
            })
    declared_dynamic = list(policy.get("dynamic_dependencies", []))
    declared_dynamic.extend(dynamic_dependencies or [])
    for name in sorted(set(str(item) for item in declared_dynamic), key=str.lower):
        bundled = by_name.get(name.lower())
        if bundled is not None:
            status = "bundled"
            bundled_relative = bundled.relative_to(root).as_posix()
        else:
            external = _policy_external(name, policy)
            status = external["status"] if external else "missing"
            bundled_relative = None
            if status == "missing":
                missing.append(name.lower())
        imports.append({
            "importer": "<dynamic>" if bundled is None else "<dynamic-loader>",
            "name": name,
            "kind": "dynamic",
            "status": status,
            "external_kind": external["kind"] if bundled is None and external else None,
            "bundled_path": bundled_relative,
        })
    external_prerequisites = sorted({
        item["name"]
        for item in imports
        if item["status"] == "declared_prerequisite"
    })
    status = "fail" if missing or non_pe or duplicate_names else (
        "pass_with_prerequisites" if external_prerequisites else "pass"
    )
    return {
        "schema_version": 1,
        "package_root": str(root),
        "entry_points": [entry.replace("\\", "/") for entry in entries],
        "files_scanned": sorted(path.relative_to(root).as_posix() for path in visited),
        "imports": imports,
        "missing": sorted(set(missing)),
        "external_prerequisites": external_prerequisites,
        "non_pe_files": sorted(non_pe),
        "export_failures": export_failures,
        "duplicate_bundled_names": duplicate_names,
        "status": "fail" if export_failures else status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--entry", action="append", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--dynamic", action="append", default=[])
    parser.add_argument("--require-export", action="append", default=[])
    args = parser.parse_args()
    result = audit(
        args.root,
        args.entry,
        _load_policy(args.policy),
        args.dynamic,
        args.require_export,
    )
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if result["status"] != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
