"""Executable tests for the CMP 50HX AR evidence validator."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ValidateCmp50hxArEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.probe_root = self.root / "probes"
        seed_directory = self.probe_root / "seed-1008"
        seed_directory.mkdir(parents=True)

        wav = b"deterministic-pcm-fixture"
        (seed_directory / "output.wav").write_bytes(wav)
        self.wav_hash = hashlib.sha256(wav).hexdigest()
        self.top5 = [
            {"token": 1721, "probability": 0.774972},
            {"token": 1687, "probability": 0.100051},
            {"token": 367, "probability": 0.034855},
            {"token": 2, "probability": 0.025219},
            {"token": 1733, "probability": 0.019549},
        ]
        probe = {
            "qtb_metrics": [{"qwen_n_frames": 2048}],
            "terminal": {"execution_outcome": "max_tokens"},
            "ar_trace": [
                "sample step=0 c0=1721 u=0.7998353243 "
                "selected_p=0.774972141 eos_id=2150 eos_p=0 eos_rank=0 "
                "candidates=50 history=0 "
                "top=1721:0.774972,1687:0.100051,367:0.034855,"
                "2:0.025219,1733:0.019549"
            ],
        }
        self._write_json(seed_directory / "probe.json", probe)

        run = {
            "seed": 1008,
            "codec_frames": 2048,
            "execution_outcome": "max_tokens",
            "wav_sha256": self.wav_hash,
            "first_32_or_all_c0": [1721],
        }
        current = {
            "first_divergence": {
                "talker_step_0": {
                    "selected_token": 1721,
                    "selected_probability": 0.774972141,
                    "top5": self.top5,
                    "philox_draw_by_seed": {"1008": 0.7998353243},
                }
            },
            "runs": [run],
        }
        prior = {"post_fix_multi_seed_soak": [run]}
        self.evidence_path = self.root / "evidence.json"
        self.prior_path = self.root / "prior.json"
        self._write_json(self.evidence_path, current)
        self._write_json(self.prior_path, prior)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def _run_validator(self) -> subprocess.CompletedProcess[str]:
        script = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "validate-cmp50hx-ar-evidence.py"
        )
        return subprocess.run(
            [
                sys.executable,
                str(script),
                "--probe-root",
                str(self.probe_root),
                "--evidence",
                str(self.evidence_path),
                "--prior-evidence",
                str(self.prior_path),
            ],
            capture_output=True,
            check=False,
            text=True,
        )

    def test_accepts_matching_raw_and_sanitized_evidence(self) -> None:
        result = self._run_validator()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("validated 1 seeds", result.stdout)

    def test_rejects_prior_wav_hash_transcription_error(self) -> None:
        prior = {
            "post_fix_multi_seed_soak": [
                {
                    "seed": 1008,
                    "codec_frames": 2048,
                    "execution_outcome": "max_tokens",
                    "wav_sha256": "0" * 64,
                    "first_32_or_all_c0": [1721],
                }
            ]
        }
        self._write_json(self.prior_path, prior)

        result = self._run_validator()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("differs from prior non-diagnostic evidence", result.stderr)


if __name__ == "__main__":
    unittest.main()
