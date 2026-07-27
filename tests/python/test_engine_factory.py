import contextlib
import io
import math
import unittest
from typing import Any

from qwen_tts_bridge_worker.cli import (
    build_engine_config,
    build_parser,
    build_worker_config,
)
from qwen_tts_bridge_worker.config import (
    MockEngineConfig,
    QwenEngineConfig,
    WorkerConfig,
)
from qwen_tts_bridge_worker.engine import (
    MockTtsEngine,
    QwenTtsEngine,
    UnsupportedAudioFormatError,
    create_engine,
)
from qwen_tts_bridge_worker.engine.types import AudioFormat, SynthesisRequest


class EngineFactoryTests(unittest.TestCase):
    def test_mock_subcommand_builds_mock_config(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["mock", "--chunks", "2", "--chunk-ms", "40"])

        config = build_engine_config(args)

        self.assertIsInstance(config, MockEngineConfig)
        assert isinstance(config, MockEngineConfig)
        self.assertEqual(2, config.chunk_count)
        self.assertEqual(40, config.chunk_duration_ms)

    def test_qwen_subcommand_builds_qwen_config(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "qwen",
                "--model-path",
                "models/qwen",
                "--runtime-backend",
                "faster",
                "--device",
                "cuda:0",
                "--dtype",
                "bfloat16",
                "--attn-implementation",
                "sdpa",
                "--max-seq-len",
                "1024",
                "--emit-every-frames",
                "4",
                "--decode-window-frames",
                "96",
                "--overlap-samples",
                "32",
                "--enable-streaming-optimizations",
                "--no-cuda-graphs",
                "--compile-mode",
                "default",
                "--use-fast-codebook",
                "--no-compile-talker",
                "--matmul-precision",
                "high",
                "--profile-prefill",
                "--profile-nvtx",
                "--prefill-backend",
                "compile_reduce_overhead",
                "--prefill-compile-compat-mode",
                "strict_bf16_sdpa_v1",
                "--no-sample",
                "--warmup-synthesis",
                "--warmup-text",
                "Prime the engine.",
                "--warmup-language",
                "English",
                "--warmup-speaker",
                "ryan",
                "--warmup-instruction",
                "Speak neutrally.",
            ]
        )

        config = build_engine_config(args)

        self.assertIsInstance(config, QwenEngineConfig)
        assert isinstance(config, QwenEngineConfig)
        self.assertEqual("models/qwen", config.model_path)
        self.assertEqual("faster", config.runtime_backend)
        self.assertEqual("cuda:0", config.device)
        self.assertEqual("bfloat16", config.dtype)
        self.assertEqual("sdpa", config.attn_implementation)
        self.assertEqual(1024, config.max_seq_len)
        self.assertEqual(4, config.emit_every_frames)
        self.assertEqual(96, config.decode_window_frames)
        self.assertEqual(32, config.overlap_samples)
        self.assertTrue(config.enable_streaming_optimizations)
        self.assertTrue(config.use_compile)
        self.assertFalse(config.use_cuda_graphs)
        self.assertEqual("default", config.compile_mode)
        self.assertTrue(config.use_fast_codebook)
        self.assertTrue(config.compile_codebook_predictor)
        self.assertFalse(config.compile_talker)
        self.assertEqual("high", config.matmul_precision)
        self.assertTrue(config.profile_prefill)
        self.assertTrue(config.profile_nvtx)
        self.assertEqual("compile_reduce_overhead", config.prefill_backend)
        self.assertEqual(
            "strict_bf16_sdpa_v1",
            config.prefill_compile_compat_mode,
        )
        self.assertFalse(config.do_sample)
        self.assertTrue(config.warmup_synthesis_enabled)
        self.assertEqual("Prime the engine.", config.warmup_text)
        self.assertEqual("English", config.warmup_language)
        self.assertEqual("ryan", config.warmup_speaker)
        self.assertEqual("Speak neutrally.", config.warmup_instruction)

    def test_qwen_subcommand_requires_model_path(self) -> None:
        parser = build_parser()

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["qwen"])

    def test_legacy_mock_options_still_work(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--mock", "--mock-chunks", "9"])

        config = build_engine_config(args)

        self.assertIsInstance(config, MockEngineConfig)
        assert isinstance(config, MockEngineConfig)
        self.assertEqual(9, config.chunk_count)

    def test_legacy_mock_options_cannot_be_mixed_with_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--mock-chunks", "9", "mock"])

        with self.assertRaisesRegex(ValueError, "legacy engine flags"):
            build_engine_config(args)

    def test_legacy_qwen_options_cannot_be_mixed_with_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["--device", "cpu", "qwen", "--model-path", "models/qwen"]
        )

        with self.assertRaisesRegex(ValueError, "legacy engine flags"):
            build_engine_config(args)

    def test_server_options_work_before_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["--worker-version", "0.3.0", "--output-queue-size", "256", "mock"]
        )

        config = build_worker_config(args)

        self.assertEqual("0.3.0", config.worker_version)
        self.assertEqual(256, config.output_queue_size)

    def test_server_options_work_after_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["mock", "--worker-version", "0.3.0", "--output-queue-size", "256"]
        )

        config = build_worker_config(args)

        self.assertEqual("0.3.0", config.worker_version)
        self.assertEqual(256, config.output_queue_size)

    def test_server_options_cannot_be_repeated_around_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["--output-queue-size", "256", "mock", "--output-queue-size", "512"]
        )

        with self.assertRaisesRegex(ValueError, "output-queue-size"):
            build_worker_config(args)

    def test_auto_startup_mode_uses_main_for_mock(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["mock"])

        config = build_worker_config(args)

        self.assertEqual("main", config.engine_startup_mode)

    def test_auto_startup_mode_uses_engine_warmup_for_qwen(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["qwen", "--model-path", "models/qwen"])

        config = build_worker_config(args)

        self.assertEqual("engine_warmup", config.engine_startup_mode)

    def test_explicit_qwen_startup_mode_is_kept_as_rollback(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "qwen",
                "--model-path",
                "models/qwen",
                "--engine-startup-mode",
                "main",
            ]
        )

        config = build_worker_config(args)

        self.assertEqual("main", config.engine_startup_mode)

    def test_create_mock_engine_from_config(self) -> None:
        config = MockEngineConfig(
            chunk_count=2,
            chunk_duration_ms=40,
            chunk_delay_seconds=0.0,
        )

        engine = create_engine(config)

        self.assertIsInstance(engine, MockTtsEngine)
        self.assertTrue(engine.capabilities.streaming)
        self.assertTrue(engine.capabilities.cancellation)

    def test_mock_engine_validates_supported_audio_format(self) -> None:
        engine = create_engine(MockEngineConfig())
        request = SynthesisRequest(
            request_id=1,
            text="test",
            output=AudioFormat.default(),
        )

        engine.validate_request(request)

        unsupported = SynthesisRequest(
            request_id=2,
            text="test",
            output=AudioFormat(sample_rate=48000),
        )

        with self.assertRaisesRegex(UnsupportedAudioFormatError, "s16le"):
            engine.validate_request(unsupported)

    def test_create_qwen_engine_from_config(self) -> None:
        engine = create_engine(QwenEngineConfig(model_path="models/qwen"))

        self.assertIsInstance(engine, QwenTtsEngine)
        self.assertFalse(engine.capabilities.streaming)
        self.assertFalse(engine.capabilities.cancellation)
        self.assertTrue(engine.capabilities.instructions)

    def test_worker_config_stores_only_selected_engine_config(self) -> None:
        config = WorkerConfig(engine=QwenEngineConfig(model_path="models/qwen"))

        self.assertIsInstance(config.engine, QwenEngineConfig)

    def test_worker_config_rejects_unknown_engine_config_type(self) -> None:
        with self.assertRaises(TypeError):
            WorkerConfig(engine=object())  # type: ignore[arg-type]

    def test_qwen_config_rejects_empty_device_and_dtype(self) -> None:
        qwen_configs: tuple[dict[str, Any], ...] = (
            {"model_path": ""},
            {"model_path": "models/qwen", "runtime_backend": "bad"},
            {"model_path": "models/qwen", "device": ""},
            {"model_path": "models/qwen", "dtype": ""},
            {"model_path": "models/qwen", "emit_every_frames": 0},
            {"model_path": "models/qwen", "decode_window_frames": 0},
            {"model_path": "models/qwen", "max_seq_len": 0},
            {"model_path": "models/qwen", "overlap_samples": -1},
            {"model_path": "models/qwen", "compile_mode": ""},
            {"model_path": "models/qwen", "matmul_precision": "fastest"},
            {
                "model_path": "models/qwen",
                "warmup_synthesis_enabled": True,
                "warmup_text": "",
            },
            {"model_path": "models/qwen", "warmup_language": ""},
        )
        for qwen_config in qwen_configs:
            with self.subTest(qwen_config=qwen_config):
                with self.assertRaises(ValueError):
                    QwenEngineConfig(**qwen_config)

    def test_qwen_config_rejects_invalid_strict_prefill_compat_contract(self) -> None:
        valid: dict[str, Any] = {
            "model_path": "models/qwen",
            "runtime_backend": "faster",
            "dtype": "bfloat16",
            "attn_implementation": "sdpa",
            "prefill_backend": "compile_reduce_overhead",
            "prefill_compile_compat_mode": "strict_bf16_sdpa_v1",
            "warmup_synthesis_enabled": True,
        }
        invalid_updates: tuple[dict[str, Any], ...] = (
            {"runtime_backend": "upstream"},
            {"dtype": "float16"},
            {"attn_implementation": "flash_attention_2"},
            {"prefill_backend": "eager"},
            {"prefill_backend": "compile_backend_eager"},
            {"warmup_synthesis_enabled": False},
        )

        for update in invalid_updates:
            qwen_config = dict(valid)
            qwen_config.update(update)
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    QwenEngineConfig(**qwen_config)

        QwenEngineConfig(**valid)

    def test_reject_invalid_mock_delay(self) -> None:
        for value in (-1.0, math.inf, math.nan):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    MockEngineConfig(chunk_delay_seconds=value)

    def test_reject_too_short_mock_chunk_duration(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 20"):
            MockEngineConfig(chunk_duration_ms=10)


if __name__ == "__main__":
    unittest.main()
