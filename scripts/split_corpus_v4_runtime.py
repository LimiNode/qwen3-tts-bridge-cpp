"""Create deterministic corpus-v4 discovery, holdout, and review partitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from scripts.audit_corpus_repetition import _record_id_set_sha256
except ModuleNotFoundError:
    from audit_corpus_repetition import _record_id_set_sha256

_CORPUS_ID = "representative-v4"
_HOLDOUT_RECORD_COUNT = 500
_REVIEW_RECORD_COUNT = 100
_REQUIRED_FIELDS = {
    "batch_id",
    "record_id",
    "text",
    "language_class",
    "category",
    "scene_context",
    "speech_intent",
    "intended_length_class",
    "template_family_id",
    "semantic_intent_id",
    "key_phrase_id",
}
_EXPECTED_BATCH_IDS = frozenset(f"v4-b{index:02d}" for index in range(1, 11))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--discovery-output", type=Path, required=True)
    parser.add_argument("--holdout-output", type=Path, required=True)
    parser.add_argument("--review-sample-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--corpus-id", default=_CORPUS_ID)
    args = parser.parse_args()

    source = args.input.read_bytes()
    records = _load_records(source)
    discovery, holdout = _split_records(records, args.seed, args.corpus_id)
    review = _select_review_sample(discovery, args.seed)
    _validate_batch_coverage(discovery, "discovery")
    _validate_batch_coverage(holdout, "runtime measurement holdout")
    _validate_batch_coverage(review, "manual review")
    _write_jsonl(args.discovery_output, discovery)
    _write_jsonl(args.holdout_output, holdout)
    _write_jsonl(args.review_sample_output, review)
    audit = _audit(
        source,
        records,
        discovery,
        holdout,
        review,
        args.seed,
        args.corpus_id,
        args.discovery_output,
        args.holdout_output,
        args.review_sample_output,
    )
    _write_object(args.audit_output, audit)
    print(json.dumps(audit, ensure_ascii=False, sort_keys=True))
    return 0


def _load_records(source: bytes) -> list[dict[str, object]]:
    records = []
    for line_number, line in enumerate(source.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"input line {line_number} is not an object")
        if set(value) != _REQUIRED_FIELDS:
            raise RuntimeError(f"input line {line_number} has an invalid schema")
        records.append(value)
    if len(records) != _HOLDOUT_RECORD_COUNT * 4:
        raise RuntimeError("corpus v4 runtime split requires exactly 2,000 records")
    record_ids = [record["record_id"] for record in records]
    if len(set(record_ids)) != len(record_ids):
        raise RuntimeError("input has duplicate record IDs")
    return records


def _split_records(
    records: list[dict[str, object]], seed: int, corpus_id: str = _CORPUS_ID
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        grouped[str(record["category"])].append(record)
    requested = _category_holdout_counts(grouped)
    discovery: list[dict[str, object]] = []
    holdout: list[dict[str, object]] = []
    for category in sorted(grouped):
        candidates = list(grouped[category])
        random.Random(f"{seed}:holdout:{category}").shuffle(candidates)
        holdout.extend(
            _with_split(record, "runtime_measurement_holdout", corpus_id)
            for record in candidates[: requested[category]]
        )
        discovery.extend(
            _with_split(record, "discovery", corpus_id)
            for record in candidates[requested[category] :]
        )
    return _sort_records(discovery), _sort_records(holdout)


def _category_holdout_counts(
    grouped: dict[str, list[dict[str, object]]]
) -> dict[str, int]:
    result = {category: len(records) // 4 for category, records in grouped.items()}
    remaining = _HOLDOUT_RECORD_COUNT - sum(result.values())
    fractions = sorted(
        (
            (len(records) % 4, category)
            for category, records in grouped.items()
        ),
        reverse=True,
    )
    for _, category in fractions[:remaining]:
        result[category] += 1
    if sum(result.values()) != _HOLDOUT_RECORD_COUNT:
        raise RuntimeError("could not allocate the runtime holdout")
    return result


def _select_review_sample(
    discovery: list[dict[str, object]], seed: int
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for record in discovery:
        grouped[
            (
                str(record["category"]),
                str(record["language_class"]),
                str(record["intended_length_class"]),
            )
        ].append(record)
    selected: list[dict[str, object]] = []
    for key in sorted(grouped):
        candidates = list(grouped[key])
        random.Random(f"{seed}:review:{key}").shuffle(candidates)
        selected.append(candidates[0])
    if len(selected) > _REVIEW_RECORD_COUNT:
        raise RuntimeError("stratified review seed exceeds 100 records")
    selected_ids = {str(record["record_id"]) for record in selected}
    remaining = [
        record for record in discovery if record["record_id"] not in selected_ids
    ]
    random.Random(f"{seed}:review:remaining").shuffle(remaining)
    selected.extend(remaining[: _REVIEW_RECORD_COUNT - len(selected)])
    if len(selected) != _REVIEW_RECORD_COUNT:
        raise RuntimeError("could not select 100 discovery review records")
    return _sort_records(selected)


def _with_split(
    record: dict[str, object], split: str, corpus_id: str
) -> dict[str, object]:
    return {
        **record,
        "corpus_id": corpus_id,
        "label": record["record_id"],
        "corpus_split": split,
    }


def _sort_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(records, key=lambda record: str(record["record_id"]))


def _audit(
    source: bytes,
    records: list[dict[str, object]],
    discovery: list[dict[str, object]],
    holdout: list[dict[str, object]],
    review: list[dict[str, object]],
    seed: int,
    corpus_id: str,
    discovery_path: Path,
    holdout_path: Path,
    review_path: Path,
) -> dict[str, Any]:
    return {
        "corpus_v4_runtime_split_schema_version": 1,
        "corpus_id": corpus_id,
        "source_records_sha256": hashlib.sha256(source).hexdigest(),
        "source_record_id_set_sha256": _record_id_set_sha256(records),
        "record_count": len(records),
        "split_seed": seed,
        "split_strategy": (
            "deterministic_category_quota_holdout_and_discovery_stratified_review_v1"
        ),
        "discovery_count": len(discovery),
        "holdout_count": len(holdout),
        "manual_review_count": len(review),
        "manual_review_status": "pending_human_review",
        "discovery_sha256": _file_sha256(discovery_path),
        "holdout_sha256": _file_sha256(holdout_path),
        "manual_review_sha256": _file_sha256(review_path),
        "distributions": {
            "source": _distributions(records),
            "discovery": _distributions(discovery),
            "runtime_measurement_holdout": _distributions(holdout),
            "manual_review": _distributions(review),
        },
        "batch_coverage": {
            "source": _batch_coverage(records),
            "discovery": _batch_coverage(discovery),
            "runtime_measurement_holdout": _batch_coverage(holdout),
            "manual_review": _batch_coverage(review),
        },
    }


def _distributions(records: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    return {
        field: dict(sorted(Counter(str(record[field]) for record in records).items()))
        for field in (
            "category",
            "language_class",
            "intended_length_class",
            "batch_id",
        )
    }


def _batch_coverage(records: list[dict[str, object]]) -> list[str]:
    return sorted({str(record["batch_id"]) for record in records})


def _validate_batch_coverage(records: list[dict[str, object]], name: str) -> None:
    coverage = set(_batch_coverage(records))
    if coverage != _EXPECTED_BATCH_IDS:
        missing = sorted(_EXPECTED_BATCH_IDS.difference(coverage))
        unexpected = sorted(coverage.difference(_EXPECTED_BATCH_IDS))
        raise RuntimeError(
            f"{name} does not cover every corpus batch: "
            f"missing={missing}, unexpected={unexpected}"
        )


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    _write_text(
        path,
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        ),
    )


def _write_object(path: Path, value: dict[str, Any]) -> None:
    _write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
