"""Tests for sealed internal runtime profile preflight."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from typing import cast

from scripts.validate_internal_runtime_profile import _validate


class ValidateInternalRuntimeProfileTests(unittest.TestCase):
    def test_accepts_exact_profile_runtime_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            evidence = root / "evidence.json"
            evidence.write_text("{}", encoding="utf-8")
            profile: dict[str, object] = {
                "profile_status": "internal_opt_in_only",
                "dtype": "bfloat16",
            }
            runtime: dict[str, object] = {"python": "3.12.10"}
            policy: dict[str, object] = {
                "runtime_policy_schema_version": 2,
                "status": "internal_opt_in_only",
                "profile_contract": {"dtype": "bfloat16"},
                "runtime_contract": {"python": "3.12.10"},
                "evidence_files": {
                    "evidence.json": hashlib.sha256(evidence.read_bytes()).hexdigest()
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
            }
            policy: dict[str, object] = {
                "runtime_policy_schema_version": 2,
                "status": "internal_opt_in_only",
                "profile_contract": {"dtype": "bfloat16"},
                "runtime_contract": {"python": "3.12.10"},
                "evidence_files": {"missing.json": "a" * 64},
            }

            report = _validate(profile, policy, {"python": "3.11.0"}, root)

        failures = cast(list[str], report["failures"])
        self.assertIn("runtime.python does not match policy", failures)
        self.assertIn("evidence file is missing: missing.json", failures)


if __name__ == "__main__":
    unittest.main()
