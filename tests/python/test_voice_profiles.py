import json
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from qwen_tts_bridge_worker.engine.voice_profiles import (
    VoiceProfileError,
    VoiceProfileRegistry,
    preflight_reference_audio,
)


def _write_pcm_wav(
    path: Path,
    *,
    channels: int = 1,
    seconds: float = 2.0,
    sample: int = 4_000,
) -> None:
    frame_count = int(24_000 * seconds)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(24_000)
        writer.writeframes(struct.pack("<h", sample) * frame_count * channels)


class VoiceProfilePreflightTests(unittest.TestCase):
    def test_accepts_stereo_pcm_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reference = Path(temporary_directory) / "stereo.wav"
            _write_pcm_wav(reference, channels=2)

            info = preflight_reference_audio(reference, "Reference text.", False)

        self.assertEqual(2, info.channels)
        self.assertEqual(24_000, info.sample_rate)

    def test_rejects_silent_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reference = Path(temporary_directory) / "silent.wav"
            _write_pcm_wav(reference, sample=0)

            with self.assertRaisesRegex(VoiceProfileError, "effectively silent"):
                preflight_reference_audio(reference, "Reference text.", False)

    def test_rejects_oversized_wav_before_decoding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reference = Path(temporary_directory) / "oversized.wav"
            reference.write_bytes(b"0" * (16 * 1024 * 1024 + 1))

            with self.assertRaisesRegex(VoiceProfileError, "size must be"):
                preflight_reference_audio(reference, "Reference text.", False)

    def test_registry_preserves_explicit_trailing_reference_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            reference = directory / "reference.wav"
            _write_pcm_wav(reference)
            registry_path = directory / "voices.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "voices": [
                            {
                                "voice_id": "experimental",
                                "reference_audio_path": "reference.wav",
                                "reference_text": "Reference text.    ",
                                "preserve_reference_text_whitespace": True,
                                "x_vector_only": False,
                            },
                            {
                                "voice_id": "normal",
                                "reference_audio_path": "reference.wav",
                                "reference_text": "Reference text.    ",
                                "x_vector_only": False,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            registry = VoiceProfileRegistry.from_json_file(registry_path, 2)

        experimental = registry.profile_for("experimental")
        normal = registry.profile_for("normal")
        self.assertEqual("Reference text.    ", experimental.reference_text)
        self.assertEqual("Reference text.", normal.reference_text)


if __name__ == "__main__":
    unittest.main()
