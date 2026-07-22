import struct
import threading
import unittest
from typing import Any, cast

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine import (
    AudioFormat,
    EngineRequestValidationError,
    QwenEngineError,
    QwenTtsEngine,
    SynthesisRequest,
    UnsupportedAudioFormatError,
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
    ) -> None:
        self.model = _NestedWrapper(model_type)
        self._supported_speakers = supported_speakers
        self.custom_stream_calls: list[dict[str, object]] = []
        self.design_stream_calls: list[dict[str, object]] = []
        self.closed_streams = 0

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
                return [0.5], 24000, {"chunk_steps": 8}

            def close(self) -> None:
                model.closed_streams += 1

        return _Stream()


class _NestedWrapper:
    def __init__(self, model_type: str) -> None:
        self.model = _InnerModel(model_type)


class QwenEngineTests(unittest.TestCase):
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
        self.assertEqual(
            {
                "text": "Hello",
                "language": "Auto",
                "speaker": "Alice",
                "instruct": "Speak warmly.",
                "chunk_size": 8,
            },
            fake_model.custom_stream_calls[0],
        )
        self.assertEqual(1, fake_model.closed_streams)

    def test_faster_voice_design_uses_fixed_chunk_streaming(self) -> None:
        fake_model = _FasterStreamingModel("voice_design")
        engine = QwenTtsEngine(
            QwenEngineConfig(
                model_path="models/qwen-design",
                runtime_backend="faster",
                emit_every_frames=12,
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

        self.assertEqual(
            {
                "text": "Hello",
                "language": "English",
                "instruct": "Low calm voice.",
                "chunk_size": 12,
            },
            fake_model.design_stream_calls[0],
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


if __name__ == "__main__":
    unittest.main()
