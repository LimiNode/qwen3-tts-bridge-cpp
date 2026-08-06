"""Stage, seal, and verify selected voice-profile assets for a portable package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import wave
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 2
_LEGACY_SCHEMA_VERSION = 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    stage_parser = subparsers.add_parser("stage")
    stage_parser.add_argument("--source-root", type=Path, required=True)
    stage_parser.add_argument("--source-registry", type=Path, required=True)
    stage_parser.add_argument("--output-root", type=Path, required=True)
    stage_parser.add_argument("--registry", type=Path, required=True)
    stage_parser.add_argument("--voice-dir", type=Path, required=True)
    stage_parser.add_argument("--provenance", type=Path, required=True)
    stage_parser.add_argument("--voice-id", action="append", required=True)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--root", type=Path, required=True)
    build_parser.add_argument("--registry", type=Path, required=True)
    build_parser.add_argument("--provenance", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--package-id", required=True)
    build_parser.add_argument("--temperature", type=float, default=0.45)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--root", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "stage":
        stage_profiles(
            source_root=args.source_root,
            source_registry=args.source_registry,
            output_root=args.output_root,
            registry=args.registry,
            voice_dir=args.voice_dir,
            provenance=args.provenance,
            voice_ids=args.voice_id,
        )
        return 0
    if args.command == "build":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(
            _json_bytes(
                build_manifest(
                    root=args.root,
                    registry=args.registry,
                    provenance=args.provenance,
                    temperature=args.temperature,
                    package_id=args.package_id,
                )
            )
        )
        return 0

    verify_manifest(args.root, _load_json(args.manifest))
    return 0


def stage_profiles(
    *,
    source_root: Path,
    source_registry: Path,
    output_root: Path,
    registry: Path,
    voice_dir: Path,
    provenance: Path,
    voice_ids: list[str],
) -> None:
    """Copy selected profiles and create a package-relative registry."""

    source_root = source_root.resolve()
    output_root = output_root.resolve()
    source_data = _load_json(source_registry)
    voices = _require_list(source_data, "voices", "source registry")
    requested_ids = _unique_voice_ids(voice_ids)
    source_by_id = {
        _require_string(entry, "voice_id", "source registry voice"): entry
        for entry in voices
        if isinstance(entry, dict)
    }
    if len(source_by_id) != len(voices):
        raise ValueError(
            "source registry voices must be object entries with unique voice_id"
        )

    staged_voices: list[dict[str, object]] = []
    staged_voice_dir = output_root / voice_dir
    staged_voice_dir.mkdir(parents=True, exist_ok=True)
    registry_path = output_root / registry
    for voice_id in requested_ids:
        entry = source_by_id.get(voice_id)
        if entry is None:
            raise ValueError(f"source registry has no requested voice_id: {voice_id}")
        source_audio = _resolve_relative(source_registry.parent, _require_string(
            entry, "reference_audio_path", f"voice profile {voice_id}"
        ))
        if not source_audio.is_file():
            raise ValueError(f"voice profile audio does not exist: {source_audio}")
        source_audio.resolve().relative_to(source_root)
        target_audio = staged_voice_dir / source_audio.name
        shutil.copyfile(source_audio, target_audio)

        staged_entry = dict(entry)
        staged_entry["reference_audio_path"] = _relative_from(
            registry_path.parent,
            target_audio,
        )
        staged_voices.append(staged_entry)

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_bytes(
        _json_bytes({"schema_version": 1, "voices": staged_voices})
    )

    provenance_path = output_root / provenance
    if not provenance_path.is_file():
        raise ValueError(f"staged provenance is missing: {provenance_path}")


def build_manifest(
    *,
    root: Path,
    registry: Path,
    provenance: Path,
    temperature: float,
    package_id: str,
    schema_version: int = _SCHEMA_VERSION,
) -> dict[str, object]:
    """Return an exact-content manifest for a staged voice registry."""

    if not (0.0 < temperature <= 2.0):
        raise ValueError("temperature must be in the interval (0, 2]")
    if schema_version not in {_LEGACY_SCHEMA_VERSION, _SCHEMA_VERSION}:
        raise ValueError("unsupported voice assets manifest schema")
    if schema_version == _SCHEMA_VERSION and not package_id.strip():
        raise ValueError("package_id must be non-empty")
    root = root.resolve()
    registry_path = _resolve_under_root(root, registry, "registry")
    provenance_path = _resolve_under_root(root, provenance, "provenance")
    registry_data = _load_json(registry_path)
    provenance_data = _load_json(provenance_path)
    provenance_profiles = {
        _require_string(entry, "voice_id", "provenance profile"): entry
        for entry in _require_list(provenance_data, "profiles", "provenance")
        if isinstance(entry, dict)
    }

    entries = _require_list(registry_data, "voices", "registry")
    voices: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("registry voice must be an object")
        voice_id = _require_string(entry, "voice_id", "registry voice")
        reference_text = _require_string(entry, "reference_text", f"voice {voice_id}")
        source_audio = _resolve_relative(
            registry_path.parent,
            _require_string(entry, "reference_audio_path", f"voice {voice_id}"),
        )
        source_audio = _resolve_under_root(
            root, source_audio, f"voice {voice_id} audio"
        )
        profile = provenance_profiles.get(voice_id)
        if profile is None:
            raise ValueError(f"provenance has no profile entry for {voice_id}")
        quality_status = _require_string(
            profile, "quality_status", f"provenance {voice_id}"
        )
        audio = {
            "path": _relative_path(root, source_audio),
            "sha256": _sha256_file(source_audio),
            "size_bytes": source_audio.stat().st_size,
            "duration_seconds": _wav_duration_seconds(source_audio),
        }
        voices.append(
            {
                "voice_id": voice_id,
                "mode": "x_vector" if entry.get("x_vector_only") is True else "icl",
                "registry_entry_sha256": _sha256(_json_bytes(entry)),
                "reference_audio": audio,
                "reference_text_sha256": _sha256(reference_text.encode("utf-8")),
                "processing_manifest": {
                    "path": _relative_path(root, provenance_path),
                    "sha256": _sha256_file(provenance_path),
                },
                "recommended_sampling": {"temperature": temperature},
                "quality_status": quality_status,
            }
        )

    payload: dict[str, object] = {
        "voice_assets_manifest_schema_version": schema_version,
        "registry": {
            "path": _relative_path(root, registry_path),
            "sha256": _sha256_file(registry_path),
        },
        "voices": sorted(voices, key=lambda value: str(value["voice_id"])),
    }
    if schema_version == _SCHEMA_VERSION:
        payload["package_id"] = package_id
    payload["voice_assets_manifest_sha256"] = _sha256(_json_bytes(payload))
    return payload


def verify_manifest(root: Path, manifest: dict[str, object]) -> None:
    """Raise ``ValueError`` unless the staged voice assets match exactly."""

    schema_version = manifest.get("voice_assets_manifest_schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version not in {_LEGACY_SCHEMA_VERSION, _SCHEMA_VERSION}
    ):
        raise ValueError("unsupported voice assets manifest schema")
    package_id = manifest.get("package_id")
    if schema_version == _SCHEMA_VERSION and (
        not isinstance(package_id, str) or not package_id.strip()
    ):
        raise ValueError("voice assets manifest package_id is invalid")
    expected_hash = manifest.get("voice_assets_manifest_sha256")
    unsigned = dict(manifest)
    unsigned.pop("voice_assets_manifest_sha256", None)
    if (
        not isinstance(expected_hash, str)
        or _sha256(_json_bytes(unsigned)) != expected_hash
    ):
        raise ValueError("voice assets manifest SHA is invalid")

    registry = manifest.get("registry")
    if not isinstance(registry, dict):
        raise ValueError("voice assets manifest registry must be an object")
    registry_path = registry.get("path")
    if not isinstance(registry_path, str):
        raise ValueError("voice assets manifest registry path is invalid")
    try:
        expected = build_manifest(
            root=root,
            registry=Path(registry_path),
            provenance=Path(_require_processing_path(manifest)),
            temperature=_manifest_temperature(manifest),
            package_id=package_id if isinstance(package_id, str) else "legacy-r3",
            schema_version=schema_version if isinstance(schema_version, int) else -1,
        )
    except ValueError as exc:
        raise ValueError("voice assets do not match manifest") from exc
    if manifest != expected:
        raise ValueError("voice assets do not match manifest")


def _require_processing_path(manifest: dict[str, object]) -> str:
    voices = _require_list(manifest, "voices", "voice assets manifest")
    if not voices or not isinstance(voices[0], dict):
        raise ValueError("voice assets manifest has no voices")
    processing = voices[0].get("processing_manifest")
    if not isinstance(processing, dict) or not isinstance(processing.get("path"), str):
        raise ValueError("voice assets manifest processing manifest path is invalid")
    return processing["path"]


def _manifest_temperature(manifest: dict[str, object]) -> float:
    voices = _require_list(manifest, "voices", "voice assets manifest")
    if not voices or not isinstance(voices[0], dict):
        raise ValueError("voice assets manifest has no voices")
    sampling = voices[0].get("recommended_sampling")
    if not isinstance(sampling, dict) or not isinstance(
        sampling.get("temperature"), float
    ):
        raise ValueError("voice assets manifest sampling is invalid")
    return sampling["temperature"]


def _unique_voice_ids(values: list[str]) -> list[str]:
    if not values or any(not value.strip() for value in values):
        raise ValueError("at least one non-empty voice_id is required")
    if len(set(values)) != len(values):
        raise ValueError("voice_id values must be unique")
    return values


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys in sealed voice metadata."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_list(value: dict[str, Any], field: str, context: str) -> list[Any]:
    result = value.get(field)
    if not isinstance(result, list):
        raise ValueError(f"{context} field must be a list: {field}")
    return result


def _require_string(value: dict[str, Any], field: str, context: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise ValueError(f"{context} field must be a non-empty string: {field}")
    return result


def _resolve_relative(base: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else base / candidate


def _resolve_under_root(root: Path, path: Path, description: str) -> Path:
    resolved = (root / path if not path.is_absolute() else path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"{description} must be inside package root: {resolved}"
        ) from exc
    if not resolved.is_file():
        raise ValueError(f"{description} does not exist: {resolved}")
    return resolved


def _relative_path(base: Path, path: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def _relative_from(base: Path, path: Path) -> str:
    return Path(os.path.relpath(path.resolve(), base.resolve())).as_posix()


def _wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getframerate() <= 0:
                raise ValueError("WAV sample rate must be positive")
            return round(wav.getnframes() / wav.getframerate(), 6)
    except (EOFError, wave.Error) as exc:
        raise ValueError(
            f"voice reference must be a readable WAV file: {path}"
        ) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
