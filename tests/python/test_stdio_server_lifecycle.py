import io
import json
import threading
import unittest
from collections.abc import Iterable
from typing import BinaryIO, cast

from qwen_tts_bridge_worker.config import CanaryRuntimeProvenance
from qwen_tts_bridge_worker.engine import (
    EngineRequestValidationError,
    GenerationSafetyLimitError,
)
from qwen_tts_bridge_worker.engine.types import (
    EngineCapabilities,
    SynthesisRequest,
)
from qwen_tts_bridge_worker.protocol import (
    Frame,
    FrameParser,
    FrameType,
    ParseStatus,
    encode_frame,
)
from qwen_tts_bridge_worker.protocol.control import encode_json_payload
from qwen_tts_bridge_worker.server import StdioWorkerServer
from qwen_tts_bridge_worker.server.stdio_server import _RequestSlot


class FailingLoadEngine:
    def __init__(self) -> None:
        self.close_called = False
        self.load_thread_name = ""

    @property
    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            streaming=False,
            cancellation=False,
            instructions=False,
            voice_clone=False,
        )

    def load(self) -> None:
        self.load_thread_name = threading.current_thread().name
        raise RuntimeError("load failed")

    def warmup(self) -> None:
        raise AssertionError("warmup must not run after load failure")

    def validate_request(
        self,
        request: SynthesisRequest,
    ) -> None:
        del request

    def synthesize_stream(
        self,
        request: SynthesisRequest,
        cancel_event: threading.Event,
    ) -> Iterable[bytes]:
        del request, cancel_event
        raise AssertionError("synthesize_stream must not run after load failure")

    def close(self) -> None:
        self.close_called = True


class _RecordingWriter:
    def __init__(self) -> None:
        self.frames: list[bytes] = []

    def send(self, frame: bytes, **_: object) -> None:
        self.frames.append(frame)


class FailingWarmupEngine:
    def __init__(self) -> None:
        self.close_called = False
        self.load_thread_name = ""
        self.warmup_thread_name = ""

    @property
    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            streaming=False,
            cancellation=False,
            instructions=False,
            voice_clone=False,
        )

    def load(self) -> None:
        self.load_thread_name = threading.current_thread().name

    def warmup(self) -> None:
        self.warmup_thread_name = threading.current_thread().name
        raise RuntimeError("warmup failed")

    def validate_request(
        self,
        request: SynthesisRequest,
    ) -> None:
        del request

    def synthesize_stream(
        self,
        request: SynthesisRequest,
        cancel_event: threading.Event,
    ) -> Iterable[bytes]:
        del request, cancel_event
        raise AssertionError("synthesize_stream must not run after warmup failure")

    def close(self) -> None:
        self.close_called = True


class RequestValidationEngine:
    @property
    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            streaming=False,
            cancellation=False,
            instructions=True,
            voice_clone=False,
        )

    def load(self) -> None:
        pass

    def warmup(self) -> None:
        pass

    def validate_request(
        self,
        request: SynthesisRequest,
    ) -> None:
        del request
        raise EngineRequestValidationError(
            "missing_required_field",
            "speaker is required",
        )

    def synthesize_stream(
        self,
        request: SynthesisRequest,
        cancel_event: threading.Event,
    ) -> Iterable[bytes]:
        del request, cancel_event
        raise AssertionError("invalid request must not reach synthesis")

    def close(self) -> None:
        pass


class SettingsEngine:
    def __init__(self) -> None:
        self.completed = threading.Event()

    @property
    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            streaming=True,
            cancellation=True,
            instructions=True,
            voice_clone=False,
            sampling_overrides=True,
            deterministic_seed=True,
        )

    def load(self) -> None:
        pass

    def warmup(self) -> None:
        pass

    def validate_request(self, request: SynthesisRequest) -> None:
        del request

    def describe_request(self, request: SynthesisRequest) -> dict[str, object]:
        self.validate_request(request)
        return {
            "effective_seed": request.seed,
            "effective_seed_explicit": request.seed is not None,
            "effective_temperature": 0.4,
            "effective_top_k": 50,
            "effective_top_p": 1.0,
            "effective_repetition_penalty": 1.05,
            "effective_do_sample": True,
        }

    def synthesize_stream(
        self,
        request: SynthesisRequest,
        cancel_event: threading.Event,
    ) -> Iterable[bytes]:
        del request, cancel_event
        self.completed.set()
        return ()

    def pop_last_generation_trace(self) -> dict[str, object]:
        return {
            "termination_reason": "eos",
            "hit_eos": True,
            "hit_max_seq_len": False,
            "hit_max_new_tokens": False,
            "codec_frame_count": 8,
            "generated_steps": 8,
            "emitted_steps": 8,
            "terminal_step_index": 8,
        }

    def close(self) -> None:
        pass


class WarmupMetricsEngine:
    def __init__(self) -> None:
        self.load_thread_name = ""
        self.warmup_thread_name = ""

    @property
    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            streaming=False,
            cancellation=False,
            instructions=True,
            voice_clone=False,
        )

    def load(self) -> None:
        self.load_thread_name = threading.current_thread().name

    def warmup(self) -> dict[str, object]:
        self.warmup_thread_name = threading.current_thread().name
        return {
            "warmup_synthesis": True,
            "warmup_audio_chunks": 2,
            "warmup_audio_bytes": 64,
            "warmup_passes": [
                {
                    "pass_index": 1,
                    "audio_chunks": 2,
                    "audio_bytes": 64,
                    "audio_duration_ms": 1.333,
                },
            ],
        }

    def validate_request(
        self,
        request: SynthesisRequest,
    ) -> None:
        del request

    def synthesize_stream(
        self,
        request: SynthesisRequest,
        cancel_event: threading.Event,
    ) -> Iterable[bytes]:
        del request, cancel_event
        return ()

    def close(self) -> None:
        pass


class NoopWarmupEngine:
    @property
    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            streaming=False,
            cancellation=False,
            instructions=True,
            voice_clone=False,
        )

    def load(self) -> None:
        pass

    def warmup(self) -> None:
        return None

    def validate_request(
        self,
        request: SynthesisRequest,
    ) -> None:
        del request

    def synthesize_stream(
        self,
        request: SynthesisRequest,
        cancel_event: threading.Event,
    ) -> Iterable[bytes]:
        del request, cancel_event
        return ()

    def close(self) -> None:
        pass


class SafetyLimitEngine(NoopWarmupEngine):
    def __init__(self) -> None:
        self.limit_reached = threading.Event()

    def synthesize_stream(
        self,
        request: SynthesisRequest,
        cancel_event: threading.Event,
    ) -> Iterable[bytes]:
        del request, cancel_event
        yield b"\0" * 480
        self.limit_reached.set()
        raise GenerationSafetyLimitError(60.0, 60.0)


class _EofAfterEvent:
    def __init__(self, payload: bytes, event: threading.Event) -> None:
        self._payload = payload
        self._event = event
        self._sent = False

    def read(self, size: int = -1) -> bytes:
        del size
        if not self._sent:
            self._sent = True
            return self._payload
        self._event.wait(timeout=5.0)
        return b""


class StdioWorkerServerLifecycleTests(unittest.TestCase):
    def test_running_cancel_is_terminal_before_engine_returns(self) -> None:
        stderr = io.StringIO()
        server = StdioWorkerServer(
            input_stream=io.BytesIO(),
            output_stream=io.BytesIO(),
            error_stream=stderr,
            engine=FailingLoadEngine(),
        )
        writer = _RecordingWriter()
        server._writer = writer  # type: ignore[assignment]
        slot = _RequestSlot(
            request=SynthesisRequest(request_id=1, text="Hello"),
            cancel_event=threading.Event(),
            state="running",
        )
        server._active[1] = slot

        server._handle_cancel(1)
        server._finish_cancelled(slot)

        self.assertTrue(slot.cancel_event.is_set())
        self.assertTrue(slot.terminal_notified)
        self.assertNotIn(1, server._active)
        frames = _parse_frames(b"".join(writer.frames))
        self.assertEqual(1, len(frames))
        self.assertEqual("cancelled", _payload(frames[0])["message_type"])
        metrics = [
            json.loads(line.removeprefix("qtb_metric "))
            for line in stderr.getvalue().splitlines()
            if line.startswith("qtb_metric ")
        ]
        terminal_metrics = [
            metric
            for metric in metrics
            if metric.get("event") == "request_finished"
            and metric.get("request_id") == 1
        ]
        cancel_metrics = [
            metric
            for metric in metrics
            if metric.get("event") == "request_cancel_received"
            and metric.get("request_id") == 1
        ]
        self.assertEqual(1, len(cancel_metrics))
        self.assertEqual(1, len(terminal_metrics))
        self.assertEqual("cancelled", terminal_metrics[0]["terminal_state"])

    def test_emits_pinned_canary_runtime_provenance(self) -> None:
        stderr = io.StringIO()
        server = StdioWorkerServer(
            input_stream=io.BytesIO(),
            output_stream=io.BytesIO(),
            error_stream=stderr,
            engine=NoopWarmupEngine(),
            canary_runtime_provenance=CanaryRuntimeProvenance(
                runtime_profile_id="rtx4090-cv06-bf16-sdpa-strict-v1-9d2a61ef",
                bridge_commit="56ecc48123456789",
                faster_wheel_sha256="a" * 64,
                compiled_allowlist_manifest_sha256="b" * 64,
                compiled_lengths=(29, 30, 32, 33, 34, 35),
            ),
        )

        self.assertEqual(0, server.run())

        metrics = [
            json.loads(line.removeprefix("qtb_metric "))
            for line in stderr.getvalue().splitlines()
            if line.startswith("qtb_metric ")
        ]
        provenance = next(
            metric
            for metric in metrics
            if metric["event"] == "canary_runtime_provenance"
        )
        self.assertEqual("56ecc48123456789", provenance["bridge_commit"])
        self.assertEqual("a" * 64, provenance["faster_wheel_sha256"])

    def test_load_failure_does_not_join_unstarted_engine_thread(self) -> None:
        engine = FailingLoadEngine()
        stderr = io.StringIO()
        server = StdioWorkerServer(
            input_stream=io.BytesIO(),
            output_stream=io.BytesIO(),
            error_stream=stderr,
            engine=engine,
        )

        exit_code = server.run()

        self.assertEqual(1, exit_code)
        self.assertTrue(engine.close_called)
        self.assertIn("load failed", stderr.getvalue())
        self.assertNotIn("cannot join thread before it is started", stderr.getvalue())

    def test_warmup_failure_does_not_join_unstarted_engine_thread(self) -> None:
        engine = FailingWarmupEngine()
        stderr = io.StringIO()
        server = StdioWorkerServer(
            input_stream=io.BytesIO(),
            output_stream=io.BytesIO(),
            error_stream=stderr,
            engine=engine,
        )

        exit_code = server.run()

        self.assertEqual(1, exit_code)
        self.assertTrue(engine.close_called)
        self.assertIn("warmup failed", stderr.getvalue())
        self.assertNotIn("cannot join thread before it is started", stderr.getvalue())

    def test_engine_request_validation_error_is_request_error(self) -> None:
        input_stream = io.BytesIO(
            _control_frame(
                0,
                {
                    "message_type": "hello",
                    "client_name": "test-client",
                    "client_version": "0.2.0",
                },
            )
            + _control_frame(
                1,
                {
                    "message_type": "synthesize",
                    "text": "Hello",
                },
            )
        )
        output_stream = io.BytesIO()
        error_stream = io.StringIO()
        server = StdioWorkerServer(
            input_stream=input_stream,
            output_stream=output_stream,
            error_stream=error_stream,
            engine=RequestValidationEngine(),
        )

        exit_code = server.run()
        frames = _parse_frames(output_stream.getvalue())

        self.assertEqual(0, exit_code)
        self.assertEqual("ready", _payload(frames[0])["message_type"])
        self.assertEqual(FrameType.ERROR_JSON, frames[1].header.frame_type)
        self.assertEqual(1, frames[1].header.request_id)
        self.assertEqual(
            {
                "message_type": "error",
                "category": "request_error",
                "code": "missing_required_field",
                "message": "speaker is required",
            },
            _payload(frames[1]),
        )
        metrics = [
            json.loads(line.removeprefix("qtb_metric "))
            for line in error_stream.getvalue().splitlines()
            if line.startswith("qtb_metric ")
        ]
        terminal = next(
            metric
            for metric in metrics
            if metric["event"] == "request_finished" and metric["request_id"] == 1
        )
        self.assertEqual("failed", terminal["terminal_state"])

    def test_unknown_sampling_field_is_rejected(self) -> None:
        input_stream = io.BytesIO(
            _control_frame(
                0,
                {
                    "message_type": "hello",
                    "client_name": "test-client",
                    "client_version": "0.2.0",
                },
            )
            + _control_frame(
                1,
                {
                    "message_type": "synthesize",
                    "text": "Hello",
                    "sampling": {"temprature": 0.4},
                },
            )
        )
        output_stream = io.BytesIO()
        server = StdioWorkerServer(
            input_stream=input_stream,
            output_stream=output_stream,
            error_stream=io.StringIO(),
            engine=NoopWarmupEngine(),
        )

        self.assertEqual(0, server.run())

        frames = _parse_frames(output_stream.getvalue())
        self.assertEqual("ready", _payload(frames[0])["message_type"])
        self.assertEqual(FrameType.ERROR_JSON, frames[1].header.frame_type)
        self.assertEqual("request_error", _payload(frames[1])["category"])
        self.assertEqual("unknown_field", _payload(frames[1])["code"])

    def test_ready_capabilities_and_effective_settings_are_emitted(self) -> None:
        input_stream = io.BytesIO(
            _control_frame(
                0,
                {
                    "message_type": "hello",
                    "client_name": "test-client",
                    "client_version": "0.2.0",
                },
            )
            + _control_frame(
                1,
                {
                    "message_type": "synthesize",
                    "text": "Hello",
                    "seed": 4242,
                },
            )
        )
        output_stream = io.BytesIO()
        error_stream = io.StringIO()
        engine = SettingsEngine()
        server = StdioWorkerServer(
            input_stream=cast(
                BinaryIO,
                _EofAfterEvent(input_stream.getvalue(), engine.completed),
            ),
            output_stream=output_stream,
            error_stream=error_stream,
            engine=engine,
        )

        self.assertEqual(0, server.run())

        frames = _parse_frames(output_stream.getvalue())
        ready = _payload(frames[0])
        capabilities = cast(dict[str, object], ready["capabilities"])
        self.assertTrue(capabilities["sampling_overrides"])
        self.assertTrue(capabilities["deterministic_seed"])
        metrics = [
            json.loads(line.removeprefix("qtb_metric "))
            for line in error_stream.getvalue().splitlines()
            if line.startswith("qtb_metric ")
        ]
        effective = next(
            metric
            for metric in metrics
            if metric["event"] == "request_effective_generation_settings"
        )
        self.assertEqual(4242, effective["effective_seed"])
        self.assertEqual(0.4, effective["effective_temperature"])
        self.assertTrue(effective["effective_do_sample"])
        completed = _payload(frames[-1])
        self.assertEqual("completed", completed["message_type"])
        self.assertEqual("completed", completed["execution_outcome"])
        self.assertEqual(
            "eos",
            cast(dict[str, object], completed["generation_trace"])[
                "termination_reason"
            ],
        )

    def test_safety_limit_is_preserved_on_terminal_metric(self) -> None:
        payload = (
            _control_frame(
                0,
                {
                    "message_type": "hello",
                    "client_name": "test-client",
                    "client_version": "0.2.0",
                },
            )
            + _control_frame(
                1,
                {
                    "message_type": "synthesize",
                    "text": "Hello",
                },
            )
        )
        engine = SafetyLimitEngine()
        output_stream = io.BytesIO()
        error_stream = io.StringIO()
        server = StdioWorkerServer(
            input_stream=cast(
                BinaryIO,
                _EofAfterEvent(payload, engine.limit_reached),
            ),
            output_stream=output_stream,
            error_stream=error_stream,
            engine=engine,
        )

        self.assertEqual(0, server.run())

        frames = _parse_frames(output_stream.getvalue())
        error = next(
            frame
            for frame in frames
            if frame.header.frame_type == FrameType.ERROR_JSON
        )
        self.assertEqual("safety_duration_limit", _payload(error)["code"])
        metrics = [
            json.loads(line.removeprefix("qtb_metric "))
            for line in error_stream.getvalue().splitlines()
            if line.startswith("qtb_metric ")
        ]
        terminal = next(
            metric
            for metric in metrics
            if metric["event"] == "request_finished" and metric["request_id"] == 1
        )
        self.assertEqual("failed", terminal["terminal_state"])
        self.assertEqual("safety_duration_limit", terminal["generation_outcome"])

    def test_warmup_metrics_are_emitted(self) -> None:
        input_stream = io.BytesIO(
            _control_frame(
                0,
                {
                    "message_type": "hello",
                    "client_name": "test-client",
                    "client_version": "0.2.0",
                },
            )
        )
        output_stream = io.BytesIO()
        stderr = io.StringIO()
        server = StdioWorkerServer(
            input_stream=input_stream,
            output_stream=output_stream,
            error_stream=stderr,
            engine=WarmupMetricsEngine(),
        )

        self.assertEqual(0, server.run())

        warmup_metrics = [
            json.loads(line.removeprefix("qtb_metric "))
            for line in stderr.getvalue().splitlines()
            if line.startswith("qtb_metric ")
            and json.loads(line.removeprefix("qtb_metric ")).get("event")
            == "engine_warmed_up"
        ]
        self.assertEqual(1, len(warmup_metrics))
        self.assertTrue(warmup_metrics[0]["warmed_up"])
        self.assertTrue(warmup_metrics[0]["warmup_synthesis"])
        self.assertEqual(2, warmup_metrics[0]["warmup_audio_chunks"])
        self.assertEqual(64, warmup_metrics[0]["warmup_audio_bytes"])

        pass_metrics = [
            json.loads(line.removeprefix("qtb_metric "))
            for line in stderr.getvalue().splitlines()
            if line.startswith("qtb_metric ")
            and json.loads(line.removeprefix("qtb_metric ")).get("event")
            == "engine_warmup_pass"
        ]
        self.assertEqual(1, len(pass_metrics))
        self.assertEqual(1, pass_metrics[0]["pass_index"])
        self.assertEqual(64, pass_metrics[0]["audio_bytes"])

    def test_noop_warmup_reports_not_warmed_up(self) -> None:
        input_stream = io.BytesIO(
            _control_frame(
                0,
                {
                    "message_type": "hello",
                    "client_name": "test-client",
                    "client_version": "0.2.0",
                },
            )
        )
        output_stream = io.BytesIO()
        stderr = io.StringIO()
        server = StdioWorkerServer(
            input_stream=input_stream,
            output_stream=output_stream,
            error_stream=stderr,
            engine=NoopWarmupEngine(),
        )

        self.assertEqual(0, server.run())

        frames = _parse_frames(output_stream.getvalue())
        ready = _payload(frames[0])
        self.assertEqual("ready", ready["message_type"])
        self.assertFalse(ready["warmed_up"])

        warmup_metrics = [
            json.loads(line.removeprefix("qtb_metric "))
            for line in stderr.getvalue().splitlines()
            if line.startswith("qtb_metric ")
            and json.loads(line.removeprefix("qtb_metric ")).get("event")
            == "engine_warmed_up"
        ]
        self.assertEqual(1, len(warmup_metrics))
        self.assertFalse(warmup_metrics[0]["warmed_up"])

    def test_engine_warmup_mode_runs_warmup_on_engine_thread(self) -> None:
        input_stream = io.BytesIO(
            _control_frame(
                0,
                {
                    "message_type": "hello",
                    "client_name": "test-client",
                    "client_version": "0.2.0",
                },
            )
        )
        engine = WarmupMetricsEngine()
        stderr = io.StringIO()
        server = StdioWorkerServer(
            input_stream=input_stream,
            output_stream=io.BytesIO(),
            error_stream=stderr,
            engine=engine,
            engine_startup_mode="engine_warmup",
        )

        self.assertEqual(0, server.run())

        self.assertEqual("MainThread", engine.load_thread_name)
        self.assertEqual("qtb-engine", engine.warmup_thread_name)
        warmup_metric = next(
            json.loads(line.removeprefix("qtb_metric "))
            for line in stderr.getvalue().splitlines()
            if line.startswith("qtb_metric ")
            and json.loads(line.removeprefix("qtb_metric ")).get("event")
            == "engine_warmed_up"
        )
        self.assertEqual("engine_warmup", warmup_metric["startup_mode"])
        self.assertEqual("qtb-engine", warmup_metric["python_thread_name"])

    def test_engine_load_warmup_mode_runs_lifecycle_on_engine_thread(self) -> None:
        input_stream = io.BytesIO(
            _control_frame(
                0,
                {
                    "message_type": "hello",
                    "client_name": "test-client",
                    "client_version": "0.2.0",
                },
            )
        )
        engine = WarmupMetricsEngine()
        stderr = io.StringIO()
        server = StdioWorkerServer(
            input_stream=input_stream,
            output_stream=io.BytesIO(),
            error_stream=stderr,
            engine=engine,
            engine_startup_mode="engine_load_warmup",
        )

        self.assertEqual(0, server.run())

        self.assertEqual("qtb-engine", engine.load_thread_name)
        self.assertEqual("qtb-engine", engine.warmup_thread_name)
        load_metric = next(
            json.loads(line.removeprefix("qtb_metric "))
            for line in stderr.getvalue().splitlines()
            if line.startswith("qtb_metric ")
            and json.loads(line.removeprefix("qtb_metric ")).get("event")
            == "engine_loaded"
        )
        self.assertEqual("engine_load_warmup", load_metric["startup_mode"])
        self.assertEqual("qtb-engine", load_metric["python_thread_name"])

    def test_engine_thread_load_failure_exits_without_ready(self) -> None:
        engine = FailingLoadEngine()
        output_stream = io.BytesIO()
        stderr = io.StringIO()
        server = StdioWorkerServer(
            input_stream=io.BytesIO(
                _control_frame(
                    0,
                    {
                        "message_type": "hello",
                        "client_name": "test-client",
                        "client_version": "0.2.0",
                    },
                )
            ),
            output_stream=output_stream,
            error_stream=stderr,
            engine=engine,
            engine_startup_mode="engine_load_warmup",
        )

        exit_code = server.run()

        self.assertEqual(1, exit_code)
        self.assertEqual("qtb-engine", engine.load_thread_name)
        self.assertTrue(engine.close_called)
        self.assertEqual([], _parse_frames(output_stream.getvalue()))
        self.assertIn("load failed", stderr.getvalue())

    def test_engine_thread_warmup_failure_exits_without_ready(self) -> None:
        engine = FailingWarmupEngine()
        output_stream = io.BytesIO()
        stderr = io.StringIO()
        server = StdioWorkerServer(
            input_stream=io.BytesIO(
                _control_frame(
                    0,
                    {
                        "message_type": "hello",
                        "client_name": "test-client",
                        "client_version": "0.2.0",
                    },
                )
            ),
            output_stream=output_stream,
            error_stream=stderr,
            engine=engine,
            engine_startup_mode="engine_warmup",
        )

        exit_code = server.run()

        self.assertEqual(1, exit_code)
        self.assertEqual("MainThread", engine.load_thread_name)
        self.assertEqual("qtb-engine", engine.warmup_thread_name)
        self.assertTrue(engine.close_called)
        self.assertEqual([], _parse_frames(output_stream.getvalue()))
        self.assertIn("warmup failed", stderr.getvalue())


def _control_frame(request_id: int, message: dict[str, object]) -> bytes:
    return encode_frame(
        FrameType.CONTROL_JSON,
        request_id,
        encode_json_payload(message),
    )


def _parse_frames(data: bytes) -> list[Frame]:
    parser = FrameParser()
    parser.append(data)
    frames: list[Frame] = []
    while True:
        result = parser.parse_next()
        if result.status == ParseStatus.NEED_MORE_DATA:
            return frames
        if result.status != ParseStatus.FRAME_READY or result.frame is None:
            raise AssertionError(f"unexpected parser result: {result}")
        frames.append(result.frame)


def _payload(frame: Frame) -> dict[str, object]:
    return json.loads(frame.payload.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
