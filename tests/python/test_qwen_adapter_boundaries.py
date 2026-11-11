"""Check adapter/module boundaries independently of real model execution."""

import unittest

from qwen_tts_bridge_worker.engine import QwenEngineError
from qwen_tts_bridge_worker.engine.qwen.errors import QwenEngineError as WarmupError
from qwen_tts_bridge_worker.engine.qwen.telemetry import _first_chunk_timing_fields
from qwen_tts_bridge_worker.engine.qwen_engine import _unpack_audio_chunk


class QwenAdapterBoundaryTests(unittest.TestCase):
    def test_warmup_and_engine_use_the_same_public_error_type(self) -> None:
        self.assertIs(QwenEngineError, WarmupError)

    def test_audio_validation_remains_an_engine_failure(self) -> None:
        with self.assertRaisesRegex(QwenEngineError, "invalid audio chunk"):
            _unpack_audio_chunk(())

    def test_timing_mapping_preserves_residuals_and_gpu_readiness(self) -> None:
        self.assertEqual(
            {
                "next_wall_ms": 10.0,
                "pcm_convert_ms": 1.0,
                "prefill_ms": 3.0,
                "ar_decode_ms": 4.0,
                "chunk_steps": 2,
                "ar_ms_per_step": 2.0,
                "stream_next_gpu_ready": False,
                "codec_wrapper_residual_ms": 3.0,
            },
            _first_chunk_timing_fields(
                {"prefill_ms": 3, "ar_decode_ms": 4, "chunk_steps": 2},
                next_wall_ms=10.0,
                pcm_convert_ms=1.0,
                stream_next_gpu_ready=False,
            ),
        )
