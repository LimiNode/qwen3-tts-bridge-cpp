"""Tests for sealed internal runtime profile preflight."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import cast

from scripts.model_runtime_manifest import build_manifest
from scripts.validate_internal_runtime_profile import _validate


class ValidateInternalRuntimeProfileTests(unittest.TestCase):
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
            profile: dict[str, object] = {
                "profile_status": "internal_opt_in_only",
                "dtype": "bfloat16",
                "model_path": "model",
            }
            runtime: dict[str, object] = {"python": "3.12.10"}
            policy: dict[str, object] = {
                "runtime_policy_schema_version": 3,
                "status": "internal_opt_in_only",
                "profile_contract": {"dtype": "bfloat16"},
                "runtime_contract": {"python": "3.12.10"},
                "evidence_files": {
                    "evidence.json": hashlib.sha256(evidence.read_bytes()).hexdigest()
                },
                "model_runtime_manifest": {
                    "path": "model-runtime-manifest.json",
                    "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                },
            }

            report = _validate(profile, policy, runtime, root)

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
                "runtime_policy_schema_version": 3,
                "status": "internal_opt_in_only",
                "profile_contract": {"dtype": "bfloat16"},
                "runtime_contract": {"python": "3.12.10"},
                "evidence_files": {"missing.json": "a" * 64},
                "model_runtime_manifest": {
                    "path": "missing-manifest.json",
                    "sha256": "b" * 64,
                },
            }

            report = _validate(profile, policy, {"python": "3.11.0"}, root)

        failures = cast(list[str], report["failures"])
        self.assertIn("runtime.python does not match policy", failures)
        self.assertIn("evidence file is missing: missing.json", failures)
        self.assertIn("model runtime manifest is missing", failures)

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
            profile: dict[str, object] = {
                "profile_status": "internal_opt_in_only",
                "dtype": "bfloat16",
                "model_path": "declared-model",
            }
            policy: dict[str, object] = {
                "runtime_policy_schema_version": 3,
                "status": "internal_opt_in_only",
                "profile_contract": {"dtype": "bfloat16"},
                "runtime_contract": {"python": "3.12.10"},
                "evidence_files": {},
                "model_runtime_manifest": {
                    "path": "model-runtime-manifest.json",
                    "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                },
            }

            report = _validate(
                profile,
                policy,
                {"python": "3.12.10"},
                root,
                model_path=actual_model,
            )

        self.assertEqual([], cast(list[str], report["failures"]))


if __name__ == "__main__":
    unittest.main()
