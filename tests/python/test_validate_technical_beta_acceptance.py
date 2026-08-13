"""Behavioral tests for fail-closed technical-beta evidence validation."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_VALIDATOR = _ROOT / "scripts" / "validate_technical_beta_acceptance.py"
_RELOCATION_GATES = [
    "package_tree_pre_smoke",
    "voice_assets_pre_smoke",
    "native_closure",
    "custom_voice_doctor_pre_smoke",
    "base_doctor_pre_smoke",
    "custom_voice_natural_eos",
    "base_natural_eos",
    "custom_voice_doctor_post_smoke",
    "base_doctor_post_smoke",
    "no_bytecode",
    "package_tree_post_smoke",
    "voice_assets_post_smoke",
]
_FAULT_CASES = [
    "replace_success",
    "replace_before_backup",
    "replace_after_backup",
    "replace_after_swap",
    "replace_published_validation_failure",
    "replace_before_backup_cleanup",
    "first_publish_after_swap",
    "first_publish_validation_failure",
]


class TechnicalBetaAcceptanceValidatorTests(unittest.TestCase):
    def _run(self, kind: str, payload: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.json"
            report.write_text(payload, encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(_VALIDATOR),
                    "--kind",
                    kind,
                    "--report",
                    str(report),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

    @staticmethod
    def _relocation_report() -> dict[str, object]:
        return {
            "schema_version": 4,
            "acceptance_pass": True,
            "required_gates": {name: True for name in _RELOCATION_GATES},
            "package": {
                "verified_manifest_digest": "a" * 64,
                "verified_manifest_digest_algorithm": "sha256(package-tree-manifest)",
            },
        }

    @staticmethod
    def _fault_report() -> dict[str, object]:
        return {
            "schema_version": 2,
            "acceptance_pass": True,
            "cases": [{"name": name, "pass": True} for name in _FAULT_CASES],
        }

    def test_accepts_complete_reports(self) -> None:
        relocation = self._run("relocation", json.dumps(self._relocation_report()))
        fault = self._run("fault", json.dumps(self._fault_report()))

        self.assertEqual(relocation.returncode, 0, relocation.stderr)
        self.assertEqual(fault.returncode, 0, fault.stderr)

    def test_rejects_missing_false_and_unknown_relocation_gates(self) -> None:
        missing = self._relocation_report()
        missing["required_gates"].pop("base_natural_eos")  # type: ignore[index]
        false = self._relocation_report()
        false["required_gates"]["base_natural_eos"] = False  # type: ignore[index]
        unknown = self._relocation_report()
        unknown["required_gates"]["optional_gate"] = True  # type: ignore[index]

        for report in (missing, false, unknown):
            result = self._run("relocation", json.dumps(report))
            self.assertNotEqual(result.returncode, 0)

    def test_rejects_duplicate_gate_keys_and_unknown_schema(self) -> None:
        duplicate = (
            '{"schema_version":4,"acceptance_pass":true,'
            '"required_gates":{"package_tree_pre_smoke":true,'
            '"package_tree_pre_smoke":true},"package":{'
            '"verified_manifest_digest":"' + "a" * 64 + '",'
            '"verified_manifest_digest_algorithm":"sha256(package-tree-manifest)"}}'
        )
        wrong_schema = self._relocation_report()
        wrong_schema["schema_version"] = 3

        self.assertNotEqual(self._run("relocation", duplicate).returncode, 0)
        self.assertNotEqual(
            self._run("relocation", json.dumps(wrong_schema)).returncode,
            0,
        )

    def test_rejects_fault_case_gaps_and_duplicates(self) -> None:
        missing = self._fault_report()
        missing["cases"].pop()  # type: ignore[index]
        duplicate = self._fault_report()
        duplicate["cases"][-1]["name"] = "replace_success"  # type: ignore[index]

        self.assertNotEqual(self._run("fault", json.dumps(missing)).returncode, 0)
        self.assertNotEqual(self._run("fault", json.dumps(duplicate)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
