"""Model-free regression tests for the canonical acceptance validator."""

from __future__ import annotations

import importlib.util
import json
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

    def test_contradictory_listening_status(self) -> None:
        receipt = self.receipt.copy()
        receipt["human_listening"] = dict(receipt["human_listening"], status="pass")
        self.assert_invalid(receipt)

    def test_index_mismatch(self) -> None:
        index = json.loads((ROOT / "docs/reports/acceptance-index.json").read_text(encoding="utf-8"))
        index["canonical_receipts"][0]["model_family"] = "VoiceDesign"
        with self.assertRaises(VALIDATOR.ValidationError):
            receipt = VALIDATOR.validate_receipt(self.receipt_path, ROOT, False)
            if receipt["model_family"] != index["canonical_receipts"][0]["model_family"]:
                raise VALIDATOR.ValidationError("index model family mismatch")


if __name__ == "__main__":
    unittest.main()
