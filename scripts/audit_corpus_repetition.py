"""Report exact sentence, closing, and n-gram repetition in a JSONL corpus."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

_TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)
_SENTENCE_RE = re.compile(r"[^.!?]+")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-ngram-size", type=int, default=4)
    parser.add_argument("--maximum-ngram-size", type=int, default=8)
    args = parser.parse_args()
    if args.minimum_ngram_size < 2 or args.maximum_ngram_size < args.minimum_ngram_size:
        parser.error("invalid n-gram range")
    records = _load_records(args.input)
    result = _audit(records, args.minimum_ngram_size, args.maximum_ngram_size)
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


def _audit(
    records: list[dict[str, object]], minimum_ngram_size: int, maximum_ngram_size: int
) -> dict[str, object]:
    sentences = Counter()
    closings = Counter()
    ngrams = {
        size: Counter() for size in range(minimum_ngram_size, maximum_ngram_size + 1)
    }
    for record in records:
        normalized_sentences = _sentences(str(record["text"]))
        sentences.update(normalized_sentences)
        if normalized_sentences:
            closings.update([normalized_sentences[-1]])
        tokens = _tokens(str(record["text"]))
        for size, counts in ngrams.items():
            counts.update(
                " ".join(tokens[index : index + size])
                for index in range(len(tokens) - size + 1)
            )
    duplicate_sentences = _duplicates(sentences)
    duplicate_closings = _duplicates(closings)
    repeated_ngrams = {
        str(size): _duplicates(counts) for size, counts in ngrams.items()
    }
    passed = (
        not duplicate_sentences
        and not duplicate_closings
        and not any(repeated_ngrams.values())
    )
    return {
        "corpus_repetition_audit_schema_version": 1,
        "record_count": len(records),
        "duplicate_sentences": duplicate_sentences,
        "duplicate_closing_blocks": duplicate_closings,
        "repeated_ngrams": repeated_ngrams,
        "passed": passed,
    }


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _sentences(text: str) -> list[str]:
    return [
        " ".join(_tokens(sentence))
        for sentence in _SENTENCE_RE.findall(text)
        if _tokens(sentence)
    ]


def _duplicates(counts: Counter[str]) -> dict[str, int]:
    return dict(sorted((value, count) for value, count in counts.items() if count > 1))


if __name__ == "__main__":
    raise SystemExit(main())
