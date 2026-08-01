"""Build a reproducible exact-prefill candidate from discovery measurements."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

_LANGUAGE_BY_CLASS = {"ru": "Russian", "en": "English", "mixed": "Auto"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--select-count", type=int, default=6)
    parser.add_argument("--current-lengths", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.select_count <= 0:
        parser.error("--select-count must be positive")

    manifest = build_manifest(
        records_path=args.records,
        discovery_path=args.discovery,
        select_count=args.select_count,
        current_lengths=_parse_lengths(args.current_lengths),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "selected_exact_lengths": manifest["selected_exact_lengths"],
                "candidate_coverage": manifest["candidate_coverage"],
            },
            sort_keys=True,
        )
    )
    return 0


def build_manifest(
    *,
    records_path: Path,
    discovery_path: Path,
    select_count: int,
    current_lengths: list[int],
) -> dict[str, object]:
    records = _load_jsonl(records_path, "records")
    discovery = _load_jsonl(discovery_path, "discovery")
    discovery_by_id = _discovery_by_id(discovery)

    lengths_by_id = _measured_lengths(records)
    if not lengths_by_id:
        raise ValueError("records contain no completed measured lengths")
    missing = sorted(set(lengths_by_id) - set(discovery_by_id))
    if missing:
        raise ValueError(f"records are missing discovery rows: {missing[:5]}")

    histogram = Counter(lengths_by_id.values())
    ranked = sorted(histogram.items(), key=lambda item: (-item[1], item[0]))
    selected = sorted(length for length, _count in ranked[:select_count])
    rows = [
        _candidate_row(record_id, discovery_by_id[record_id], length)
        for length in selected
        for record_id, measured_length in lengths_by_id.items()
        if measured_length == length
    ]
    selected_rows = _first_row_per_length(rows, selected)
    total = len(lengths_by_id)
    return {
        "artifact_schema_version": 1,
        "method": "frequency_ranked_exact_prefill_lengths_from_completed_discovery",
        "records_path": str(records_path),
        "records_sha256": _sha256(records_path),
        "discovery_path": str(discovery_path),
        "discovery_sha256": _sha256(discovery_path),
        "corpus_id": _corpus_id(discovery),
        "record_count": total,
        "selected_exact_lengths": selected,
        "histogram": _histogram_rows(ranked, total),
        "candidate_coverage": _coverage(selected, histogram, total),
        "current_exact_lengths": current_lengths,
        "current_coverage": _coverage(current_lengths, histogram, total),
        "rows": selected_rows,
    }


def _load_jsonl(path: Path, name: str) -> list[dict[str, Any]]:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read {name}: {path}") from exc
    rows: list[dict[str, Any]] = []
    for number, raw in enumerate(raw_lines, 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} line {number} is not valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{name} line {number} must be an object")
        rows.append(value)
    if not rows:
        raise ValueError(f"{name} must contain at least one row")
    return rows


def _discovery_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        record_id = row.get("record_id")
        text = row.get("text")
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("discovery row has invalid record_id")
        if not isinstance(text, str) or not text:
            raise ValueError(f"discovery row {record_id} has invalid text")
        if record_id in result:
            raise ValueError(f"discovery contains duplicate record_id: {record_id}")
        result[record_id] = row
    return result


def _measured_lengths(rows: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        if row.get("execution_outcome") != "completed":
            continue
        record_id = row.get("record_id")
        route = row.get("first_chunk_route")
        length = route.get("talker_prefill_length") if isinstance(route, dict) else None
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("completed record has invalid record_id")
        if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
            raise ValueError(f"completed record {record_id} has invalid prefill length")
        if record_id in result:
            raise ValueError(
                f"records contain duplicate completed record_id: {record_id}"
            )
        result[record_id] = length
    return result


def _candidate_row(
    record_id: str, row: dict[str, Any], length: int
) -> dict[str, object]:
    language_class = row.get("language_class")
    language = _LANGUAGE_BY_CLASS.get(language_class, "Auto")
    text = str(row["text"])
    return {
        "label": record_id,
        "record_id": record_id,
        "text": text,
        "text_characters": len(text),
        "language": language,
        "language_class": language_class,
        "instruction": "",
        "instruction_characters": 0,
        "talker_prefill_length": length,
    }


def _first_row_per_length(
    rows: list[dict[str, object]], lengths: list[int]
) -> list[dict[str, object]]:
    result: dict[int, dict[str, object]] = {}
    for row in rows:
        length = int(row["talker_prefill_length"])
        result.setdefault(length, row)
    missing = [length for length in lengths if length not in result]
    if missing:
        raise ValueError(f"cannot select rows for lengths: {missing}")
    return [result[length] for length in lengths]


def _histogram_rows(
    ranked: list[tuple[int, int]], total: int
) -> list[dict[str, object]]:
    cumulative = 0
    result = []
    for length, count in ranked:
        cumulative += count
        result.append(
            {
                "talker_prefill_length": length,
                "count": count,
                "fraction": round(count / total, 6),
                "cumulative_fraction": round(cumulative / total, 6),
            }
        )
    return result


def _coverage(
    lengths: list[int], histogram: Counter[int], total: int
) -> dict[str, object]:
    covered = sum(histogram[length] for length in lengths)
    return {
        "selected_count": len(lengths),
        "covered_prompts": covered,
        "covered_fraction": round(covered / total, 6),
    }


def _corpus_id(rows: list[dict[str, Any]]) -> str:
    values = {row.get("corpus_id") for row in rows}
    if len(values) != 1 or not isinstance(next(iter(values)), str):
        raise ValueError("discovery must have exactly one string corpus_id")
    return str(next(iter(values)))


def _parse_lengths(value: str) -> list[int]:
    result = [int(item.strip()) for item in value.split(",") if item.strip()]
    if any(length <= 0 for length in result) or len(result) != len(set(result)):
        raise ValueError("lengths must be unique positive integers")
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
