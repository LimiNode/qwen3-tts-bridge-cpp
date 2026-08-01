"""Build a stratified discovery-only workload for two exact allowlists."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--samples-per-length", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.samples_per_length <= 0:
        parser.error("--samples-per-length must be positive")
    report = build_fixture(
        records_path=args.records,
        discovery_path=args.discovery,
        baseline_manifest_path=args.baseline_manifest,
        candidate_manifest_path=args.candidate_manifest,
        samples_per_length=args.samples_per_length,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


def build_fixture(
    *,
    records_path: Path,
    discovery_path: Path,
    baseline_manifest_path: Path,
    candidate_manifest_path: Path,
    samples_per_length: int,
    output_dir: Path,
) -> dict[str, object]:
    if output_dir.exists():
        raise ValueError(f"output directory already exists: {output_dir}")
    records = _load_jsonl(records_path)
    discovery = _load_jsonl(discovery_path)
    baseline = _load_object(baseline_manifest_path)
    candidate = _load_object(candidate_manifest_path)
    corpus_id = _single_corpus_id(discovery)
    discovery_by_id = {str(row["record_id"]): row for row in discovery}
    lengths = sorted(
        set(_selected_lengths(baseline)).union(_selected_lengths(candidate))
    )
    selected, selected_count_by_length = _select_records(
        records,
        discovery_by_id,
        lengths,
        samples_per_length,
    )
    output_dir.mkdir(parents=True)
    fixture_path = output_dir / "discovery.jsonl"
    fixture_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in selected
        ),
        encoding="utf-8",
    )
    fixture_sha256 = _sha256(fixture_path)
    audit = {
        "artifact_schema_version": 1,
        "corpus_id": corpus_id,
        "discovery_count": len(selected),
        "discovery_sha256": fixture_sha256,
        "fixture_kind": "same_wheel_exact_allowlist_ab",
        "source_records": _provenance(records_path),
        "source_discovery": _provenance(discovery_path),
        "baseline_manifest": _provenance(baseline_manifest_path),
        "candidate_manifest": _provenance(candidate_manifest_path),
        "samples_per_length": samples_per_length,
        "selected_lengths": lengths,
        "selected_count_by_length": selected_count_by_length,
    }
    (output_dir / "runtime-split-audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "fixture_path": str(fixture_path),
        "record_count": len(selected),
        "selected_lengths": lengths,
        "sha256": fixture_sha256,
    }


def _select_records(
    records: list[dict[str, Any]],
    discovery_by_id: dict[str, dict[str, Any]],
    lengths: list[int],
    samples_per_length: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    selected_by_length: dict[int, list[dict[str, Any]]] = defaultdict(list)
    wanted = set(lengths)
    for record in records:
        if record.get("execution_outcome") != "completed":
            continue
        route = record.get("first_chunk_route")
        if not isinstance(route, dict):
            continue
        length = route.get("talker_prefill_length")
        record_id = record.get("record_id")
        if (
            not isinstance(length, int)
            or length not in wanted
            or not isinstance(record_id, str)
            or len(selected_by_length[length]) >= samples_per_length
        ):
            continue
        source = discovery_by_id.get(record_id)
        if source is None:
            raise ValueError(f"record {record_id} is absent from discovery")
        selected_by_length[length].append(source)
    missing = [
        length
        for length in lengths
        if len(selected_by_length[length]) != samples_per_length
    ]
    if missing:
        raise ValueError(f"not enough completed samples for lengths: {missing}")
    return (
        [row for length in lengths for row in selected_by_length[length]],
        {str(length): len(selected_by_length[length]) for length in lengths},
    )


def _selected_lengths(manifest: dict[str, Any]) -> list[int]:
    values = manifest.get("selected_exact_lengths")
    if not isinstance(values, list) or not values:
        raise ValueError("manifest lacks selected_exact_lengths")
    result = [value for value in values if isinstance(value, int) and value > 0]
    if len(result) != len(values) or len(result) != len(set(result)):
        raise ValueError("manifest exact lengths must be unique positive integers")
    return result


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected object")
        rows.append(value)
    if not rows:
        raise ValueError(f"{path}: no rows")
    return rows


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected object")
    return value


def _single_corpus_id(rows: list[dict[str, Any]]) -> str:
    values = {row.get("corpus_id") for row in rows}
    if len(values) != 1 or not isinstance(next(iter(values)), str):
        raise ValueError("discovery must have one corpus_id")
    return str(next(iter(values)))


def _provenance(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
