"""Model-free checks for the native portable package contract."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSEMBLER = ROOT / "scripts" / "assemble-native-portable-release.ps1"
AUDITOR = ROOT / "scripts" / "audit-native-dependencies.py"
DOC = ROOT / "docs" / "native-portable-package.md"


def _load_auditor():
    spec = importlib.util.spec_from_file_location("native_dependency_audit", AUDITOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load dependency auditor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativePortablePackagingContractTests(unittest.TestCase):
    def test_assembler_requires_real_native_inputs_and_manifest(self) -> None:
        script = ASSEMBLER.read_text(encoding="utf-8")
        for token in (
            "$NativeWorkerExecutable",
            "$RuntimeRoot",
            "$SaveWavExecutable",
            "$PlayExecutable",
            "Assert-RuntimeManifest",
            "qwen.dll",
            "dependency-inventory.json",
            "SHA256SUMS.txt",
            "python_required = $false",
            "models_included = $false",
            ".qtb-native-release-root",
            "audit-native-dependencies.py",
        ):
            self.assertIn(token, script)

    def test_assembler_rejects_weights_and_test_runtime_files(self) -> None:
        script = ASSEMBLER.read_text(encoding="utf-8")
        self.assertIn("Model or user audio must not be inside native runtime", script)
        self.assertIn("test/fake native runtime file", script)
        self.assertIn("unmanifested file", script)

    def test_auditor_marks_non_pe_entry_as_failure(self) -> None:
        auditor = _load_auditor()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "entry.exe").write_bytes(b"not a PE")
            result = auditor.audit(root, ["entry.exe"])
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["non_pe_files"], ["entry.exe"])

    def test_auditor_rejects_duplicate_bundled_module_names(self) -> None:
        auditor = _load_auditor()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bin").mkdir()
            (root / "runtime").mkdir()
            (root / "bin" / "qwen.dll").write_bytes(b"not a PE")
            (root / "runtime" / "qwen.dll").write_bytes(b"not a PE")
            (root / "entry.exe").write_bytes(b"not a PE")
            result = auditor.audit(root, ["entry.exe"])
        self.assertEqual(result["status"], "fail")
        self.assertIn("qwen.dll", result["duplicate_bundled_names"])

    def test_auditor_cli_writes_structured_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "entry.exe").write_bytes(b"not a PE")
            output = root / "audit.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(AUDITOR),
                    "--root",
                    str(root),
                    "--entry",
                    "entry.exe",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 2)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "fail")
            self.assertIn("entry.exe", payload["non_pe_files"])

    def test_documentation_does_not_promise_acceptance(self) -> None:
        document = DOC.read_text(encoding="utf-8")
        self.assertIn("not yet a hardware or listening acceptance result", document)
        self.assertIn("Python/FasterQwen distribution remains a separate", document)
        self.assertIn("outside the source checkout", document)


if __name__ == "__main__":
    unittest.main()
