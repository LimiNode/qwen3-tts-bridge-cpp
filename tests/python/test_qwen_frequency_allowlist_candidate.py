from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "qwen_frequency_allowlist_candidate.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "qwen_frequency_allowlist_candidate", _SCRIPT_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class FrequencyAllowlistCandidateTests(unittest.TestCase):
    def test_manifest_selects_completed_frequency_order_and_source_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = root / "records.jsonl"
            discovery = root / "discovery.jsonl"
            _write_jsonl(
                records,
                [
                    _record("a", 20),
                    _record("b", 18),
                    _record("c", 20),
                    _record("d", 18),
                    _record("e", 19),
                    {"record_id": "ignored", "execution_outcome": "failed"},
                ],
            )
            _write_jsonl(
                discovery,
                [
                    _discovery("a", "ru", "one"),
                    _discovery("b", "en", "two"),
                    _discovery("c", "mixed", "three"),
                    _discovery("d", "ru", "four"),
                    _discovery("e", "en", "five"),
                ],
            )

            manifest = _MODULE.build_manifest(
                records_path=records,
                discovery_path=discovery,
                select_count=2,
                current_lengths=[19],
            )

        self.assertEqual([18, 20], manifest["selected_exact_lengths"])
        self.assertEqual(4, manifest["candidate_coverage"]["covered_prompts"])
        self.assertEqual(0.8, manifest["candidate_coverage"]["covered_fraction"])
        self.assertEqual(1, manifest["current_coverage"]["covered_prompts"])
        rows = manifest["rows"]
        self.assertEqual(["b", "a"], [row["record_id"] for row in rows])
        self.assertEqual(["English", "Russian"], [row["language"] for row in rows])

    def test_manifest_rejects_completed_record_without_discovery_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = root / "records.jsonl"
            discovery = root / "discovery.jsonl"
            _write_jsonl(records, [_record("missing", 20)])
            _write_jsonl(discovery, [_discovery("known", "ru", "text")])

            with self.assertRaisesRegex(ValueError, "missing discovery rows"):
                _MODULE.build_manifest(
                    records_path=records,
                    discovery_path=discovery,
                    select_count=1,
                    current_lengths=[],
                )


def _record(record_id: str, length: int) -> dict[str, object]:
    return {
        "record_id": record_id,
        "execution_outcome": "completed",
        "first_chunk_route": {"talker_prefill_length": length},
    }


def _discovery(record_id: str, language_class: str, text: str) -> dict[str, object]:
    return {
        "record_id": record_id,
        "corpus_id": "test-corpus",
        "language_class": language_class,
        "text": text,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
