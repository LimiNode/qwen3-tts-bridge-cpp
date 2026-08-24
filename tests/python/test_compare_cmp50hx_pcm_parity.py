"""Regression tests for the dependency-free CMP PCM parity analyzer."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_module():
    path = Path(__file__).parents[2] / "scripts" / "compare-cmp50hx-pcm-parity.py"
    spec = importlib.util.spec_from_file_location("cmp_pcm_parity", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PCM_PARITY = _load_module()


class CompareCmp50hxPcmParityTests(unittest.TestCase):
    def test_metrics_report_exact_and_small_delta_cases(self) -> None:
        exact = PCM_PARITY.compute_metrics(
            PCM_PARITY.array.array("h", [0, 12, -12]),
            PCM_PARITY.array.array("h", [0, 12, -12]),
        )
        self.assertEqual(exact["exact_sample_match_count"], 3)
        self.assertEqual(exact["rms_pcm_delta"], 0.0)
        self.assertIsNone(exact["snr_db"])
        self.assertTrue(exact["snr_db_is_infinite"])
        json.dumps(exact, allow_nan=False)

        delta = PCM_PARITY.compute_metrics(
            PCM_PARITY.array.array("h", [100, -100]),
            PCM_PARITY.array.array("h", [101, -98]),
        )
        self.assertEqual(delta["exact_sample_match_count"], 0)
        self.assertEqual(delta["max_abs_pcm_delta"], 2)
        self.assertGreater(delta["snr_db"], 30.0)
        self.assertFalse(delta["snr_db_is_infinite"])

    def test_read_metadata_rejects_byte_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary) / "capture.pcm"
            capture.write_bytes(b"\x00\x00")
            capture.with_name("capture.pcm.json").write_text(
                json.dumps(
                    {
                        "measurement": "raw_s16le_pcm_capture",
                        "completed": True,
                        "byte_count": 4,
                        "audio_format": {
                            "sample_format": "s16le",
                            "sample_rate": 24_000,
                            "channels": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "byte count"):
                PCM_PARITY.read_metadata(capture)


if __name__ == "__main__":
    unittest.main()
