import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from qwen_tts_bridge_worker.cli import build_engine_config, build_parser
from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine.qwen.ggml_backend import load_ggml_custom_voice_model
from qwen_tts_bridge_worker.engine.qwen_engine import QwenTtsEngine
from qwen_tts_bridge_worker.engine.types import SynthesisRequest


def _ggml_config(**overrides: object) -> QwenEngineConfig:
    values: dict[str, object] = {
        "model_path": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        "runtime_backend": "ggml",
        "ggml_cache_dir": "tmp/gguf",
        "ggml_python_path": "tmp/qwentts-python",
        "ggml_cuda_dll_dir": "C:/CUDA/bin/x64",
    }
    values.update(overrides)
    return QwenEngineConfig(**values)  # type: ignore[arg-type]


class _FakeGgmlModel:
    tts_model_type = "custom_voice"
    supports_custom_voice_instructions = False

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def stream_generate_custom_voice(self, **kwargs: object):
        self.calls.append(dict(kwargs))
        return iter([([0.25, -0.25], 24000)])

    def close(self) -> None:
        pass


class _FakeGgmlQwenTts:
    calls: list[tuple[str, dict[str, object]]] = []

    @classmethod
    def from_pretrained(cls, model_path: str, **kwargs: object) -> _FakeGgmlModel:
        cls.calls.append((model_path, dict(kwargs)))
        return _FakeGgmlModel()


class GgmlBackendTests(unittest.TestCase):
    def test_ggml_cli_constructs_local_native_config(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "qwen",
                "--model-path",
                "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
                "--runtime-backend",
                "ggml",
                "--ggml-cache-dir",
                "tmp/gguf",
                "--ggml-python-path",
                "tmp/qwentts-python",
                "--ggml-cuda-dll-dir",
                "C:/CUDA/bin/x64",
            ]
        )

        config = build_engine_config(args)

        self.assertIsInstance(config, QwenEngineConfig)
        assert isinstance(config, QwenEngineConfig)
        self.assertEqual("ggml", config.runtime_backend)
        self.assertEqual("BF16", config.ggml_quant)

    def test_ggml_requires_explicit_local_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "ggml_cache_dir"):
            QwenEngineConfig(
                model_path="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
                runtime_backend="ggml",
            )

    def test_ggml_rejects_faster_only_trace_control(self) -> None:
        with self.assertRaisesRegex(ValueError, "collect_generation_trace"):
            _ggml_config(collect_generation_trace=True)

    def test_ggml_rejects_nondefault_ignored_bridge_controls(self) -> None:
        for name, value in (
            ("emit_every_frames", 16),
            ("decode_window_frames", 48),
            ("overlap_samples", 8),
            ("use_cuda_graphs", False),
            ("prefill_backend", "compile_reduce_overhead"),
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, name):
                    _ggml_config(**{name: value})

    def test_ggml_loader_uses_local_gguf_and_defers_native_import(self) -> None:
        _FakeGgmlQwenTts.calls.clear()
        with (
            patch(
                "qwen_tts_bridge_worker.engine.qwen.ggml_backend._add_windows_dll_directory"
            ) as add_dll_directory,
            patch(
                "qwen_tts_bridge_worker.engine.qwen.ggml_backend._add_python_package_path"
            ) as add_python_path,
            patch(
                "qwen_tts_bridge_worker.engine.qwen.ggml_backend.importlib.import_module",
                return_value=SimpleNamespace(QwenTTS=_FakeGgmlQwenTts),
            ) as import_module,
        ):
            model = load_ggml_custom_voice_model(
                _ggml_config(ggml_library_path="C:/native/qwen.dll")
            )

        self.assertEqual("custom_voice", model.tts_model_type)
        add_dll_directory.assert_called_once_with("C:/CUDA/bin/x64")
        add_python_path.assert_called_once_with("tmp/qwentts-python")
        import_module.assert_called_once_with("qwentts_cpp")
        self.assertEqual(
            [
                (
                    "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
                    {
                        "quant": "BF16",
                        "cache_dir": "tmp/gguf",
                        "local_files_only": True,
                        "library_path": "C:/native/qwen.dll",
                    },
                )
            ],
            _FakeGgmlQwenTts.calls,
        )

    def test_ggml_stream_forwards_explicit_seed_without_torch_runtime(self) -> None:
        model = _FakeGgmlModel()
        engine = QwenTtsEngine(_ggml_config(), model_loader=lambda _config: model)
        engine.load()

        request = SynthesisRequest(
            request_id=7,
            text="native smoke",
            language="english",
            speaker="ryan",
            seed=42,
        )
        self.assertEqual(
            [b'\xff\x1f\x01\xe0'],
            list(engine.synthesize_stream(request, threading.Event())),
        )
        self.assertEqual(1, len(model.calls))
        self.assertEqual(42, model.calls[0]["seed"])
        self.assertEqual("ryan", model.calls[0]["speaker"])

    def test_ggml_rejects_auto_language(self) -> None:
        model = _FakeGgmlModel()
        engine = QwenTtsEngine(_ggml_config(), model_loader=lambda _config: model)
        engine.load()

        with self.assertRaisesRegex(ValueError, "explicit language"):
            engine.validate_request(
                SynthesisRequest(
                    request_id=1,
                    text="native smoke",
                    language="auto",
                    speaker="ryan",
                )
            )

    def test_ggml_forwards_explicit_non_english_language(self) -> None:
        model = _FakeGgmlModel()
        engine = QwenTtsEngine(_ggml_config(), model_loader=lambda _config: model)
        engine.load()

        list(
            engine.synthesize_stream(
                SynthesisRequest(
                    request_id=1,
                    text="Привет",
                    language="russian",
                    speaker="ryan",
                ),
                threading.Event(),
            )
        )

        self.assertEqual("russian", model.calls[0]["language"])

    def test_ggml_rejects_unvalidated_custom_voice_instruction(self) -> None:
        model = _FakeGgmlModel()
        engine = QwenTtsEngine(_ggml_config(), model_loader=lambda _config: model)
        engine.load()
        with self.assertRaisesRegex(ValueError, "style instructions"):
            engine.validate_request(
                SynthesisRequest(
                    request_id=1,
                    text="native smoke",
                    language="english",
                    speaker="ryan",
                    instruction="whisper",
                )
            )
