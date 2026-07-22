import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_WORKER_SCRIPT = _REPO_ROOT / "scripts" / "package-worker.ps1"
_PACKAGE_PYTHON_WORKER_SCRIPT = _REPO_ROOT / "scripts" / "package-python-worker.ps1"
_INSPECT_PORTABLE_WORKER_SCRIPT = (
    _REPO_ROOT / "scripts" / "inspect-portable-python-worker.ps1"
)
_PACKAGING_REQUIREMENTS = _REPO_ROOT / "worker" / "requirements-packaging.lock.txt"
_TEST_PORTABLE_PYTHON_WORKER_SCRIPT = (
    _REPO_ROOT / "scripts" / "test-portable-python-worker.ps1"
)
_TEST_PORTABLE_PYTHON_WORKER_CPP_SCRIPT = (
    _REPO_ROOT / "scripts" / "test-portable-python-worker-cpp.ps1"
)
_README = _REPO_ROOT / "README.md"
_PYTHON_CHECKS_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "python-checks.yml"
_CPP_CHECKS_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "cpp-checks.yml"
_PORTABLE_QWEN_IMPORT_WORKFLOW = (
    _REPO_ROOT / ".github" / "workflows" / "portable-qwen-import-probe.yml"
)
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

    def test_portable_worker_script_rejects_unsafe_worker_output_paths(self) -> None:
        script = _PACKAGE_PYTHON_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("Assert-RelativeDirectoryName", script)
        self.assertIn("Assert-StrictChildPath", script)
        self.assertIn("Assert-PortableWorkerMarker", script)
        self.assertIn("Assert-NotUnderPath", script)
        self.assertIn(".qtb-portable-worker-root", script)
        self.assertIn("Refusing to modify existing portable worker output", script)
        self.assertIn("must not be inside source tree", script)
        self.assertIn("must be a strict child", script)
        self.assertIn("must not be '.' or '..'", script)
        self.assertIn("without path separators", script)

    def test_portable_worker_script_installs_real_project_packages(self) -> None:
        script = _PACKAGE_PYTHON_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("worker/src/qwen_tts_bridge_worker", script)
        self.assertIn("external/python/Qwen3-TTS-streaming", script)
        self.assertIn('$IncludeQwenFork', script)
        self.assertIn('"qwen_tts"', script)
        self.assertIn("external/python/faster-qwen3-tts", script)
        self.assertIn('$IncludeFasterQwen', script)
        self.assertIn('"faster_qwen3_tts"', script)
        self.assertIn("Remove-EditableInstallArtifacts", script)
        self.assertIn('__editable__*', script)
        self.assertIn("Remove-StagedPackageArtifacts", script)
        self.assertIn("Install-ProjectWheelToTarget", script)
        self.assertIn("Write-BuildManifest", script)
        self.assertIn("build-manifest.json", script)
        self.assertIn("wheel_sha256", script)
        self.assertIn("wheel_artifact", script)
        self.assertIn('$WheelArtifactRoot = Join-Path $WorkerOutput "wheels"', script)
        self.assertIn("git_commit", script)
        self.assertIn("git_dirty", script)
        self.assertIn("Assert-CleanSources", script)
        self.assertIn("$AllowDirtySources", script)
        self.assertIn("Refusing to package dirty source trees", script)
        self.assertIn("Get-PythonToolVersions", script)
        self.assertIn("Get-PipFreeze", script)
        self.assertIn("torch_cuda", script)
        self.assertIn("pip_freeze", script)
        self.assertNotIn("executable = [string]$PythonEnvironment.executable", script)
        self.assertIn("--no-build-isolation", script)
        self.assertIn("--find-links", script)
        self.assertIn("Remove-PythonBytecode", script)
        self.assertIn("Remove-PythonBytecode -Root $PythonOutput", script)
        self.assertIn("Remove-StagedScriptDirectory", script)
        self.assertIn("PYTHONDONTWRITEBYTECODE", script)
        self.assertIn("QTB_PROBE_QWEN_IMPORT", script)
        self.assertIn("qwen_tts.inference.qwen3_tts_model", script)
        self.assertIn("QTB_PROBE_FASTER_QWEN_IMPORT", script)
        self.assertIn("import faster_qwen3_tts", script)
        self.assertIn("-ProbeQwenImport:($null -ne $QwenPackageSource)", script)
        self.assertIn(
            "-ProbeFasterQwenImport:($null -ne $FasterQwenPackageSource)",
            script,
        )

    def test_packaging_requirements_include_wheel_build_tools(self) -> None:
        requirements = _PACKAGING_REQUIREMENTS.read_text(encoding="utf-8")

        self.assertIn("setuptools==", requirements)
        self.assertIn("wheel==", requirements)

    def test_portable_worker_script_rejects_path_leaking_artifacts(self) -> None:
        script = _PACKAGE_PYTHON_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("*.egg-link", script)
        self.assertIn("distutils-precedence.pth", script)
        self.assertIn("Assert-PortableSitePaths", script)
        self.assertIn("executable .pth entries", script)
        self.assertIn("QTB_FORBIDDEN_SYS_PATH_ROOTS", script)
        self.assertIn("portable worker sys.path leaks source paths", script)

    def test_portable_worker_script_writes_cmd_launcher(self) -> None:
        script = _PACKAGE_PYTHON_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("qwen_tts_worker.cmd", script)
        self.assertIn("PYTHONHOME", script)
        self.assertIn("PYTHONPATH", script)
        self.assertIn("PYTHONNOUSERSITE", script)
        self.assertIn("PYTHONDONTWRITEBYTECODE", script)
        self.assertIn("-B -P -s -m qwen_tts_bridge_worker", script)
        self.assertIn("-m qwen_tts_bridge_worker", script)

    def test_portable_worker_smoke_wrapper_uses_protocol_verifier(self) -> None:
        script = _TEST_PORTABLE_PYTHON_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("verify_packaged_worker.py", script)
        self.assertIn("worker-python/qwen_tts_worker.cmd", script)
        self.assertIn("$PreviousPythonPath", script)
        self.assertIn("finally", script)

    def test_portable_worker_cpp_smoke_uses_direct_python_executable(self) -> None:
        script = _TEST_PORTABLE_PYTHON_WORKER_CPP_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("qwen_tts_save_wav.exe", script)
        self.assertIn("python/python.exe", script)
        self.assertIn("$env:PYTHONHOME", script)
        self.assertIn("$env:PYTHONPATH", script)
        self.assertIn("$env:PYTHONNOUSERSITE", script)
        self.assertIn("$env:PYTHONDONTWRITEBYTECODE", script)
        self.assertIn('"--worker-arg",', script)
        self.assertIn('"-B"', script)
        self.assertIn('"-P"', script)
        self.assertIn('"-s"', script)
        self.assertIn('"qwen_tts_bridge_worker"', script)
        self.assertIn("verify_wav.py", script)

    def test_python_ci_validates_portable_worker_dry_run(self) -> None:
        workflow = _PYTHON_CHECKS_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("scripts/inspect-portable-python-worker.ps1", workflow)
        self.assertIn("scripts/package-python-worker.ps1", workflow)
        self.assertIn("portable-qwen-import-probe.yml", workflow)
        self.assertIn("scripts/test-portable-python-worker.ps1", workflow)
        self.assertIn(
            ".\\scripts\\package-python-worker.ps1 -Python python -DryRun",
            workflow,
        )

    def test_manual_ci_validates_portable_qwen_import(self) -> None:
        workflow = _PORTABLE_QWEN_IMPORT_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch", workflow)
        self.assertIn("submodules: true", workflow)
        self.assertIn("-InstallQwenFork", workflow)
        self.assertIn("-IncludeQwenFork", workflow)
        self.assertIn("inspect-portable-python-worker.ps1", workflow)
        self.assertIn("-ProbeQwenImport", workflow)
        self.assertIn("package-python-worker.ps1", workflow)
        self.assertNotIn("pull_request", workflow)

    def test_portable_worker_inspector_reports_qwen_import(self) -> None:
        script = _INSPECT_PORTABLE_WORKER_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("PYTHONHOME", script)
        self.assertIn("PYTHONPATH", script)
        self.assertIn("PYTHONNOUSERSITE", script)
        self.assertIn("qwen_tts_bridge_worker", script)
        self.assertIn("qwen_tts.inference.qwen3_tts_model", script)
        self.assertIn("external/python/Qwen3-TTS-streaming", script)
        self.assertNotIn("external/python/Qwen3-TTS-streaming/qwen_tts", script)
        self.assertIn("source_path_leaks", script)
        self.assertIn("module_origin_leaks", script)
        self.assertIn("portable worker module origins leak source paths", script)
        self.assertIn("qwen_import_ok", script)

    def test_cpp_ci_smokes_portable_worker_through_transport(self) -> None:
        workflow = _CPP_CHECKS_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("scripts/test-portable-python-worker-cpp.ps1", workflow)
        self.assertIn("Package portable Python worker", workflow)
        self.assertIn("Smoke-test portable worker through C++ transport", workflow)
        self.assertIn(".\\scripts\\test-portable-python-worker-cpp.ps1", workflow)
        self.assertIn('"worker/**"', workflow)

    def test_portable_worker_docs_recommend_environment_overrides(self) -> None:
        readme = _README.read_text(encoding="utf-8")

        self.assertIn("environment_overrides", readme)
        self.assertIn("complete replacement environment", readme)
        self.assertIn("PYTHONHOME", readme)
        self.assertIn(".qtb-portable-worker-root", readme)
        self.assertIn("local wheel", readme)


if __name__ == "__main__":
    unittest.main()
