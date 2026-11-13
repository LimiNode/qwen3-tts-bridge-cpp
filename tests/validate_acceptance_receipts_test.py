"""Model-free regression tests for the canonical acceptance validator."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_acceptance_receipts", ROOT / "scripts/validate-acceptance-receipts.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class AcceptanceReceiptValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.receipt_path = ROOT / "docs/reports/base-portable-cmp50hx-20261030.json"
        self.receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))

    def assert_invalid(self, receipt: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ValidationError):
                VALIDATOR.validate_receipt(path, ROOT, False)

    def test_existing_receipts_validate(self) -> None:
        VALIDATOR.validate_index(ROOT)
        VALIDATOR.validate_receipt(self.receipt_path, ROOT, False)
        VALIDATOR.validate_receipt(
            ROOT / "docs/reports/voice-design-frozen-cmp50hx-20261028.json", ROOT, False
        )

    def version_two_receipt(self) -> dict:
        receipt = copy.deepcopy(self.receipt)
        receipt["hardware"].update(
            gpu_uuid="GPU-40361931-6cb5-ac58-a059-5ba3e70986fb",
            gpu_uuid_status="recorded",
        )
        for artifact in receipt["artifacts"]:
            artifact["availability"] = {"status": "not_checked", "reason": "Test fixture only; payload not inspected."}
        receipt.update(
            schema_version=2,
            case_result={"status": "not_assessed", "reason": "Repeat and restart not run."},
            listening_result={"status": "not_assessed", "reason": "Scoped partial listening only."},
            release_disposition={"status": "conditional", "reason": "Open release gates."},
        )
        return receipt

    def test_version_two_positive_and_complete_acceptance(self) -> None:
        receipt = self.version_two_receipt()
        temporary_root = ROOT / ".tmp/acceptance-validator-tests"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            path = Path(directory) / "receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            VALIDATOR.validate_receipt(path, ROOT, False)
            receipt["mechanical"] = {key: "pass" for key in receipt["mechanical"]}
            receipt["human_listening"].update(
                status="pass", criteria={key: "pass" for key in receipt["human_listening"]["criteria"]}
            )
            receipt["input_identity"].update(status="recorded", corpus_sha256="a" * 64)
            receipt["case_result"]["status"] = "pass"
            receipt["listening_result"]["status"] = "pass"
            receipt["release_disposition"]["status"] = "accepted"
            receipt["release_status"] = "accepted"
            for artifact in receipt["artifacts"]:
                artifact["availability"] = {"status": "local", "reason": "Synthetic positive fixture."}
            path.write_text(json.dumps(receipt), encoding="utf-8")
            VALIDATOR.validate_receipt(path, ROOT, False)

    def test_version_two_requires_separate_nonblank_result_layers(self) -> None:
        for field in VALIDATOR.RESULT_FIELDS:
            for malformed in (None, "pass", {}, {"status": [], "reason": "Invalid"},
                              {"status": "conditional", "reason": " "}):
                with self.subTest(field=field, malformed=malformed):
                    receipt = self.version_two_receipt()
                    receipt[field] = malformed
                    self.assert_invalid(receipt)
            receipt = self.version_two_receipt()
            del receipt[field]
            self.assert_invalid(receipt)

    def test_result_layers_reject_incomplete_or_contradictory_pass(self) -> None:
        for field, status in (("case_result", "pass"), ("listening_result", "pass"),
                              ("release_disposition", "accepted")):
            with self.subTest(field=field):
                receipt = self.version_two_receipt()
                receipt[field]["status"] = status
                self.assert_invalid(receipt)

    def test_schema_version_rejects_boolean_and_unknown(self) -> None:
        for version in (True, 1.0, 3, "2"):
            receipt = self.receipt.copy()
            receipt["schema_version"] = version
            self.assert_invalid(receipt)

    def test_version_two_requires_honest_artifact_availability(self) -> None:
        for value in (None, {"status": "archive", "reason": " "}, {"status": "assumed", "reason": "Unknown"}):
            receipt = self.version_two_receipt()
            receipt["artifacts"][0]["availability"] = value
            self.assert_invalid(receipt)
        receipt = self.version_two_receipt()
        del receipt["artifacts"][0]["availability"]
        self.assert_invalid(receipt)

    def test_accepted_receipt_requires_pinned_model_and_gpu_identity(self) -> None:
        receipt = self.version_two_receipt()
        receipt["mechanical"] = {key: "pass" for key in receipt["mechanical"]}
        receipt["human_listening"].update(
            status="pass", criteria={key: "pass" for key in receipt["human_listening"]["criteria"]}
        )
        receipt["input_identity"].update(status="recorded", corpus_sha256="a" * 64)
        receipt["case_result"] = {"status": "pass", "reason": "All gates passed."}
        receipt["listening_result"] = {"status": "pass", "reason": "All criteria passed."}
        receipt["release_disposition"] = {"status": "accepted", "reason": "Release gate passed."}
        receipt["release_status"] = "accepted"
        for artifact in receipt["artifacts"]:
            artifact["availability"] = {"status": "local", "reason": "Available."}
        receipt["model_revision"] = "not_pinned"
        self.assert_invalid(receipt)

        receipt["model_revision"] = "a" * 64
        del receipt["hardware"]["gpu_uuid_status"]
        self.assert_invalid(receipt)

    def test_uuid_unavailable_requires_machine_reason(self) -> None:
        receipt = self.version_two_receipt()
        receipt["hardware"] = dict(
            self.receipt["hardware"], gpu_uuid_status="unavailable", gpu_uuid_reason="operator_note"
        )
        self.assert_invalid(receipt)
        receipt["hardware"]["gpu_uuid_reason"] = "driver_api_unavailable"
        VALIDATOR.validate_receipt(
            self._write_temp_receipt(receipt), ROOT, False
        )

    def _write_temp_receipt(self, receipt: dict) -> Path:
        directory = tempfile.mkdtemp()
        path = Path(directory) / "receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        return path

    def test_invalid_model_family(self) -> None:
        receipt = self.receipt.copy()
        receipt["model_family"] = "unknown"
        self.assert_invalid(receipt)

    def test_malformed_hardware(self) -> None:
        receipt = self.receipt.copy()
        receipt["hardware"] = {"gpu": "CMP 50HX"}
        self.assert_invalid(receipt)

    def test_path_traversal_and_cross_run_artifacts(self) -> None:
        receipt = self.receipt.copy()
        receipt["artifacts"] = [dict(receipt["artifacts"][0], path=".tmp/base-acceptance/run/../../other.json")]
        self.assert_invalid(receipt)
        receipt["artifacts"] = [dict(receipt["artifacts"][0], path=".tmp/base-acceptance/voice-design-frozen-cmp50hx-20261028/out.wav")]
        self.assert_invalid(receipt)
        for path in (".tmp/base-acceptance/base-portable-cmp50hx-20261030/a//b.wav", ".tmp/base-acceptance/base-portable-cmp50hx-20261030/a/./b.wav"):
            receipt["artifacts"] = [dict(receipt["artifacts"][0], path=path)]
            self.assert_invalid(receipt)

    def test_symlink_artifact_root_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload_root = root / ".tmp/base-acceptance"
            payload_root.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            link = payload_root / "symlink-run"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            receipt = self.receipt.copy()
            receipt["artifact_root"] = ".tmp/base-acceptance/symlink-run"
            receipt["artifacts"] = [dict(receipt["artifacts"][0], path=".tmp/base-acceptance/symlink-run/out.wav")]
            path = root / "receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ValidationError):
                VALIDATOR.validate_receipt(path, root, False)

    def test_contradictory_listening_status(self) -> None:
        receipt = self.receipt.copy()
        receipt["human_listening"] = dict(receipt["human_listening"], status="pass")
        self.assert_invalid(receipt)

    def test_partial_pass_requires_incomplete_scope(self) -> None:
        receipt = self.receipt.copy()
        listening = dict(receipt["human_listening"])
        listening["criteria"] = {key: "pass" for key in listening["criteria"]}
        receipt["human_listening"] = listening
        self.assert_invalid(receipt)
        listening["criteria"] = {key: "not_assessed" for key in listening["criteria"]}
        receipt["human_listening"] = listening
        self.assert_invalid(receipt)

    def test_accepted_requires_core_mechanical_gates(self) -> None:
        receipt = self.receipt.copy()
        receipt["release_status"] = "accepted"
        receipt["mechanical"] = dict(receipt["mechanical"], model_load="not_run")
        receipt["human_listening"] = dict(
            receipt["human_listening"],
            status="pass",
            criteria={key: "pass" for key in receipt["human_listening"]["criteria"]},
        )
        self.assert_invalid(receipt)

    def test_index_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "docs/reports"
            reports.mkdir(parents=True)
            shutil.copy2(self.receipt_path, reports / self.receipt_path.name)
            voice_path = ROOT / "docs/reports/voice-design-frozen-cmp50hx-20261028.json"
            shutil.copy2(voice_path, reports / voice_path.name)
            shutil.copy2(ROOT / "docs/reports/russian-stress-cmp50hx-acceptance-2026-10-07.json", reports / "russian-stress-cmp50hx-acceptance-2026-10-07.json")
            index = json.loads((ROOT / "docs/reports/acceptance-index.json").read_text(encoding="utf-8"))
            index["canonical_receipts"][0]["model_family"] = "VoiceDesign"
            index_path = reports / "acceptance-index.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ValidationError):
                VALIDATOR.validate_index(root, index_path=index_path)

    def test_index_rejects_duplicate_and_traversal_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "docs/reports"
            reports.mkdir(parents=True)
            shutil.copy2(self.receipt_path, reports / self.receipt_path.name)
            shutil.copy2(ROOT / "docs/reports/russian-stress-cmp50hx-acceptance-2026-10-07.json", reports / "russian-stress-cmp50hx-acceptance-2026-10-07.json")
            index = {
                "schema_version": 1,
                "generated_at": "2026-11-01",
                "canonical_receipts": [
                    {"acceptance_id": "base-portable-cmp50hx-20261030", "receipt": "docs/reports/base-portable-cmp50hx-20261030.json", "model_family": "Base", "backend": "faster", "human_listening": "partial_pass", "release_status": "conditional"},
                    {"acceptance_id": "base-portable-cmp50hx-20261030", "receipt": "docs/reports/base-portable-cmp50hx-20261030.json", "model_family": "Base", "backend": "faster", "human_listening": "partial_pass", "release_status": "conditional"},
                ],
                "legacy_reference_reports": [],
            }
            index_path = reports / "acceptance-index.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ValidationError):
                VALIDATOR.validate_index(root, index_path=index_path)
            index["canonical_receipts"][1]["acceptance_id"] = "other"
            index["canonical_receipts"][1]["receipt"] = "docs/reports/../outside.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ValidationError):
                VALIDATOR.validate_index(root, index_path=index_path)


if __name__ == "__main__":
    unittest.main()
