"""Validate candidate 200-record corpus-v4 batches and cumulative quotas."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

try:
    from scripts.audit_corpus_repetition import _audit
except ModuleNotFoundError:
    from audit_corpus_repetition import _audit

_BATCH_RECORDS = 200
_REQUIRED = {
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
_WORD_RANGES = {
    "micro": (1, 3),
    "short": (4, 7),
    "medium": (8, 18),
    "long": (19, 35),
    "extended": (36, 65),
}
_GLOBAL_QUOTAS = {
    "language_class": {"ru": 1300, "en": 500, "mixed": 200},
    "intended_length_class": {
        "micro": 300,
        "short": 400,
        "medium": 700,
        "long": 400,
        "extended": 200,
    },
}
_WORD_RE = re.compile(r"\S+")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-batches", type=int, default=10)
    args = parser.parse_args()
    if args.expected_batches <= 0:
        parser.error("--expected-batches must be positive")
    result = _validate(args.inputs, args.expected_batches)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


def _validate(paths: list[Path], expected_batches: int) -> dict[str, object]:
    batches = [_load_batch(path) for path in paths]
    records = [record for batch in batches for record in batch]
    repetition = _audit(records)
    failures = {
        "batch_record_count": [
            str(path)
            for path, batch in zip(paths, batches, strict=True)
            if len(batch) != _BATCH_RECORDS
        ],
        "record_contract": _record_failures(records),
        "duplicate_text": _duplicate_texts(records),
        "quota_ceiling": _quota_failures(records),
        "repetition": repetition["violations"] if not repetition["passed"] else {},
    }
    complete = len(paths) == expected_batches
    if complete:
        failures["quota_completion"] = _quota_completion_failures(records)
    passed = not any(failures.values())
    return {
        "corpus_v4_batch_validation_schema_version": 1,
        "batch_count": len(paths),
        "expected_batch_count": expected_batches,
        "record_count": len(records),
        "complete": complete,
        "input_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        },
        "distributions": {
            key: dict(sorted(Counter(str(record[key]) for record in records).items()))
            for key in _GLOBAL_QUOTAS
        },
        "failures": failures,
        "passed": passed,
    }


def _load_batch(path: Path) -> list[dict[str, object]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise RuntimeError(f"{path} has a non-object record")
            records.append(value)
    return records


def _record_failures(records: list[dict[str, object]]) -> list[str]:
    failures = []
    for index, record in enumerate(records, 1):
        if _REQUIRED.difference(record):
            failures.append(str(index))
            continue
        text = record["text"]
        length_class = record["intended_length_class"]
        if not isinstance(text, str) or length_class not in _WORD_RANGES:
            failures.append(str(index))
            continue
        minimum, maximum = _WORD_RANGES[str(length_class)]
        if not minimum <= len(_WORD_RE.findall(text)) <= maximum:
            failures.append(str(index))
    return failures


def _duplicate_texts(records: list[dict[str, object]]) -> dict[str, int]:
    counts = Counter(str(record.get("text", "")).casefold() for record in records)
    return dict(sorted((text, count) for text, count in counts.items() if count > 1))


def _quota_failures(records: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    result = {}
    for key, quotas in _GLOBAL_QUOTAS.items():
        counts = Counter(str(record.get(key)) for record in records)
        over = {
            value: count
            for value, count in counts.items()
            if count > quotas.get(value, 0)
        }
        if over:
            result[key] = over
    return result


def _quota_completion_failures(
    records: list[dict[str, object]],
) -> dict[str, dict[str, int]]:
    result = {}
    for key, quotas in _GLOBAL_QUOTAS.items():
        counts = Counter(str(record.get(key)) for record in records)
        mismatch = {
            value: counts.get(value, 0)
            for value, quota in quotas.items()
            if counts.get(value, 0) != quota
        }
        if mismatch:
            result[key] = mismatch
    return result


if __name__ == "__main__":
    raise SystemExit(main())
