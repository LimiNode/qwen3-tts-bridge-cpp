"""Model-free checks for the native portable package contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
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


def _load_verifier():
    path = ROOT / "scripts" / "verify-native-package.py"
    spec = importlib.util.spec_from_file_location("native_package_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load package verifier")
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
            "native-dependency-policy.json",
            "verify-native-package.py",
            "--require-export",
            "Assert-NoPathOverlap",
            "Assert-NoReparsePoints",
            "outputBackup",
            "publishedOutput",
            "--extract-check",
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

    def test_auditor_records_missing_declared_dynamic_dependencies(self) -> None:
        auditor = _load_auditor()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "entry.exe").write_bytes(b"not a PE")
            result = auditor.audit(
                root,
                ["entry.exe"],
                {"guaranteed_system": [], "declared_prerequisites": []},
                ["cudart64_12.dll", "vcruntime140.dll", "ggml-cuda.dll"],
            )
        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            result["missing"],
            ["cudart64_12.dll", "ggml-cuda.dll", "vcruntime140.dll"],
        )

    def test_archive_verifier_covers_hidden_files_and_rejects_incomplete_zip(
        self,
    ) -> None:
        verifier = _load_verifier()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "package"
            root.mkdir()
            (root / ".qtb-native-release-root").write_text("owned\n", encoding="utf-8")
            (root / ".hidden-runtime-note").write_bytes(b"hidden")
            (root / "bin").mkdir()
            (root / "bin" / "tool.exe").write_bytes(b"fixture")
            files = []
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.name == ".qtb-native-release-root":
                    continue
                relative = path.relative_to(root).as_posix()
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                files.append({"path": relative, "sha256": digest})
            manifest = {
                "native_release_manifest_schema_version": 1,
                "files": files,
            }
            (root / "release-manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            checksums = []
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.name in {
                    "SHA256SUMS.txt",
                    ".qtb-native-release-root",
                }:
                    continue
                checksums.append(
                    f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
                    f"{path.relative_to(root).as_posix()}"
                )
            (root / "SHA256SUMS.txt").write_text(
                "\n".join(checksums) + "\n", encoding="utf-8"
            )
            archive = Path(temporary) / "package.zip"
            verifier.create_archive(root, archive)
            verifier.verify_archive(root, archive, True)
            with zipfile.ZipFile(archive, "a") as zipped:
                del_entry = zipped.namelist()[0]
                entries = [
                    (info.filename, zipped.read(info.filename))
                    for info in zipped.infolist()
                    if info.filename != del_entry
                ]
            incomplete = Path(temporary) / "incomplete.zip"
            with zipfile.ZipFile(incomplete, "w") as zipped:
                for name, payload in entries:
                    zipped.writestr(name, payload)
            with self.assertRaises(ValueError):
                verifier.verify_archive(root, incomplete, False)

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
        self.assertIn("not yet a hardware or listening acceptance", document)
        self.assertIn("Python/FasterQwen distribution remains a separate", document)
        self.assertIn("outside the source checkout", document)

    def test_release_config_uses_relocatable_runtime_and_model_paths(self) -> None:
        config = json.loads(
            (ROOT / "config" / "native-package.example.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(config["runtime_dir"], "runtime/qwentts")
        self.assertEqual(config["model_root"], "models")
        self.assertNotIn("sm75", config["runtime_dir"].lower())
        self.assertTrue(config["model_profiles"]["base"]["talker_model"].startswith("models/"))


if __name__ == "__main__":
    unittest.main()
