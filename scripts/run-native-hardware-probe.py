"""Run one fail-closed, reproducible QTB native-worker hardware probe.

The probe measures request-to-first-PCM and records every PCM arrival. It does
not normalize, trim, or play audio. A successful exit requires a completed
request with the expected execution outcome, non-empty PCM, and no playback
starvation between chunks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import queue
import struct
import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Any

HEADER = struct.Struct("<4sHHHHIQ")
MAX_FRAME_PAYLOAD = 64 * 1024 * 1024


def frame(request_id: int, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return HEADER.pack(b"QTB1", 1, HEADER.size, 1, 0, len(data), request_id) + data


def read_frame(stream: Any) -> tuple[int, int, Any]:
    header = stream.read(HEADER.size)
    if len(header) != HEADER.size:
        raise RuntimeError("native worker closed stdout before a complete frame")
    magic, version, header_size, frame_type, flags, payload_size, request_id = (
        HEADER.unpack(header)
    )
    if magic != b"QTB1" or version != 1 or header_size < HEADER.size or flags != 0:
        raise RuntimeError("native worker returned an invalid QTB frame header")
    if payload_size > MAX_FRAME_PAYLOAD:
        raise RuntimeError(
            f"native worker returned an oversized QTB payload: {payload_size}"
        )
    if header_size > HEADER.size:
        extension = stream.read(header_size - HEADER.size)
        if len(extension) != header_size - HEADER.size:
            raise RuntimeError("native worker closed during a QTB header extension")
    payload = stream.read(payload_size)
    if len(payload) != payload_size:
        raise RuntimeError("native worker closed during a QTB payload")
    if frame_type in (1, 3):
        return frame_type, request_id, json.loads(payload.decode("utf-8"))
    return frame_type, request_id, payload


class FrameReader:
    """Read blocking stdout frames on a daemon thread with caller timeouts."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._items: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, name="qtb-frame-reader", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            while True:
                self._items.put(("frame", read_frame(self._stream)))
        except BaseException as error:
            self._items.put(("error", error))

    def read(self, timeout: float) -> tuple[int, int, Any]:
        try:
            kind, value = self._items.get(timeout=timeout)
        except queue.Empty as error:
            raise TimeoutError(
                f"timed out waiting for a native worker frame ({timeout:.1f}s)"
            ) from error
        if kind == "error":
            raise value
        return value


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_pcm_wav(path: Path, pcm_s16le: bytes) -> None:
    """Write captured mono 24 kHz s16le probe PCM as a reviewable WAV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24000)
        stream.writeframes(pcm_s16le)


def first_existing(*paths: Path) -> Path | None:
    return next((path.resolve() for path in paths if path.is_file()), None)


def hardware_identity() -> dict[str, Any]:
    result: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }
    try:
        probe = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        probe = None
    if probe is not None:
        result["nvidia_smi_exit_code"] = probe.returncode
        result["nvidia_smi"] = probe.stdout.strip()
        if probe.stderr.strip():
            result["nvidia_smi_stderr"] = probe.stderr.strip()
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--talker-model", type=Path, required=True)
    parser.add_argument("--codec-model", type=Path, required=True)
    parser.add_argument("--voice-registry-path", type=Path)
    parser.add_argument("--voice-id", default="")
    parser.add_argument("--reference-audio-path", type=Path)
    parser.add_argument("--reference-text", default="")
    parser.add_argument("--x-vector-only", action="store_true")
    parser.add_argument("--text", required=True)
    parser.add_argument("--language", default="auto")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--stream-max-chunk-frames", type=int, default=1)
    parser.add_argument("--warmup-synthesis", action="store_true")
    parser.add_argument("--warmup-text", default="Warmup.")
    parser.add_argument("--warmup-language", default="auto")
    parser.add_argument("--warmup-voice-id", default="")
    parser.add_argument("--expected-execution-outcome", default="natural_eos")
    parser.add_argument("--startup-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--output-wav",
        type=Path,
        help="optional path for the captured mono 24 kHz s16le PCM WAV",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.worker = args.worker.resolve()
    args.runtime_dir = args.runtime_dir.resolve()
    args.talker_model = args.talker_model.resolve()
    args.codec_model = args.codec_model.resolve()
    if args.voice_registry_path:
        args.voice_registry_path = args.voice_registry_path.resolve()
    if args.reference_audio_path:
        args.reference_audio_path = args.reference_audio_path.resolve()
    args.output = args.output.resolve()
    if args.output_wav:
        args.output_wav = args.output_wav.resolve()
    if args.voice_id and args.reference_audio_path:
        raise SystemExit("--voice-id and --reference-audio-path are mutually exclusive")

    worker_args = [
        str(args.worker),
        "--runtime-dir",
        str(args.runtime_dir),
        "--talker-model",
        str(args.talker_model),
        "--codec-model",
        str(args.codec_model),
        "--stream-max-chunk-frames",
        str(args.stream_max_chunk_frames),
    ]
    if args.voice_registry_path:
        worker_args += ["--voice-registry-path", str(args.voice_registry_path)]
    if args.warmup_synthesis:
        worker_args += ["--warmup-synthesis", "--warmup-text", args.warmup_text]
        worker_args += ["--warmup-language", args.warmup_language]
        if args.warmup_voice_id:
            worker_args += ["--warmup-voice-id", args.warmup_voice_id]

    stderr_lines: list[str] = []
    process = subprocess.Popen(
        worker_args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    frame_reader = FrameReader(process.stdout)
    frame_reader.start()

    def drain_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_lines.append(line.decode("utf-8", errors="replace").rstrip())

    stderr_thread = threading.Thread(
        target=drain_stderr, name="qtb-stderr-reader", daemon=True
    )
    stderr_thread.start()

    def send(request_id: int, payload: dict[str, Any]) -> None:
        assert process.stdin is not None
        process.stdin.write(frame(request_id, payload))
        process.stdin.flush()

    runtime_manifest = first_existing(
        args.runtime_dir / "runtime-manifest.json",
        args.runtime_dir / "manifest.json",
    )
    dll = first_existing(
        args.runtime_dir / "qwen.dll", args.runtime_dir / "qwen-cuda.dll"
    )
    evidence: dict[str, Any] = {
        "worker": str(args.worker),
        "worker_args": worker_args,
        "runtime_dir": str(args.runtime_dir),
        "runtime_manifest": str(runtime_manifest) if runtime_manifest else None,
        "talker_model": str(args.talker_model),
        "codec_model": str(args.codec_model),
        "voice_registry_path": str(args.voice_registry_path)
        if args.voice_registry_path
        else "",
        "voice_id": args.voice_id,
        "reference_audio_path": str(args.reference_audio_path)
        if args.reference_audio_path
        else "",
        "reference_text": args.reference_text,
        "x_vector_only": args.x_vector_only,
        "text": args.text,
        "language": args.language,
        "seed": args.seed,
        "stream_max_chunk_frames": args.stream_max_chunk_frames,
        "warmup": {
            "synthesis": args.warmup_synthesis,
            "text": args.warmup_text,
            "language": args.warmup_language,
            "voice_id": args.warmup_voice_id,
        },
        "expected_execution_outcome": args.expected_execution_outcome,
        "ready": None,
        "first_pcm_ms": None,
        "audio_bytes": 0,
        "chunks": [],
        "output_wav": str(args.output_wav) if args.output_wav else "",
        "starvation_detected": False,
        "terminal": None,
        "qtb_metrics": [],
        "hardware": hardware_identity(),
        "hashes": {
            "worker": sha256_file(args.worker),
            "qwen_dll": sha256_file(dll) if dll else None,
            "talker_model": sha256_file(args.talker_model),
            "codec_model": sha256_file(args.codec_model),
            "runtime_manifest": sha256_file(runtime_manifest)
            if runtime_manifest
            else None,
            "voice_registry": sha256_file(args.voice_registry_path)
            if args.voice_registry_path
            else None,
            "reference_audio": sha256_file(args.reference_audio_path)
            if args.reference_audio_path
            else None,
        },
    }

    failure: BaseException | None = None
    captured_pcm = bytearray()
    try:
        send(
            0,
            {
                "message_type": "hello",
                "client_name": "native-hardware-probe",
                "client_version": "1",
            },
        )
        frame_type, _, ready = frame_reader.read(args.startup_timeout_seconds)
        if frame_type != 1 or ready.get("message_type") != "ready":
            raise RuntimeError(f"expected ready, got {ready!r}")
        evidence["ready"] = ready
        if bool(ready.get("warmed_up")) != args.warmup_synthesis:
            raise RuntimeError(
                "ready.warmed_up does not match the requested warmup state"
            )
        if args.voice_id and args.voice_id not in ready.get("voice_ids", []):
            raise RuntimeError(
                f"requested voice_id is absent from ready.voice_ids: {args.voice_id}"
            )

        request: dict[str, Any] = {
            "message_type": "synthesize",
            "text": args.text,
            "language": args.language,
            "output": {"sample_format": "s16le", "sample_rate": 24000, "channels": 1},
        }
        if args.voice_id:
            request["voice_id"] = args.voice_id
        if args.reference_audio_path:
            request["reference_audio_path"] = str(args.reference_audio_path)
            request["reference_text"] = args.reference_text
            request["x_vector_only"] = args.x_vector_only
        if args.seed is not None:
            request["seed"] = args.seed
        request_started = time.perf_counter()
        send(1, request)
        previous_arrival_ms: float | None = None
        previous_audio_duration_ms: float | None = None
        while True:
            frame_type, request_id, payload = frame_reader.read(
                args.request_timeout_seconds
            )
            if frame_type == 2 and request_id == 1:
                arrival_ms = (time.perf_counter() - request_started) * 1000.0
                audio_bytes = len(payload)
                audio_duration_ms = audio_bytes / (2.0 * 24000.0) * 1000.0
                gap_ms = (
                    None
                    if previous_arrival_ms is None
                    else arrival_ms - previous_arrival_ms
                )
                buffer_slack_ms = (
                    None
                    if gap_ms is None or previous_audio_duration_ms is None
                    else previous_audio_duration_ms - gap_ms
                )
                if buffer_slack_ms is not None and buffer_slack_ms < 0.0:
                    evidence["starvation_detected"] = True
                evidence["chunks"].append(
                    {
                        "index": len(evidence["chunks"]),
                        "arrival_ms": arrival_ms,
                        "bytes": audio_bytes,
                        "audio_duration_ms": audio_duration_ms,
                        "gap_ms": gap_ms,
                        "buffer_slack_ms": buffer_slack_ms,
                    }
                )
                evidence["audio_bytes"] += audio_bytes
                captured_pcm.extend(payload)
                if evidence["first_pcm_ms"] is None:
                    evidence["first_pcm_ms"] = arrival_ms
                previous_arrival_ms = arrival_ms
                previous_audio_duration_ms = audio_duration_ms
            elif frame_type == 1 and request_id == 1:
                message_type = payload.get("message_type")
                if message_type in {"completed", "cancelled"}:
                    evidence["terminal"] = payload
                    break
            elif frame_type == 3 and request_id == 1:
                evidence["terminal"] = payload
                break
        terminal = evidence["terminal"]
        if (
            not isinstance(terminal, dict)
            or terminal.get("message_type") != "completed"
        ):
            raise RuntimeError(f"request did not complete successfully: {terminal!r}")
        if terminal.get("execution_outcome") != args.expected_execution_outcome:
            raise RuntimeError(
                "unexpected execution outcome: "
                f"{terminal.get('execution_outcome')!r} != "
                f"{args.expected_execution_outcome!r}"
            )
        if evidence["first_pcm_ms"] is None or evidence["audio_bytes"] <= 0:
            raise RuntimeError("completed request did not emit PCM")
        if evidence["starvation_detected"]:
            raise RuntimeError("PCM arrival gaps exceeded the preceding audio buffer")
        send(0, {"message_type": "shutdown", "mode": "cancel"})
    except BaseException as error:
        failure = error
        evidence["probe_error"] = str(error)
    finally:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        stderr_thread.join(timeout=5)

    for line in stderr_lines:
        if line.startswith("qtb_metric "):
            try:
                evidence["qtb_metrics"].append(json.loads(line[len("qtb_metric ") :]))
            except json.JSONDecodeError:
                pass
    evidence["stderr_tail"] = stderr_lines[-200:]
    evidence["worker_exit_code"] = process.returncode
    if args.output_wav and captured_pcm:
        write_pcm_wav(args.output_wav, bytes(captured_pcm))
        evidence["output_wav_sha256"] = sha256_file(args.output_wav)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 1 if failure is not None or process.returncode != 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
