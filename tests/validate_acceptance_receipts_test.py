"""Model-free regression tests for the canonical acceptance validator."""

from __future__ import annotations

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
