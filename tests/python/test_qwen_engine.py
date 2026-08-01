import importlib
import json
import random
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine import (
    AudioFormat,
    EngineRequestValidationError,
    GenerationSafetyLimitError,
    QwenEngineError,
    QwenTtsEngine,
    SynthesisRequest,
    UnsupportedAudioFormatError,
)
from qwen_tts_bridge_worker.engine.qwen_engine import (
    _prefill_snapshot_max_abs,
    _preserved_rng_state,
    _reset_after_partial_generation,
)


class _InnerModel:
    def __init__(self, model_type: str) -> None:
        self.tts_model_type = model_type


class _CustomVoiceModel:
    def __init__(self, supported_speakers: list[str] | None = None) -> None:
        self.model = _InnerModel("custom_voice")
        self._supported_speakers = supported_speakers or ["Alice"]
        self.last_call: dict[str, object] | None = None

    def generate_custom_voice(
        self,
        text: str,
        language: str | None,
        speaker: str,
        instruct: str | None,
    ) -> tuple[list[list[float]], int]:
        self.last_call = {
            "text": text,
            "language": language,
            "speaker": speaker,
            "instruct": instruct,
        }
        return [[-1.0, 0.0, 1.0]], 24000

    def get_supported_speakers(self) -> list[str]:
        return self._supported_speakers


class _VoiceDesignModel:
    def __init__(self) -> None:
        self.model = _InnerModel("voice_design")
        self.last_call: dict[str, object] | None = None

    def generate_voice_design(
        self,
        text: str,
        language: str | None,
        instruct: str,
    ) -> tuple[list[list[float]], int]:
        self.last_call = {
            "text": text,
            "language": language,
            "instruct": instruct,
        }
        return [[0.25, -0.25]], 24000


class _BaseModel:
    def __init__(self) -> None:
        self.model = _InnerModel("base")


class _StreamingInnerModel(_InnerModel):
    def __init__(self, model_type: str) -> None:
        super().__init__(model_type)
        self.stream_calls: list[dict[str, object]] = []

    def stream_generate_pcm(self, **kwargs: object) -> object:
        self.stream_calls.append(dict(kwargs))
        yield [-0.5], 24000
        yield [0.5], 24000


class _StreamingWrapperModel:
    def __init__(
        self,
        model_type: str,
        supported_speakers: list[str] | None = None,
    ) -> None:
        self.model = _StreamingInnerModel(model_type)
        self._supported_speakers = supported_speakers
        self.tokenized_texts: list[str] = []

    def get_supported_speakers(self) -> list[str] | None:
        return self._supported_speakers

    def _build_assistant_text(self, text: str) -> str:
        return f"assistant:{text}"

    def _build_instruct_text(self, text: str) -> str:
        return f"instruct:{text}"

    def _tokenize_texts(self, texts: list[str]) -> list[str]:
        self.tokenized_texts.extend(texts)
        return [f"ids:{text}" for text in texts]

    def generate_custom_voice(self, *args: Any, **kwargs: Any) -> object:
        raise AssertionError("streaming path must not call generate_custom_voice")

    def generate_voice_design(self, *args: Any, **kwargs: Any) -> object:
        raise AssertionError("streaming path must not call generate_voice_design")


class _EmptyStreamingWrapperModel(_StreamingWrapperModel):
    def __init__(self) -> None:
        super().__init__("custom_voice", supported_speakers=["Alice"])

        class _EmptyInnerModel(_InnerModel):
            def __init__(self) -> None:
                super().__init__("custom_voice")

            def stream_generate_pcm(self, **kwargs: object) -> object:
                if False:
                    yield [], 24000

        self.model = _EmptyInnerModel()


class _FasterStreamingModel:
    def __init__(
        self,
        model_type: str,
        supported_speakers: list[str] | None = None,
        *,
        dtype: str = "bfloat16",
        attn_implementation: str = "sdpa",
        prefill_compile_compat_mode: str = "none",
        prefill_compile_compat_metadata: dict[str, object] | None = None,
    ) -> None:
        self.model = _NestedWrapper(model_type, attn_implementation)
        self.dtype = dtype
        self.prefill_compile_compat_mode = prefill_compile_compat_mode
        self.prefill_compile_compat_metadata = (
            prefill_compile_compat_metadata
            if prefill_compile_compat_metadata is not None
            else self._default_prefill_compile_compat_metadata(
                prefill_compile_compat_mode
            )
        )
        self._supported_speakers = supported_speakers
        self.custom_stream_calls: list[dict[str, object]] = []
        self.design_stream_calls: list[dict[str, object]] = []
        self.closed_streams = 0
        self.collect_generation_trace = False
        self.last_generation_trace: dict[str, object] = {}

    def _default_prefill_compile_compat_metadata(
        self,
        mode: str,
    ) -> dict[str, object]:
        validated = mode != "none"
        validated_modules = (
            {"attention": 1, "mlp": 1, "rmsnorm": 4} if validated else {}
        )
        return {
            "prefill_compile_compat_metadata_version": 1,
            "prefill_compile_compat_wrapper_mode": mode,
            "prefill_compile_compat_declared_mode": mode,
            "prefill_compile_compat_mode": mode,
            "prefill_compile_compat_applied": False,
            "prefill_compile_compat_reused": False,
            "prefill_compile_compat_patched_modules": {},
            "prefill_compile_compat_validated_modules": validated_modules,
            "prefill_compile_compat_target_fingerprint": {
                "schema_version": 1,
                "attention": validated_modules.get("attention", 0),
                "expected_decoder_layers": validated_modules.get("attention", 0),
                "mlp": validated_modules.get("mlp", 0),
                "rmsnorm": validated_modules.get("rmsnorm", 0),
            },
        }

    def get_supported_speakers(self) -> list[str] | None:
        return self._supported_speakers

    def generate_custom_voice_streaming(self, **kwargs: object) -> object:
        self.custom_stream_calls.append(dict(kwargs))
        return self._stream()

    def generate_voice_design_streaming(self, **kwargs: object) -> object:
        self.design_stream_calls.append(dict(kwargs))
        return self._stream()

    def _stream(self) -> object:
        model = self

        class _Stream:
            def __iter__(self) -> "_Stream":
                self._index = 0
                return self

            def __next__(self) -> tuple[list[float], int, dict[str, object]]:
                if self._index >= 2:
                    raise StopIteration
                self._index += 1
                return (
                    [0.5],
                    24000,
                    {
                        "prefill_ms": 12.0,
                        "decode_ms": 80.0,
                        "chunk_steps": 8,
                        "chunk_target_steps": 8,
                        "chunk_schedule_index": 1,
                        "profile_schema_version": 3,
                        "profile_path": "fast",
                        "profile_request_role": "first_user",
                        "profile_prefill_enabled": True,
                        "profile_complete": True,
                        "events_complete": True,
                        "components_finite": True,
                        "components_nonnegative": True,
                        "all_component_streams_equal": True,
                        "prefill_total_gpu_ms": 11.0,
                        "talker_forward_gpu_ms": 6.0,
                        "first_sample_gpu_ms": 1.0,
                        "prefill_kv_gpu_ms": 2.0,
                        "generation_state_gpu_ms": 1.5,
                        "prefill_to_sync_gpu_ms": 0.5,
                        "prefill_gpu_component_sum_ms": 11.0,
                        "prefill_gpu_partition_error_ms": 0.0,
                        "prefill_gpu_accounting_error_ms": 0.0,
                        "talker_forward_gpu_stream_id": 1234,
                        "prefill_shape_length": 21,
                        "prefill_shape_policy": "compiled_allowlist",
                        "prefill_shape_allowlist_hit": True,
                        "prefill_compile_on_miss": False,
                    },
                )

            def close(self) -> None:
                model.closed_streams += 1

        return _Stream()


class _PrimeStreamingModel(_FasterStreamingModel):
    def __init__(self, termination_reason: str) -> None:
        super().__init__(
            "custom_voice",
            supported_speakers=["Alice"],
            prefill_compile_compat_mode="strict_bf16_sdpa_v1",
        )
        self._termination_reason = termination_reason

    def _stream(self) -> object:
        parent = super()._stream()
        model = self

        class _TracedStream:
            def __iter__(self) -> "_TracedStream":
                self._iterator = iter(parent)
                return self

            def __next__(self) -> tuple[list[float], int, dict[str, object]]:
                try:
                    return next(self._iterator)
                except StopIteration:
                    model.last_generation_trace = {
                        "codec_sha256": "prime-trace",
                        "codec_frame_count": 2,
                        "termination_reason": model._termination_reason,
                    }
                    raise

            def close(self) -> None:
                parent.close()

        return _TracedStream()


class _TalkerConfig:
    def __init__(self, attn_implementation: str) -> None:
        self._attn_implementation = attn_implementation


class _ModelConfig:
    def __init__(self, attn_implementation: str) -> None:
        self.talker_config = _TalkerConfig(attn_implementation)


class _NestedWrapper:
    def __init__(self, model_type: str, attn_implementation: str = "sdpa") -> None:
        self.model = _InnerModel(model_type)
        self.config = _ModelConfig(attn_implementation)


def _generation_prime_config(manifest: Path) -> QwenEngineConfig:
    return QwenEngineConfig(
        model_path="models/qwen-custom",
        runtime_backend="faster",
        dtype="bfloat16",
        attn_implementation="sdpa",
        max_audio_seconds_per_utterance=60.0,
        prefill_backend="compile_reduce_overhead",
        prefill_compile_compat_mode="strict_bf16_sdpa_v1",
        prefill_compile_lengths=(16,),
        prefill_compile_on_miss=False,
        prefill_unknown_shape_policy="eager",
        prefill_compile_policy="exact_allowlist",
        prefill_allowlist_warmup_manifest=str(manifest),
        prefill_require_precompiled=True,
        prefill_first_chunk_warmup_enabled=True,
        prefill_first_chunk_warmup_length=16,
        prefill_generation_prime_enabled=True,
        collect_generation_trace=True,
    )


class QwenEngineTests(unittest.TestCase):
    def test_safety_duration_limit_fails_after_delivering_bounded_pcm(self) -> None:
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-custom",
                max_audio_seconds_per_utterance=1.0 / 24_000.0,
            ),
            model_loader=lambda _config: _StreamingWrapperModel(
                "custom_voice",
                supported_speakers=["Alice"],
            ),
        )
        engine.load()
        request = SynthesisRequest(request_id=1, text="Hello", speaker="Alice")

        chunks = []
        with self.assertRaises(GenerationSafetyLimitError) as raised:
            for chunk in engine.synthesize_stream(request, threading.Event()):
                chunks.append(chunk)

        self.assertEqual(1, len(chunks))
        self.assertEqual(2, len(chunks[0]))
        self.assertEqual(1.0 / 24_000.0, raised.exception.limit_seconds)

    def test_prefill_snapshot_rejects_structural_mismatch(self) -> None:
        cases = (
            ({"hidden": 1}, {"cache": 1}, "dictionary keys mismatch"),
            ([1], (1,), "type mismatch"),
            ([1], [1, 2], "sequence length mismatch"),
        )

        for left, right, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(QwenEngineError, message):
                    _prefill_snapshot_max_abs(left, right)

    def test_prefill_snapshot_rejects_tensor_dtype_mismatch(self) -> None:
        class _EmptyTensor:
            def __init__(self, dtype: str) -> None:
                self.shape = (1, 4)
                self.dtype = dtype

            def numel(self) -> int:
                return 0

        with self.assertRaisesRegex(QwenEngineError, "dtype mismatch"):
            _prefill_snapshot_max_abs(
                _EmptyTensor("bfloat16"),
                _EmptyTensor("float32"),
            )

    def test_capabilities_are_conservative_before_load(self) -> None:
        engine = QwenTtsEngine(QwenEngineConfig(model_path="models/qwen-custom"))

        self.assertFalse(engine.capabilities.streaming)
        self.assertFalse(engine.capabilities.cancellation)
        self.assertTrue(engine.capabilities.instructions)

    def test_custom_voice_generation_is_mapped_to_pcm(self) -> None:
        fake_model = _CustomVoiceModel()
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-custom",
                emit_every_frames=4,
                decode_window_frames=96,
                overlap_samples=32,
            ),
            model_loader=lambda _config: fake_model,
        )
        engine.load()

        chunks = list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    language="English",
                    speaker="Alice",
                    instruction="Speak warmly.",
                ),
                threading.Event(),
            )
        )

        self.assertEqual([struct.pack("<hhh", -32767, 0, 32767)], chunks)
        self.assertEqual(
            {
                "text": "Hello",
                "language": "English",
                "speaker": "Alice",
                "instruct": "Speak warmly.",
            },
            fake_model.last_call,
        )

    def test_full_audio_fallback_does_not_advertise_streaming(self) -> None:
        engine = QwenTtsEngine(
            QwenEngineConfig(model_path="models/qwen-custom"),
            model_loader=lambda _config: _CustomVoiceModel(),
        )
        engine.load()

        self.assertFalse(engine.capabilities.streaming)
        self.assertFalse(engine.capabilities.cancellation)

    def test_auto_language_becomes_model_default_language(self) -> None:
        fake_model = _CustomVoiceModel()
        engine = QwenTtsEngine(
            QwenEngineConfig(model_path="models/qwen-custom"),
            model_loader=lambda _config: fake_model,
        )
        engine.load()

        list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    language="auto",
                    speaker="Alice",
                ),
                threading.Event(),
            )
        )

        self.assertIsNotNone(fake_model.last_call)
        assert fake_model.last_call is not None
        self.assertIsNone(fake_model.last_call["language"])

    def test_custom_voice_requires_explicit_speaker(self) -> None:
        engine = QwenTtsEngine(
            QwenEngineConfig(model_path="models/qwen-custom"),
            model_loader=lambda _config: _CustomVoiceModel(),
        )
        engine.load()

        for speaker in ("", "   "):
            with self.subTest(speaker=speaker):
                with self.assertRaisesRegex(
                    EngineRequestValidationError,
                    "explicit speaker",
                ):
                    engine.validate_request(
                        SynthesisRequest(
                            request_id=1,
                            text="Hello",
                            speaker=speaker,
                        )
                    )

    def test_custom_voice_allows_advertised_default_speaker(self) -> None:
        fake_model = _CustomVoiceModel(supported_speakers=["default"])
        engine = QwenTtsEngine(
            QwenEngineConfig(model_path="models/qwen-custom"),
            model_loader=lambda _config: fake_model,
        )
        engine.load()

        chunks = list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    speaker="default",
                ),
                threading.Event(),
            )
        )

        self.assertEqual([struct.pack("<hhh", -32767, 0, 32767)], chunks)
        assert fake_model.last_call is not None
        self.assertEqual("default", fake_model.last_call["speaker"])

    def test_custom_voice_uses_stream_generate_pcm(self) -> None:
        fake_model = _StreamingWrapperModel(
            "custom_voice",
            supported_speakers=["Alice"],
        )
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-custom",
                emit_every_frames=4,
                decode_window_frames=96,
                overlap_samples=32,
            ),
            model_loader=lambda _config: fake_model,
        )
        engine.load()

        self.assertTrue(engine.capabilities.streaming)
        self.assertTrue(engine.capabilities.cancellation)

        chunks = list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    language="English",
                    speaker="Alice",
                    instruction="Speak warmly.",
                ),
                threading.Event(),
            )
        )

        self.assertEqual([struct.pack("<h", -16383), struct.pack("<h", 16383)], chunks)
        self.assertEqual(1, len(fake_model.model.stream_calls))
        stream_call = fake_model.model.stream_calls[0]
        self.assertEqual(["English"], stream_call["languages"])
        self.assertEqual(["Alice"], stream_call["speakers"])
        self.assertEqual(4, stream_call["emit_every_frames"])
        self.assertEqual(96, stream_call["decode_window_frames"])
        self.assertEqual(32, stream_call["overlap_samples"])
        self.assertIsNotNone(stream_call["instruct_ids"])
        self.assertIn("assistant:Hello", fake_model.tokenized_texts)
        self.assertIn("instruct:Speak warmly.", fake_model.tokenized_texts)
        metrics = engine.pop_last_chunk_metrics()
        self.assertIsNotNone(metrics)
        assert metrics is not None
        self.assertEqual(len("ids:assistant:Hello"), metrics["text_token_count"])
        self.assertEqual(
            len("ids:instruct:Speak warmly."),
            metrics["instruction_token_count"],
        )
        self.assertEqual(
            len("ids:assistant:Hello") + len("ids:instruct:Speak warmly."),
            metrics["prefill_sequence_length"],
        )

    def test_warmup_synthesis_consumes_stream(self) -> None:
        fake_model = _StreamingWrapperModel(
            "custom_voice",
            supported_speakers=["Alice"],
        )
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-custom",
                warmup_synthesis_enabled=True,
                warmup_synthesis_passes=2,
                warmup_text="Prime.",
                warmup_language="English",
                warmup_speaker="Alice",
                warmup_instruction="Speak neutrally.",
            ),
            model_loader=lambda _config: fake_model,
        )

        warmup_fields = engine.warmup()

        self.assertIsNotNone(warmup_fields)
        assert warmup_fields is not None
        self.assertEqual(2, warmup_fields["warmup_synthesis_passes"])
        self.assertEqual(4, warmup_fields["warmup_audio_chunks"])
        self.assertGreater(cast(int, warmup_fields["warmup_audio_bytes"]), 0)
        self.assertEqual(2, len(cast(list[object], warmup_fields["warmup_passes"])))
        self.assertEqual(2, len(fake_model.model.stream_calls))
        stream_call = fake_model.model.stream_calls[0]
        self.assertEqual(["English"], stream_call["languages"])
        self.assertEqual(["Alice"], stream_call["speakers"])
        self.assertIn("assistant:Prime.", fake_model.tokenized_texts)
        self.assertIn("instruct:Speak neutrally.", fake_model.tokenized_texts)

    def test_warmup_synthesis_rejects_zero_audio(self) -> None:
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-custom",
                warmup_synthesis_enabled=True,
                warmup_text="Prime.",
                warmup_speaker="Alice",
            ),
            model_loader=lambda _config: _EmptyStreamingWrapperModel(),
        )

        with self.assertRaisesRegex(QwenEngineError, "produced no audio"):
            engine.warmup()

    def test_warmup_synthesis_can_stop_after_bounded_chunks(self) -> None:
        fake_model = _StreamingWrapperModel(
            "custom_voice",
            supported_speakers=["Alice"],
        )
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-custom",
                warmup_synthesis_enabled=True,
                warmup_max_output_chunks=1,
                warmup_text="Prime.",
                warmup_speaker="Alice",
            ),
            model_loader=lambda _config: fake_model,
        )

        warmup_fields = engine.warmup()

        self.assertIsNotNone(warmup_fields)
        assert warmup_fields is not None
        self.assertEqual(1, warmup_fields["warmup_audio_chunks"])
        warmup_passes = cast(list[dict[str, object]], warmup_fields["warmup_passes"])
        self.assertTrue(warmup_passes[0]["bounded"])
        self.assertEqual(1, warmup_passes[0]["max_output_chunks"])

    def test_generation_prime_requires_natural_eos_and_keeps_metrics_internal(
        self,
    ) -> None:
        try:
            torch = importlib.import_module("torch")
        except ModuleNotFoundError:
            self.skipTest("torch is required for generation-prime coverage")
        if not torch.cuda.is_available():
            self.skipTest("CUDA is required for strict generation-prime coverage")

        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "talker_prefill_length": 16,
                                "text": "Prime.",
                                "language": "English",
                                "speaker": "Alice",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            fake_model = _PrimeStreamingModel("eos")
            engine = QwenTtsEngine(
                _generation_prime_config(manifest),
                model_loader=lambda _config: fake_model,
            )

            engine.load()
            fields = engine._run_prefill_generation_prime()

        self.assertTrue(fields["prefill_generation_prime_ready"])
        self.assertTrue(fields["prefill_generation_prime_internal_only"])
        self.assertTrue(fields["prefill_generation_prime_requires_natural_eos"])
        self.assertEqual(60.0, fields["prefill_generation_prime_safety_limit_seconds"])
        self.assertEqual(
            fields["prefill_generation_prime_rng_before"],
            fields["prefill_generation_prime_rng_after"],
        )
        self.assertEqual(1, len(fake_model.custom_stream_calls))
        self.assertIsNone(engine.pop_last_chunk_metrics())

    def test_generation_prime_rejects_non_eos_termination(self) -> None:
        try:
            torch = importlib.import_module("torch")
        except ModuleNotFoundError:
            self.skipTest("torch is required for generation-prime coverage")
        if not torch.cuda.is_available():
            self.skipTest("CUDA is required for strict generation-prime coverage")

        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "talker_prefill_length": 16,
                                "text": "Prime.",
                                "language": "English",
                                "speaker": "Alice",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            engine = QwenTtsEngine(
                _generation_prime_config(manifest),
                model_loader=lambda _config: _PrimeStreamingModel("max_new_tokens"),
            )
            engine.load()

            with self.assertRaisesRegex(QwenEngineError, "natural eos"):
                engine._run_prefill_generation_prime()

    def test_custom_voice_rejects_unsupported_speaker(self) -> None:
        engine = QwenTtsEngine(
            QwenEngineConfig(model_path="models/qwen-custom"),
            model_loader=lambda _config: _CustomVoiceModel(),
        )
        engine.load()

        with self.assertRaisesRegex(
            EngineRequestValidationError,
            "does not support speaker",
        ):
            engine.validate_request(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    speaker="Bob",
                )
            )

    def test_voice_design_uses_instruction_as_instruct(self) -> None:
        fake_model = _VoiceDesignModel()
        engine = QwenTtsEngine(
            QwenEngineConfig(model_path="models/qwen-voice-design"),
            model_loader=lambda _config: fake_model,
        )
        engine.load()

        chunks = list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    language="English",
                    instruction="Low calm voice.",
                ),
                threading.Event(),
            )
        )

        self.assertEqual([struct.pack("<hh", 8191, -8191)], chunks)
        self.assertEqual(
            {
                "text": "Hello",
                "language": "English",
                "instruct": "Low calm voice.",
            },
            fake_model.last_call,
        )

    def test_voice_design_uses_stream_generate_pcm(self) -> None:
        fake_model = _StreamingWrapperModel("voice_design")
        engine = QwenTtsEngine(
            QwenEngineConfig(model_path="models/qwen-voice-design"),
            model_loader=lambda _config: fake_model,
        )
        engine.load()

        chunks = list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    language="auto",
                    instruction="Low calm voice.",
                ),
                threading.Event(),
            )
        )

        self.assertEqual([struct.pack("<h", -16383), struct.pack("<h", 16383)], chunks)
        self.assertEqual(1, len(fake_model.model.stream_calls))
        stream_call = fake_model.model.stream_calls[0]
        self.assertEqual(["Auto"], stream_call["languages"])
        self.assertNotIn("speakers", stream_call)
        self.assertIsNotNone(stream_call["instruct_ids"])
        self.assertIn("assistant:Hello", fake_model.tokenized_texts)
        self.assertIn("instruct:Low calm voice.", fake_model.tokenized_texts)

    def test_faster_custom_voice_uses_fixed_chunk_streaming(self) -> None:
        fake_model = _FasterStreamingModel(
            "custom_voice",
            supported_speakers=["Alice"],
        )
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-custom",
                runtime_backend="faster",
                emit_every_frames=8,
                emit_chunk_schedule=(6, 8, 12),
                overlap_samples=240,
            ),
            model_loader=lambda _config: fake_model,
        )
        engine.load()

        chunks = list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    language="auto",
                    speaker="Alice",
                    instruction="Speak warmly.",
                ),
                threading.Event(),
            )
        )

        self.assertEqual([struct.pack("<h", 16383), struct.pack("<h", 16383)], chunks)
        self.assertEqual(1, len(fake_model.custom_stream_calls))
        custom_stream_call = dict(fake_model.custom_stream_calls[0])
        cancel_check = custom_stream_call.pop("cancel_check")
        self.assertTrue(callable(cancel_check))
        self.assertFalse(cancel_check())
        self.assertEqual(
            {
                "text": "Hello",
                "language": "Auto",
                "speaker": "Alice",
                "instruct": "Speak warmly.",
                "chunk_size": 8,
                "chunk_schedule": (6, 8, 12),
                "overlap_samples": 240,
                "do_sample": True,
                "prefill_backend": "eager",
                "prefill_compile_compat_mode": "none",
            },
            custom_stream_call,
        )
        self.assertEqual(1, fake_model.closed_streams)
        metrics = engine.pop_last_chunk_metrics()
        self.assertIsNotNone(metrics)
        assert metrics is not None
        self.assertEqual(12.0, metrics["prefill_ms"])
        self.assertEqual(3, metrics["profile_schema_version"])
        self.assertEqual("fast", metrics["profile_path"])
        self.assertEqual("first_user", metrics["profile_request_role"])
        self.assertTrue(metrics["profile_prefill_enabled"])
        self.assertTrue(metrics["profile_complete"])
        self.assertTrue(metrics["events_complete"])
        self.assertTrue(metrics["components_finite"])
        self.assertTrue(metrics["components_nonnegative"])
        self.assertTrue(metrics["all_component_streams_equal"])
        self.assertEqual(11.0, metrics["prefill_total_gpu_ms"])
        self.assertEqual(6.0, metrics["talker_forward_gpu_ms"])
        self.assertEqual(0.0, metrics["prefill_gpu_partition_error_ms"])
        self.assertEqual(0.0, metrics["prefill_gpu_accounting_error_ms"])
        self.assertEqual(1234, metrics["talker_forward_gpu_stream_id"])
        self.assertEqual(21, metrics["prefill_shape_length"])
        self.assertEqual("compiled_allowlist", metrics["prefill_shape_policy"])
        self.assertTrue(metrics["prefill_shape_allowlist_hit"])
        self.assertFalse(metrics["prefill_compile_on_miss"])
        self.assertEqual(80.0, metrics["ar_decode_ms"])
        self.assertEqual(8, metrics["chunk_steps"])
        self.assertEqual(8, metrics["chunk_target_steps"])
        self.assertEqual(1, metrics["chunk_schedule_index"])
        self.assertEqual(10.0, metrics["ar_ms_per_step"])
        self.assertIn("codec_wrapper_residual_ms", metrics)

    def test_faster_generation_trace_is_captured_after_completed_stream(self) -> None:
        fake_model = _FasterStreamingModel(
            "custom_voice",
            supported_speakers=["Alice"],
        )
        fake_model.last_generation_trace = {
            "codec_sha256": "a" * 64,
            "codec_frame_count": 2,
            "termination_reason": "eos",
            "terminal_token_id": 9,
            "terminal_step_index": 2,
            "generated_steps": 2,
            "emitted_steps": 2,
            "hit_eos": True,
            "hit_max_new_tokens": False,
            "hit_max_seq_len": False,
        }
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-custom",
                runtime_backend="faster",
                collect_generation_trace=True,
            ),
            model_loader=lambda _config: fake_model,
        )
        engine.load()

        list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    language="auto",
                    speaker="Alice",
                ),
                threading.Event(),
            )
        )

        self.assertTrue(fake_model.collect_generation_trace)
        self.assertEqual(
            fake_model.last_generation_trace,
            engine.pop_last_generation_trace(),
        )
        self.assertIsNone(engine.pop_last_generation_trace())

    def test_faster_stream_preserves_timing_input_metadata(self) -> None:
        fake_model = _FasterStreamingModel(
            "custom_voice",
            supported_speakers=["Alice"],
        )
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-custom",
                runtime_backend="faster",
            ),
            model_loader=lambda _config: fake_model,
        )
        engine.load()

        list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    speaker="Alice",
                ),
                threading.Event(),
            )
        )

        metrics = engine.pop_last_chunk_metrics()
        self.assertIsNotNone(metrics)
        assert metrics is not None
        self.assertEqual(12.0, metrics["prefill_ms"])

    def test_faster_stream_forwards_prefill_profile_flag(self) -> None:
        fake_model = _FasterStreamingModel(
            "custom_voice",
            supported_speakers=["Alice"],
            prefill_compile_compat_mode="strict_bf16_sdpa_v1",
        )
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-custom",
                runtime_backend="faster",
                dtype="bfloat16",
                attn_implementation="sdpa",
                profile_prefill=True,
                profile_nvtx=True,
                prefill_backend="compile_reduce_overhead",
                prefill_compile_compat_mode="strict_bf16_sdpa_v1",
                warmup_synthesis_enabled=True,
                do_sample=False,
            ),
            model_loader=lambda _config: fake_model,
        )
        engine.load()

        list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    speaker="Alice",
                ),
                threading.Event(),
            )
        )

        self.assertTrue(fake_model.custom_stream_calls[0]["profile_prefill"])
        self.assertTrue(fake_model.custom_stream_calls[0]["profile_nvtx"])
        self.assertEqual(
            "first_user",
            fake_model.custom_stream_calls[0]["profile_request_role"],
        )
        self.assertEqual(
            "compile_reduce_overhead",
            fake_model.custom_stream_calls[0]["prefill_backend"],
        )
        self.assertEqual(
            "strict_bf16_sdpa_v1",
            fake_model.custom_stream_calls[0]["prefill_compile_compat_mode"],
        )
        self.assertFalse(fake_model.custom_stream_calls[0]["do_sample"])

    def test_faster_stream_keeps_prefill_shape_policy_on_loaded_model(self) -> None:
        fake_model = _FasterStreamingModel(
            "custom_voice",
            supported_speakers=["Alice"],
            prefill_compile_compat_mode="strict_bf16_sdpa_v1",
        )
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-custom",
                runtime_backend="faster",
                dtype="bfloat16",
                attn_implementation="sdpa",
                prefill_backend="compile_reduce_overhead",
                prefill_compile_compat_mode="strict_bf16_sdpa_v1",
                prefill_compile_lengths=(16, 21),
                prefill_compile_on_miss=False,
                prefill_unknown_shape_policy="eager",
                warmup_synthesis_enabled=True,
            ),
            model_loader=lambda _config: fake_model,
        )
        engine.load()

        list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    speaker="Alice",
                ),
                threading.Event(),
            )
        )

        self.assertNotIn("prefill_compile_lengths", fake_model.custom_stream_calls[0])
        self.assertNotIn("prefill_compile_on_miss", fake_model.custom_stream_calls[0])
        self.assertNotIn(
            "prefill_unknown_shape_policy",
            fake_model.custom_stream_calls[0],
        )

    def test_strict_prefill_compat_rejects_unvalidated_voice_design_model(self) -> None:
        fake_model = _FasterStreamingModel(
            "voice_design",
            prefill_compile_compat_mode="strict_bf16_sdpa_v1",
        )
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-design",
                runtime_backend="faster",
                dtype="bfloat16",
                attn_implementation="sdpa",
                prefill_backend="compile_reduce_overhead",
                prefill_compile_compat_mode="strict_bf16_sdpa_v1",
                warmup_synthesis_enabled=True,
            ),
            model_loader=lambda _config: fake_model,
        )

        with self.assertRaisesRegex(QwenEngineError, "CustomVoice"):
            engine.load()

    def test_strict_prefill_compat_rejects_loaded_runtime_mismatch(self) -> None:
        cases = (
            {
                "fake": {"prefill_compile_compat_mode": "none"},
                "match": "did not apply",
            },
            {
                "fake": {"dtype": "float16"},
                "match": "dtype=bfloat16",
            },
            {
                "fake": {"attn_implementation": "eager"},
                "match": "attention=sdpa",
            },
            {
                "fake": {
                    "prefill_compile_compat_metadata": {
                        "prefill_compile_compat_metadata_version": 1,
                        "prefill_compile_compat_wrapper_mode": ("strict_bf16_sdpa_v1"),
                        "prefill_compile_compat_declared_mode": ("strict_bf16_sdpa_v1"),
                        "prefill_compile_compat_mode": "strict_bf16_sdpa_v1",
                        "prefill_compile_compat_applied": True,
                        "prefill_compile_compat_reused": False,
                        "prefill_compile_compat_patched_modules": {
                            "attention": 1,
                            "mlp": 1,
                            "rmsnorm": 4,
                        },
                        "prefill_compile_compat_validated_modules": {
                            "attention": 1,
                            "mlp": 1,
                            "rmsnorm": 4,
                        },
                        "prefill_compile_compat_target_fingerprint": {
                            "schema_version": 1,
                            "attention": 1,
                            "expected_decoder_layers": 1,
                            "mlp": 1,
                            "rmsnorm": 4,
                        },
                    }
                },
                "match": "idle",
            },
            {
                "fake": {
                    "prefill_compile_compat_metadata": {
                        "prefill_compile_compat_metadata_version": 1,
                        "prefill_compile_compat_wrapper_mode": ("strict_bf16_sdpa_v1"),
                        "prefill_compile_compat_declared_mode": ("strict_bf16_sdpa_v1"),
                        "prefill_compile_compat_mode": "strict_bf16_sdpa_v1",
                        "prefill_compile_compat_applied": False,
                        "prefill_compile_compat_reused": False,
                        "prefill_compile_compat_patched_modules": {},
                        "prefill_compile_compat_validated_modules": {
                            "attention": 1,
                            "mlp": 1,
                            "rmsnorm": 1,
                        },
                        "prefill_compile_compat_target_fingerprint": {
                            "schema_version": 1,
                            "attention": 1,
                            "expected_decoder_layers": 1,
                            "mlp": 1,
                            "rmsnorm": 1,
                        },
                    }
                },
                "match": "RMSNorm",
            },
        )
        for case in cases:
            fake_kwargs = {
                "prefill_compile_compat_mode": "strict_bf16_sdpa_v1",
                **case["fake"],
            }
            fake_model = _FasterStreamingModel(
                "custom_voice",
                supported_speakers=["Alice"],
                **fake_kwargs,
            )
            engine = QwenTtsEngine(
                QwenEngineConfig(
                    model_path="models/qwen-custom",
                    runtime_backend="faster",
                    dtype="bfloat16",
                    attn_implementation="sdpa",
                    prefill_backend="compile_reduce_overhead",
                    prefill_compile_compat_mode="strict_bf16_sdpa_v1",
                    warmup_synthesis_enabled=True,
                ),
                model_loader=lambda _config, fake_model=fake_model: fake_model,
            )
            with self.subTest(case=case):
                with self.assertRaisesRegex(QwenEngineError, str(case["match"])):
                    engine.load()

    def test_faster_voice_design_uses_fixed_chunk_streaming(self) -> None:
        fake_model = _FasterStreamingModel("voice_design")
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-design",
                runtime_backend="faster",
                emit_every_frames=12,
                emit_chunk_schedule=(6, 8, 12),
            ),
            model_loader=lambda _config: fake_model,
        )
        engine.load()

        list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    language="English",
                    instruction="Low calm voice.",
                ),
                threading.Event(),
            )
        )

        design_stream_call = dict(fake_model.design_stream_calls[0])
        cancel_check = design_stream_call.pop("cancel_check")
        self.assertTrue(callable(cancel_check))
        self.assertFalse(cancel_check())
        self.assertEqual(
            {
                "text": "Hello",
                "language": "English",
                "instruct": "Low calm voice.",
                "chunk_size": 12,
                "chunk_schedule": (6, 8, 12),
                "do_sample": True,
                "prefill_backend": "eager",
                "prefill_compile_compat_mode": "none",
            },
            design_stream_call,
        )

    def test_faster_stream_is_closed_on_cancel(self) -> None:
        fake_model = _FasterStreamingModel(
            "custom_voice",
            supported_speakers=["Alice"],
        )
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-custom",
                runtime_backend="faster",
            ),
            model_loader=lambda _config: fake_model,
        )
        engine.load()
        cancel_event = threading.Event()

        stream = engine.synthesize_stream(
            SynthesisRequest(
                request_id=1,
                text="Hello",
                speaker="Alice",
            ),
            cancel_event,
        )
        iterator = iter(stream)
        next(iterator)
        cancel_event.set()

        with self.assertRaises(StopIteration):
            next(iterator)
        self.assertEqual(1, fake_model.closed_streams)
        cancel_check = fake_model.custom_stream_calls[0]["cancel_check"]
        self.assertTrue(callable(cancel_check))
        self.assertTrue(cancel_check())

    def test_voice_design_requires_instruction(self) -> None:
        engine = QwenTtsEngine(
            QwenEngineConfig(model_path="models/qwen-voice-design"),
            model_loader=lambda _config: _VoiceDesignModel(),
        )
        engine.load()

        with self.assertRaisesRegex(
            EngineRequestValidationError,
            "requires an instruction",
        ):
            engine.validate_request(SynthesisRequest(request_id=1, text="Hello"))

    def test_base_voice_clone_is_not_wired_yet(self) -> None:
        engine = QwenTtsEngine(
            QwenEngineConfig(model_path="models/qwen-base"),
            model_loader=lambda _config: _BaseModel(),
        )
        engine.load()

        with self.assertRaisesRegex(EngineRequestValidationError, "voice-clone"):
            engine.validate_request(
                SynthesisRequest(request_id=1, text="Hello"),
            )

    def test_unsupported_audio_format_is_rejected(self) -> None:
        engine = QwenTtsEngine(QwenEngineConfig(model_path="models/qwen"))

        with self.assertRaisesRegex(UnsupportedAudioFormatError, "s16le"):
            engine.validate_request(
                SynthesisRequest(
                    request_id=1,
                    text="Hello",
                    output=AudioFormat(sample_rate=48000),
                )
            )

    def test_preserved_rng_state_restores_python_numpy_and_torch_cpu(self) -> None:
        try:
            numpy = importlib.import_module("numpy")
            torch = importlib.import_module("torch")
        except ModuleNotFoundError:
            self.skipTest("NumPy and torch are required for RNG state coverage")
        random.seed(4242)
        numpy.random.seed(4242)
        torch.manual_seed(4242)
        expected_python = random.random()
        expected_numpy = numpy.random.random()
        expected_torch = torch.rand(4)
        random.seed(4242)
        numpy.random.seed(4242)
        torch.manual_seed(4242)

        with _preserved_rng_state(require_cuda=False):
            random.random()
            numpy.random.random()
            torch.rand(4)

        self.assertEqual(expected_python, random.random())
        self.assertEqual(expected_numpy, numpy.random.random())
        self.assertTrue(torch.equal(expected_torch, torch.rand(4)))

    def test_preserved_rng_state_restores_torch_cuda(self) -> None:
        try:
            torch = importlib.import_module("torch")
        except ModuleNotFoundError:
            self.skipTest("torch is required for CUDA RNG state coverage")
        if not torch.cuda.is_available():
            self.skipTest("CUDA is required to test CUDA RNG preservation")

        torch.manual_seed(4242)
        torch.cuda.manual_seed_all(4242)
        expected = torch.rand(4, device="cuda")
        torch.manual_seed(4242)
        torch.cuda.manual_seed_all(4242)

        with _preserved_rng_state():
            torch.rand(4, device="cuda")

        self.assertTrue(torch.equal(expected, torch.rand(4, device="cuda")))

    def test_partial_generation_reset_requires_contract(self) -> None:
        with self.assertRaisesRegex(
            QwenEngineError,
            "reset_after_partial_generation",
        ):
            _reset_after_partial_generation(SimpleNamespace())

    def test_partial_generation_reset_accepts_complete_contract(self) -> None:
        metadata = {
            "reset_api_version": 1,
            "talker_graph_reset": True,
            "predictor_graphs_reset": 2,
            "compiled_prefill_cache_preserved": True,
            "cuda_graphs_preserved": True,
            "generation_mask_cache_preserved": True,
        }
        model = SimpleNamespace(reset_after_partial_generation=lambda: metadata)

        self.assertEqual(metadata, _reset_after_partial_generation(model))


if __name__ == "__main__":
    unittest.main()
