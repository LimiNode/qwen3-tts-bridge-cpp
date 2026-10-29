import hashlib
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
    sample_rate: int = 24_000,
    seconds: float = 2.0,
    sample: int = 4_000,
) -> None:
    frame_count = int(sample_rate * seconds)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(struct.pack("<h", sample) * frame_count * channels)


class VoiceProfilePreflightTests(unittest.TestCase):
    def test_bundled_example_registry_is_self_contained(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        registry_path = (
            repository
            / "examples"
            / "voice-profiles"
            / "registry.example.json"
        )
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        expected_hashes = {
            "kraftwerk_robot_3_ru.wav": (
                "baba7f26a9eb8de1df53a51c4b33ac6c"
                "b3625fe70509d7c1a281b64d4827000b"
            ),
            "kraftwerk_robot_ru_fidelity.wav": (
                "90e5f7576991ea5b9f0a85e9109f7bd3"
                "1ff667c4a12d58783a06c650796c3ca1"
            ),
            "kraftwerk_robot_ru_warm.wav": (
                "b8285c5925d89d90435afa2f084a197a"
                "9e428dec41fff09c74969e6624a4b147"
            ),
            "kraftwerk_robot_ru_source_like.wav": (
                "b2480523e3dae70f2267260e3d60dce0"
                "c04dbe19f332f3fae6b031a54ab640f3"
            ),
            "kraftwerk_robot_ru_warm_metal.wav": (
                "9c96c277ffb61709a511a01ee715bd4c"
                "15b1ccc669c9c55ca900f2229bb2799a"
            ),
        }

        self.assertEqual(1, registry["schema_version"])
        self.assertEqual(9, len(registry["voices"]))
        for row in registry["voices"]:
            reference = (registry_path.parent / row["reference_audio_path"]).resolve()
            self.assertTrue(reference.is_relative_to(registry_path.parent.resolve()))
            self.assertTrue(reference.is_file())
            self.assertEqual(
                expected_hashes[reference.name],
                hashlib.sha256(reference.read_bytes()).hexdigest(),
            )

        whitespace = {
            row["voice_id"]: row["reference_text"]
            for row in registry["voices"]
            if row["voice_id"].startswith("kraftwerk_robot_ru_icl_period")
        }
        self.assertEqual(
            "Я твой слуга, я твой работник.",
            whitespace["kraftwerk_robot_ru_icl_period"],
        )
        self.assertEqual(
            "Я твой слуга, я твой работник. ",
            whitespace["kraftwerk_robot_ru_icl_period_space"],
        )
        self.assertEqual(
            "Я твой слуга, я твой работник.    ",
            whitespace["kraftwerk_robot_ru_icl_period_four_spaces"],
        )

    def test_accepts_stereo_pcm_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reference = Path(temporary_directory) / "stereo.wav"
            _write_pcm_wav(reference, channels=2)

            info = preflight_reference_audio(reference, "Reference text.", False)

        self.assertEqual(2, info.channels)
        self.assertEqual(24_000, info.sample_rate)

    def test_accepts_python_only_non_24khz_reference_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reference = Path(temporary_directory) / "sixteen-khz.wav"
            _write_pcm_wav(reference, sample_rate=16_000)

            info = preflight_reference_audio(reference, "Reference text.", False)

        # The native process worker deliberately accepts only mono 24 kHz
        # PCM16/float32 references.  This fixture documents the wider Python
        # preflight boundary without claiming cross-backend compatibility.
        self.assertEqual(16_000, info.sample_rate)

    def test_rejects_silent_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reference = Path(temporary_directory) / "silent.wav"
            _write_pcm_wav(reference, sample=0)

            with self.assertRaisesRegex(VoiceProfileError, "effectively silent"):
                preflight_reference_audio(reference, "Reference text.", False)

    def test_accepts_twenty_second_reference_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reference = Path(temporary_directory) / "twenty-seconds.wav"
            _write_pcm_wav(reference, seconds=20.0)

            info = preflight_reference_audio(reference, "Reference text.", False)

        self.assertEqual(20.0, info.duration_seconds)

    def test_rejects_reference_wav_longer_than_twenty_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            reference = Path(temporary_directory) / "too-long.wav"
            _write_pcm_wav(reference, seconds=20.1)

            with self.assertRaisesRegex(VoiceProfileError, "between 2 and 20 seconds"):
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

    def test_empty_registry_is_valid_without_registered_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            registry_path = Path(temporary_directory) / "voices.json"
            registry_path.write_text(
                json.dumps({"schema_version": 1, "voices": []}),
                encoding="utf-8",
            )

            registry = VoiceProfileRegistry.from_json_file(registry_path, 1)

        self.assertEqual((), registry.voice_ids)

    def test_duplicate_voice_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            reference = directory / "reference.wav"
            _write_pcm_wav(reference)
            registry_path = directory / "voices.json"
            profile = {
                "voice_id": "duplicate",
                "reference_audio_path": "reference.wav",
                "reference_text": "Reference text.",
            }
            registry_path.write_text(
                json.dumps({"schema_version": 1, "voices": [profile, profile]}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(VoiceProfileError, "duplicate voice_id"):
                VoiceProfileRegistry.from_json_file(registry_path, 1)


if __name__ == "__main__":
    unittest.main()
