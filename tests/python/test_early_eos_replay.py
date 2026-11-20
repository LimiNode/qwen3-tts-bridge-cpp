"""Observable validation and causality tests for the read-only EOS study."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "analyze-early-eos-replay.py"
SPEC = importlib.util.spec_from_file_location("early_eos_replay", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)
TEXT = "МГУ находится в Москве. Инженер проверил USB-порт, GPS и новый процессор."


def write_fixture(run: Path, short_text: bool = False) -> None:
    """Two serial requests; the held-out example shares a training bad prefix."""
    requests, results, lines = [], [], []
    for request_id, seed in enumerate((2, 21), 1):
        frames = 1 if short_text else 3
        text = "Да!" if short_text else TEXT
        requests.append({"label": f"seed-{seed}", "text": text, "seed": seed})
        for step in range(frames):
            lines.append(f"[Sample] step={step} c0=10 u=0.5 subseq={step * 16}")
            lines.append(
                f"[ARTrace] predictor step={step} codes=" + ",".join(["10"] * 16)
            )
            if step == 0:
                lines.append(
                    "qtb_metric "
                    + json.dumps(
                        {
                            "event": "native_pcm_signal",
                            "request_id": request_id,
                            "chunk_index": 0,
                            "float_peak_abs": 0.01,
                            "float_rms": 0.001,
                            "s16_peak_abs": 300,
                            "s16_rms": 30,
                        }
                    )
                )
        lines.append(f"[Sample] step={frames} c0=2150 u=0.5 subseq={frames * 16}")
        lines.append(
            "qtb_metric "
            + json.dumps(
                {
                    "event": "request_finished",
                    "request_id": request_id,
                    "qwen_n_frames": frames,
                    "execution_outcome": "natural_eos",
                }
            )
        )
        chunks = [{"arrival_ms": 10, "audio_bytes": study.FRAME_BYTES}]
        if frames > 1:
            chunks.append({"arrival_ms": 20, "audio_bytes": 2 * study.FRAME_BYTES})
        results.append(
            {
                "request_id": request_id,
                "label": f"seed-{seed}",
                "completion_metadata": {"codec_frame_count": frames},
                "completion_execution_outcome": "natural_eos",
                "first_audio_ms": 10,
                "completed_ms": 25,
                "chunks": chunks,
            }
        )
    (run / "requests.jsonl").write_text(
        "\n".join(json.dumps(request, ensure_ascii=False) for request in requests),
        encoding="utf-8",
    )
    (run / "benchmark.json").write_text(
        json.dumps({"requests": results, "warmups": []})
    )
    (run / "stderr.log").write_text("\n".join(lines))
    (run / "invocation.json").write_text(json.dumps({"explicit_seed_order": [2, 21]}))


class EarlyEosReplayTests(unittest.TestCase):
    def test_seeds_and_features_align_without_mutating_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            write_fixture(run)
            before = {path.name: path.read_bytes() for path in run.iterdir()}
            result = study.analyze_run(run)
            self.assertEqual([2, 21], [row["seed"] for row in result["requests"]])
            self.assertEqual(3, len(result["requests"][0]["codes"]))
            self.assertEqual(1, result["candidates"][0]["held_out"]["tp"])
            self.assertEqual(
                before, {path.name: path.read_bytes() for path in run.iterdir()}
            )

    def test_equal_horizon_is_not_released_before_eos_decision(self) -> None:
        row = {
            "text": TEXT,
            "frames": 3,
            "first_pcm_ms": 10,
            "terminal_ms": 25,
            "duration_proxy": True,
            "chunks": [
                {"arrival_ms": 10, "audio_bytes": study.FRAME_BYTES},
                {"arrival_ms": 20, "audio_bytes": 2 * study.FRAME_BYTES},
            ],
        }
        self.assertEqual(20, study.release_boundary(row, 2)["release_ms"])
        gated = study.release_boundary(row, 3)
        self.assertIsNone(gated["release_ms"])
        self.assertEqual(25, gated["decision_ms"])

    def test_gate_never_reads_future_terminal_outcome(self) -> None:
        row = {
            "text": TEXT,
            "frames": 3,
            "first_pcm_ms": 10,
            "terminal_ms": 25,
            "chunks": [
                {"arrival_ms": 10, "audio_bytes": study.FRAME_BYTES},
                {"arrival_ms": 20, "audio_bytes": 2 * study.FRAME_BYTES},
            ],
        }
        for outcome in ("natural_eos", "max_tokens", "error"):
            with self.subTest(outcome=outcome):
                row["duration_proxy"] = study.duration_proxy(TEXT, 3, outcome)
                gated = study.release_boundary(row, 3)
                self.assertIsNone(gated["release_ms"])
                self.assertEqual(25, gated["decision_ms"])
                self.assertFalse(gated["gate_bypassed_unassessed_text"])
                self.assertEqual(20, study.release_boundary(row, 2)["release_ms"])

    def test_short_legitimate_utterance_has_no_failure_label_or_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            write_fixture(run, short_text=True)
            result = study.analyze_run(run)
            self.assertIsNone(result["requests"][0]["duration_proxy"])
            self.assertEqual(10, result["requests"][0]["policies"][-1]["release_ms"])
            self.assertEqual(1, result["candidates"][0]["held_out"]["unassessed"])

    def test_training_fit_never_reads_held_out_labels(self) -> None:
        rows = [
            {"seed": 2, "duration_proxy": True, "codes": [[10] * 16]},
            {"seed": 21, "duration_proxy": True, "codes": [[999] * 16]},
        ]
        original = study.fit_prefixes(rows, 1)
        rows[1]["duration_proxy"] = False
        self.assertEqual(original, study.fit_prefixes(rows, 1))
        self.assertEqual([[10]], original)
        probe = copy.deepcopy(rows[1])
        probe["codes"] = [[10] * 16]
        self.assertTrue(study.prefix_risk(probe, original, 1))
        probe["duration_proxy"] = True
        probe["frames"] = 100
        self.assertTrue(study.prefix_risk(probe, original, 1))

    def test_missing_predictor_or_malformed_trace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            write_fixture(run)
            path = run / "stderr.log"
            original = path.read_text()
            path.write_text(
                original.replace("[ARTrace] predictor step=1", "[ignored] step=1", 1)
            )
            with self.assertRaisesRegex(ValueError, "noncontiguous|missing"):
                study.analyze_run(run)
            path.write_text(original.replace("u=0.5", "u=nan", 1))
            with self.assertRaisesRegex(ValueError, "malformed"):
                study.analyze_run(run)

    def test_interleaving_duplicate_terminal_and_seed_order_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            write_fixture(run)
            path = run / "stderr.log"
            original = path.read_text()
            path.write_text(original.replace('"request_id": 1', '"request_id": 2', 1))
            with self.assertRaisesRegex(ValueError, "interleaved"):
                study.analyze_run(run)
            terminal = next(
                line for line in original.splitlines() if "request_finished" in line
            )
            path.write_text(original + "\n" + terminal)
            with self.assertRaisesRegex(ValueError, "duplicate terminal"):
                study.analyze_run(run)
            path.write_text(original)
            (run / "invocation.json").write_text(
                json.dumps({"explicit_seed_order": [21, 2]})
            )
            with self.assertRaisesRegex(ValueError, "seed order"):
                study.analyze_run(run)

    def test_chunk_after_terminal_and_corrupt_frame_size_are_rejected(self) -> None:
        row = {
            "text": TEXT,
            "frames": 1,
            "first_pcm_ms": 10,
            "terminal_ms": 9,
            "duration_proxy": True,
            "chunks": [{"arrival_ms": 10, "audio_bytes": study.FRAME_BYTES}],
        }
        with self.assertRaisesRegex(ValueError, "ordering"):
            study.release_boundary(row, 1)
        row["terminal_ms"] = 20
        row["chunks"][0]["audio_bytes"] = 1
        with self.assertRaisesRegex(ValueError, "complete"):
            study.release_boundary(row, 1)

    def test_cli_never_overwrites_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            write_fixture(run)
            output = run / "existing.json"
            output.write_text("preserve")
            process = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--run-dir",
                    str(run),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                timeout=10,
            )
            self.assertNotEqual(0, process.returncode)
            self.assertEqual("preserve", output.read_text())


if __name__ == "__main__":
    unittest.main()
