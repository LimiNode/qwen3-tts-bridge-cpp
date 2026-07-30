"""Measure corpus repetition with frequency limits that preserve natural phrasing."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

_TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)
_SENTENCE_RE = re.compile(r"[^.!?]+")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--corpus-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    input_bytes = args.input.read_bytes()
    records = _load_records_bytes(input_bytes)
    result = _audit(
        records,
        source_records_sha256=hashlib.sha256(input_bytes).hexdigest(),
        source_record_id_set_sha256=_record_id_set_sha256(records),
        corpus_id=args.corpus_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


def _load_records(path: Path) -> list[dict[str, object]]:
    return _load_records_bytes(path.read_bytes())


def _load_records_bytes(value: bytes) -> list[dict[str, object]]:
    records = []
    for line_number, line in enumerate(
        value.decode("utf-8").splitlines(), 1
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


def _audit(
    records: list[dict[str, object]],
    *,
    source_records_sha256: str | None = None,
    source_record_id_set_sha256: str | None = None,
    corpus_id: str | None = None,
) -> dict[str, Any]:
    texts = Counter(normalize_exact_text(str(record["text"])) for record in records)
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
        normalized_text = normalize_exact_text(str(record["text"]))
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
    result: dict[str, Any] = {
        "corpus_repetition_audit_schema_version": 4,
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
    if source_records_sha256 is not None or source_record_id_set_sha256 is not None:
        if not _is_sha256(source_records_sha256) or not _is_sha256(
            source_record_id_set_sha256
        ):
            raise RuntimeError("audit source provenance must contain SHA-256 values")
        result["source_records_sha256"] = source_records_sha256
        result["source_record_id_set_sha256"] = source_record_id_set_sha256
    if corpus_id is not None:
        if not isinstance(corpus_id, str) or not corpus_id:
            raise RuntimeError("audit corpus_id is invalid")
        result["corpus_id"] = corpus_id
    return result


def _record_id_set_sha256(records: list[dict[str, object]]) -> str:
    labels = sorted(
        _record_label(record, index) for index, record in enumerate(records, 1)
    )
    encoded = "".join(f"{label}\n" for label in labels).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.casefold())


def normalize_exact_text(text: str) -> str:
    """Return the canonical exact-duplicate key for a corpus text."""
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


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
