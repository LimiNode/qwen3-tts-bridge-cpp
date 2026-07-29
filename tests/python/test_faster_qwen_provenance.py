import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.faster_qwen_provenance import load_faster_qwen_provenance


class FasterQwenProvenanceTests(unittest.TestCase):
    def test_loads_manifest_with_matching_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "faster.bundle"
            bundle.write_bytes(b"bundle payload")
            bundle_sha256 = hashlib.sha256(bundle.read_bytes()).hexdigest()
            manifest = root / "provenance.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "wheel_sha256": "a" * 64,
                        "source_commit": "b" * 40,
                        "bundle_path": bundle.name,
                        "bundle_sha256": bundle_sha256,
                    }
                ),
                encoding="utf-8",
            )

            result = load_faster_qwen_provenance(manifest)

            self.assertEqual("a" * 64, result["wheel_sha256"])
            self.assertEqual("b" * 40, result["source_commit"])
            self.assertEqual(str(bundle.resolve()), result["bundle_path"])

    def test_rejects_bundle_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "faster.bundle"
            bundle.write_bytes(b"bundle payload")
            manifest = root / "provenance.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "wheel_sha256": "a" * 64,
                        "source_commit": "b" * 40,
                        "bundle_path": bundle.name,
                        "bundle_sha256": "c" * 64,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "bundle SHA-256 mismatch"):
                load_faster_qwen_provenance(manifest)


if __name__ == "__main__":
    unittest.main()
