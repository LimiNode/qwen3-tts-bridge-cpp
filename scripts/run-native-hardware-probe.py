"""Run one reproducible QTB native-worker hardware probe.

The probe intentionally measures first PCM from the first byte of a request
until the first audio frame arrives.  It does not normalize, trim, or play the
audio; the worker's stderr diagnostics and the raw protocol result are kept in
the evidence JSON for later acceptance analysis.
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

HEADER = struct.Struct("<4sHHHHIQ")


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
    parser.add_argument("--output", type=Path, required=True)
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

    def drain_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_lines.append(line.decode("utf-8", errors="replace").rstrip())

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()

    def send(request_id: int, payload: dict[str, Any]) -> None:
        assert process.stdin is not None
        process.stdin.write(frame(request_id, payload))
        process.stdin.flush()

    evidence: dict[str, Any] = {
        "worker": str(args.worker),
        "runtime_dir": str(args.runtime_dir),
        "talker_model": str(args.talker_model),
        "codec_model": str(args.codec_model),
        "voice_id": args.voice_id,
        "reference_audio_path": (
            str(args.reference_audio_path) if args.reference_audio_path else ""
        ),
        "text": args.text,
        "language": args.language,
        "stream_max_chunk_frames": args.stream_max_chunk_frames,
        "warmup_synthesis": args.warmup_synthesis,
        "ready": None,
        "first_pcm_ms": None,
        "audio_bytes": 0,
        "terminal": None,
        "qtb_metrics": [],
    }
    try:
        send(
            0,
            {
                "message_type": "hello",
                "client_name": "native-hardware-probe",
                "client_version": "1",
            },
        )
        frame_type, _, ready = read_frame(process.stdout)
        if frame_type != 1 or ready.get("message_type") != "ready":
            raise RuntimeError(f"expected ready, got {ready!r}")
        evidence["ready"] = ready

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
        send(1, request)
        started = time.perf_counter()
        while True:
            frame_type, request_id, payload = read_frame(process.stdout)
            if frame_type == 2 and request_id == 1:
                evidence["audio_bytes"] += len(payload)
                if evidence["first_pcm_ms"] is None:
                    evidence["first_pcm_ms"] = (time.perf_counter() - started) * 1000.0
            elif frame_type == 1 and request_id == 1:
                message_type = payload.get("message_type")
                if message_type in {"completed", "cancelled", "error"}:
                    evidence["terminal"] = payload
                    break
            elif frame_type == 3 and request_id == 1:
                evidence["terminal"] = payload
                break
        send(0, {"message_type": "shutdown", "mode": "cancel"})
    finally:
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    for line in stderr_lines:
        if line.startswith("qtb_metric "):
            try:
                evidence["qtb_metrics"].append(json.loads(line[len("qtb_metric ") :]))
            except json.JSONDecodeError:
                pass
    evidence["stderr_tail"] = stderr_lines[-200:]
    evidence["worker_exit_code"] = process.returncode
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if process.returncode != 0 or evidence["terminal"] is None:
        return 1
    return 0 if evidence["first_pcm_ms"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
