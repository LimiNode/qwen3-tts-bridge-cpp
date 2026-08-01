"""Tests for sealed internal runtime profile preflight."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from scripts.model_runtime_manifest import build_manifest
from scripts.validate_internal_runtime_profile import (
    _effective_worker_config,
    _repository_identity_sha256,
    _validate,
    _worker_source_bundle_sha256,
)


class ValidateInternalRuntimeProfileTests(unittest.TestCase):
    def test_repository_text_identity_normalizes_windows_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            text = root / "evidence.json"
            text.write_bytes(b"{\r\n  \"value\": true\r\n}\r\n")
            binary = root / "evidence.bundle"
            binary.write_bytes(b"bundle\r\npayload\r\n")

            self.assertEqual(
                hashlib.sha256(b"{\n  \"value\": true\n}\n").hexdigest(),
                _repository_identity_sha256(text),
            )
            self.assertEqual(
                hashlib.sha256(binary.read_bytes()).hexdigest(),
                _repository_identity_sha256(binary),
            )

    def test_worker_bundle_identity_normalizes_windows_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            source = root / "package"
            source.mkdir()
            (source / "worker.py").write_bytes(b"def main():\r\n    return 0\r\n")

            expected = hashlib.sha256()
            expected.update(b"worker.py\0def main():\n    return 0\n\0")
            self.assertEqual(expected.hexdigest(), _worker_source_bundle_sha256(source))

    def test_accepts_exact_profile_runtime_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            evidence = root / "evidence.json"
            evidence.write_text("{}", encoding="utf-8")
            model = root / "model"
            model.mkdir()
            (model / "config.json").write_text("config", encoding="utf-8")
            manifest = root / "model-runtime-manifest.json"
            manifest.write_text(
                json.dumps(build_manifest(model, "Qwen/example", "revision")),
                encoding="utf-8",
            )
            triton_manifest = root / "triton-installed-runtime-manifest.json"
            triton_manifest.write_text("{}", encoding="utf-8")
            profile: dict[str, object] = {
                "profile_status": "internal_opt_in_only",
                "dtype": "bfloat16",
                "model_path": "model",
            }
            runtime: dict[str, object] = {"python": "3.12.10"}
            policy: dict[str, object] = {
                "runtime_policy_schema_version": 4,
                "status": "internal_opt_in_only",
                "profile_contract": {"dtype": "bfloat16"},
                "runtime_contract": {"python": "3.12.10"},
                "effective_worker_contract": {"runtime_backend": "faster"},
                "evidence_files": {
                    "evidence.json": hashlib.sha256(evidence.read_bytes()).hexdigest()
                },
                "model_runtime_manifest": {
                    "path": "model-runtime-manifest.json",
                    "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                },
                "triton_installed_runtime_manifest": {
                    "path": "triton-installed-runtime-manifest.json",
                    "sha256": hashlib.sha256(triton_manifest.read_bytes()).hexdigest(),
                    "distribution": "triton-windows",
                },
            }

            with patch(
                "scripts.validate_internal_runtime_profile.verify_triton_manifest"
            ):
                report = _validate(
                    profile,
                    policy,
                    runtime,
                    root,
                    effective_worker_config={"runtime_backend": "faster"},
                )

        self.assertEqual([], cast(list[str], report["failures"]))

    def test_fails_closed_for_runtime_or_evidence_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            profile: dict[str, object] = {
                "profile_status": "internal_opt_in_only",
                "dtype": "bfloat16",
                "model_path": "model",
            }
            policy: dict[str, object] = {
                "runtime_policy_schema_version": 4,
                "status": "internal_opt_in_only",
                "profile_contract": {"dtype": "bfloat16"},
                "runtime_contract": {"python": "3.12.10"},
                "effective_worker_contract": {"runtime_backend": "faster"},
                "evidence_files": {"missing.json": "a" * 64},
                "model_runtime_manifest": {
                    "path": "missing-manifest.json",
                    "sha256": "b" * 64,
                },
                "triton_installed_runtime_manifest": {
                    "path": "missing-triton-manifest.json",
                    "sha256": "c" * 64,
                    "distribution": "triton-windows",
                },
            }

            report = _validate(
                profile,
                policy,
                {"python": "3.11.0"},
                root,
                effective_worker_config={"runtime_backend": "faster"},
            )

        failures = cast(list[str], report["failures"])
        self.assertIn("runtime.python does not match policy", failures)
        self.assertIn("evidence file is missing: missing.json", failures)
        self.assertIn("model runtime manifest is missing", failures)
        self.assertIn("Triton installed runtime manifest is missing", failures)

    def test_validates_an_explicit_model_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            declared_model = root / "declared-model"
            actual_model = root / "actual-model"
            declared_model.mkdir()
            actual_model.mkdir()
            (declared_model / "config.json").write_text("wrong", encoding="utf-8")
            (actual_model / "config.json").write_text("right", encoding="utf-8")
            manifest = root / "model-runtime-manifest.json"
            manifest.write_text(
                json.dumps(build_manifest(actual_model, "Qwen/example", "revision")),
                encoding="utf-8",
            )
            triton_manifest = root / "triton-installed-runtime-manifest.json"
            triton_manifest.write_text("{}", encoding="utf-8")
            profile: dict[str, object] = {
                "profile_status": "internal_opt_in_only",
                "dtype": "bfloat16",
                "model_path": "declared-model",
            }
            policy: dict[str, object] = {
                "runtime_policy_schema_version": 4,
                "status": "internal_opt_in_only",
                "profile_contract": {"dtype": "bfloat16"},
                "runtime_contract": {"python": "3.12.10"},
                "effective_worker_contract": {"runtime_backend": "faster"},
                "evidence_files": {},
                "model_runtime_manifest": {
                    "path": "model-runtime-manifest.json",
                    "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                },
                "triton_installed_runtime_manifest": {
                    "path": "triton-installed-runtime-manifest.json",
                    "sha256": hashlib.sha256(triton_manifest.read_bytes()).hexdigest(),
                    "distribution": "triton-windows",
                },
            }

            with patch(
                "scripts.validate_internal_runtime_profile.verify_triton_manifest"
            ):
                report = _validate(
                    profile,
                    policy,
                    {"python": "3.12.10"},
                    root,
                    model_path=actual_model,
                    effective_worker_config={"runtime_backend": "faster"},
                )

        self.assertEqual([], cast(list[str], report["failures"]))

    def test_parses_effective_worker_config_with_worker_parser(self) -> None:
        config = _effective_worker_config(
            [
                "-m",
                "qwen_tts_bridge_worker",
                "qwen",
                "--model-path",
                "models/example",
                "--runtime-backend",
                "faster",
                "--dtype",
                "bfloat16",
                "--attn-implementation",
                "sdpa",
                "--prefill-backend",
                "compile_reduce_overhead",
                "--prefill-compile-compat-mode",
                "strict_bf16_sdpa_v1",
                "--prefill-compile-lengths",
                "18,19",
                "--prefill-compile-policy",
                "exact_allowlist",
                "--prefill-allowlist-warmup-manifest",
                "candidate-manifest.json",
                "--no-prefill-compile-on-miss",
                "--prefill-require-precompiled",
                "--prefill-first-chunk-warmup",
                "--prefill-first-chunk-warmup-length",
                "18",
                "--collect-generation-trace",
                "--max-audio-seconds-per-utterance",
                "60",
                "--prefill-generation-prime",
            ]
        )

        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config["runtime_backend"], "faster")
        self.assertEqual(config["prefill_compile_lengths"], [18, 19])
        self.assertFalse(config["prefill_compile_on_miss"])
        self.assertTrue(config["prefill_generation_prime_enabled"])


if __name__ == "__main__":
    unittest.main()
