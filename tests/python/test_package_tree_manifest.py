import tempfile
import unittest
from pathlib import Path

from scripts.package_tree_manifest import build_manifest, verify_manifest


class PackageTreeManifestTests(unittest.TestCase):
    def test_verifies_exact_files_and_rejects_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "package"
            manifest_path = root / "manifests" / "package-tree.json"
            (root / "worker").mkdir(parents=True)
            (root / "worker" / "qwen_tts_worker.cmd").write_text(
                "@echo off\n", encoding="ascii"
            )
            (root / "bin").mkdir()
            (root / "bin" / "qwen_tts_save_wav.exe").write_bytes(b"native")

            manifest_path.parent.mkdir()
            manifest_path.write_bytes(build_manifest(root, manifest_path))
            verify_manifest(root, manifest_path)

            (root / "worker" / "qwen_tts_worker.cmd").write_text(
                "changed\n", encoding="ascii"
            )
            with self.assertRaisesRegex(ValueError, "does not match"):
                verify_manifest(root, manifest_path)

            manifest_path.write_bytes(build_manifest(root, manifest_path))
            (root / "worker" / "__pycache__").mkdir()
            verify_manifest(root, manifest_path)
            (root / "worker" / "__pycache__" / "worker.pyc").write_bytes(b"pyc")
            with self.assertRaisesRegex(ValueError, "forbidden bytecode"):
                verify_manifest(root, manifest_path)

    def test_rejects_unexpected_directories_and_nonempty_mutable_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "package"
            manifest_path = root / "manifests" / "package-tree.json"
            (root / "worker").mkdir(parents=True)
            (root / "worker" / "worker.py").write_text("pass\n", encoding="ascii")
            manifest_path.parent.mkdir()
            manifest_path.write_bytes(build_manifest(root, manifest_path))

            (root / "unexpected").mkdir()
            with self.assertRaisesRegex(ValueError, "unexpected directory"):
                verify_manifest(root, manifest_path)

            (root / "unexpected").rmdir()
            cache = root / "worker" / "__pycache__"
            cache.mkdir()
            (cache / "note.txt").write_text("not cache bytecode", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "must remain empty"):
                verify_manifest(root, manifest_path)


if __name__ == "__main__":
    unittest.main()
