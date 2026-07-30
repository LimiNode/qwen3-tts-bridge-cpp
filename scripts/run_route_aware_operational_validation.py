"""Exercise completed, cancelled, and rejected outcomes against one QTB worker."""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from qwen_tts_bridge_worker.protocol import Frame, FrameParser, FrameType, ParseStatus
from qwen_tts_bridge_worker.protocol.control import encode_json_payload
from qwen_tts_bridge_worker.protocol.framing import encode_frame


@dataclass(frozen=True, slots=True)
class Operation:
    """One deterministic terminal-outcome operation."""

    outcome: str
    text: str | None
    speaker: str = "ryan"
    seed: int | None = None


class WorkerHarness:
    """Minimal local QTB protocol harness that preserves raw stderr diagnostics."""

    def __init__(
        self,
        executable: Path,
        args: list[str],
        timeout_seconds: float,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._process = subprocess.Popen(
            [str(executable), *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._frames: queue.Queue[Frame] = queue.Queue()
        self._stderr: list[bytes] = []
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._stderr_reader.start()

    def send_control(self, request_id: int, message: dict[str, object]) -> None:
        if self._process.stdin is None:
            raise RuntimeError("worker stdin is unavailable")
        self._process.stdin.write(
            encode_frame(
                FrameType.CONTROL_JSON,
                request_id,
                encode_json_payload(message),
            )
        )
        self._process.stdin.flush()

    def read_frame(self, predicate: Callable[[Frame], bool]) -> Frame:
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            if self._process.poll() is not None:
                raise RuntimeError("worker exited before the expected protocol frame")
            try:
                frame = self._frames.get(timeout=0.1)
            except queue.Empty as exc:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "timed out waiting for worker protocol frame"
                    ) from exc
                continue
            if predicate(frame):
                return frame

    def close(self) -> int:
        try:
            if self._process.poll() is None:
                # Protocol v1 supports cooperative shutdown only through cancel.
                self.send_control(0, {"message_type": "shutdown", "mode": "cancel"})
                self.read_frame(lambda frame: _is_control(frame, 0, "shutdown_ack"))
            return self._process.wait(timeout=self._timeout_seconds)
        finally:
            self._reader.join(timeout=1.0)
            self._stderr_reader.join(timeout=1.0)

    def stderr_bytes(self) -> bytes:
        return b"".join(self._stderr)

    def _read_stdout(self) -> None:
        if self._process.stdout is None:
            return
        parser = FrameParser()
        read_chunk = getattr(self._process.stdout, "read1", self._process.stdout.read)
        while chunk := cast(bytes, read_chunk(64 * 1024)):
            parser.append(chunk)
            while True:
                result = parser.parse_next()
                if result.status == ParseStatus.NEED_MORE_DATA:
                    break
                if result.status == ParseStatus.FATAL_ERROR:
                    return
                if result.frame is not None:
                    self._frames.put(result.frame)

    def _read_stderr(self) -> None:
        if self._process.stderr is None:
            return
        while chunk := self._process.stderr.read(4096):
            self._stderr.append(chunk)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worker_executable", type=Path)
    parser.add_argument("--worker-arg", action="append", default=[])
    parser.add_argument("--request-manifest", type=Path, required=True)
    parser.add_argument("--stderr-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--completed", type=int, default=60)
    parser.add_argument("--cancelled-before-audio", type=int, default=15)
    parser.add_argument("--cancelled-after-audio", type=int, default=15)
    parser.add_argument("--failed", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args()
    _validate_args(parser, args)
    request_specs = _load_request_specs(args.request_manifest)
    operations = _operations(
        request_specs,
        completed=args.completed,
        cancelled_before_audio=args.cancelled_before_audio,
        cancelled_after_audio=args.cancelled_after_audio,
        failed=args.failed,
    )
    harness = WorkerHarness(
        args.worker_executable.resolve(),
        list(args.worker_arg),
        args.timeout_seconds,
    )
    results: list[str] = []
    try:
        harness.send_control(
            0,
            {
                "message_type": "hello",
                "client_name": "route-aware-operational-validation",
                "client_version": "0.2.0",
            },
        )
        harness.read_frame(lambda frame: _is_control(frame, 0, "ready"))
        for request_id, operation in enumerate(operations, 1):
            results.append(_run_operation(harness, request_id, operation))
        exit_code = harness.close()
    finally:
        args.stderr_output.parent.mkdir(parents=True, exist_ok=True)
        args.stderr_output.write_bytes(harness.stderr_bytes())
    if exit_code != 0:
        raise RuntimeError(f"worker exited with code {exit_code}")
    summary = {
        "operation_schema_version": 1,
        "requested_outcomes": {
            "completed": args.completed,
            "cancelled_before_audio": args.cancelled_before_audio,
            "cancelled_after_audio": args.cancelled_after_audio,
            "failed": args.failed,
        },
        "observed_outcomes": {
            outcome: results.count(outcome) for outcome in sorted(set(results))
        },
        "operation_count": len(results),
        "passed": results == [operation.outcome for operation in operations],
    }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(summary, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["passed"] else 1


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not args.worker_executable.is_file():
        parser.error("worker_executable was not found")
    if any(
        value < 0
        for value in (
            args.completed,
            args.cancelled_before_audio,
            args.cancelled_after_audio,
            args.failed,
        )
    ):
        parser.error("outcome counts must be non-negative")
    if sum(
        (
            args.completed,
            args.cancelled_before_audio,
            args.cancelled_after_audio,
            args.failed,
        )
    ) == 0:
        parser.error("at least one operation is required")
    if args.timeout_seconds <= 0.0:
        parser.error("--timeout-seconds must be positive")


def _load_request_specs(path: Path) -> list[Operation]:
    request_specs = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        text = value.get("text") if isinstance(value, dict) else None
        if not isinstance(text, str) or not text:
            raise RuntimeError(f"request manifest line {line_number} has invalid text")
        speaker = value.get("speaker", "ryan")
        seed = value.get("seed")
        if not isinstance(speaker, str) or not speaker:
            raise RuntimeError(
                f"request manifest line {line_number} has invalid speaker"
            )
        if not isinstance(seed, int) and seed is not None:
            raise RuntimeError(f"request manifest line {line_number} has invalid seed")
        request_specs.append(
            Operation(outcome="", text=text, speaker=speaker, seed=seed)
        )
    if not request_specs:
        raise RuntimeError("request manifest contains no texts")
    return request_specs


def _operations(
    request_specs: list[Operation],
    *,
    completed: int,
    cancelled_before_audio: int,
    cancelled_after_audio: int,
    failed: int,
) -> list[Operation]:
    normal_specs = iter(request_specs)

    def normal(outcome: str, count: int) -> list[Operation]:
        return [
            _with_outcome(
                next(normal_specs, request_specs[index % len(request_specs)]),
                outcome,
            )
            for index in range(count)
        ]

    return (
        normal("completed", completed)
        + normal("cancelled_before_audio", cancelled_before_audio)
        + normal("cancelled_after_audio", cancelled_after_audio)
        + [Operation(outcome="failed", text=None) for _ in range(failed)]
    )


def _with_outcome(specification: Operation, outcome: str) -> Operation:
    return Operation(
        outcome=outcome,
        text=specification.text,
        speaker=specification.speaker,
        seed=specification.seed,
    )


def _run_operation(
    harness: WorkerHarness,
    request_id: int,
    operation: Operation,
) -> str:
    if operation.outcome == "failed":
        harness.send_control(
            request_id,
            {"message_type": "synthesize", "output": "bad"},
        )
        harness.read_frame(
            lambda frame: frame.header.request_id == request_id
            and frame.header.frame_type == FrameType.ERROR_JSON
        )
        return "failed"
    assert operation.text is not None
    message: dict[str, object] = {
        "message_type": "synthesize",
        "text": operation.text,
        "language": "auto",
        "speaker": operation.speaker,
        "output": {"sample_rate": 24000, "channels": 1, "sample_format": "s16le"},
    }
    if operation.seed is not None:
        message["seed"] = operation.seed
    harness.send_control(request_id, message)
    harness.read_frame(lambda frame: _is_control(frame, request_id, "queued"))
    harness.read_frame(lambda frame: _is_control(frame, request_id, "started"))
    if operation.outcome == "cancelled_before_audio":
        harness.send_control(request_id, {"message_type": "cancel"})
        harness.read_frame(lambda frame: _is_control(frame, request_id, "cancelled"))
        return operation.outcome
    first_audio = harness.read_frame(
        lambda frame: frame.header.request_id == request_id
        and frame.header.frame_type == FrameType.AUDIO_PCM
    )
    if not first_audio.payload:
        raise RuntimeError("worker produced an empty audio frame")
    if operation.outcome == "cancelled_after_audio":
        harness.send_control(request_id, {"message_type": "cancel"})
        harness.read_frame(lambda frame: _is_control(frame, request_id, "cancelled"))
        return operation.outcome
    harness.read_frame(lambda frame: _is_control(frame, request_id, "completed"))
    return operation.outcome


def _is_control(frame: Frame, request_id: int, message_type: str) -> bool:
    if (
        frame.header.request_id != request_id
        or frame.header.frame_type != FrameType.CONTROL_JSON
    ):
        return False
    try:
        payload = json.loads(frame.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("message_type") == message_type


if __name__ == "__main__":
    raise SystemExit(main())
