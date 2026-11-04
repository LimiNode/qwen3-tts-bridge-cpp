"""Capture native-worker stdout before any QTB1 parsing takes place."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time


HEADER = struct.Struct("<4sHHHHIQ")
MAX_CAPTURE_BYTES = 8 * 1024 * 1024


def frame(frame_type: int, request_id: int, payload: dict) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return HEADER.pack(b"QTB1", 1, 24, frame_type, 0, len(body), request_id) + body


def capture_stream(stream, output, metadata, label: str, lock: threading.Lock) -> None:
    offset = 0
    while True:
        chunk = stream.read(65536)
        if not chunk:
            return
        with lock:
            remaining = MAX_CAPTURE_BYTES - output.tell()
            if remaining > 0:
                output.write(chunk[:remaining])
                output.flush()
            metadata.append({
                "stream": label,
                "offset": offset,
                "size": len(chunk),
                "timestamp_ns": time.time_ns(),
                "stored": min(len(chunk), max(remaining, 0)),
            })
            offset += len(chunk)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--talker-model", type=Path, required=True)
    parser.add_argument("--codec-model", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--stream-max-chunk-frames", type=int, default=4)
    parser.add_argument("--max-admitted-requests", type=int, default=16)
    parser.add_argument("--two-requests", action="store_true")
    parser.add_argument("--sync-stdio", action="store_true")
    parser.add_argument("--settle-seconds", type=float, default=0.35)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    run_dir = args.output_root / f"run-{time.time_ns()}-{os.getpid()}"
    run_dir.mkdir()
    stdout_path = run_dir / "stdout.bin"
    stderr_path = run_dir / "stderr.bin"
    metadata_path = run_dir / "metadata.json"

    command = [
        str(args.worker),
        "--runtime-dir", str(args.runtime_dir),
        "--manifest-path", str(args.manifest_path),
        "--talker-model", str(args.talker_model),
        "--codec-model", str(args.codec_model),
        "--stream-max-chunk-frames", str(args.stream_max_chunk_frames),
        "--max-admitted-requests", str(args.max_admitted_requests),
    ]
    metadata = {
        "command": command,
        "pid": None,
        "sends": [],
        "chunks": [],
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "capture_limit_bytes": MAX_CAPTURE_BYTES,
    }
    environment = os.environ.copy()
    publication_path = run_dir / "publication.bin"
    environment["QTB_NATIVE_PUBLICATION_CAPTURE"] = str(publication_path)
    if args.sync_stdio:
        environment["QTB_NATIVE_SYNC_STDIO"] = "1"
    lock = threading.Lock()
    started = time.monotonic()
    stdout_file = stdout_path.open("wb")
    try:
        stderr_file = stderr_path.open("wb")
    except BaseException:
        stdout_file.close()
        raise
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=environment,
        )
    except BaseException:
        stdout_file.close()
        stderr_file.close()
        raise
    metadata["pid"] = process.pid

    stdout_thread = threading.Thread(
        target=capture_stream,
        args=(process.stdout, stdout_file, metadata["chunks"], "stdout", lock),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=capture_stream,
        args=(process.stderr, stderr_file, metadata["chunks"], "stderr", lock),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    def send(request_id: int, payload: dict) -> None:
        encoded = frame(1, request_id, payload)
        process.stdin.write(encoded)
        process.stdin.flush()
        metadata["sends"].append({
            "request_id": request_id,
            "message_type": payload["message_type"],
            "size": len(encoded),
            "timestamp_ns": time.time_ns(),
        })

    try:
        send(0, {
            "message_type": "hello",
            "client_name": "native-frame-capture",
            "client_version": "diagnostic",
        })
        time.sleep(args.settle_seconds)
        synthesize = {
            "message_type": "synthesize",
            "text": "native frame capture",
            "language": "auto",
            "instruction": "",
            "output": {"sample_format": "s16le", "sample_rate": 24000, "channels": 1},
        }
        send(100, synthesize)
        if args.two_requests:
            send(101, synthesize)
        time.sleep(args.settle_seconds)
        send(100, {"message_type": "cancel"})
        time.sleep(args.settle_seconds)
        send(0, {"message_type": "shutdown", "mode": "cancel"})
    except (BrokenPipeError, OSError) as error:
        metadata["send_error"] = repr(error)
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired:
            metadata["timeout"] = True
            process.kill()
            process.wait()
        stdout_thread.join(timeout=2.0)
        stderr_thread.join(timeout=2.0)
        stdout_file.close()
        stderr_file.close()

    metadata["returncode"] = process.returncode
    metadata["duration_ms"] = round((time.monotonic() - started) * 1000.0, 3)
    metadata["stdout_bytes"] = stdout_path.stat().st_size
    metadata["stderr_bytes"] = stderr_path.stat().st_size
    metadata["publication_path"] = str(publication_path)
    metadata["publication_bytes"] = publication_path.stat().st_size if publication_path.exists() else 0
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(run_dir)
    return 0 if process.returncode == 0 and not metadata.get("timeout") else 1


if __name__ == "__main__":
    sys.exit(main())
