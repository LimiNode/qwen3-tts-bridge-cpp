"""Audit a local Russian stress-model directory for native split-GGUF use.

The audit is deliberately offline and does not download model files.  It
reports the files and formats present, then determines whether a talker GGUF
and codec GGUF pair can be passed to the current qwentts native worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any


GGUF_HEADER_SIZE = 24
SUPPORTED_GGUF_VERSIONS = {1, 2, 3}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_gguf(path: Path) -> dict[str, Any]:
    """Return a lightweight GGUF header report without parsing model tensors."""

    report: dict[str, Any] = {"is_gguf": False}
    try:
        with path.open("rb") as stream:
            header = stream.read(GGUF_HEADER_SIZE)
    except OSError as error:
        report["error"] = str(error)
        return report

    if len(header) < GGUF_HEADER_SIZE:
        report["error"] = "file is shorter than a GGUF header"
        return report

    magic, version, tensor_count, metadata_count = struct.unpack("<4sIQQ", header)
    report.update(
        {
            "magic": magic.decode("ascii", errors="replace"),
            "version": version,
            "tensor_count": tensor_count,
            "metadata_count": metadata_count,
            "is_gguf": magic == b"GGUF",
            "supported_version": version in SUPPORTED_GGUF_VERSIONS,
        }
    )
    return report


def classify_file(path: Path) -> list[str]:
    """Classify a model artifact by conservative filename and suffix rules."""

    name = path.name.lower()
    suffix = path.suffix.lower()
    roles: list[str] = []
    if suffix == ".gguf":
        if "talker" in name:
            roles.append("talker_gguf")
        if "predictor" in name:
            roles.append("predictor_gguf")
        if "codec" in name or "tokenizer" in name:
            roles.append("codec_gguf_candidate")
    if suffix == ".onnx":
        if "decoder" in name or "codec" in name:
            roles.append("codec_decoder_onnx")
        if "encoder" in name:
            roles.append("codec_encoder_onnx")
        if "speaker" in name and "encoder" in name:
            roles.append("speaker_encoder_onnx")
    if name == "stress.json":
        roles.append("stress_metadata")
    return roles


def load_stress_metadata(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {"present": True, "valid_json": False, "error": str(error)}
    if not isinstance(value, dict):
        return {"present": True, "valid_json": False, "error": "metadata must be a JSON object"}
    stress_marks = str(value.get("stress_marks", ""))
    return {
        "present": True,
        "valid_json": True,
        "language": value.get("language"),
        "base": value.get("base"),
        "stress_marks": stress_marks,
        "uses_combining_acute": "U+0301" in stress_marks or "0301" in stress_marks,
        "yo_not_marked": "ё" in stress_marks.lower() and "not" in stress_marks.lower(),
        "raw": value,
    }


def audit_model_directory(
    model_dir: Path,
    *,
    repo_id: str | None = None,
    revision: str | None = None,
    metadata_file: Path | None = None,
    include_hashes: bool = False,
) -> dict[str, Any]:
    """Build a JSON-compatible compatibility report for ``model_dir``."""

    root = model_dir.resolve()
    if not root.is_dir():
        raise ValueError(f"model directory does not exist: {root}")

    files: list[dict[str, Any]] = []
    role_files: dict[str, list[str]] = {}
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and not {".git", ".hg", ".svn"}.intersection(item.parts)
    ):
        relative = path.relative_to(root).as_posix()
        roles = classify_file(path)
        entry: dict[str, Any] = {
            "path": relative,
            "size_bytes": path.stat().st_size,
            "suffix": path.suffix.lower(),
            "roles": roles,
        }
        if path.suffix.lower() == ".gguf":
            entry["gguf"] = inspect_gguf(path)
        if include_hashes:
            entry["sha256"] = sha256(path)
        files.append(entry)
        for role in roles:
            role_files.setdefault(role, []).append(relative)

    stress_path = root / "stress.json"
    metadata = load_stress_metadata(metadata_file or stress_path)
    talkers = role_files.get("talker_gguf", [])
    codecs = role_files.get("codec_gguf_candidate", [])
    predictors = role_files.get("predictor_gguf", [])
    valid_talkers = [
        item["path"]
        for item in files
        if "talker_gguf" in item["roles"]
        and item.get("gguf", {}).get("is_gguf")
        and item.get("gguf", {}).get("supported_version")
    ]
    valid_codecs = [
        item["path"]
        for item in files
        if "codec_gguf_candidate" in item["roles"]
        and item.get("gguf", {}).get("is_gguf")
        and item.get("gguf", {}).get("supported_version")
    ]
    blockers: list[str] = []
    if not valid_talkers:
        blockers.append("missing a valid talker GGUF")
    if not valid_codecs:
        blockers.append("missing a valid codec/tokenizer GGUF required by qwentts --codec-model")
    if role_files.get("codec_decoder_onnx") or role_files.get("codec_encoder_onnx"):
        blockers.append("ONNX codec assets are not accepted as the native split-GGUF codec model")
    if predictors and not valid_codecs:
        blockers.append("standalone predictor GGUF does not replace the required native codec GGUF")

    report: dict[str, Any] = {
        "schema_version": 1,
        "audit": "russian_stress_model_compatibility",
        "model_directory": str(root),
        "repository": {"id": repo_id, "revision": revision},
        "stress_metadata": metadata,
        "files": files,
        "roles": role_files,
        "native_requirements": {
            "talker_gguf_candidates": talkers,
            "codec_gguf_candidates": codecs,
            "predictor_gguf_candidates": predictors,
            "valid_talker_gguf": valid_talkers,
            "valid_codec_gguf": valid_codecs,
            "native_split_gguf_compatible": bool(valid_talkers and valid_codecs),
            "blockers": blockers,
        },
        "production_default_changed": False,
    }
    if metadata_file is not None:
        report["metadata_file"] = str(metadata_file.resolve())
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--repo-id")
    parser.add_argument("--revision")
    parser.add_argument("--metadata-file", type=Path)
    parser.add_argument("--hash-files", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = audit_model_directory(
            args.model_dir,
            repo_id=args.repo_id,
            revision=args.revision,
            metadata_file=args.metadata_file,
            include_hashes=args.hash_files,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
