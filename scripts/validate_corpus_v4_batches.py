"""Validate candidate 200-record corpus-v4 batches and cumulative quotas."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from scripts.audit_corpus_repetition import _audit, normalize_exact_text
except ModuleNotFoundError:
    from audit_corpus_repetition import _audit, normalize_exact_text

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
_COMPATIBILITY = {
    "game_commentary": {
        "contexts": {"gameplay_stream"},
        "intents": {
            "spontaneous_reaction",
            "game_commentary",
            "coordination_instruction",
            "explanation",
        },
    },
    "live_chat": {
        "contexts": {"just_chatting_stream", "community_event"},
        "intents": {
            "spontaneous_reaction",
            "audience_reply",
            "casual_discussion",
            "story_anecdote",
            "moderation_or_technical",
            "explanation",
        },
    },
    "conversation": {
        "contexts": {"offline_conversation"},
        "intents": {
            "casual_discussion",
            "story_anecdote",
            "explanation",
            "opinion_review",
        },
    },
    "game_review": {
        "contexts": {"offline_conversation", "technical_stream"},
        "intents": {"casual_discussion", "opinion_review", "explanation"},
    },
    "game_dialogue": {
        "contexts": {"scripted_character"},
        "intents": {"character_dialogue", "coordination_instruction"},
    },
    "stream_event": {
        "contexts": {"technical_stream", "community_event"},
        "intents": {
            "spontaneous_reaction",
            "audience_reply",
            "moderation_or_technical",
            "explanation",
        },
    },
    "transition": {
        "contexts": {"gameplay_stream", "just_chatting_stream", "technical_stream"},
        "intents": {"transition", "coordination_instruction", "explanation"},
    },
}
_WORD_RE = re.compile(r"[\w'-]+", re.UNICODE)
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


def _validate(paths: list[Path], expected_batches: int) -> dict[str, Any]:
    loaded = [_load_batch(path) for path in paths]
    batches = [batch for batch, _ in loaded]
    parse_failures = [failure for _, failures in loaded for failure in failures]
    records = [record for batch in batches for record in batch]
    record_failures = _record_failures(records)
    valid_records = [record for record in records if _record_valid(record)]
    valid_batches = [
        [record for record in batch if _record_valid(record)] for batch in batches
    ]
    repetition = _audit(valid_records) if valid_records else {"passed": True}
    failures = {
        "batch_record_count": [
            str(path)
            for path, batch in zip(paths, batches, strict=True)
            if len(batch) != _BATCH_RECORDS
        ],
        "parse": parse_failures,
        "record_contract": record_failures,
        "record_contract_details": _record_failure_details(records),
        "batch_identity": _batch_identity_failures(valid_batches),
        "contiguous_batch_prefix": _contiguous_prefix_failures(valid_batches),
        "duplicate_record_id": _duplicate_values(records, "record_id"),
        "duplicate_text": _duplicate_texts(valid_records),
        "quota_ceiling": _quota_failures(valid_records),
        "metadata_frequency": _metadata_frequency_failures(valid_records),
        "repetition": repetition["violations"] if not repetition["passed"] else {},
        "repetition_records": (
            repetition["violation_records"] if not repetition["passed"] else {}
        ),
    }
    complete = len(paths) == expected_batches
    if complete:
        failures["quota_completion"] = _quota_completion_failures(valid_records)
    passed = not any(failures.values())
    return {
        "corpus_v4_batch_validation_schema_version": 1,
        "batch_count": len(paths),
        "expected_batch_count": expected_batches,
        "record_count": len(records),
        "valid_record_count": len(valid_records),
        "complete": complete,
        "input_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        },
        "distributions": {
            key: dict(
                sorted(Counter(str(record[key]) for record in valid_records).items())
            )
            for key in _GLOBAL_QUOTAS
        },
        "remaining_quotas": _remaining_quotas(valid_records),
        "failures": failures,
        "passed": passed,
    }


def _load_batch(path: Path) -> tuple[list[dict[str, object]], list[str]]:
    records = []
    failures = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if line.strip():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                failures.append(f"{path}:{line_number}:invalid_json")
                continue
            if not isinstance(value, dict):
                failures.append(f"{path}:{line_number}:non_object")
                continue
            records.append(value)
    if not records and not failures:
        failures.append(f"{path}:empty_file")
    return records, failures


def _record_failures(records: list[dict[str, object]]) -> list[str]:
    failures = []
    for index, record in enumerate(records, 1):
        if not _record_valid(record):
            failures.append(str(index))
    return failures


def _record_failure_details(records: list[dict[str, object]]) -> dict[str, list[str]]:
    return {
        _record_label(record, index): _record_failure_reasons(record)
        for index, record in enumerate(records, 1)
        if _record_failure_reasons(record)
    }


def _record_valid(record: dict[str, object]) -> bool:
    return not _record_failure_reasons(record)


def _record_failure_reasons(record: dict[str, object]) -> list[str]:
    missing = sorted(_REQUIRED.difference(record))
    if missing:
        return [f"missing:{field}" for field in missing]
    non_string = sorted(
        field
        for field in _REQUIRED
        if not isinstance(record[field], str) or not str(record[field]).strip()
    )
    if non_string:
        return [f"empty_or_non_string:{field}" for field in non_string]
    unknown = sorted(
        field for field, values in _ENUMS.items() if record[field] not in values
    )
    if unknown:
        return [f"unknown_enum:{field}" for field in unknown]
    category = str(record["category"])
    compatibility = _COMPATIBILITY[category]
    if str(record["scene_context"]) not in compatibility["contexts"]:
        return ["incompatible_scene_context"]
    if str(record["speech_intent"]) not in compatibility["intents"]:
        return ["incompatible_speech_intent"]
    text = str(record["text"])
    length_class = str(record["intended_length_class"])
    batch_id = str(record["batch_id"])
    record_id = str(record["record_id"])
    if not _BATCH_ID_RE.fullmatch(batch_id) or not _RECORD_ID_RE.fullmatch(record_id):
        return ["invalid_batch_or_record_id"]
    if not record_id.startswith(f"{batch_id}-"):
        return ["record_id_batch_mismatch"]
    minimum, maximum = _WORD_RANGES[length_class]
    if not minimum <= len(_WORD_RE.findall(text)) <= maximum:
        return ["text_length_out_of_range"]
    return []


def _record_label(record: dict[str, object], index: int) -> str:
    record_id = record.get("record_id")
    if isinstance(record_id, str) and record_id:
        return record_id
    return str(index)


def _duplicate_texts(records: list[dict[str, object]]) -> dict[str, int]:
    counts = Counter(
        normalize_exact_text(str(record.get("text", ""))) for record in records
    )
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


def _contiguous_prefix_failures(batches: list[list[dict[str, object]]]) -> list[str]:
    batch_ids = {str(record["batch_id"]) for batch in batches for record in batch}
    expected = {f"v4-b{index:02d}" for index in range(1, len(batches) + 1)}
    return (
        []
        if batch_ids == expected
        else sorted(batch_ids.symmetric_difference(expected))
    )


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
