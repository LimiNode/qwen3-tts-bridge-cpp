import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_WORKER_SCRIPT = _REPO_ROOT / "scripts" / "package-worker.ps1"
_PACKAGE_PYTHON_WORKER_SCRIPT = _REPO_ROOT / "scripts" / "package-python-worker.ps1"
_TEST_PORTABLE_PYTHON_WORKER_SCRIPT = (
    _REPO_ROOT / "scripts" / "test-portable-python-worker.ps1"
)
_PYTHON_CHECKS_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "python-checks.yml"
_NARROW_AUDIO_PROFILE = (
    _REPO_ROOT / "worker" / "packaging" / "nuitka-qwen-narrow-audio.yml"
)
_RUNTIME_PROFILE = _REPO_ROOT / "worker" / "packaging" / "nuitka-qwen-runtime.yml"


class QwenPackagingProfileTests(unittest.TestCase):
    def test_qwen_profile_keeps_internal_torch_functorch_available(self) -> None:
        script = _PACKAGE_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("--nofollow-import-to=torch._functorch", script)
        self.assertNotIn("--nofollow-import-to=functorch", script)

    def test_qwen_profile_keeps_torch_testing_internal_available(self) -> None:
        script = _PACKAGE_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("--nofollow-import-to=torch.testing._internal", script)

    def test_qwen_profile_allows_optional_excluded_module_probes(self) -> None:
        script = _PACKAGE_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("--no-deployment-flag=excluded-module-usage", script)

    def test_qwen_profile_includes_torch_distribution_metadata(self) -> None:
        script = _PACKAGE_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("--include-distribution-metadata=torch", script)

    def test_qwen_profile_includes_generation_runtime(self) -> None:
        script = _PACKAGE_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("--include-package=transformers.generation", script)

    def test_qwen_profile_includes_transformers_distributed_config(self) -> None:
        script = _PACKAGE_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("--include-package=transformers.distributed", script)

    def test_qwen_profile_includes_peft_adapter_mixin_runtime(self) -> None:
        script = _PACKAGE_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("--include-module=transformers.integrations.peft", script)

    def test_qwen_profile_includes_encodec_feature_extractor_runtime(self) -> None:
        script = _PACKAGE_WORKER_SCRIPT.read_text(encoding="utf-8")
        profile = _RUNTIME_PROFILE.read_text(encoding="utf-8")

        self.assertIn("--include-module=transformers.models.encodec", script)
        self.assertIn(
            "--include-module=transformers.models.encodec.feature_extraction_encodec",
            script,
        )
        self.assertNotIn("--include-package=transformers.models.encodec", script)
        self.assertIn("EncodecFeatureExtractor", profile)

    def test_qwen_runtime_profile_stubs_flex_attention(self) -> None:
        profile = _RUNTIME_PROFILE.read_text(encoding="utf-8")

        self.assertIn("torch._dynamo.allow_in_graph removed", profile)
        self.assertIn(
            "flex_attention is not packaged by the Qwen eager inference profile",
            profile,
        )

    def test_qwen_runtime_profile_stubs_tensor_parallel(self) -> None:
        profile = _RUNTIME_PROFILE.read_text(encoding="utf-8")

        self.assertIn("_is_dtensor_available = False", profile)
        self.assertIn(
            "tensor parallel is not packaged by the Qwen eager inference profile",
            profile,
        )

    def test_qwen_runtime_profile_stubs_quantizer_zoo(self) -> None:
        profile = _RUNTIME_PROFILE.read_text(encoding="utf-8")

        self.assertIn(
            "quantized model loading is not packaged by the "
            "Qwen eager inference profile",
            profile,
        )

    def test_qwen_runtime_profile_stubs_encoder_decoder_auto_tokenizer(self) -> None:
        profile = _RUNTIME_PROFILE.read_text(encoding="utf-8")

        self.assertIn("transformers.models.auto.tokenization_auto", profile)
        self.assertIn("class EncoderDecoderConfig", profile)

    def test_qwen_runtime_profile_uses_direct_auto_model_import(self) -> None:
        profile = _RUNTIME_PROFILE.read_text(encoding="utf-8")

        self.assertIn("transformers.modeling_layers", profile)
        self.assertIn("from .models.auto.modeling_auto import AutoModel", profile)

    def test_narrow_audio_profile_keeps_reference_audio_modules_out(self) -> None:
        profile = _NARROW_AUDIO_PROFILE.read_text(encoding="utf-8")

        self.assertIn("'librosa': 'not needed by CustomVoice", profile)
        self.assertIn("librosa is packaged only by -QwenProfile VoiceClone", profile)

    def test_qwen_profile_uses_explicit_transformers_runtime_shape(self) -> None:
        script = _PACKAGE_WORKER_SCRIPT.read_text(encoding="utf-8")
        profile = _NARROW_AUDIO_PROFILE.read_text(encoding="utf-8")

        self.assertIn("--disable-plugins=transformers", script)
        self.assertIn('Join-Path $WorkerOutput "transformers/models"', script)
        self.assertIn('Join-Path $TransformersModels "__init__.py"', script)
        self.assertIn('@("auto", "mimi")', script)
        self.assertIn("qtb_packaging_placeholder.py", script)
        self.assertIn("from .modeling_auto import AutoModel", script)
        self.assertIn('"AutoProcessor"', script)
        self.assertIn("models.auto.configuration_auto", profile)
        self.assertIn("models.auto.modeling_auto", profile)
        self.assertIn("models.auto.processing_auto", profile)
        self.assertIn("models.auto.feature_extraction_auto", profile)


class PortablePythonWorkerPackagingTests(unittest.TestCase):
    def test_portable_worker_script_uses_separate_packaging_environment(self) -> None:
        script = _PACKAGE_PYTHON_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('$VenvPath = ".venv-packaging"', script)
        self.assertIn('$WorkerDirectoryName = "worker-python"', script)
        self.assertIn('"Scripts/python.exe"', script)

    def test_portable_worker_script_copies_real_project_packages(self) -> None:
        script = _PACKAGE_PYTHON_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("worker/src/qwen_tts_bridge_worker", script)
        self.assertIn("external/python/Qwen3-TTS-streaming", script)
        self.assertIn('$IncludeQwenFork', script)
        self.assertIn('"qwen_tts"', script)
        self.assertIn("Remove-EditableInstallArtifacts", script)
        self.assertIn('__editable__*', script)

    def test_portable_worker_script_writes_cmd_launcher(self) -> None:
        script = _PACKAGE_PYTHON_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("qwen_tts_worker.cmd", script)
        self.assertIn("PYTHONHOME", script)
        self.assertIn("PYTHONPATH", script)
        self.assertIn("-m qwen_tts_bridge_worker", script)

    def test_portable_worker_smoke_wrapper_uses_protocol_verifier(self) -> None:
        script = _TEST_PORTABLE_PYTHON_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("verify_packaged_worker.py", script)
        self.assertIn("worker-python/qwen_tts_worker.cmd", script)

    def test_python_ci_validates_portable_worker_dry_run(self) -> None:
        workflow = _PYTHON_CHECKS_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("scripts/package-python-worker.ps1", workflow)
        self.assertIn("scripts/test-portable-python-worker.ps1", workflow)
        self.assertIn(
            ".\\scripts\\package-python-worker.ps1 -Python python -DryRun",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
