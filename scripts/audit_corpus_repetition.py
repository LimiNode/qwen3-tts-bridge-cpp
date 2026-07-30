"""Measure corpus repetition with frequency limits that preserve natural phrasing."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

_TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)
_SENTENCE_RE = re.compile(r"[^.!?]+")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = _audit(_load_records(args.input))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


def _load_records(path: Path) -> list[dict[str, object]]:
    records = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not isinstance(value.get("text"), str):
            raise RuntimeError(f"input line {line_number} has no text")
        records.append(value)
    if not records:
        raise RuntimeError("input contains no records")
    return records


def _audit(records: list[dict[str, object]]) -> dict[str, Any]:
    texts = Counter(str(record["text"]).strip().casefold() for record in records)
    sentences = Counter()
    closings = Counter()
    ngrams = {size: Counter() for size in range(4, 9)}
    exact_occurrences: dict[str, list[str]] = {}
    sentence_occurrences: dict[str, list[str]] = {}
    closing_occurrences: dict[str, list[str]] = {}
    ngram_occurrences: dict[str, dict[str, list[str]]] = {
        str(size): {} for size in ngrams
    }
    for index, record in enumerate(records, 1):
        label = _record_label(record, index)
        normalized_text = str(record["text"]).strip().casefold()
        exact_occurrences.setdefault(normalized_text, []).append(label)
        normalized_sentences = _sentences(str(record["text"]))
        sentences.update(normalized_sentences)
        for sentence in normalized_sentences:
            sentence_occurrences.setdefault(sentence, []).append(label)
        if normalized_sentences:
            closings.update([normalized_sentences[-1]])
            closing_occurrences.setdefault(normalized_sentences[-1], []).append(label)
        tokens = _tokens(str(record["text"]))
        for size, counts in ngrams.items():
            for token_index in range(len(tokens) - size + 1):
                value = " ".join(tokens[token_index : token_index + size])
                counts.update([value])
                ngram_occurrences[str(size)].setdefault(value, []).append(label)
    limits = {
        "exact_text": 1,
        "sentence": 2,
        "closing_block": max(1, math.ceil(len(records) * 0.02)),
        "4": 6,
        "5": 4,
        "6": 2,
        "7": 2,
        "8": 1,
    }
    violations = {
        "exact_text": _over_limit(texts, limits["exact_text"]),
        "sentence": _over_limit(sentences, limits["sentence"]),
        "closing_block": _over_limit(closings, limits["closing_block"]),
        "ngrams": {
            str(size): _over_limit(counts, limits[str(size)])
            for size, counts in ngrams.items()
        },
    }
    passed = not violations["exact_text"] and not violations["sentence"]
    passed = passed and not violations["closing_block"]
    passed = passed and not any(violations["ngrams"].values())
    return {
        "corpus_repetition_audit_schema_version": 3,
        "record_count": len(records),
        "limits": limits,
        "frequencies": {
            "duplicate_exact_text": _duplicates(texts),
            "duplicate_sentences": _duplicates(sentences),
            "duplicate_closing_blocks": _duplicates(closings),
            "repeated_ngrams": {
                str(size): _duplicates(counts) for size, counts in ngrams.items()
            },
        },
        "violations": violations,
        "violation_records": {
            "exact_text": _selected_occurrences(
                violations["exact_text"], exact_occurrences
            ),
            "sentence": _selected_occurrences(
                violations["sentence"], sentence_occurrences
            ),
            "closing_block": _selected_occurrences(
                violations["closing_block"], closing_occurrences
            ),
            "ngrams": {
                str(size): _selected_occurrences(
                    violations["ngrams"][str(size)], ngram_occurrences[str(size)]
                )
                for size in ngrams
            },
        },
        "passed": passed,
    }


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.casefold())


def _sentences(text: str) -> list[str]:
    return [
        " ".join(_tokens(sentence))
        for sentence in _SENTENCE_RE.findall(text)
        if _tokens(sentence)
    ]


def _duplicates(counts: Counter[str]) -> dict[str, int]:
    return dict(sorted((value, count) for value, count in counts.items() if count > 1))


def _over_limit(counts: Counter[str], limit: int) -> dict[str, int]:
    return dict(
        sorted((value, count) for value, count in counts.items() if count > limit)
    )


def _record_label(record: dict[str, object], index: int) -> str:
    record_id = record.get("record_id")
    if isinstance(record_id, str) and record_id:
        return record_id
    return str(index)


def _selected_occurrences(
    violations: dict[str, int], occurrences: dict[str, list[str]]
) -> dict[str, list[str]]:
    return {value: occurrences[value] for value in violations}


if __name__ == "__main__":
    raise SystemExit(main())
