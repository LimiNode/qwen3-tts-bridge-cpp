"""Smoke-test a packaged QwenTTSBridge worker executable."""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, cast

from qwen_tts_bridge_worker.protocol import (
    Frame,
    FrameParser,
    FrameType,
    ParseStatus,
    encode_frame,
)
from qwen_tts_bridge_worker.protocol.control import encode_json_payload


class PackagedWorkerHarness:
    """Small protocol harness for a packaged worker executable."""

    stdout_read_size = 64 * 1024

    def __init__(
        self,
        worker_executable: Path,
        args: list[str],
        timeout_seconds: float,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._process = subprocess.Popen(
            [str(worker_executable), *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._frames: queue.Queue[Frame] = queue.Queue()
        self._reader_errors: queue.Queue[str] = queue.Queue()
        self._stderr_chunks: list[bytes] = []
        self._stderr_lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_reader = threading.Thread(
            target=self._read_stderr,
            daemon=True,
        )
        self._reader.start()
        self._stderr_reader.start()

    def send_control(self, request_id: int, message: dict[str, object]) -> None:
        """Send one control JSON frame."""

        if self._process.stdin is None:
            raise RuntimeError("worker stdin is not available")
        self._process.stdin.write(
            encode_frame(
                FrameType.CONTROL_JSON,
                request_id,
                encode_json_payload(message),
            )
        )
        self._process.stdin.flush()

    def read_frame(
        self,
        predicate: Callable[[Frame], bool] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> Frame:
        """Read the next matching protocol frame."""

        timeout = (
            self._timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        deadline = time.monotonic() + timeout
        while True:
            self._raise_reader_error_if_any()
            if self._process.poll() is not None:
                self._join_reader_threads()
                stderr = self.stderr_text()
                raise RuntimeError(
                    "packaged worker exited before expected frame"
                    + (f"; stderr:\n{stderr}" if stderr else "")
                )
            try:
                frame = self._frames.get(
                    timeout=min(0.1, max(0.0, deadline - time.monotonic()))
                )
            except queue.Empty as exc:
                self._raise_reader_error_if_any()
                if self._process.poll() is not None:
                    self._join_reader_threads()
                    stderr = self.stderr_text()
                    raise RuntimeError(
                        "packaged worker exited before expected frame"
                        + (f"; stderr:\n{stderr}" if stderr else "")
                    ) from exc
                if time.monotonic() < deadline:
                    continue
                raise RuntimeError(
                    "timed out waiting for packaged worker frame"
                ) from exc

            if predicate is None or predicate(frame):
                return frame
            if frame.header.frame_type == FrameType.ERROR_JSON:
                payload = _json_payload(frame)
                raise RuntimeError(
                    "packaged worker returned error frame while waiting for "
                    f"expected frame: {payload}"
                )

    def wait(self) -> int:
        """Wait for the process and close pipes."""

        try:
            exit_code = self._process.wait(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            self._process.terminate()
            exit_code = self._process.wait(timeout=self._timeout_seconds)
            raise RuntimeError(
                "packaged worker did not exit before timeout"
            ) from exc
        finally:
            self._join_reader_threads()
            self._close_pipes()

        return exit_code

    @property
    def pid(self) -> int:
        """Return the worker process identifier."""

        return int(self._process.pid)

    def close(self) -> None:
        """Best-effort worker cleanup."""

        if self._process.poll() is None:
            try:
                self.send_control(0, {"message_type": "shutdown", "mode": "cancel"})
            except (BrokenPipeError, OSError, RuntimeError):
                pass
            try:
                self._process.wait(timeout=self._timeout_seconds)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                self._process.wait(timeout=self._timeout_seconds)
        self._join_reader_threads()
        self._close_pipes()

    def stderr_text(self) -> str:
        """Return captured stderr as UTF-8 text."""

        with self._stderr_lock:
            return b"".join(self._stderr_chunks).decode(
                "utf-8",
                errors="replace",
            )

    def _read_stdout(self) -> None:
        if self._process.stdout is None:
            self._reader_errors.put("worker stdout is not available")
            return

        read_chunk = getattr(self._process.stdout, "read1", None)
        if not callable(read_chunk):
            read_chunk = self._process.stdout.read

        parser = FrameParser()
        while True:
            chunk = cast(bytes, read_chunk(self.stdout_read_size))
            if not chunk:
                return
            parser.append(chunk)
            while True:
                result = parser.parse_next()
                if result.status == ParseStatus.NEED_MORE_DATA:
                    break
                if result.status == ParseStatus.FATAL_ERROR:
                    self._reader_errors.put(result.message)
                    return
                if result.frame is not None:
                    self._frames.put(result.frame)

    def _read_stderr(self) -> None:
        if self._process.stderr is None:
            return

        while True:
            try:
                chunk = self._process.stderr.read(4096)
            except ValueError:
                return
            if not chunk:
                return
            with self._stderr_lock:
                self._stderr_chunks.append(chunk)

    def _join_reader_threads(self) -> None:
        self._reader.join(timeout=1.0)
        self._stderr_reader.join(timeout=1.0)

    def _close_pipes(self) -> None:
        for pipe in (
            self._process.stdin,
            self._process.stdout,
            self._process.stderr,
        ):
            if pipe is None:
                continue
            try:
                pipe.close()
            except OSError:
                pass

    def _raise_reader_error_if_any(self) -> None:
        try:
            message = self._reader_errors.get_nowait()
        except queue.Empty:
            return
        raise RuntimeError(f"packaged worker stdout parser failed: {message}")


def main() -> int:
    """Run the packaged worker smoke test."""

    parser = argparse.ArgumentParser()
    parser.add_argument("worker_executable", type=Path)
    parser.add_argument(
        "--worker-prefix-arg",
        action="append",
        default=[],
        help="Argument inserted before the worker engine command.",
    )
    parser.add_argument("--engine", choices=("mock", "qwen"), default="mock")
    parser.add_argument("--model-path")
    parser.add_argument(
        "--runtime-backend",
        choices=("upstream", "faster"),
        default="upstream",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--attn-implementation", default="")
    parser.add_argument("--max-seq-len", type=int, default=2048)
    parser.add_argument("--emit-every-frames", type=int, default=8)
    parser.add_argument("--decode-window-frames", type=int, default=80)
    parser.add_argument("--overlap-samples", type=int, default=0)
    parser.add_argument("--enable-streaming-optimizations", action="store_true")
    parser.add_argument("--no-compile", action="store_true")
    parser.add_argument("--no-cuda-graphs", action="store_true")
    parser.add_argument("--compile-mode", default="reduce-overhead")
    parser.add_argument("--use-fast-codebook", action="store_true")
    parser.add_argument("--no-compile-codebook-predictor", action="store_true")
    parser.add_argument("--no-compile-talker", action="store_true")
    parser.add_argument("--matmul-precision", default="")
    parser.add_argument("--profile-prefill", action="store_true")
    parser.add_argument("--profile-nvtx", action="store_true")
    parser.add_argument(
        "--prefill-backend",
        choices=(
            "eager",
            "compile_backend_eager",
            "compile_backend_aot_eager",
            "compile_default",
            "compile_inductor_default",
            "compile_reduce_overhead",
        ),
        default="eager",
    )
    parser.add_argument(
        "--prefill-compile-compat-mode",
        choices=("none", "strict_bf16_sdpa_v1"),
        default="none",
    )
    parser.add_argument(
        "--prefill-compile-lengths",
        type=_parse_prefill_compile_lengths,
        default=(),
    )
    parser.add_argument(
        "--no-prefill-compile-on-miss",
        action="store_false",
        dest="prefill_compile_on_miss",
        default=True,
    )
    parser.add_argument(
        "--prefill-unknown-shape-policy",
        choices=("eager", "error"),
        default="eager",
    )
    parser.add_argument("--no-sample", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--seed-mode",
        choices=("request_id", "fixed"),
        default="request_id",
    )
    parser.add_argument("--warmup-seed", type=int, default=None)
    parser.add_argument("--warmup-synthesis", action="store_true")
    parser.add_argument(
        "--warmup-synthesis-passes",
        type=int,
        default=1,
    )
    parser.add_argument("--warmup-max-output-chunks", type=int, default=None)
    parser.add_argument("--warmup-unbounded-passes", type=int, default=0)
    parser.add_argument(
        "--expect-warmed-up",
        choices=("auto", "true", "false"),
        default="auto",
    )
    parser.add_argument("--warmup-text", default="Warmup.")
    parser.add_argument("--warmup-language", default="auto")
    parser.add_argument("--warmup-speaker", default="")
    parser.add_argument("--warmup-instruction", default="")
    parser.add_argument(
        "--engine-startup-mode",
        choices=("auto", "main", "engine_warmup", "engine_load_warmup"),
        default="auto",
    )
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--mock-chunks", type=int, default=1)
    parser.add_argument("--text", default="Packaged worker smoke test.")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--speaker", default="")
    parser.add_argument("--instruction", default="")
    parser.add_argument(
        "--require-natural-eos",
        action="store_true",
        help="Require FasterQwen terminal telemetry to prove natural EOS.",
    )
    args = parser.parse_args()

    worker_executable = args.worker_executable.resolve()
    if not worker_executable.is_file():
        parser.error(f"worker executable was not found: {worker_executable}")
    if args.engine == "qwen" and not args.model_path:
        parser.error("--model-path is required for --engine qwen")
    if args.require_natural_eos and (
        args.engine != "qwen" or args.runtime_backend != "faster"
    ):
        parser.error(
            "--require-natural-eos requires --engine qwen --runtime-backend faster"
        )

    harness = PackagedWorkerHarness(
        worker_executable=worker_executable,
        args=_worker_process_args(args),
        timeout_seconds=args.timeout_seconds,
    )
    try:
        _exercise_worker(
            harness,
            text=args.text,
            language=args.language,
            speaker=args.speaker,
            instruction=args.instruction,
            expect_warmed_up=_expected_warmed_up(args),
            require_natural_eos=args.require_natural_eos,
        )
    finally:
        harness.close()

    print(f"packaged worker smoke test passed: {worker_executable}")
    return 0


def _worker_args(args: argparse.Namespace) -> list[str]:
    engine = str(args.engine)
    if engine == "mock":
        return ["mock", "--chunks", str(args.mock_chunks)]

    model_path = args.model_path
    if not isinstance(model_path, str) or not model_path:
        raise RuntimeError("--model-path is required for --engine qwen")

    worker_args = [
        "qwen",
        "--model-path",
        model_path,
        "--runtime-backend",
        str(args.runtime_backend),
        "--device",
        str(args.device),
        "--dtype",
        str(args.dtype),
        "--max-seq-len",
        str(args.max_seq_len),
        "--emit-every-frames",
        str(args.emit_every_frames),
        "--decode-window-frames",
        str(args.decode_window_frames),
        "--overlap-samples",
        str(args.overlap_samples),
    ]
    attn_implementation = str(args.attn_implementation)
    if attn_implementation:
        worker_args.extend(["--attn-implementation", attn_implementation])
    if args.enable_streaming_optimizations:
        worker_args.append("--enable-streaming-optimizations")
    if args.no_compile:
        worker_args.append("--no-compile")
    if args.no_cuda_graphs:
        worker_args.append("--no-cuda-graphs")
    compile_mode = str(args.compile_mode)
    if compile_mode:
        worker_args.extend(["--compile-mode", compile_mode])
    if args.use_fast_codebook:
        worker_args.append("--use-fast-codebook")
    if args.no_compile_codebook_predictor:
        worker_args.append("--no-compile-codebook-predictor")
    if args.no_compile_talker:
        worker_args.append("--no-compile-talker")
    if args.matmul_precision:
        worker_args.extend(["--matmul-precision", str(args.matmul_precision)])
    if getattr(args, "profile_prefill", False):
        worker_args.append("--profile-prefill")
    if getattr(args, "profile_nvtx", False):
        worker_args.append("--profile-nvtx")
    if getattr(args, "collect_generation_trace", False) or getattr(
        args, "require_natural_eos", False
    ):
        worker_args.append("--collect-generation-trace")
    prefill_backend = str(getattr(args, "prefill_backend", "eager"))
    if prefill_backend:
        worker_args.extend(["--prefill-backend", prefill_backend])
    prefill_compile_compat_mode = str(
        getattr(args, "prefill_compile_compat_mode", "none")
    )
    if prefill_compile_compat_mode:
        worker_args.extend(
            ["--prefill-compile-compat-mode", prefill_compile_compat_mode]
        )
    prefill_compile_lengths = getattr(args, "prefill_compile_lengths", ())
    if prefill_compile_lengths:
        worker_args.extend(
            [
                "--prefill-compile-lengths",
                ",".join(str(length) for length in prefill_compile_lengths),
            ]
        )
    if not getattr(args, "prefill_compile_on_miss", True):
        worker_args.append("--no-prefill-compile-on-miss")
    worker_args.extend(
        [
            "--prefill-unknown-shape-policy",
            str(getattr(args, "prefill_unknown_shape_policy", "eager")),
        ]
    )
    worker_args.extend(
        [
            "--prefill-compile-policy",
            str(getattr(args, "prefill_compile_policy", "diagnostic_dynamic")),
        ]
    )
    prefill_allowlist_warmup_manifest = str(
        getattr(args, "prefill_allowlist_warmup_manifest", "")
    )
    if prefill_allowlist_warmup_manifest:
        worker_args.extend(
            [
                "--prefill-allowlist-warmup-manifest",
                prefill_allowlist_warmup_manifest,
            ]
        )
    worker_args.extend(
        [
            "--prefill-allowlist-warmup-repeats",
            str(getattr(args, "prefill_allowlist_warmup_repeats", 3)),
            "--prefill-allowlist-max-entries",
            str(getattr(args, "prefill_allowlist_max_entries", 6)),
            "--prefill-allowlist-max-abs-threshold",
            str(getattr(args, "prefill_allowlist_max_abs_threshold", 0.0)),
        ]
    )
    if getattr(args, "prefill_require_precompiled", False):
        worker_args.append("--prefill-require-precompiled")
    if getattr(args, "prefill_first_chunk_warmup", False):
        worker_args.append("--prefill-first-chunk-warmup")
        warmup_length = getattr(args, "prefill_first_chunk_warmup_length", None)
        if warmup_length is None:
            raise ValueError(
                "prefill_first_chunk_warmup requires "
                "prefill_first_chunk_warmup_length"
            )
        worker_args.extend(
            ["--prefill-first-chunk-warmup-length", str(warmup_length)]
        )
    if getattr(args, "no_sample", False):
        worker_args.append("--no-sample")
    seed = getattr(args, "seed", None)
    if seed is not None:
        worker_args.extend(["--seed", str(seed)])
    worker_args.extend(["--seed-mode", str(getattr(args, "seed_mode", "request_id"))])
    warmup_seed = getattr(args, "warmup_seed", None)
    if warmup_seed is not None:
        worker_args.extend(["--warmup-seed", str(warmup_seed)])
    if args.warmup_synthesis:
        worker_args.append("--warmup-synthesis")
    worker_args.extend(["--warmup-synthesis-passes", str(args.warmup_synthesis_passes)])
    worker_args.extend(["--warmup-unbounded-passes", str(args.warmup_unbounded_passes)])
    warmup_max_output_chunks = getattr(args, "warmup_max_output_chunks", None)
    if warmup_max_output_chunks is not None:
        worker_args.extend(
            ["--warmup-max-output-chunks", str(warmup_max_output_chunks)]
        )
    worker_args.extend(["--warmup-text", str(args.warmup_text)])
    worker_args.extend(["--warmup-language", str(args.warmup_language)])
    if args.warmup_speaker:
        worker_args.extend(["--warmup-speaker", str(args.warmup_speaker)])
    if args.warmup_instruction:
        worker_args.extend(["--warmup-instruction", str(args.warmup_instruction)])
    worker_args.extend(
        ["--engine-startup-mode", str(getattr(args, "engine_startup_mode", "auto"))]
    )
    return worker_args


def _worker_process_args(args: argparse.Namespace) -> list[str]:
    return [*getattr(args, "worker_prefix_arg", []), *_worker_args(args)]


def _parse_prefill_compile_lengths(value: str) -> tuple[int, ...]:
    text = value.strip()
    if not text:
        return ()
    lengths: list[int] = []
    for part in text.split(","):
        item = part.strip()
        if not item:
            raise argparse.ArgumentTypeError(
                "--prefill-compile-lengths must not contain empty items"
            )
        try:
            length = int(item)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                "--prefill-compile-lengths must contain integers"
            ) from exc
        if length <= 0:
            raise argparse.ArgumentTypeError(
                "--prefill-compile-lengths must contain positive integers"
            )
        lengths.append(length)
    if len(set(lengths)) != len(lengths):
        raise argparse.ArgumentTypeError(
            "--prefill-compile-lengths must not contain duplicates"
        )
    return tuple(lengths)


def _exercise_worker(
    harness: PackagedWorkerHarness,
    text: str,
    language: str,
    speaker: str,
    instruction: str,
    expect_warmed_up: bool,
    require_natural_eos: bool,
) -> None:
    harness.send_control(
        0,
        {
            "message_type": "hello",
            "client_name": "packaged-worker-smoke",
            "client_version": "0.2.0",
        },
    )
    ready = _control_payload(
        harness.read_frame(lambda frame: _is_control_message(frame, "ready", 0))
    )
    _expect(
        ready.get("warmed_up") is expect_warmed_up,
        "worker reported warmed_up="
        f"{ready.get('warmed_up')!r}, expected {expect_warmed_up!r}",
    )

    harness.send_control(
        1,
        _synthesize_payload(
            text=text,
            language=language,
            speaker=speaker,
            instruction=instruction,
        ),
    )

    harness.read_frame(lambda frame: _is_control_message(frame, "queued", 1))
    harness.read_frame(lambda frame: _is_control_message(frame, "started", 1))
    audio = harness.read_frame(
        lambda frame: frame.header.frame_type == FrameType.AUDIO_PCM
        and frame.header.request_id == 1
    )
    _expect(len(audio.payload) > 0, "packaged worker produced an empty PCM frame")
    completed = _control_payload(
        harness.read_frame(lambda frame: _is_control_message(frame, "completed", 1))
    )
    if require_natural_eos:
        _require_natural_eos(completed)

    harness.send_control(0, {"message_type": "shutdown", "mode": "cancel"})
    harness.read_frame(lambda frame: _is_control_message(frame, "shutdown_ack", 0))
    exit_code = harness.wait()
    _expect(exit_code == 0, f"packaged worker exited with code {exit_code}")


def _require_natural_eos(completed: dict[str, object]) -> None:
    _expect(
        completed.get("execution_outcome") == "completed",
        "completed event does not report execution_outcome=completed",
    )
    trace = completed.get("generation_trace")
    _expect(isinstance(trace, dict), "completed event has no generation_trace")
    trace = cast(dict[str, object], trace)
    _expect(
        trace.get("termination_reason") == "eos",
        "generation trace termination_reason is not eos",
    )
    _expect(trace.get("hit_eos") is True, "generation trace did not hit EOS")
    _expect(
        trace.get("hit_max_seq_len") is False,
        "generation trace reached max_seq_len",
    )
    _expect(
        trace.get("hit_max_new_tokens") is False,
        "generation trace reached max_new_tokens",
    )
    counters = {
        name: trace.get(name)
        for name in (
            "codec_frame_count",
            "generated_steps",
            "emitted_steps",
            "terminal_step_index",
        )
    }
    _expect(
        all(isinstance(value, int) and value > 0 for value in counters.values()),
        "generation trace counters are incomplete",
    )
    _expect(
        len(set(cast(int, value) for value in counters.values())) == 1,
        "generation trace counters are inconsistent",
    )


def _synthesize_payload(
    text: str,
    language: str,
    speaker: str,
    instruction: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "message_type": "synthesize",
        "text": text,
        "language": language,
        "output": {
            "sample_format": "s16le",
            "sample_rate": 24000,
            "channels": 1,
        },
    }
    if speaker:
        payload["speaker"] = speaker
    if instruction:
        payload["instruction"] = instruction
    return payload


def _expected_warmed_up(args: argparse.Namespace) -> bool:
    expectation = str(args.expect_warmed_up)
    if expectation == "true":
        return True
    if expectation == "false":
        return False
    if str(args.engine) == "mock":
        return True
    return bool(args.warmup_synthesis)


def _is_control_message(
    frame: Frame,
    message_type: str,
    request_id: int,
) -> bool:
    if frame.header.frame_type != FrameType.CONTROL_JSON:
        return False
    if frame.header.request_id != request_id:
        return False
    return _control_payload(frame).get("message_type") == message_type


def _control_payload(frame: Frame) -> dict[str, object]:
    return _json_payload(frame)


def _json_payload(frame: Frame) -> dict[str, object]:
    return json.loads(frame.payload.decode("utf-8"))


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    raise SystemExit(main())
