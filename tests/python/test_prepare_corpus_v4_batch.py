"""Tests for immutable v4 batch preparation and its provenance sidecar."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_corpus_v4_batch import _prepare


class PrepareCorpusV4BatchTests(unittest.TestCase):
    def test_preparer_writes_matching_sha_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = _write_candidate(root / "candidate.jsonl")
            output = root / "prepared.jsonl"
            sidecar = _prepare(
                candidate,
                "v4-b02",
                output,
                overwrite_ids=False,
                overwrite_output=False,
            )

            prepared = [json.loads(line) for line in output.read_text().splitlines()]
            output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
            saved_sidecar = json.loads(
                output.with_suffix(output.suffix + ".sha256.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual("v4-b02-001", prepared[0]["record_id"])
        self.assertEqual("v4-b02-200", prepared[-1]["record_id"])
        self.assertEqual(output_sha256, sidecar["output_sha256"])
        self.assertEqual(sidecar, saved_sidecar)

    def test_preparer_refuses_existing_output_without_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = _write_candidate(root / "candidate.jsonl")
            output = root / "prepared.jsonl"
            _prepare(
                candidate,
                "v4-b02",
                output,
                overwrite_ids=False,
                overwrite_output=False,
            )
            original = output.read_bytes()

            with self.assertRaisesRegex(RuntimeError, "already exists"):
                _prepare(
                    candidate,
                    "v4-b02",
                    output,
                    overwrite_ids=False,
                    overwrite_output=False,
                )

            self.assertEqual(original, output.read_bytes())
            _prepare(
                candidate,
                "v4-b02",
                output,
                overwrite_ids=False,
                overwrite_output=True,
            )
            self.assertEqual(original, output.read_bytes())

    def test_preparer_refuses_an_orphaned_existing_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = _write_candidate(root / "candidate.jsonl")
            output = root / "prepared.jsonl"
            output.with_suffix(output.suffix + ".sha256.json").write_text(
                "{}", encoding="utf-8"
            )

            with self.assertRaisesRegex(RuntimeError, "already exists"):
                _prepare(
                    candidate,
                    "v4-b02",
                    output,
                    overwrite_ids=False,
                    overwrite_output=False,
                )

    def test_preparer_refuses_to_replace_the_candidate_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = _write_candidate(Path(directory) / "candidate.jsonl")

            with self.assertRaisesRegex(RuntimeError, "must differ"):
                _prepare(
                    candidate,
                    "v4-b02",
                    candidate,
                    overwrite_ids=False,
                    overwrite_output=False,
                )


def _write_candidate(path: Path) -> Path:
    path.write_text(
        "".join(
            json.dumps({"text": f"candidate {index}"}) + "\n"
            for index in range(1, 201)
        ),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
