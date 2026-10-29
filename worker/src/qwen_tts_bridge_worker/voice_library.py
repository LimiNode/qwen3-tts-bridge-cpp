"""Managed user voice library built on the schema-1 voice registry."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import struct
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from qwen_tts_bridge_worker.engine.voice_profiles import (
    VoiceProfileError,
    preflight_reference_audio,
)
from qwen_tts_bridge_worker.model_resolver import (
    default_user_config_path,
    load_user_config,
    resolve_native_profile,
)

_SCHEMA_VERSION = 1
_MAGIC = b"QTB1"
_FRAME_HEADER = struct.Struct("<4sHHHHIQ")
_MAX_MANIFEST_BYTES = 1 << 20
_MAX_SPEAKER_DIMENSION = 1 << 20
_MAX_SPEAKER_BYTES = 16 << 20
_MAX_RVQ_CODEBOOKS = 64
_MAX_RVQ_FRAMES = 1 << 20
_MAX_RVQ_BYTES = 256 << 20
_MAX_NATIVE_STDERR_BYTES = 1 << 20
_ENTRY_MARKER = ".qtb-managed-entry"


class VoiceLibraryError(ValueError):
    """Raised for invalid, conflicting, or unverifiable voice-library state."""


def default_voice_registry_path(config_path: Path | None = None) -> Path:
    """Resolve the managed registry path from the user CLI config."""

    config = _selected_config_path(config_path)
    payload = load_user_config(config)
    value = payload.get("voice_library")
    if isinstance(value, dict):
        configured = value.get("registry_path")
        if isinstance(configured, str) and configured.strip():
            path = Path(configured).expanduser()
            return (
                (config.parent / path).resolve()
                if not path.is_absolute()
                else path.resolve()
            )
    configured = payload.get("voice_registry_path")
    if isinstance(configured, str) and configured.strip():
        path = Path(configured).expanduser()
        return (
            (config.parent / path).resolve()
            if not path.is_absolute()
            else path.resolve()
        )
    return config.parent / "voices" / "registry.json"


def load_voice_rows(
    registry_path: Path, *, allow_missing: bool = True
) -> list[dict[str, Any]]:
    """Load and validate schema-1 registry rows."""

    if not registry_path.is_file():
        if allow_missing:
            return []
        raise VoiceLibraryError(f"voice registry was not found: {registry_path}")
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VoiceLibraryError(
            f"voice registry is not valid UTF-8 JSON: {registry_path}"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _SCHEMA_VERSION
    ):
        raise VoiceLibraryError("voice registry must be a schema_version 1 object")
    rows = payload.get("voices")
    if not isinstance(rows, list):
        raise VoiceLibraryError("voice registry voices must be an array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise VoiceLibraryError("each voice registry row must be an object")
        voice_id = row.get("voice_id")
        if not isinstance(voice_id, str) or not voice_id.strip():
            raise VoiceLibraryError("voice_id must be a non-empty string")
        voice_id = voice_id.strip()
        if voice_id in seen:
            raise VoiceLibraryError(f"duplicate voice_id: {voice_id}")
        seen.add(voice_id)
        result.append(dict(row, voice_id=voice_id))
    return result


def add_voice(
    registry_path: Path,
    *,
    voice_id: str,
    wav_path: Path,
    reference_text: str,
    x_vector_only: bool,
    preserve_reference_text_whitespace: bool,
) -> dict[str, Any]:
    """Validate and atomically add a managed copy of a reference WAV."""

    voice_id = _require_voice_id(voice_id)
    text = (
        reference_text if preserve_reference_text_whitespace else reference_text.strip()
    )
    try:
        audio = preflight_reference_audio(wav_path, text, x_vector_only)
    except VoiceProfileError as exc:
        raise VoiceLibraryError(str(exc)) from exc
    registry_path = registry_path.expanduser().resolve()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with _registry_lock(registry_path):
        rows = load_voice_rows(registry_path)
        _cleanup_orphaned_entries(registry_path, rows)
        if any(row["voice_id"] == voice_id for row in rows):
            raise VoiceLibraryError(f"voice_id already exists: {voice_id}")
        internal_id = _internal_id(voice_id)
        entry_dir = registry_path.parent / "entries" / internal_id
        if entry_dir.exists():
            raise VoiceLibraryError(f"managed voice entry already exists: {entry_dir}")
        staging = (
            registry_path.parent / f".entry-{internal_id}.{uuid.uuid4().hex}.incomplete"
        )
        try:
            (staging / "native").mkdir(parents=True)
            managed_wav = staging / "reference.wav"
            shutil.copy2(audio.path, managed_wav)
            if _sha256_file(managed_wav) != audio.sha256:
                raise VoiceLibraryError(
                    "managed reference copy does not match the validated source WAV"
                )
            (staging / "reference.txt").write_text(text, encoding="utf-8")
            (staging / _ENTRY_MARKER).write_text(
                json.dumps({"schema_version": 1, "voice_id": voice_id}) + "\n",
                encoding="utf-8",
            )
            entry_dir.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(entry_dir)
            relative_wav = Path("entries") / internal_id / "reference.wav"
            row: dict[str, Any] = {
                "voice_id": voice_id,
                "reference_audio_path": relative_wav.as_posix(),
                "reference_text": text,
                "preserve_reference_text_whitespace": (
                    preserve_reference_text_whitespace
                ),
                "x_vector_only": x_vector_only,
                "managed_reference_audio": True,
                "source_reference_audio_path": str(audio.path),
                "reference_audio_sha256": audio.sha256,
            }
            _atomic_write_registry(registry_path, rows + [row])
            return row
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(entry_dir, ignore_errors=True)
            raise


def list_voices(registry_path: Path) -> list[dict[str, Any]]:
    """Return deterministic user-facing voice status rows without loading models."""

    rows = load_voice_rows(registry_path)
    result: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda value: value["voice_id"]):
        audio_path = _row_audio_path(registry_path, row)
        python_status = "missing"
        if audio_path.is_file():
            try:
                audio = preflight_reference_audio(
                    audio_path,
                    str(row.get("reference_text", "")),
                    bool(row.get("x_vector_only", False)),
                )
                expected = row.get("reference_audio_sha256")
                python_status = (
                    "compatible" if expected in (None, audio.sha256) else "changed"
                )
            except VoiceProfileError:
                python_status = "incompatible"
        native_status = "unprepared"
        native_entries: list[dict[str, Any]] = []
        references = row.get("native_references")
        if isinstance(references, dict):
            native_entries.extend(
                value for value in references.values() if isinstance(value, dict)
            )
        legacy = row.get("native_reference")
        if isinstance(legacy, dict):
            native_entries.append(legacy)
        if native_entries:
            native_status = (
                "prepared"
                if all(
                    isinstance(native.get("manifest_path"), str)
                    and _manifest_files_present(registry_path, native["manifest_path"])
                    for native in native_entries
                )
                else "stale"
            )
        result.append(
            {
                "voice_id": row["voice_id"],
                "reference_audio_present": audio_path.is_file(),
                "python_status": python_status,
                "native_status": native_status,
                "native_profile_count": len(native_entries),
            }
        )
    return result


def show_voice(registry_path: Path, voice_id: str) -> dict[str, Any]:
    """Return the full persisted row plus current file metadata."""

    row = _find_row(load_voice_rows(registry_path, allow_missing=False), voice_id)
    audio_path = _row_audio_path(registry_path, row)
    result = dict(row)
    result["registry_path"] = str(registry_path)
    result["resolved_reference_audio_path"] = str(audio_path)
    result["reference_audio_present"] = audio_path.is_file()
    if audio_path.is_file():
        try:
            info = preflight_reference_audio(
                audio_path,
                str(row.get("reference_text", "")),
                bool(row.get("x_vector_only", False)),
            )
            result["audio"] = {
                "sha256": info.sha256,
                "duration_seconds": info.duration_seconds,
                "sample_rate": info.sample_rate,
                "channels": info.channels,
                "sample_width_bytes": info.sample_width_bytes,
            }
        except VoiceProfileError as exc:
            result["audio_error"] = str(exc)
    return result


def verify_voice(
    registry_path: Path,
    voice_id: str,
    *,
    backend: str,
    native_profile: str | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Verify Python compatibility or persisted native identity."""

    row = _find_row(load_voice_rows(registry_path, allow_missing=False), voice_id)
    audio_path = _row_audio_path(registry_path, row)
    if backend == "python":
        try:
            info = preflight_reference_audio(
                audio_path,
                str(row.get("reference_text", "")),
                bool(row.get("x_vector_only", False)),
            )
        except (VoiceProfileError, OSError) as exc:
            return {
                "voice_id": voice_id,
                "backend": backend,
                "status": "incompatible",
                "error": str(exc),
            }
        expected = row.get("reference_audio_sha256")
        status = "compatible" if expected in (None, info.sha256) else "incompatible"
        return {
            "voice_id": voice_id,
            "backend": backend,
            "status": status,
            "sha256": info.sha256,
            "path": str(audio_path),
        }
    if backend != "native":
        raise VoiceLibraryError("backend must be python or native")
    if not native_profile:
        raise VoiceLibraryError("native verification requires --native-profile")
    try:
        _validate_native_reference_paths(registry_path, row)
    except VoiceLibraryError as exc:
        return {
            "voice_id": voice_id,
            "backend": backend,
            "native_profile": native_profile,
            "status": "prepared_corrupt",
            "error": str(exc),
        }
    try:
        profile = resolve_native_profile(native_profile, config_path=config_path)
        binding = _native_binding(profile, native_profile)
    except ValueError as exc:
        return {
            "voice_id": voice_id,
            "backend": backend,
            "native_profile": native_profile,
            "status": "model_unavailable",
            "error": str(exc),
        }
    native, binding_changed = _select_native_reference(
        row, binding["binding_key"], native_profile
    )
    if native is None:
        return {
            "voice_id": voice_id,
            "backend": backend,
            "native_profile": native_profile,
            "status": "unprepared",
            "binding_key": binding["binding_key"],
        }
    if binding_changed:
        return {
            "voice_id": voice_id,
            "backend": backend,
            "native_profile": native_profile,
            "status": "prepared_stale",
            "reason": "model_binding_changed",
            "binding_key": binding["binding_key"],
        }
    try:
        manifest_path = _resolve_registry_relative_path(
            registry_path, native["manifest_path"], "manifest_path"
        )
    except (KeyError, TypeError, VoiceLibraryError) as exc:
        return {
            "voice_id": voice_id,
            "backend": backend,
            "native_profile": native_profile,
            "status": "prepared_corrupt",
            "error": str(exc),
        }
    if not manifest_path.is_file():
        return {
            "voice_id": voice_id,
            "backend": backend,
            "native_profile": native_profile,
            "status": "unprepared",
            "manifest_path": str(manifest_path),
        }
    try:
        manifest = _read_json_file_bounded(manifest_path, _MAX_MANIFEST_BYTES)
        if not isinstance(manifest, dict):
            raise ValueError("native manifest must be a JSON object")
        if (
            manifest.get("schema_version") != 1
            or manifest.get("format") != "qwen3-tts-native-voice-reference"
        ):
            raise ValueError("unsupported native manifest format")
        current_source_hash = _sha256_file(audio_path)
        recorded_source_hash = row.get("reference_audio_sha256")
        if (
            manifest.get("source_wav_sha256") != current_source_hash
            or recorded_source_hash not in (None, current_source_hash)
            or manifest.get("reference_text") != row.get("reference_text", "")
            or manifest.get("x_vector_only") != bool(row.get("x_vector_only", False))
        ):
            return {
                "voice_id": voice_id,
                "backend": backend,
                "native_profile": native_profile,
                "status": "prepared_stale",
                "manifest_path": str(manifest_path),
            }
        engine = manifest["engine"]
        if (
            engine.get("name") != binding["engine"]
            or engine.get("commit") != binding["engine_commit"]
            or engine.get("abi_version") != binding["qt_abi_version"]
        ):
            return {
                "voice_id": voice_id,
                "backend": backend,
                "native_profile": native_profile,
                "status": "prepared_stale",
                "manifest_path": str(manifest_path),
            }
        models = manifest["models"]
        if (
            models.get("talker_sha256") != binding["talker_sha256"]
            or models.get("codec_sha256") != binding["codec_sha256"]
        ):
            return {
                "voice_id": voice_id,
                "backend": backend,
                "native_profile": native_profile,
                "status": "prepared_stale",
                "manifest_path": str(manifest_path),
            }
        preprocessing = manifest["preprocessing"]
        expected_silence = 0 if bool(row.get("x_vector_only", False)) else 12_000
        if (
            preprocessing.get("version") != 1
            or preprocessing.get("sample_rate") != 24_000
            or preprocessing.get("channels") != 1
            or preprocessing.get("sample_format") != "float32"
            or preprocessing.get("icl_trailing_silence_samples") != expected_silence
        ):
            raise ValueError("native manifest preprocessing is incompatible")
        _verify_prepared_artifacts(
            manifest_path,
            manifest,
            bool(row.get("x_vector_only", False)),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "voice_id": voice_id,
            "backend": backend,
            "native_profile": native_profile,
            "status": "prepared_corrupt",
            "error": str(exc),
            "manifest_path": str(manifest_path),
        }
    return {
        "voice_id": voice_id,
        "backend": backend,
        "native_profile": native_profile,
        "status": "prepared_valid",
        "manifest_path": str(manifest_path),
        "binding_key": binding["binding_key"],
    }


def prepare_voice(
    registry_path: Path,
    voice_id: str,
    *,
    native_profile: str,
    config_path: Path | None = None,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    """Prepare one voice through the authoritative native worker."""

    if timeout_seconds <= 0:
        raise VoiceLibraryError("timeout_seconds must be greater than zero")
    registry_path = registry_path.expanduser().resolve()
    row = _find_row(load_voice_rows(registry_path, allow_missing=False), voice_id)
    current = verify_voice(
        registry_path,
        voice_id,
        backend="native",
        native_profile=native_profile,
        config_path=config_path,
    )
    if current["status"] == "prepared_valid":
        return current | {"idempotent": True}
    if current["status"] in {"prepared_stale", "prepared_corrupt"}:
        if current.get("reason") != "model_binding_changed":
            raise VoiceLibraryError(
                "native reference is stale or corrupt; remove it explicitly "
                "before re-preparing"
            )
    profile = resolve_native_profile(native_profile, config_path=config_path)
    try:
        binding = _native_binding(profile, native_profile)
    except ValueError as exc:
        raise VoiceLibraryError(str(exc)) from exc
    audio_path = _row_audio_path(registry_path, row)
    try:
        info = preflight_reference_audio(
            audio_path,
            str(row.get("reference_text", "")),
            bool(row.get("x_vector_only", False)),
        )
    except VoiceProfileError as exc:
        raise VoiceLibraryError(f"reference is not native-compatible: {exc}") from exc
    source_hash = info.sha256
    if info.sample_rate != 24000 or info.channels != 1 or info.sample_width_bytes != 2:
        raise VoiceLibraryError("native preparation requires a mono 24000 Hz PCM16 WAV")
    relative_manifest = (
        Path("entries")
        / _internal_id(voice_id)
        / "native"
        / binding["binding_key"]
        / "manifest.json"
    )
    temp_registry = registry_path.parent / f".prepare-{uuid.uuid4().hex}.json"
    temp_row = dict(row)
    temp_row.pop("native_references", None)
    temp_row["native_reference"] = {
        "manifest_path": relative_manifest.as_posix(),
        "prepare_if_missing": True,
    }
    temp_payload = {"schema_version": 1, "voices": [temp_row]}
    _atomic_write_payload(temp_registry, temp_payload)
    try:
        worker = _resolve_native_worker(config_path, native_profile)
        command = [
            str(worker),
            "--runtime-dir",
            str(profile.runtime_dir),
            "--talker-model",
            str(profile.talker_model),
            "--codec-model",
            str(profile.codec_model),
            "--voice-registry-path",
            str(temp_registry),
        ]
        _run_native_prepare(command, voice_id, timeout_seconds)
        manifest_path = registry_path.parent / relative_manifest
        if not manifest_path.is_file():
            raise VoiceLibraryError(
                "native worker exited without publishing the expected manifest"
            )
        if _sha256_file(audio_path) != source_hash:
            raise VoiceLibraryError(
                "reference WAV changed during native preparation; retry explicitly"
            )
        # Verify before publishing the authoritative row.
        temp_verified = _verify_row_manifest(
            temp_registry, temp_row, native_profile, config_path
        )
        if temp_verified["status"] != "prepared_valid":
            raise VoiceLibraryError(
                f"native preparation did not produce a valid manifest: {temp_verified}"
            )
        with _registry_lock(registry_path):
            rows = load_voice_rows(registry_path, allow_missing=False)
            current_row = _find_row(rows, voice_id)
            if current_row != row:
                raise VoiceLibraryError(
                    "voice registry row changed during native preparation"
                )
            existing = current_row.get("native_references", {})
            if not isinstance(existing, dict):
                raise VoiceLibraryError("native_references must be an object")
            references = dict(existing)
            references[binding["binding_key"]] = {
                "manifest_path": relative_manifest.as_posix(),
                "prepare_if_missing": False,
                "native_profile": native_profile,
                "engine": binding["engine"],
                "engine_commit": binding["engine_commit"],
                "qt_abi_version": binding["qt_abi_version"],
                "talker_sha256": binding["talker_sha256"],
                "codec_sha256": binding["codec_sha256"],
            }
            current_row["native_references"] = references
            _atomic_write_registry(registry_path, rows)
        verified = verify_voice(
            registry_path,
            voice_id,
            backend="native",
            native_profile=native_profile,
            config_path=config_path,
        )
        return verified | {"idempotent": False}
    finally:
        temp_registry.unlink(missing_ok=True)


def _verify_row_manifest(
    registry_path: Path,
    row: dict[str, Any],
    native_profile: str,
    config_path: Path | None,
) -> dict[str, Any]:
    # Reuse the normal verifier with the temporary registry's row.
    return verify_voice(
        registry_path,
        row["voice_id"],
        backend="native",
        native_profile=native_profile,
        config_path=config_path,
    )


def _run_native_prepare(
    command: list[str], voice_id: str, timeout_seconds: float
) -> None:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise VoiceLibraryError(f"could not start native worker: {exc}") from exc
    assert (
        process.stdin is not None
        and process.stdout is not None
        and process.stderr is not None
    )
    stdin = process.stdin
    stdout = process.stdout
    stderr_stream = process.stderr
    stderr_chunks: list[bytes] = []
    stderr_overflow = threading.Event()
    stderr_thread = threading.Thread(
        target=_capture_stderr,
        args=(stderr_stream, stderr_chunks, stderr_overflow),
        daemon=True,
    )
    stderr_thread.start()
    frames: queue.Queue[dict[str, Any] | BaseException | None] = queue.Queue()
    reader = threading.Thread(
        target=_read_native_frames, args=(stdout, frames), daemon=True
    )
    reader.start()
    try:
        stdin.write(
            _frame(
                {
                    "message_type": "hello",
                    "client_name": "qwen-tts-voice-library",
                    "client_version": "1",
                }
            )
        )
        stdin.flush()
        deadline = time.monotonic() + timeout_seconds
        ready = False
        while time.monotonic() < deadline:
            try:
                message = frames.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                break
            if message is None:
                raise VoiceLibraryError(
                    "native worker closed protocol stream before ready"
                )
            if isinstance(message, BaseException):
                raise message
            if message.get("message_type") == "ready":
                ready = True
                ids = message.get("voice_ids", [])
                if not isinstance(ids, list) or not all(
                    isinstance(item, str) for item in ids
                ):
                    raise VoiceLibraryError(
                        "native worker returned an invalid ready voice_ids list"
                    )
                if voice_id not in ids:
                    raise VoiceLibraryError(
                        f"native worker did not advertise prepared voice_id: {voice_id}"
                    )
                break
            if message.get("message_type") == "error" or message.get("category"):
                raise VoiceLibraryError(f"native worker preparation failed: {message}")
        if not ready:
            raise VoiceLibraryError("native worker did not become ready before timeout")
        stdin.write(_frame({"message_type": "shutdown", "mode": "cancel"}))
        stdin.flush()
        shutdown_deadline = time.monotonic() + max(1.0, min(timeout_seconds, 10.0))
        shutdown_ack = False
        while time.monotonic() < shutdown_deadline:
            try:
                message = frames.get(timeout=0.1)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            if message is None:
                break
            if isinstance(message, BaseException):
                raise message
            if message.get("message_type") == "shutdown_ack":
                shutdown_ack = True
                break
            if message.get("message_type") == "error" or message.get("category"):
                raise VoiceLibraryError(f"native worker shutdown failed: {message}")
        if not shutdown_ack:
            raise VoiceLibraryError("native worker did not acknowledge shutdown")
        process.wait(timeout=max(1.0, min(timeout_seconds, 10.0)))
        stderr_thread.join(timeout=1.0)
        if stderr_overflow.is_set():
            raise VoiceLibraryError("native worker stderr exceeded the capture limit")
        if process.returncode != 0:
            detail = _stderr_text(stderr_chunks)
            suffix = f": {detail}" if detail else ""
            raise VoiceLibraryError(
                f"native worker exited with code {process.returncode}{suffix}"
            )
        metrics = _parse_native_metrics(stderr_chunks)
        evidence = [
            metric
            for metric in metrics
            if metric.get("event") == "native_voice_reference_ready"
            and metric.get("voice_id") == voice_id
            and metric.get("source") in {"persisted", "extracted_and_persisted"}
        ]
        if not evidence:
            raise VoiceLibraryError(
                "native worker did not report voice preparation evidence"
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        process.kill()
        detail = _stderr_text(stderr_chunks)
        suffix = f": {detail}" if detail else ""
        raise VoiceLibraryError(f"native preparation failed{suffix}") from exc
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)
        try:
            stdin.close()
        except OSError:
            pass
        reader.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)
        stdout.close()
        stderr_stream.close()


def _frame(payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return _FRAME_HEADER.pack(_MAGIC, 1, 24, 1, 0, len(encoded), 0) + encoded


def _read_native_frames(
    stream: Any, frames: queue.Queue[dict[str, Any] | BaseException | None]
) -> None:
    try:
        while True:
            frames.put(_read_frame_blocking(stream))
    except (OSError, VoiceLibraryError) as exc:
        frames.put(exc)
    finally:
        frames.put(None)


def _read_frame_blocking(stream: Any) -> dict[str, Any]:
    header = stream.read(_FRAME_HEADER.size)
    if not isinstance(header, bytes) or len(header) != _FRAME_HEADER.size:
        raise VoiceLibraryError("native worker closed protocol stream before ready")
    magic, version, header_size, frame_type, flags, payload_size, _request_id = (
        _FRAME_HEADER.unpack(header)
    )
    if (
        magic != _MAGIC
        or version != 1
        or header_size < _FRAME_HEADER.size
        or header_size > 4096
        or frame_type not in {1, 3}
        or flags != 0
        or payload_size > 1_048_576
    ):
        raise VoiceLibraryError("native worker returned an invalid protocol frame")
    if header_size > _FRAME_HEADER.size:
        extension = stream.read(header_size - _FRAME_HEADER.size)
        if len(extension) != header_size - _FRAME_HEADER.size:
            raise VoiceLibraryError("native worker returned a truncated frame header")
    payload = stream.read(payload_size)
    if len(payload) != payload_size:
        raise VoiceLibraryError("native worker returned a truncated protocol frame")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VoiceLibraryError("native worker returned invalid control JSON") from exc
    if not isinstance(value, dict):
        raise VoiceLibraryError("native worker control payload must be an object")
    return value


def _stderr_text(stderr_chunks: list[bytes]) -> str:
    if not stderr_chunks:
        return ""
    return stderr_chunks[0].decode("utf-8", errors="replace").strip()[:400]


def _capture_stderr(
    stream: Any, chunks: list[bytes], overflow: threading.Event
) -> None:
    total = 0
    while True:
        chunk = stream.read(64 * 1024)
        if not chunk:
            return
        total += len(chunk)
        if total <= _MAX_NATIVE_STDERR_BYTES:
            chunks.append(chunk)
        else:
            overflow.set()


def _parse_native_metrics(chunks: list[bytes]) -> list[dict[str, Any]]:
    evidence = b"".join(chunks).decode("utf-8", errors="replace")
    metrics: list[dict[str, Any]] = []
    for line in evidence.splitlines():
        if not line.startswith("qtb_metric "):
            continue
        try:
            value = json.loads(line[len("qtb_metric ") :])
        except json.JSONDecodeError as exc:
            raise VoiceLibraryError(
                "native worker emitted malformed qtb_metric JSON"
            ) from exc
        if not isinstance(value, dict):
            raise VoiceLibraryError("native worker qtb_metric must be an object")
        metrics.append(value)
    return metrics


@contextmanager
def _registry_lock(registry_path: Path) -> Iterator[None]:
    lock = registry_path.with_name(registry_path.name + ".lock")
    descriptor = -1
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_RDWR)
        if os.name == "nt":
            if os.fstat(descriptor).st_size == 0:
                os.lseek(descriptor, 0, os.SEEK_SET)
                try:
                    os.write(descriptor, b"\0")
                except OSError as exc:
                    raise VoiceLibraryError(
                        "voice registry is being modified by another process: "
                        f"{registry_path}"
                    ) from exc
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise VoiceLibraryError(
                    "voice registry is being modified by another process: "
                    f"{registry_path}"
                ) from exc
        else:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise VoiceLibraryError(
                    "voice registry is being modified by another process: "
                    f"{registry_path}"
                ) from exc
    except BaseException:
        if descriptor != -1:
            os.close(descriptor)
        raise
    try:
        yield
    finally:
        if descriptor != -1:
            if os.name == "nt":
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(descriptor)


def _atomic_write_registry(path: Path, rows: list[dict[str, Any]]) -> None:
    _atomic_write_payload(path, {"schema_version": _SCHEMA_VERSION, "voices": rows})


def _atomic_write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json_file_bounded(path: Path, maximum_bytes: int) -> Any:
    if not path.is_file():
        raise OSError(f"file was not found: {path}")
    with path.open("rb") as source:
        payload = source.read(maximum_bytes + 1)
    if len(payload) > maximum_bytes:
        raise ValueError(f"JSON file is too large: {path}")
    return json.loads(payload.decode("utf-8"))


def _selected_config_path(path: Path | None) -> Path:
    return (default_user_config_path() if path is None else path).expanduser().resolve()


def _require_voice_id(value: str) -> str:
    value = value.strip()
    if not value:
        raise VoiceLibraryError("voice_id must be a non-empty string")
    if len(value) > 128:
        raise VoiceLibraryError("voice_id is too long")
    return value


def _internal_id(voice_id: str) -> str:
    return hashlib.sha256(voice_id.encode("utf-8")).hexdigest()[:32]


def _find_row(rows: list[dict[str, Any]], voice_id: str) -> dict[str, Any]:
    voice_id = _require_voice_id(voice_id)
    for row in rows:
        if row["voice_id"] == voice_id:
            return row
    raise VoiceLibraryError(f"voice_id was not found: {voice_id}")


def _row_audio_path(registry_path: Path, row: dict[str, Any]) -> Path:
    value = row.get("reference_audio_path")
    if not isinstance(value, str) or not value.strip():
        raise VoiceLibraryError(f"voice {row['voice_id']} has no reference_audio_path")
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (registry_path.parent / path).resolve()


def _resolve_registry_relative_path(
    registry_path: Path, value: str, field_name: str
) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise VoiceLibraryError(f"{field_name} must be a relative managed path")
    root = registry_path.parent.resolve()
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise VoiceLibraryError(f"{field_name} escapes the registry directory") from exc
    return resolved


def _manifest_files_present(registry_path: Path, relative: str) -> bool:
    try:
        manifest = _resolve_registry_relative_path(
            registry_path, relative, "manifest_path"
        )
    except VoiceLibraryError:
        return False
    if not manifest.is_file():
        return False
    try:
        value = _read_json_file_bounded(manifest, _MAX_MANIFEST_BYTES)
        if not isinstance(value, dict):
            return False
        if (
            value.get("schema_version") != 1
            or value.get("format") != "qwen3-tts-native-voice-reference"
        ):
            return False
        _verify_prepared_artifacts(
            manifest, value, bool(value.get("x_vector_only", False))
        )
        return True
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        VoiceLibraryError,
    ):
        return False


def _resolve_manifest_artifact(manifest_path: Path, value: str) -> Path:
    artifact = Path(value)
    if artifact.is_absolute() or any(
        part in {"", ".", ".."} for part in artifact.parts
    ):
        raise VoiceLibraryError("native manifest artifact path is not relative")
    root = manifest_path.parent.resolve()
    resolved = (root / artifact).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise VoiceLibraryError(
            "native manifest artifact escapes its directory"
        ) from exc
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in value
    )


def _read_bounded_artifact(path: Path, expected_size: int, maximum_size: int) -> bytes:
    if expected_size <= 0 or expected_size > maximum_size or not path.is_file():
        raise ValueError(f"native artifact is missing or has an invalid size: {path}")
    actual_size = path.stat().st_size
    if actual_size != expected_size or actual_size > maximum_size:
        raise ValueError(f"native artifact size mismatch: {path}")
    with path.open("rb") as source:
        value = source.read(expected_size + 1)
    if len(value) != expected_size:
        raise ValueError(f"native artifact changed while reading: {path}")
    return value


def _cleanup_orphaned_entries(
    registry_path: Path, rows: list[dict[str, Any]], *, limit: int = 64
) -> None:
    entries = registry_path.parent / "entries"
    if not entries.is_dir():
        return
    referenced = {
        Path(str(row.get("reference_audio_path", ""))).parts[1]
        for row in rows
        if isinstance(row.get("reference_audio_path"), str)
        and len(Path(str(row["reference_audio_path"])).parts) >= 2
        and Path(str(row["reference_audio_path"])).parts[0] == "entries"
    }
    inspected = 0
    for entry in entries.iterdir():
        if inspected >= limit:
            break
        inspected += 1
        if not entry.is_dir() or entry.name in referenced:
            continue
        marker = entry / _ENTRY_MARKER
        if not marker.is_file():
            continue
        try:
            value = _read_json_file_bounded(marker, 4096)
            if not isinstance(value, dict):
                continue
            orphan_id = value.get("voice_id")
            if (
                value.get("schema_version") != 1
                or not isinstance(orphan_id, str)
                or _internal_id(orphan_id) != entry.name
            ):
                continue
            children = {child.name for child in entry.iterdir()}
            if not children.issubset(
                {_ENTRY_MARKER, "reference.wav", "reference.txt", "native"}
            ):
                continue
            shutil.rmtree(entry)
        except (OSError, ValueError, json.JSONDecodeError):
            continue


def _load_runtime_identity(runtime_dir: Path) -> dict[str, Any]:
    path = runtime_dir / "manifest.json"
    try:
        value = _read_json_file_bounded(path, _MAX_MANIFEST_BYTES)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"native runtime manifest is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"native runtime manifest identity is invalid: {path}")
    if (
        value.get("schema_version") != 1
        or value.get("engine") != "qwentts.cpp"
        or not isinstance(value.get("engine_commit"), str)
        or not value["engine_commit"]
        or isinstance(value.get("qt_abi_version"), bool)
        or not isinstance(value.get("qt_abi_version"), int)
        or value["qt_abi_version"] <= 0
        or str(value.get("architecture", "")).lower() != "x64"
        or not isinstance(value.get("backend"), str)
        or not value["backend"]
    ):
        raise ValueError(f"native runtime manifest identity is invalid: {path}")
    files = value.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError(f"native runtime manifest files are invalid: {path}")
    dll_declared = False
    for item in files:
        if not isinstance(item, dict):
            raise ValueError(f"native runtime manifest file is invalid: {path}")
        relative = item.get("path")
        expected = item.get("sha256")
        if (
            not isinstance(relative, str)
            or not isinstance(expected, str)
            or len(expected) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in expected)
        ):
            raise ValueError(f"native runtime manifest file is invalid: {path}")
        artifact = _resolve_runtime_artifact(runtime_dir, relative)
        if not artifact.is_file() or _sha256_file(artifact) != expected.lower():
            raise ValueError(f"native runtime file verification failed: {artifact}")
        if artifact.name.lower() == "qwen.dll":
            dll_declared = True
    if not dll_declared:
        raise ValueError(f"native runtime manifest does not declare qwen.dll: {path}")
    return value


def _resolve_runtime_artifact(runtime_dir: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError("native runtime manifest contains an unsafe path")
    root = runtime_dir.resolve()
    artifact = (root / relative).resolve()
    try:
        artifact.relative_to(root)
    except ValueError as exc:
        raise ValueError("native runtime manifest file escapes its directory") from exc
    return artifact


def _verify_prepared_artifacts(
    manifest_path: Path, manifest: dict[str, Any], x_vector_only: bool
) -> None:
    speaker = manifest.get("speaker")
    if not isinstance(speaker, dict):
        raise ValueError("native speaker artifact declaration is invalid")
    dimension = speaker.get("dimension")
    size_bytes = speaker.get("size_bytes")
    if (
        isinstance(dimension, bool)
        or not isinstance(dimension, int)
        or dimension <= 0
        or dimension > _MAX_SPEAKER_DIMENSION
        or isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes != dimension * 4
        or size_bytes > _MAX_SPEAKER_BYTES
    ):
        raise ValueError("native speaker dimensions are invalid")
    if speaker.get("scalar") != "float32-le":
        raise ValueError("native speaker scalar is unsupported")
    speaker_hash = speaker.get("sha256")
    if not _is_sha256(speaker_hash):
        raise ValueError("native speaker SHA-256 is invalid")
    speaker_name = speaker.get("path")
    if not isinstance(speaker_name, str):
        raise ValueError("native speaker path is invalid")
    speaker_path = _resolve_manifest_artifact(manifest_path, speaker_name)
    speaker_bytes = _read_bounded_artifact(speaker_path, size_bytes, _MAX_SPEAKER_BYTES)
    if _sha256_bytes(speaker_bytes) != speaker_hash.lower():
        raise ValueError("native speaker artifact is missing or corrupt")
    try:
        values = struct.unpack(f"<{dimension}f", speaker_bytes)
    except struct.error as exc:
        raise ValueError("native speaker artifact is truncated") from exc
    if not all(value == value and abs(value) != float("inf") for value in values):
        raise ValueError("native speaker artifact contains NaN or Inf")
    rvq = manifest.get("rvq")
    if x_vector_only:
        if rvq is not None:
            raise ValueError("x-vector-only native manifest contains RVQ data")
        return
    if not isinstance(rvq, dict):
        raise ValueError("ICL native manifest has no RVQ data")
    codebooks = rvq.get("codebooks")
    frames = rvq.get("frames")
    rvq_size_declared = rvq.get("size_bytes")
    if (
        isinstance(codebooks, bool)
        or not isinstance(codebooks, int)
        or codebooks <= 0
        or codebooks > _MAX_RVQ_CODEBOOKS
        or isinstance(frames, bool)
        or not isinstance(frames, int)
        or frames <= 0
        or frames > _MAX_RVQ_FRAMES
        or isinstance(rvq_size_declared, bool)
        or not isinstance(rvq_size_declared, int)
    ):
        raise ValueError("native RVQ dimensions are invalid")
    rvq_name = rvq.get("path")
    rvq_hash = rvq.get("sha256")
    if not isinstance(rvq_name, str) or not _is_sha256(rvq_hash):
        raise ValueError("native RVQ artifact declaration is invalid")
    expected_size = (
        (codebooks * frames * 11 + 7) // 8
    )
    if (
        rvq.get("bits_per_code") != 11
        or rvq.get("layout") != "codebook-major-frame-fastest"
        or rvq_size_declared != expected_size
        or rvq_size_declared > _MAX_RVQ_BYTES
    ):
        raise ValueError("native RVQ dimensions or layout are invalid")
    rvq_path = _resolve_manifest_artifact(manifest_path, rvq_name)
    rvq_bytes = _read_bounded_artifact(rvq_path, rvq_size_declared, _MAX_RVQ_BYTES)
    if _sha256_bytes(rvq_bytes) != rvq_hash.lower():
        raise ValueError("native RVQ artifact is missing or corrupt")


def _native_binding(profile: Any, native_profile: str) -> dict[str, Any]:
    runtime = _load_runtime_identity(profile.runtime_dir)
    binding: dict[str, Any] = {
        "native_profile": native_profile,
        "engine": runtime["engine"],
        "engine_commit": runtime["engine_commit"],
        "qt_abi_version": runtime["qt_abi_version"],
        "talker_sha256": _sha256_file(profile.talker_model),
        "codec_sha256": _sha256_file(profile.codec_model),
    }
    encoded = json.dumps(
        binding, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    binding["binding_key"] = hashlib.sha256(encoded).hexdigest()[:32]
    return binding


def _select_native_reference(
    row: dict[str, Any], binding_key: str, native_profile: str
) -> tuple[dict[str, Any] | None, bool]:
    references = row.get("native_references")
    if isinstance(references, dict):
        exact = references.get(binding_key)
        if isinstance(exact, dict):
            return exact, False
        for candidate in references.values():
            if (
                isinstance(candidate, dict)
                and candidate.get("native_profile") == native_profile
            ):
                return candidate, True
    legacy = row.get("native_reference")
    if isinstance(legacy, dict):
        return legacy, False
    return None, False


def _validate_native_reference_paths(registry_path: Path, row: dict[str, Any]) -> None:
    candidates: list[object] = []
    legacy = row.get("native_reference")
    if legacy is not None:
        candidates.append(legacy)
    references = row.get("native_references")
    if references is not None:
        if not isinstance(references, dict):
            raise VoiceLibraryError("native_references must be an object")
        candidates.extend(references.values())
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise VoiceLibraryError("native reference entry must be an object")
        path = candidate.get("manifest_path")
        if not isinstance(path, str):
            raise VoiceLibraryError("native reference requires manifest_path")
        _resolve_registry_relative_path(registry_path, path, "manifest_path")


def _resolve_native_worker(config_path: Path | None, profile_name: str) -> Path:
    config_file = _selected_config_path(config_path)
    config = load_user_config(config_file)
    profiles = config.get("native_profiles")
    entry = profiles.get(profile_name) if isinstance(profiles, dict) else None
    runtime = config.get("runtime")
    value: object = entry.get("worker") if isinstance(entry, dict) else None
    if not isinstance(value, str) and isinstance(runtime, dict):
        value = runtime.get("native_worker") or runtime.get("worker")
    if isinstance(value, str) and value.strip():
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = config_file.parent / path
        path = path.resolve()
        if path.is_file():
            return path
        raise VoiceLibraryError(f"native worker was not found: {path}")
    selected = shutil.which("qwen_tts_native_worker.exe") or shutil.which(
        "qwen_tts_native_worker"
    )
    if selected:
        return Path(selected).resolve()
    raise VoiceLibraryError(
        "native worker is not configured; set runtime.native_worker or "
        "native_profiles.<name>.worker"
    )
