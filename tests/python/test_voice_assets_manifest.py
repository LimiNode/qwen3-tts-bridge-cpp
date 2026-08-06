import json
import tempfile
import unittest
import wave
from pathlib import Path

from scripts.voice_assets_manifest import (
    build_manifest,
    stage_profiles,
    verify_manifest,
)


class VoiceAssetsManifestTests(unittest.TestCase):
    def test_stages_and_verifies_selected_voice_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_root = Path(temporary_directory) / "source"
            package_root = Path(temporary_directory) / "package"
            (source_root / "assets").mkdir(parents=True)
            _write_wav(source_root / "assets" / "voice.wav")
            registry = source_root / "voices.json"
            registry.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "voices": [
                            {
                                "voice_id": "robot",
                                "reference_audio_path": "assets/voice.wav",
                                "reference_text": "Reference text.",
                                "x_vector_only": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (package_root / "provenance").mkdir(parents=True)
            (package_root / "provenance" / "voice-assets.json").write_text(
                json.dumps(
                    {
                        "profiles": [
                            {
                                "voice_id": "robot",
                                "quality_status": (
                                    "accepted_experimental_character_profile"
                                ),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            stage_profiles(
                source_root=source_root,
                source_registry=registry,
                output_root=package_root,
                registry=Path("config/voice-profiles.json"),
                voice_dir=Path("voices"),
                provenance=Path("provenance/voice-assets.json"),
                voice_ids=["robot"],
            )
            manifest = build_manifest(
                root=package_root,
                registry=Path("config/voice-profiles.json"),
                provenance=Path("provenance/voice-assets.json"),
                temperature=0.45,
                package_id="test-package",
            )

            verify_manifest(package_root, manifest)
            self.assertEqual("test-package", manifest["package_id"])
            voices = manifest["voices"]
            self.assertIsInstance(voices, list)
            assert isinstance(voices, list)
            first_voice = voices[0]
            self.assertIsInstance(first_voice, dict)
            assert isinstance(first_voice, dict)
            self.assertEqual("icl", first_voice["mode"])
            reference_audio = first_voice["reference_audio"]
            self.assertIsInstance(reference_audio, dict)
            assert isinstance(reference_audio, dict)
            self.assertEqual(
                0.1,
                reference_audio["duration_seconds"],
            )
            (package_root / "voices" / "voice.wav").write_bytes(b"changed")
            with self.assertRaisesRegex(
                ValueError, "voice assets do not match manifest"
            ):
                verify_manifest(package_root, manifest)


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24000)
        stream.writeframes(b"\0\0" * 2400)


if __name__ == "__main__":
    unittest.main()
