"""Model-free checks for the native portable package contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

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
    @staticmethod
    def _minimal_pe(machine: int, optional_magic: int) -> bytes:
        payload = bytearray(512)
        payload[:2] = b"MZ"
        payload[0x3C:0x40] = (0x80).to_bytes(4, "little")
        payload[0x80:0x84] = b"PE\0\0"
        payload[0x84:0x86] = machine.to_bytes(2, "little")
        payload[0x86:0x88] = (0).to_bytes(2, "little")
        payload[0x94:0x96] = (96).to_bytes(2, "little")
        payload[0x98:0x9A] = optional_magic.to_bytes(2, "little")
        return bytes(payload)

    @staticmethod
    def _pe_with_imports(
        imports: list[str], delay_imports: list[str] | None = None
    ) -> bytes:
        """Build a small valid PE32+ image with real import directories.

        The fixture is deliberately generated in the test rather than loaded
        through a patched parser.  It exercises the same RVA-to-file mapping
        and descriptor layouts used by AMD64 release binaries while keeping
        the repository free of generated executables.
        """
        delay_imports = delay_imports or []
        pe_offset = 0x80
        section_rva = 0x1000
        raw_offset = 0x200
        raw_size = 0x400
        optional_size = 0xF0
        section_table = pe_offset + 4 + 20 + optional_size
        payload = bytearray(raw_offset + raw_size)
        payload[:2] = b"MZ"
        struct.pack_into("<I", payload, 0x3C, pe_offset)
        payload[pe_offset : pe_offset + 4] = b"PE\0\0"
        struct.pack_into(
            "<HHIIIHH",
            payload,
            pe_offset + 4,
            0x8664,
            1,
            0,
            0,
            0,
            optional_size,
            0x2022,
        )
        optional = pe_offset + 4 + 20
        struct.pack_into("<H", payload, optional, 0x20B)
        struct.pack_into("<I", payload, optional + 0x38, 0x2000)
        struct.pack_into("<I", payload, optional + 0x3C, raw_offset)
        struct.pack_into("<H", payload, optional + 0x5C, 3)
        struct.pack_into("<I", payload, optional + 0x6C, 16)
        directory = optional + 112
        if imports:
            struct.pack_into(
                "<II", payload, directory + 8, section_rva, (len(imports) + 1) * 20
            )
        if delay_imports:
            struct.pack_into(
                "<II",
                payload,
                directory + 13 * 8,
                section_rva + 0x80,
                (len(delay_imports) + 1) * 32,
            )
        struct.pack_into(
            "<8sIIIIIIHHI",
            payload,
            section_table,
            b".idata\0\0",
            raw_size,
            section_rva,
            raw_size,
            raw_offset,
            0,
            0,
            0,
            0,
            0x40000040,
        )

        cursor = 0x40

        def write_name(name: str) -> int:
            nonlocal cursor
            encoded = name.encode("ascii") + b"\0"
            start = cursor
            payload[raw_offset + cursor : raw_offset + cursor + len(encoded)] = encoded
            cursor += len(encoded)
            return section_rva + start

        for index, name in enumerate(imports):
            name_rva = write_name(name)
            struct.pack_into(
                "<5I",
                payload,
                raw_offset + index * 20,
                0,
                0,
                0,
                name_rva,
                0,
            )
        for index, name in enumerate(delay_imports):
            name_rva = write_name(name)
            struct.pack_into(
                "<8I",
                payload,
                raw_offset + 0x80 + index * 32,
                1,
                name_rva,
                0,
                0,
                0,
                0,
                0,
                0,
            )
        return bytes(payload)

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
            "scripts/start-native-play.ps1",
            "scripts/ensure-native-models.ps1",
        ):
            self.assertIn(token, script)

    def test_assembler_rejects_weights_and_test_runtime_files(self) -> None:
        script = ASSEMBLER.read_text(encoding="utf-8")
        self.assertIn("Model or user audio must not be inside native runtime", script)
        self.assertIn("test/fake native runtime file", script)
        self.assertIn("unmanifested file", script)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is required")
    def test_notice_name_collision_fails_before_publication(self) -> None:
        temporary_root = ROOT / ".tmp" / "native-packaging-tests"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            output = root / "output"
            runtime.mkdir()
            output.mkdir()
            (runtime / "qwen.dll").write_bytes(b"runtime-preflight-fixture")
            (root / "tool.exe").write_bytes(b"executable-preflight-fixture")
            (runtime / "manifest.json").write_text(
                json.dumps({
                    "schema_version": 1, "engine": "qwentts.cpp",
                    "architecture": "x64", "qt_abi_version": 6,
                    "engine_commit": "130cb99", "backend": "cpu",
                    "files": [{
                        "path": "qwen.dll",
                        "sha256": hashlib.sha256(
                            (runtime / "qwen.dll").read_bytes()
                        ).hexdigest(),
                    }],
                }),
                encoding="utf-8",
            )
            for directory, name in (("one", "LICENSE"), ("two", "license")):
                (root / directory).mkdir()
                (root / directory / name).write_text(directory, encoding="utf-8")
            (output / ".qtb-native-release-root").write_text("owned", encoding="utf-8")
            sentinel = output / "preserve.txt"
            sentinel.write_bytes(b"existing package remains unchanged")
            runner = root / "invoke.ps1"
            assembler_path = str(ASSEMBLER).replace("'", "''")
            runner.write_text(
                "$tool = Join-Path $PSScriptRoot 'tool.exe'\n"
                f"& '{assembler_path}' -NativeWorkerExecutable $tool "
                "-SaveWavExecutable $tool -PlayExecutable $tool "
                "-RuntimeRoot (Join-Path $PSScriptRoot 'runtime') "
                "-NoticeFile @((Join-Path $PSScriptRoot 'one/LICENSE'), "
                "(Join-Path $PSScriptRoot 'two/license')) "
                "-OutputRoot (Join-Path $PSScriptRoot 'output') -Clean\n",
                encoding="utf-8-sig",
            )
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(runner)],
                env={key: value for key, value in os.environ.items()
                     if key.casefold() != "psmodulepath"},
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn(
                "Native notice destination name collision",
                completed.stdout + completed.stderr,
            )
            self.assertEqual(
                b"existing package remains unchanged", sentinel.read_bytes()
            )
            self.assertFalse((root / ".output.assembling").exists())

    def test_auditor_marks_non_pe_entry_as_failure(self) -> None:
        auditor = _load_auditor()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "entry.exe").write_bytes(b"not a PE")
            result = auditor.audit(root, ["entry.exe"])
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["non_pe_files"], ["entry.exe"])

    def test_auditor_rejects_pe32_x86_entry(self) -> None:
        auditor = _load_auditor()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "entry.exe").write_bytes(
                self._minimal_pe(0x14C, 0x10B)
            )
            result = auditor.audit(root, ["entry.exe"])
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["architecture_failures"][0]["machine"], "0x014c")

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

    def test_auditor_traverses_declared_dynamic_module_imports(self) -> None:
        auditor = _load_auditor()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "entry.exe").write_bytes(self._minimal_pe(0x8664, 0x20B))
            (root / "backend.dll").write_bytes(self._minimal_pe(0x8664, 0x20B))

            def imports(path: Path) -> list[dict[str, str]]:
                if path.name.lower() == "backend.dll":
                    return [{"name": "helper.dll", "kind": "import"}]
                return []

            with patch.object(auditor, "_imports", side_effect=imports):
                result = auditor.audit(
                    root,
                    ["entry.exe"],
                    {"guaranteed_system": [], "declared_prerequisites": []},
                    ["backend.dll"],
                )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["missing"], ["helper.dll"])

    def test_auditor_parses_normal_delay_and_transitive_pe_imports(self) -> None:
        auditor = _load_auditor()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "entry.exe").write_bytes(self._pe_with_imports(["backend.dll"]))
            (root / "backend.dll").write_bytes(
                self._pe_with_imports(["helper.dll"], ["delay-helper.dll"])
            )
            result = auditor.audit(
                root,
                ["entry.exe"],
                {"guaranteed_system": [], "declared_prerequisites": []},
                ["backend.dll"],
            )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["missing"], ["delay-helper.dll", "helper.dll"])
        self.assertTrue(
            any(
                item.get("importer") == "backend.dll"
                and item.get("name") == "delay-helper.dll"
                and item.get("kind") == "delay"
                for item in result["imports"]
            )
        )
        self.assertFalse(result["architecture_failures"])

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
        self.assertIn("outside the source checkout", " ".join(document.split()))

    def test_release_config_uses_relocatable_runtime_and_model_paths(self) -> None:
        config = json.loads(
            (ROOT / "config" / "native-package.example.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(config["runtime_dir"], "runtime/qwentts")
        self.assertEqual(config["model_root"], "models")
        self.assertEqual(config["default_model_profile"], "ru-stress")
        self.assertEqual(config["save_wav"], "bin/qwen_tts_save_wav.exe")
        self.assertTrue(config["require_model_hashes"])
        for profile in config["model_profiles"].values():
            for key in ("talker_sha256", "codec_sha256"):
                self.assertRegex(profile["model_download"][key], r"^[0-9a-f]{64}$")
        self.assertNotIn("sm75", config["runtime_dir"].lower())
        self.assertEqual(
            config["model_profiles"]["base"]["talker_model"],
            "base/qwen-talker-1.7b-base-Q8_0.gguf",
        )
        self.assertEqual(
            config["model_profiles"]["base"]["codec_model"],
            "common/qwen-tokenizer-12hz-Q8_0.gguf",
        )
        self.assertEqual(
            config["model_profiles"]["ru-stress"]["talker_model"],
            "ru-stress/qwen-talker-1.7b-ru-stress-Q8_0.gguf",
        )


if __name__ == "__main__":
    unittest.main()
