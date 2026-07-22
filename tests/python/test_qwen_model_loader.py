import unittest
from unittest.mock import patch

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine.qwen.model_loader import load_qwen_model


class _FakeConfig:
    pass


class _FakeProcessor:
    pass


class _FakeAutoConfig:
    def register(self, *_args: object) -> None:
        pass


class _FakeAutoModel:
    def __init__(self, model: object) -> None:
        self.model = model
        self.calls: list[tuple[str, dict[str, object]]] = []

    def register(self, *_args: object) -> None:
        pass

    def from_pretrained(self, model_path: str, **kwargs: object) -> object:
        self.calls.append((model_path, dict(kwargs)))
        return self.model


class _FakeAutoProcessor:
    def register(self, *_args: object) -> None:
        pass

    def from_pretrained(self, *_args: object, **_kwargs: object) -> object:
        return object()


class _FakeQwenWrapper:
    def __init__(self) -> None:
        self.optimization_calls: list[dict[str, object]] = []

    def enable_streaming_optimizations(self, **kwargs: object) -> "_FakeQwenWrapper":
        self.optimization_calls.append(dict(kwargs))
        return self


class _FakeQwenModelModule:
    def __init__(self, auto_model: _FakeAutoModel) -> None:
        self.AutoConfig = _FakeAutoConfig
        self.Qwen3TTSModel = _FakeWrapperClass(auto_model)


class _FakeWrapperClass:
    def __init__(self, auto_model: _FakeAutoModel) -> None:
        self.auto_model = auto_model

    def from_pretrained(self, model_path: str, **kwargs: object) -> object:
        return self.auto_model.from_pretrained(model_path, **kwargs)


class QwenModelLoaderTests(unittest.TestCase):
    def test_streaming_optimizations_are_optional(self) -> None:
        model = _FakeQwenWrapper()
        auto_model = _FakeAutoModel(model)

        with patch(
            "qwen_tts_bridge_worker.engine.qwen.model_loader.importlib.import_module",
            side_effect=_fake_import_module(auto_model),
        ):
            loaded = load_qwen_model(QwenEngineConfig(model_path="models/qwen"))

        self.assertIs(model, loaded)
        self.assertEqual([], model.optimization_calls)

    def test_streaming_optimizations_are_forwarded(self) -> None:
        model = _FakeQwenWrapper()
        auto_model = _FakeAutoModel(model)

        with patch(
            "qwen_tts_bridge_worker.engine.qwen.model_loader.importlib.import_module",
            side_effect=_fake_import_module(auto_model),
        ):
            loaded = load_qwen_model(
                QwenEngineConfig(
                    model_path="models/qwen",
                    enable_streaming_optimizations=True,
                    decode_window_frames=96,
                    use_compile=False,
                    use_cuda_graphs=False,
                    compile_mode="default",
                    compile_codebook_predictor=False,
                    compile_talker=False,
                )
            )

        self.assertIs(model, loaded)
        self.assertEqual(
            [
                {
                    "decode_window_frames": 96,
                    "use_compile": False,
                    "use_cuda_graphs": False,
                    "compile_mode": "default",
                    "compile_codebook_predictor": False,
                    "compile_talker": False,
                }
            ],
            model.optimization_calls,
        )


def _fake_import_module(auto_model: _FakeAutoModel):
    def import_module(name: str) -> object:
        if name == "qwen_tts.inference.qwen3_tts_model":
            return _FakeQwenModelModule(auto_model)
        if name == "transformers":
            return _FakeTransformers(auto_model)
        if name == "qwen_tts.core.models.processing_qwen3_tts":
            return _FakeProcessorModule()
        raise AssertionError(f"unexpected import: {name}")

    return import_module


class _FakeTransformers:
    def __init__(self, auto_model: _FakeAutoModel) -> None:
        self.AutoConfig = _FakeAutoConfig()
        self.AutoModel = auto_model
        self.AutoProcessor = _FakeAutoProcessor()


class _FakeProcessorModule:
    Qwen3TTSProcessor = _FakeProcessor


if __name__ == "__main__":
    unittest.main()
