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
                            "U+0301 after the stressed vowel; ё is not marked"
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
        self.assertTrue(
            any("ONNX codec" in blocker for blocker in requirements["blockers"])
        )

    def test_talker_and_codec_gguf_pair_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for name in ("qwen-talker-q8.gguf", "qwen-tokenizer-12hz-q8.gguf"):
                (root / name).write_bytes(struct.pack("<4sIQQ", b"GGUF", 2, 2, 3))

            report = audit.audit_model_directory(root, include_hashes=True)

        requirements = report["native_requirements"]
        self.assertTrue(requirements["native_split_gguf_compatible"])
        valid_pair = (
            requirements["valid_talker_gguf"] + requirements["valid_codec_gguf"]
        )
        self.assertEqual(2, len(valid_pair))
        self.assertTrue(all("sha256" in entry for entry in report["files"]))


if __name__ == "__main__":
    unittest.main()
