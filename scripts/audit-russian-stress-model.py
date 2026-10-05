"""Audit a local Russian stress-model directory for native split-GGUF use.

The audit is deliberately offline and does not download model files.  It
reports the files and formats present, then determines whether a talker GGUF
and codec GGUF pair can be passed to the current qwentts native worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any, BinaryIO

GGUF_HEADER_SIZE = 24
SUPPORTED_GGUF_VERSIONS = {1, 2, 3}
GGUF_METADATA_TYPES = {
    0: "uint8", 1: "int8", 2: "uint16", 3: "int16", 4: "uint32",
    5: "int32", 6: "float32", 7: "bool", 8: "string", 9: "array",
    10: "uint64", 11: "int64", 12: "float64",
}
GGUF_SCALAR_FORMATS = {
    0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
    6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d",
}
GGUF_METADATA_KEYS = {
    "general.architecture", "general.basename", "general.file_type",
    "general.name", "general.quantization_version", "tokenizer.ggml.model",
    "tokenizer.ggml.tokens",
}
QUANTIZATION_RE = re.compile(
    r"(?:q\d+(?:_[a-z0-9]+)?|f16|f32|fp16|fp32)", re.IGNORECASE
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    value = stream.read(size)
    if len(value) != size:
        raise ValueError("truncated GGUF metadata")
    return value


def _read_gguf_string(stream: BinaryIO) -> str:
    length = struct.unpack("<Q", _read_exact(stream, 8))[0]
    if length > 16 * 1024 * 1024:
        raise ValueError("GGUF metadata string is too large")
    return _read_exact(stream, length).decode("utf-8", errors="replace")


def _read_gguf_value(stream: BinaryIO, value_type: int) -> Any:
    if value_type == 8:
        return _read_gguf_string(stream)
    scalar_format = GGUF_SCALAR_FORMATS.get(value_type)
    if scalar_format is not None:
        size = struct.calcsize(scalar_format)
        return struct.unpack(scalar_format, _read_exact(stream, size))[0]
    if value_type == 9:
        element_type = struct.unpack("<I", _read_exact(stream, 4))[0]
        length = struct.unpack("<Q", _read_exact(stream, 8))[0]
        if length > 1_000_000:
            raise ValueError("GGUF metadata array is too large")
        for _ in range(length):
            _read_gguf_value(stream, element_type)
        return {
            "type": GGUF_METADATA_TYPES.get(element_type, str(element_type)),
            "length": length,
        }
    raise ValueError(f"unsupported GGUF metadata type: {value_type}")


def read_gguf_metadata(path: Path) -> dict[str, Any]:
    """Read selected GGUF metadata without loading tensor data."""

    metadata: dict[str, Any] = {}
    with path.open("rb") as stream:
        header = _read_exact(stream, GGUF_HEADER_SIZE)
        magic, version, _tensor_count, metadata_count = struct.unpack("<4sIQQ", header)
        if magic != b"GGUF" or version not in SUPPORTED_GGUF_VERSIONS:
            return metadata
        for _ in range(metadata_count):
            key = _read_gguf_string(stream)
            value_type = struct.unpack("<I", _read_exact(stream, 4))[0]
            value = _read_gguf_value(stream, value_type)
            if key in GGUF_METADATA_KEYS:
                metadata[key] = value
    return metadata


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
    if report["is_gguf"] and report["supported_version"]:
        try:
            report["metadata"] = read_gguf_metadata(path)
        except (OSError, ValueError, struct.error) as error:
            report["metadata_error"] = str(error)
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
        return {
            "present": True,
            "valid_json": False,
            "error": "metadata must be a JSON object",
        }
    stress_marks = str(value.get("stress_marks", ""))
    return {
        "present": True,
        "valid_json": True,
        "language": value.get("language"),
        "base": value.get("base"),
        "stress_marks": stress_marks,
        "uses_combining_acute": "U+0301" in stress_marks or "0301" in stress_marks,
        "yo_not_marked": (
            "\u0451" in stress_marks.lower() and "not" in stress_marks.lower()
        ),
        "raw": value,
    }


def inspect_tokenizer(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {"present": True, "valid_json": False, "error": str(error)}
    model = value.get("model") if isinstance(value, dict) else None
    vocab = model.get("vocab") if isinstance(model, dict) else None
    return {
        "present": True,
        "valid_json": isinstance(value, dict),
        "model_type": model.get("type") if isinstance(model, dict) else None,
        "vocab_size": len(vocab) if isinstance(vocab, dict) else None,
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
    tokenizer = inspect_tokenizer(root / "tokenizer.json")
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
        blockers.append(
            "missing a valid codec/tokenizer GGUF required by qwentts --codec-model"
        )
    if role_files.get("codec_decoder_onnx") or role_files.get("codec_encoder_onnx"):
        blockers.append(
            "ONNX codec assets are not accepted as the native split-GGUF codec model"
        )
    if predictors and not valid_codecs:
        blockers.append(
            "standalone predictor GGUF does not replace the required native codec GGUF"
        )
    if not metadata.get("present") or not metadata.get("valid_json"):
        blockers.append("missing valid stress.json provenance")

    license_files = [
        item["path"]
        for item in files
        if item["path"].split("/")[-1].lower().startswith(("license", "copying"))
    ]
    quantization_variants = sorted(
        {
            match.group(0).lower()
            for item in files
            for match in QUANTIZATION_RE.finditer(item["path"])
        }
    )

    report: dict[str, Any] = {
        "schema_version": 1,
        "audit": "russian_stress_model_compatibility",
        "model_directory": str(root),
        "repository": {"id": repo_id, "revision": revision},
        "stress_metadata": metadata,
        "tokenizer": tokenizer,
        "provenance": {
            "source_repo": repo_id,
            "source_revision": revision,
            "base_model": metadata.get("base"),
            "license_files": license_files,
            "quantization_variants": quantization_variants,
            "stress_marker": "U+0301 combining acute after stressed vowel",
            "yo_marker": "U+0451 is not marked by the source contract",
        },
        "files": files,
        "roles": role_files,
        "native_requirements": {
            "talker_gguf_candidates": talkers,
            "codec_gguf_candidates": codecs,
            "predictor_gguf_candidates": predictors,
            "valid_talker_gguf": valid_talkers,
            "valid_codec_gguf": valid_codecs,
            "native_split_gguf_compatible": bool(valid_talkers and valid_codecs),
            "loader_contract": {
                "talker_argument": "GGUF",
                "codec_argument": "GGUF tokenizer/codec model",
                "standalone_predictor_argument": False,
                "onnx_codec_accepted": False,
            },
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
