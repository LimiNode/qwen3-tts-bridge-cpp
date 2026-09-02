"""Regression tests for real-model benchmark request-shape parsing."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark_packaged_worker import _load_request_shapes, _synthesize_payload


class BenchmarkRequestShapeTests(unittest.TestCase):
    def test_loads_base_profile_voice_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "shapes.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "label": "registered-profile",
                        "text": "Profile acceptance.",
                        "voice_id": "local_voice",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            shapes = _load_request_shapes(path)

        self.assertEqual(shapes[0]["voice_id"], "local_voice")
        self.assertEqual(shapes[0]["reference_audio_path"], "")

    def test_rejects_mixed_profile_and_direct_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "shapes.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "label": "invalid",
                        "text": "Invalid profile request.",
                        "voice_id": "local_voice",
                        "reference_audio_path": "reference.wav",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "mixes voice_id"):
                _load_request_shapes(path)

    def test_payload_forwards_profile_id(self) -> None:
        payload = _synthesize_payload(
            text="Profile acceptance.",
            language="English",
            speaker="",
            instruction="",
            voice_id="local_voice",
        )

        self.assertEqual(payload["voice_id"], "local_voice")
        self.assertNotIn("speaker", payload)


if __name__ == "__main__":
    unittest.main()
