from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "qwen_corpus_discovery.py"
_SPEC = importlib.util.spec_from_file_location("qwen_corpus_discovery", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class QwenCorpusDiscoveryTest(unittest.TestCase):
    def test_load_discovery_records_requires_pinned_sha_and_discovery_split(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "discovery.jsonl"
            input_path.write_text(
                json.dumps(
                    {
                        "record_id": "record-1",
                        "text": "hello",
                        "corpus_id": "corpus-v4",
                        "corpus_split": "discovery",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            audit_path = root / "audit.json"
            audit_path.write_text(
                json.dumps(
                    {
                        "corpus_id": "corpus-v4",
                        "discovery_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                        "discovery_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            records, sha256, corpus_id = _MODULE._load_discovery_records(
                input_path,
                audit_path,
                "corpus-v4",
            )

            self.assertEqual(1, len(records))
            self.assertEqual("corpus-v4", corpus_id)
            self.assertEqual(hashlib.sha256(input_path.read_bytes()).hexdigest(), sha256)

    def test_load_discovery_records_rejects_holdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "holdout.jsonl"
            input_path.write_text(
                json.dumps(
                    {
                        "record_id": "record-1",
                        "text": "hello",
                        "corpus_id": "corpus-v4",
                        "corpus_split": "runtime_measurement_holdout",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            audit_path = root / "audit.json"
            audit_path.write_text(
                json.dumps(
                    {
                        "corpus_id": "corpus-v4",
                        "discovery_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                        "discovery_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "holdout is forbidden"):
                _MODULE._load_discovery_records(input_path, audit_path, "corpus-v4")

    def test_distribution_and_language_mapping_are_deterministic(self) -> None:
        rows = [
            {"first_audio_ms": 10.0, "inverse_rtf": 1.0},
            {"first_audio_ms": 20.0, "inverse_rtf": 3.0},
        ]
        self.assertEqual(
            {"min": 10.0, "p50": 15.0, "p90": 19.0, "p95": 19.5, "p99": 19.9, "max": 20.0, "mean": 15.0},
            _MODULE._distribution(rows, "first_audio_ms"),
        )
        self.assertEqual("Russian", _MODULE._language_for_record("ru"))
        self.assertEqual("English", _MODULE._language_for_record("en"))
        self.assertEqual("Auto", _MODULE._language_for_record("mixed"))

    def test_generation_outcome_distinguishes_max_sequence_from_eos(self) -> None:
        self.assertEqual(
            "eos",
            _MODULE._generation_outcome({"hit_eos": True, "hit_max_seq_len": False}),
        )
        self.assertEqual(
            "max_seq_len",
            _MODULE._generation_outcome(
                {"hit_eos": False, "hit_max_seq_len": True}
            ),
        )

    def test_measured_row_records_request_seed_contract(self) -> None:
        row = _MODULE._measure_record(
            _MetricEngine(),
            7,
            {
                "record_id": "record-7",
                "text": "hello",
                "language_class": "en",
            },
            "ryan",
            20260731,
        )

        self.assertEqual(7, row["request_id"])
        self.assertEqual(20260738, row["derived_request_seed"])
        self.assertEqual("eos", row["generation_outcome"])

    def test_summary_preserves_holdout_split(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            row = {
                "record_id": "record-1",
                "execution_outcome": "completed",
                "generation_outcome": "eos",
                "first_audio_ms": 10.0,
                "completed_ms": 20.0,
                "inverse_rtf": 2.0,
                "audio_seconds": 1.0,
                "first_chunk_route": {"talker_prefill_length": 18},
            }
            (output_dir / "records.jsonl").write_text(
                json.dumps(row) + "\n",
                encoding="utf-8",
            )

            summary = _MODULE._write_summary(
                output_dir,
                {
                    "corpus_id": "corpus-v4",
                    "corpus_split": "runtime_measurement_holdout",
                    "input_sha256": "a" * 64,
                    "profile": {"sha256": "b" * 64},
                    "runtime": {},
                },
                [{"record_id": "record-1"}],
            )

        self.assertEqual("runtime_measurement_holdout", summary["corpus_split"])


class _MetricEngine:
    def validate_request(self, request: object) -> None:
        del request

    def synthesize_stream(self, request: object, cancel_event: object):
        del request, cancel_event
        yield b"\0" * 48_000

    def pop_last_chunk_metrics(self) -> dict[str, object]:
        return {"talker_prefill_length": 32}

    def pop_last_generation_trace(self) -> dict[str, object]:
        return {"hit_eos": True, "termination_reason": "eos"}


if __name__ == "__main__":
    unittest.main()
