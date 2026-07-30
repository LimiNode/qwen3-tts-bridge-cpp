"""Assign stable v4 batch and record IDs to a 200-record candidate JSONL file."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

_BATCH_ID_RE = re.compile(r"v4-b(0[1-9]|10)")
_BATCH_RECORDS = 200


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite-ids", action="store_true")
    args = parser.parse_args()
    if not _BATCH_ID_RE.fullmatch(args.batch_id):
        parser.error("--batch-id must use v4-b01 through v4-b10")
    records = _load(args.input)
    if len(records) != _BATCH_RECORDS:
        raise RuntimeError("candidate batch must contain exactly 200 records")
    if not args.overwrite_ids and any(
        "batch_id" in record or "record_id" in record for record in records
    ):
        raise RuntimeError(
            "candidate already has IDs; pass --overwrite-ids to replace them"
        )
    prepared = [
        {
            **record,
            "batch_id": args.batch_id,
            "record_id": f"{args.batch_id}-{index:03d}",
        }
        for index, record in enumerate(records, 1)
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in prepared
    )
    args.output.write_text(output, encoding="utf-8")
    sidecar = {
        "batch_id": args.batch_id,
        "record_count": len(prepared),
        "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "preparer_source_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
    }
    args.output.with_suffix(args.output.suffix + ".sha256.json").write_text(
        json.dumps(sidecar, sort_keys=True), encoding="utf-8"
    )
    return 0


def _load(path: Path) -> list[dict[str, object]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise RuntimeError("candidate batch contains a non-object record")
            records.append(value)
    return records


if __name__ == "__main__":
    raise SystemExit(main())
