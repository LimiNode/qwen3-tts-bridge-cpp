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
    "category": {
        "game_commentary": 490,
        "live_chat": 380,
        "conversation": 320,
        "game_review": 260,
        "game_dialogue": 100,
        "stream_event": 330,
        "transition": 120,
    },
}
_ENUMS = {
    "language_class": frozenset(_GLOBAL_QUOTAS["language_class"]),
    "category": frozenset(_GLOBAL_QUOTAS["category"]),
    "intended_length_class": frozenset(_WORD_RANGES),
    "scene_context": frozenset(
        {
            "gameplay_stream",
            "just_chatting_stream",
            "technical_stream",
            "offline_conversation",
            "scripted_character",
            "community_event",
        }
    ),
    "speech_intent": frozenset(
        {
            "spontaneous_reaction",
            "audience_reply",
            "game_commentary",
            "casual_discussion",
            "opinion_review",
            "character_dialogue",
            "coordination_instruction",
            "moderation_or_technical",
            "story_anecdote",
            "transition",
            "explanation",
        }
    ),
}
_FREQUENCY_LIMITS = {
    "template_family_id": 20,
    "semantic_intent_id": 10,
    "key_phrase_id": 4,
}
_WORD_RE = re.compile(r"\S+")
_BATCH_ID_RE = re.compile(r"v4-b(0[1-9]|10)")
_RECORD_ID_RE = re.compile(r"v4-b(0[1-9]|10)-(?:00[1-9]|0[1-9]\d|1\d\d|200)")


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
        "batch_identity": _batch_identity_failures(batches),
        "duplicate_record_id": _duplicate_values(records, "record_id"),
        "duplicate_text": _duplicate_texts(records),
        "quota_ceiling": _quota_failures(records),
        "metadata_frequency": _metadata_frequency_failures(records),
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
        "remaining_quotas": _remaining_quotas(records),
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
        if any(
            not isinstance(record[field], str) or not str(record[field]).strip()
            for field in _REQUIRED
        ):
            failures.append(str(index))
            continue
        if any(record[field] not in values for field, values in _ENUMS.items()):
            failures.append(str(index))
            continue
        text = str(record["text"])
        length_class = str(record["intended_length_class"])
        batch_id = str(record["batch_id"])
        record_id = str(record["record_id"])
        if not _BATCH_ID_RE.fullmatch(batch_id) or not _RECORD_ID_RE.fullmatch(
            record_id
        ):
            failures.append(str(index))
            continue
        if not record_id.startswith(f"{batch_id}-"):
            failures.append(str(index))
            continue
        minimum, maximum = _WORD_RANGES[str(length_class)]
        if not minimum <= len(_WORD_RE.findall(text)) <= maximum:
            failures.append(str(index))
    return failures


def _duplicate_texts(records: list[dict[str, object]]) -> dict[str, int]:
    counts = Counter(str(record.get("text", "")).casefold() for record in records)
    return dict(sorted((text, count) for text, count in counts.items() if count > 1))


def _duplicate_values(records: list[dict[str, object]], field: str) -> dict[str, int]:
    counts = Counter(str(record.get(field, "")) for record in records)
    return dict(sorted((value, count) for value, count in counts.items() if count > 1))


def _batch_identity_failures(batches: list[list[dict[str, object]]]) -> list[str]:
    failures = []
    for index, batch in enumerate(batches, 1):
        batch_ids = {record.get("batch_id") for record in batch}
        record_ids = {record.get("record_id") for record in batch}
        if len(batch_ids) != 1 or len(record_ids) != _BATCH_RECORDS:
            failures.append(str(index))
            continue
        batch_id = next(iter(batch_ids))
        expected = {f"{batch_id}-{record:03d}" for record in range(1, 201)}
        if record_ids != expected:
            failures.append(str(index))
    return failures


def _metadata_frequency_failures(
    records: list[dict[str, object]],
) -> dict[str, dict[str, int]]:
    failures = {}
    for field, limit in _FREQUENCY_LIMITS.items():
        counts = Counter(str(record.get(field, "")) for record in records)
        over = {value: count for value, count in counts.items() if count > limit}
        if over:
            failures[field] = over
    return failures


def _remaining_quotas(records: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    return {
        field: {
            value: quota
            - Counter(str(record.get(field)) for record in records).get(value, 0)
            for value, quota in quotas.items()
        }
        for field, quotas in _GLOBAL_QUOTAS.items()
    }


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
