"""Audit Windows PE imports for a native release directory.

The auditor intentionally uses only the Python standard library.  It walks
imports from the supplied entry points, records whether each DLL is bundled,
and classifies known Windows/driver imports separately from unresolved third
party dependencies.  It does not load or execute any binary.
"""

from __future__ import annotations

import argparse
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


def _imports(path: Path) -> list[str]:
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
    import_rva = _u32(data, data_directory + 8)
    if not import_rva:
        return []
    section_table = optional + optional_size
    sections: list[tuple[int, int, int, int]] = []
    for index in range(section_count):
        section = section_table + index * 40
        virtual_size = _u32(data, section + 8)
        virtual_address = _u32(data, section + 12)
        raw_size = _u32(data, section + 16)
        raw_pointer = _u32(data, section + 20)
        sections.append((virtual_address, max(virtual_size, raw_size), raw_pointer, raw_size))

    def rva_to_file_offset(rva: int) -> int:
        for virtual_address, span, raw_pointer, raw_size in sections:
            if virtual_address <= rva < virtual_address + span:
                delta = rva - virtual_address
                if delta >= raw_size:
                    raise PeFormatError(f"RVA outside raw section in {path.name}")
                return raw_pointer + delta
        raise PeFormatError(f"RVA not mapped by a section in {path.name}")

    descriptor = rva_to_file_offset(import_rva)
    names: list[str] = []
    for index in range(65536):
        entry = descriptor + index * 20
        if entry + 20 > len(data):
            raise PeFormatError(f"truncated import table in {path.name}")
        original_first_thunk, _, _, name_rva, _ = struct.unpack_from("<5I", data, entry)
        if not (original_first_thunk or name_rva):
            break
        name_offset = rva_to_file_offset(name_rva)
        end = data.find(b"\0", name_offset)
        if end < 0:
            raise PeFormatError(f"unterminated import name in {path.name}")
        names.append(data[name_offset:end].decode("ascii"))
    else:
        raise PeFormatError(f"import table is unbounded in {path.name}")
    return names


_SYSTEM_PREFIXES = (
    "api-ms-win-",
    "ext-ms-win-",
)
_SYSTEM_NAMES = {
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
    "ucrtbase.dll",
}


def _classify_external(name: str) -> str:
    lower = name.lower()
    if lower == "nvcuda.dll":
        return "driver"
    if lower in _SYSTEM_NAMES or lower.startswith(_SYSTEM_PREFIXES):
        return "windows"
    if lower.startswith(("msvcp", "vcruntime")) and lower.endswith(".dll"):
        return "vc_runtime"
    if lower.startswith(("cudart", "cublas", "cufft", "curand", "cusparse")):
        return "cuda_runtime"
    return "unresolved_external"


def audit(root: Path, entries: list[str]) -> dict[str, object]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"package root does not exist: {root}")
    by_name = {path.name.lower(): path for path in root.rglob("*.dll")}
    by_name.update({path.name.lower(): path for path in root.rglob("*.exe")})
    queue: deque[tuple[str, Path]] = deque()
    for entry in entries:
        path = (root / entry).resolve()
        if not path.is_file() or root not in path.parents:
            raise ValueError(f"entry is not a package file: {entry}")
        queue.append((entry.replace("\\", "/"), path))
    visited: set[Path] = set()
    imports: list[dict[str, object]] = []
    unresolved: list[str] = []
    non_pe: list[str] = []
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
        for name in sorted(set(names), key=str.lower):
            bundled = by_name.get(name.lower())
            if bundled is not None:
                status = "bundled"
                bundled_relative = bundled.relative_to(root).as_posix()
                queue.append((bundled_relative, bundled))
            else:
                status = _classify_external(name)
                if status == "unresolved_external":
                    unresolved.append(name.lower())
                bundled_relative = None
            imports.append({
                "importer": relative,
                "name": name,
                "status": status,
                "bundled_path": bundled_relative,
            })
    return {
        "schema_version": 1,
        "package_root": str(root),
        "entry_points": [entry.replace("\\", "/") for entry in entries],
        "files_scanned": sorted(path.relative_to(root).as_posix() for path in visited),
        "imports": imports,
        "unresolved_external": sorted(set(unresolved)),
        "non_pe_files": sorted(non_pe),
        "status": "fail" if unresolved or non_pe else "pass",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--entry", action="append", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.root, args.entry)
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
