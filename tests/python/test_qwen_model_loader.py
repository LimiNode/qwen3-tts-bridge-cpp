import unittest
from types import SimpleNamespace
from unittest.mock import patch

from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine.qwen.model_loader import (
    QwenModelLoadError,
    _configure_code_predictor_compute_dtype,
    load_qwen_model,
)


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
    def test_model_code_predictor_dtype_does_not_require_predictor_layout(self) -> None:
        _configure_code_predictor_compute_dtype(
            object(),
            QwenEngineConfig(model_path="models/qwen"),
        )

    def test_float32_code_predictor_mutates_predictor_and_restores_embeddings(
        self,
    ) -> None:
        fake_torch = type("Torch", (), {"float32": "float32"})()
        predictor = _FakePredictor(("float16", "bfloat16"), layer_count=2)

        with patch(
            "qwen_tts_bridge_worker.engine.qwen.model_loader.importlib.import_module",
            return_value=fake_torch,
        ):
            _configure_code_predictor_compute_dtype(
                _model_with_predictor(predictor),
                QwenEngineConfig(
                    model_path="models/qwen",
                    code_predictor_compute_dtype="float32",
                ),
            )

        self.assertEqual(1, predictor.float_calls)
        self.assertEqual("float32", predictor.__dict__["_bridge_compute_dtype"])
        self.assertEqual(
            [["float16"], ["bfloat16"]],
            [embedding.to_dtypes for embedding in predictor.model.codec_embedding],
        )
        self.assertEqual(
            [0, 0],
            [layer.mlp.down_proj.float_calls for layer in predictor.model.layers],
        )

    def test_mlp_float32_code_predictor_mutates_only_down_projections(self) -> None:
        fake_torch = type("Torch", (), {"float32": "float32"})()
        predictor = _FakePredictor(("float16",), layer_count=3)

        with patch(
            "qwen_tts_bridge_worker.engine.qwen.model_loader.importlib.import_module",
            return_value=fake_torch,
        ):
            _configure_code_predictor_compute_dtype(
                _model_with_predictor(predictor),
                QwenEngineConfig(
                    model_path="models/qwen",
                    code_predictor_compute_dtype="mlp_float32",
                ),
            )

        self.assertEqual(0, predictor.float_calls)
        self.assertFalse(hasattr(predictor, "_bridge_compute_dtype"))
        self.assertEqual(
            [1, 1, 1],
            [layer.mlp.down_proj.float_calls for layer in predictor.model.layers],
        )
        self.assertEqual(
            ["float32", "float32", "float32"],
            [
                layer.mlp.__dict__["_bridge_compute_dtype"]
                for layer in predictor.model.layers
            ],
        )

    def test_float32_code_predictor_rejects_malformed_layout(self) -> None:
        fake_torch = type("Torch", (), {"float32": "float32"})()

        with (
            patch(
                "qwen_tts_bridge_worker.engine.qwen.model_loader.importlib.import_module",
                return_value=fake_torch,
            ),
            self.assertRaises(QwenModelLoadError),
        ):
            _configure_code_predictor_compute_dtype(
                object(),
                QwenEngineConfig(
                    model_path="models/qwen",
                    code_predictor_compute_dtype="float32",
                ),
            )

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


class _FakeParameter:
    def __init__(self, dtype: object) -> None:
        self.dtype = dtype


class _FakeEmbedding:
    def __init__(self, dtype: object) -> None:
        self.parameter = _FakeParameter(dtype)
        self.to_dtypes: list[object] = []

    def parameters(self):
        yield self.parameter

    def to(self, *, dtype: object) -> "_FakeEmbedding":
        self.to_dtypes.append(dtype)
        self.parameter.dtype = dtype
        return self


class _FakeProjection:
    def __init__(self) -> None:
        self.float_calls = 0

    def float(self) -> "_FakeProjection":
        self.float_calls += 1
        return self


class _FakeMlp:
    def __init__(self) -> None:
        self.down_proj = _FakeProjection()


class _FakeLayer:
    def __init__(self) -> None:
        self.mlp = _FakeMlp()


class _FakePredictorModel:
    def __init__(self, embedding_dtypes: tuple[object, ...], layer_count: int) -> None:
        self.codec_embedding = [
            _FakeEmbedding(dtype) for dtype in embedding_dtypes
        ]
        self.layers = [_FakeLayer() for _ in range(layer_count)]


class _FakePredictor:
    def __init__(self, embedding_dtypes: tuple[object, ...], layer_count: int) -> None:
        self.float_calls = 0
        self.model = _FakePredictorModel(embedding_dtypes, layer_count)

    def float(self) -> "_FakePredictor":
        self.float_calls += 1
        return self


def _model_with_predictor(predictor: object) -> object:
    return SimpleNamespace(
        model=SimpleNamespace(
            talker=SimpleNamespace(code_predictor=predictor),
        )
    )


if __name__ == "__main__":
    unittest.main()
