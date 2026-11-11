"""Native worker preparation and protocol helpers for the managed voice library."""

from __future__ import annotations

import json
import queue
import struct
import subprocess
import threading
import time
from typing import Any

from qwen_tts_bridge_worker.voice_library_errors import VoiceLibraryError

_MAGIC = b"QTB1"
_FRAME_HEADER = struct.Struct("<4sHHHHIQ")
_MAX_NATIVE_STDERR_BYTES = 1 << 20

def run_native_prepare(
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
