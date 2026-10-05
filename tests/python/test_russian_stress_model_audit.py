"""Tests for the offline Russian stress-model compatibility audit."""

from __future__ import annotations

import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path


def _load_audit_module():
    script = Path(__file__).parents[2] / "scripts" / "audit-russian-stress-model.py"
    spec = importlib.util.spec_from_file_location("russian_stress_audit", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load audit script: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = _load_audit_module()


class RussianStressModelAuditTests(unittest.TestCase):
    @staticmethod
    def _gguf(metadata: dict[str, str]) -> bytes:
        payload = bytearray(struct.pack("<4sIQQ", b"GGUF", 3, 1, len(metadata)))
        for key, value in metadata.items():
            key_bytes = key.encode("utf-8")
            value_bytes = value.encode("utf-8")
            payload.extend(struct.pack("<Q", len(key_bytes)))
            payload.extend(key_bytes)
            payload.extend(struct.pack("<I", 8))
            payload.extend(struct.pack("<Q", len(value_bytes)))
            payload.extend(value_bytes)
        return bytes(payload)

    def test_onnx_codec_package_is_explicitly_incompatible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "qwen3_tts_talker.q8_0.gguf").write_bytes(
                struct.pack("<4sIQQ", b"GGUF", 3, 1, 1)
            )
            (root / "qwen3_tts_predictor.q8_0.gguf").write_bytes(b"predictor")
            (root / "qwen3_tts_decoder.fp16.onnx").write_bytes(b"decoder")
            (root / "qwen3_tts_codec_encoder.fp32.onnx").write_bytes(b"encoder")
            (root / "stress.json").write_text(
                json.dumps(
                    {
                        "stress_marks": (
                            "U+0301 after the stressed vowel; \u0451 is not marked"
                        ),
                        "language": "ru",
                    }
                ),
                encoding="utf-8",
            )

            report = audit.audit_model_directory(root)

        requirements = report["native_requirements"]
        self.assertFalse(requirements["native_split_gguf_compatible"])
        self.assertTrue(report["stress_metadata"]["uses_combining_acute"])
        self.assertTrue(report["stress_metadata"]["yo_not_marked"])
        self.assertEqual(
            "U+0301 combining acute after stressed vowel",
            report["provenance"]["stress_marker"],
        )
        self.assertTrue(
            any("ONNX codec" in blocker for blocker in requirements["blockers"])
        )

    def test_talker_and_codec_gguf_pair_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "qwen-talker-q8.gguf").write_bytes(
                self._gguf(
                    {
                        "general.architecture": "qwen3_tts",
                        "general.basename": "ru-stress-talker",
                    }
                )
            )
            (root / "qwen-tokenizer-12hz-q8.gguf").write_bytes(
                self._gguf({"general.name": "qwen3-tts-12hz-codec"})
            )
            (root / "tokenizer.json").write_text(
                json.dumps({"model": {"type": "BPE", "vocab": {"a": 0}}}),
                encoding="utf-8",
            )

            report = audit.audit_model_directory(root, include_hashes=True)

        requirements = report["native_requirements"]
        self.assertTrue(requirements["native_split_gguf_compatible"])
        valid_pair = (
            requirements["valid_talker_gguf"] + requirements["valid_codec_gguf"]
        )
        self.assertEqual(2, len(valid_pair))
        self.assertTrue(all("sha256" in entry for entry in report["files"]))
        talker = next(item for item in report["files"] if "talker" in item["path"])
        self.assertEqual(
            "qwen3_tts", talker["gguf"]["metadata"]["general.architecture"]
        )
        self.assertEqual(1, report["tokenizer"]["vocab_size"])


if __name__ == "__main__":
    unittest.main()
