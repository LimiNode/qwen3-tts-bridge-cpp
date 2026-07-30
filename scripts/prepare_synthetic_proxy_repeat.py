"""Derive a deterministic shuffled manifest for repeatability runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--order-seed", type=int, required=True)
    parser.add_argument("--request-seed", type=int, required=True)
    parser.add_argument("--speaker", required=True)
    args = parser.parse_args()

    source_bytes = args.input.read_bytes()
    records = _read_records(args.input, source_bytes)
    random.Random(args.order_seed).shuffle(records)
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()

    for index, record in enumerate(records, 1):
        record["source_corpus_sha256"] = source_sha256
        record["source_label"] = record["label"]
        record["label"] = _repeat_label(record, index)
        record["repeat_order_seed"] = args.order_seed
        record["seed"] = args.request_seed
        record["speaker"] = args.speaker

    args.output.parent.mkdir(parents=True, exist_ok=True)
    output = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )
    args.output.write_text(
        output,
        encoding="utf-8",
    )
    return 0


def _read_records(path: Path, source_bytes: bytes) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(source_bytes.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"input line {line_number} is not an object")
        if not isinstance(value.get("text"), str) or not value["text"]:
            raise RuntimeError(f"input line {line_number} has invalid text")
        if not isinstance(value.get("label"), str) or not value["label"]:
            raise RuntimeError(f"input line {line_number} has invalid label")
        records.append(value)
    if not records:
        raise RuntimeError(f"input manifest {path} contains no records")
    return records


def _repeat_label(record: dict[str, object], index: int) -> str:
    corpus_id = record.get("corpus_id")
    if isinstance(corpus_id, str) and corpus_id:
        return f"{corpus_id}-repeat-{index:04d}"
    return f"repeat-{index:04d}"


if __name__ == "__main__":
    raise SystemExit(main())
