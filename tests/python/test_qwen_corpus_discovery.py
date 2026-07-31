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


if __name__ == "__main__":
    unittest.main()
