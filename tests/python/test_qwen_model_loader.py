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


class _FakeFasterQwen:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def from_pretrained(self, model_path: str, **kwargs: object) -> object:
        self.calls.append((model_path, dict(kwargs)))
        return _FakeQwenWrapper()


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
                    use_fast_codebook=True,
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
                    "use_fast_codebook": True,
                    "compile_codebook_predictor": False,
                    "compile_talker": False,
                }
            ],
            model.optimization_calls,
        )

    def test_matmul_precision_is_configured_before_load(self) -> None:
        model = _FakeQwenWrapper()
        auto_model = _FakeAutoModel(model)
        fake_torch = _FakeTorchModule()

        def import_module(name: str) -> object:
            if name == "torch":
                return fake_torch
            return _fake_import_module(auto_model)(name)

        with patch(
            "qwen_tts_bridge_worker.engine.qwen.model_loader.importlib.import_module",
            side_effect=import_module,
        ):
            load_qwen_model(
                QwenEngineConfig(
                    model_path="models/qwen",
                    matmul_precision="high",
                )
            )

        self.assertEqual(["high"], fake_torch.matmul_precision_calls)

    def test_faster_backend_uses_faster_loader(self) -> None:
        fake_faster = _FakeFasterQwen()

        def import_module(name: str) -> object:
            if name == "faster_qwen3_tts":
                return _FakeFasterModule(fake_faster)
            raise AssertionError(f"unexpected import: {name}")

        with patch(
            "qwen_tts_bridge_worker.engine.qwen.model_loader.importlib.import_module",
            side_effect=import_module,
        ):
            load_qwen_model(
                QwenEngineConfig(
                    model_path="models/qwen",
                    runtime_backend="faster",
                    device="cuda:0",
                    dtype="auto",
                    attn_implementation="",
                    max_seq_len=1024,
                )
            )

        self.assertEqual(1, len(fake_faster.calls))
        self.assertEqual("models/qwen", fake_faster.calls[0][0])
        self.assertEqual(
            {
                "device": "cuda:0",
                "dtype": "bfloat16",
                "attn_implementation": "eager",
                "max_seq_len": 1024,
                "prefill_backend": "eager",
                "prefill_compile_compat_mode": "none",
                "prefill_compile_lengths": (),
                "prefill_compile_on_miss": True,
                "prefill_unknown_shape_policy": "eager",
                "prefill_require_precompiled": False,
            },
            fake_faster.calls[0][1],
        )

    def test_faster_backend_forwards_prefill_compile_compat_mode(self) -> None:
        fake_faster = _FakeFasterQwen()

        def import_module(name: str) -> object:
            if name == "faster_qwen3_tts":
                return _FakeFasterModule(fake_faster)
            raise AssertionError(f"unexpected import: {name}")

        with patch(
            "qwen_tts_bridge_worker.engine.qwen.model_loader.importlib.import_module",
            side_effect=import_module,
        ):
            load_qwen_model(
                QwenEngineConfig(
                    model_path="models/qwen",
                    runtime_backend="faster",
                    dtype="bfloat16",
                    attn_implementation="sdpa",
                    prefill_backend="compile_reduce_overhead",
                    prefill_compile_compat_mode="strict_bf16_sdpa_v1",
                    prefill_compile_lengths=(16, 21),
                    prefill_compile_on_miss=False,
                    prefill_unknown_shape_policy="eager",
                    warmup_synthesis_enabled=True,
                )
            )

        self.assertEqual(
            "compile_reduce_overhead",
            fake_faster.calls[0][1]["prefill_backend"],
        )
        self.assertEqual(
            "strict_bf16_sdpa_v1",
            fake_faster.calls[0][1]["prefill_compile_compat_mode"],
        )
        self.assertEqual(
            (16, 21),
            fake_faster.calls[0][1]["prefill_compile_lengths"],
        )
        self.assertFalse(fake_faster.calls[0][1]["prefill_compile_on_miss"])
        self.assertEqual(
            "eager",
            fake_faster.calls[0][1]["prefill_unknown_shape_policy"],
        )
        self.assertFalse(fake_faster.calls[0][1]["prefill_require_precompiled"])

    def test_exact_allowlist_load_defers_require_precompiled_until_warmup(
        self,
    ) -> None:
        fake_faster = _FakeFasterQwen()

        def import_module(name: str) -> object:
            if name == "faster_qwen3_tts":
                return _FakeFasterModule(fake_faster)
            raise AssertionError(f"unexpected import: {name}")

        with patch(
            "qwen_tts_bridge_worker.engine.qwen.model_loader.importlib.import_module",
            side_effect=import_module,
        ):
            load_qwen_model(
                QwenEngineConfig(
                    model_path="models/qwen",
                    runtime_backend="faster",
                    dtype="bfloat16",
                    attn_implementation="sdpa",
                    prefill_backend="compile_reduce_overhead",
                    prefill_compile_compat_mode="strict_bf16_sdpa_v1",
                    prefill_compile_lengths=(16,),
                    prefill_compile_on_miss=False,
                    prefill_unknown_shape_policy="eager",
                    prefill_compile_policy="exact_allowlist",
                    prefill_allowlist_warmup_manifest="manifest.json",
                    prefill_require_precompiled=True,
                )
            )

        self.assertFalse(fake_faster.calls[0][1]["prefill_require_precompiled"])


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


class _FakeFasterModule:
    def __init__(self, faster_qwen: _FakeFasterQwen) -> None:
        self.FasterQwen3TTS = faster_qwen


class _FakeTorchModule:
    def __init__(self) -> None:
        self.matmul_precision_calls: list[str] = []

    def set_float32_matmul_precision(self, value: str) -> None:
        self.matmul_precision_calls.append(value)


if __name__ == "__main__":
    unittest.main()
