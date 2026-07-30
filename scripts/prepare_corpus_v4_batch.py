"""Assign stable v4 batch and record IDs to a 200-record candidate JSONL file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

_BATCH_ID_RE = re.compile(r"v4-b(0[1-9]|10)")
_BATCH_RECORDS = 200


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite-ids", action="store_true")
    parser.add_argument("--overwrite-output", action="store_true")
    args = parser.parse_args()
    if not _BATCH_ID_RE.fullmatch(args.batch_id):
        parser.error("--batch-id must use v4-b01 through v4-b10")
    _prepare(
        args.input,
        args.batch_id,
        args.output,
        overwrite_ids=args.overwrite_ids,
        overwrite_output=args.overwrite_output,
    )
    return 0


def _prepare(
    input_path: Path,
    batch_id: str,
    output_path: Path,
    *,
    overwrite_ids: bool,
    overwrite_output: bool,
) -> dict[str, object]:
    if input_path.resolve() == output_path.resolve():
        raise RuntimeError("prepared output must differ from the candidate input")
    sidecar_path = output_path.with_suffix(output_path.suffix + ".sha256.json")
    existing_outputs = [path for path in (output_path, sidecar_path) if path.exists()]
    if existing_outputs and not overwrite_output:
        raise RuntimeError(
            "prepared output or sidecar already exists; pass --overwrite-output "
            "to replace it"
        )
    records = _load(input_path)
    if len(records) != _BATCH_RECORDS:
        raise RuntimeError("candidate batch must contain exactly 200 records")
    if not overwrite_ids and any(
        "batch_id" in record or "record_id" in record for record in records
    ):
        raise RuntimeError(
            "candidate already has IDs; pass --overwrite-ids to replace them"
        )
    prepared = [
        {
            **record,
            "batch_id": batch_id,
            "record_id": f"{batch_id}-{index:03d}",
        }
        for index, record in enumerate(records, 1)
    ]
    output = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in prepared
    )
    sidecar = {
        "batch_id": batch_id,
        "record_count": len(prepared),
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "preparer_source_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_atomically(output_path, output)
    _write_text_atomically(sidecar_path, json.dumps(sidecar, sort_keys=True))
    return sidecar


def _load(path: Path) -> list[dict[str, object]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise RuntimeError("candidate batch contains a non-object record")
            records.append(value)
    return records


def _write_text_atomically(path: Path, value: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(value)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
