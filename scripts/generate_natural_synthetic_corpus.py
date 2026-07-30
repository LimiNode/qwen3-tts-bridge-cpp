"""Generate a natural, provenance-pinned synthetic corpus for shape discovery."""

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_CORPUS_ID = "streamer-game-voice-natural-v2"
_SCHEMA_VERSION = 2
_DEFAULT_SEED = 20260731
_TOTAL_RECORDS = 2000
_HOLDOUT_RECORDS = 500
_CATEGORY_QUOTAS = {
    "live_chat": 640,
    "game_commentary": 480,
    "game_review": 320,
    "game_dialogue": 280,
    "stream_event": 160,
    "transition": 120,
}
_LANGUAGE_QUOTAS = {"ru": 1400, "en": 400, "mixed": 200}
_LENGTH_QUOTAS = {"short": 400, "medium": 800, "long": 500, "extended": 300}
_WORD_RANGES = {
    "short": (3, 24),
    "medium": (8, 40),
    "long": (18, 80),
    "extended": (35, 130),
}
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_TEMPLATE_PATH = (
    Path(__file__).with_name("data") / "natural_synthetic_corpus_v2_templates.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery-output", type=Path, required=True)
    parser.add_argument("--holdout-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--manual-review-output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    args = parser.parse_args()

    templates, template_data_sha256 = _load_templates(_TEMPLATE_PATH)
    provenance = _provenance(args.seed, template_data_sha256)
    records = _build_records(args.seed, templates, provenance)
    discovery, holdout = _split_records(records, args.seed)
    _write_jsonl(args.discovery_output, discovery)
    _write_jsonl(args.holdout_output, holdout)
    manual_review = _manual_review_records(records, args.seed)
    _write_jsonl(args.manual_review_output, manual_review)
    audit = _audit(
        records,
        discovery,
        holdout,
        manual_review,
        args.discovery_output,
        args.holdout_output,
        args.manual_review_output,
        provenance,
    )
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False, sort_keys=True))
    return 0


def _load_templates(path: Path) -> tuple[dict[str, Any], str]:
    source = path.read_bytes()
    value = json.loads(source)
    if not isinstance(value, dict):
        raise RuntimeError("natural corpus template data must be an object")
    return value, _sha256(source)


def _provenance(seed: int, template_data_sha256: str) -> dict[str, object]:
    config = {
        "category_quotas": _CATEGORY_QUOTAS,
        "corpus_id": _CORPUS_ID,
        "holdout_records": _HOLDOUT_RECORDS,
        "language_quotas": _LANGUAGE_QUOTAS,
        "length_quotas": _LENGTH_QUOTAS,
        "schema_version": _SCHEMA_VERSION,
        "total_records": _TOTAL_RECORDS,
        "word_ranges": _WORD_RANGES,
    }
    return {
        "generation_seed": seed,
        "generation_config_sha256": _sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ),
        "generator_source_sha256": _sha256(Path(__file__).read_bytes()),
        "template_data_sha256": template_data_sha256,
    }


def _build_records(
    seed: int,
    templates: dict[str, Any],
    provenance: dict[str, object],
) -> list[dict[str, object]]:
    rng = random.Random(seed)
    categories = _expanded(_CATEGORY_QUOTAS)
    languages = _expanded(_LANGUAGE_QUOTAS)
    length_classes = _expanded(_LENGTH_QUOTAS)
    for values in (categories, languages, length_classes):
        rng.shuffle(values)

    records: list[dict[str, object]] = []
    seen_texts: set[str] = set()
    for index, (category, language, length_class) in enumerate(
        zip(categories, languages, length_classes, strict=True),
        1,
    ):
        text = _unique_text(
            rng, templates, category, language, length_class, seen_texts
        )
        record: dict[str, object] = {
            "category": category,
            "corpus_id": _CORPUS_ID,
            "corpus_schema_version": _SCHEMA_VERSION,
            "generator_model": "natural-compositional-template-v2",
            "intended_length_class": length_class,
            "label": f"natural-v2-{index:04d}",
            "language": "auto",
            "language_class": language,
            "speaker": "ryan",
            "text": text,
            **provenance,
        }
        records.append(record)
    return records


def _unique_text(
    rng: random.Random,
    templates: dict[str, Any],
    category: str,
    language: str,
    length_class: str,
    seen_texts: set[str],
) -> str:
    for _ in range(1000):
        text = _compose_text(rng, templates[language], category, length_class)
        if text not in seen_texts:
            seen_texts.add(text)
            return text
    raise RuntimeError(
        "template corpus cannot produce a unique natural utterance for "
        f"{language}/{category}/{length_class}"
    )


def _compose_text(
    rng: random.Random,
    template: dict[str, Any],
    category: str,
    length_class: str,
) -> str:
    context = _choose(rng, template["contexts"])[category]
    qualifier = _choose(rng, template["qualifiers"])
    if length_class == "short":
        stem = _choose(rng, template["short"]).format(context=context)
        return f"{stem} {_choose(rng, template['short_endings'])}"

    opening = _choose(rng, template["openings"])
    action = _choose(rng, template["actions"])
    if length_class == "medium":
        return _medium_sentence(template, context, opening, action, qualifier)

    observation = _choose(rng, template["observations"])
    if length_class == "long":
        return _long_sentence(
            template, context, opening, observation, action, qualifier
        )

    reason = _choose(rng, template["reasons"])
    closing = _choose(rng, template["closings"])
    return _extended_sentence(
        template, context, opening, observation, action, reason, closing, qualifier
    )


def _medium_sentence(
    template: dict[str, Any],
    context: str,
    opening: str,
    action: str,
    qualifier: str,
) -> str:
    if template is not None and "the chat" in template["contexts"].values():
        return f"In {context}, {opening}. {qualifier}, {action}."
    return f"В {context} {opening}. {qualifier}, {action}."


def _long_sentence(
    template: dict[str, Any],
    context: str,
    opening: str,
    observation: str,
    action: str,
    qualifier: str,
) -> str:
    if "the chat" in template["contexts"].values():
        sentence = f"In {context}, {opening}. {observation.capitalize()}."
        return f"{sentence} {qualifier}, {action}."
    sentence = f"В {context} {opening}. {observation.capitalize()}."
    return f"{sentence} {qualifier}, {action}."


def _extended_sentence(
    template: dict[str, Any],
    context: str,
    opening: str,
    observation: str,
    action: str,
    reason: str,
    closing: str,
    qualifier: str,
) -> str:
    if "the chat" in template["contexts"].values():
        return (
            f"In {context}, {opening}. {observation.capitalize()}. "
            f"{qualifier}, {action}, because {reason}. {closing}"
        )
    return (
        f"В {context} {opening}. {observation.capitalize()}. "
        f"{qualifier}, {action}, потому что {reason}. {closing}"
    )


def _split_records(
    records: list[dict[str, object]],
    seed: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for record in records:
        key = (
            str(record["category"]),
            str(record["language_class"]),
            str(record["intended_length_class"]),
        )
        grouped[key].append(record)
    rng = random.Random(seed + 1)
    holdout: list[dict[str, object]] = []
    discovery: list[dict[str, object]] = []
    for key in sorted(grouped):
        group = grouped[key]
        rng.shuffle(group)
        holdout_count = round(len(group) * _HOLDOUT_RECORDS / _TOTAL_RECORDS)
        holdout.extend(
            _with_split(record, "holdout") for record in group[:holdout_count]
        )
        discovery.extend(
            _with_split(record, "discovery") for record in group[holdout_count:]
        )
    _rebalance_holdout(discovery, holdout, _HOLDOUT_RECORDS)
    return sorted(discovery, key=lambda item: str(item["label"])), sorted(
        holdout,
        key=lambda item: str(item["label"]),
    )


def _rebalance_holdout(
    discovery: list[dict[str, object]],
    holdout: list[dict[str, object]],
    target: int,
) -> None:
    while len(holdout) < target:
        holdout.append(_with_split(discovery.pop(), "holdout"))
    while len(holdout) > target:
        discovery.append(_with_split(holdout.pop(), "discovery"))


def _with_split(record: dict[str, object], split: str) -> dict[str, object]:
    return {**record, "corpus_split": split}


def _manual_review_records(
    records: list[dict[str, object]],
    seed: int,
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for record in records:
        grouped[
            (
                str(record["category"]),
                str(record["language_class"]),
                str(record["intended_length_class"]),
            )
        ].append(record)
    rng = random.Random(seed + 2)
    selected = [rng.choice(grouped[key]) for key in sorted(grouped)]
    remaining = [record for record in records if record not in selected]
    rng.shuffle(remaining)
    selected.extend(remaining[: 100 - len(selected)])
    return [
        {
            "label": record["label"],
            "category": record["category"],
            "language_class": record["language_class"],
            "intended_length_class": record["intended_length_class"],
            "text": record["text"],
            "review_status": "pending_manual_review",
        }
        for record in sorted(selected, key=lambda item: str(item["label"]))
    ]


def _audit(
    records: list[dict[str, object]],
    discovery: list[dict[str, object]],
    holdout: list[dict[str, object]],
    manual_review: list[dict[str, object]],
    discovery_path: Path,
    holdout_path: Path,
    review_path: Path,
    provenance: dict[str, object],
) -> dict[str, object]:
    word_counts = [_word_count(str(record["text"])) for record in records]
    class_failures = [
        record["label"] for record in records if not _length_class_valid(record)
    ]
    language_failures = [
        record["label"] for record in records if not _language_valid(record)
    ]
    return {
        "audit_schema_version": 1,
        "corpus_id": _CORPUS_ID,
        "record_count": len(records),
        "discovery_count": len(discovery),
        "holdout_count": len(holdout),
        "manual_review_count": len(manual_review),
        "manual_review_status": "pending_manual_review",
        "filler_strategy": "none",
        "unique_text_count": len({str(record["text"]) for record in records}),
        "uniqueness_percent": 100.0
        * len({str(record["text"]) for record in records})
        / len(records),
        "class_validation_failures": class_failures,
        "language_validation_failures": language_failures,
        "max_repeated_token_run": max(
            _max_repeated_token_run(str(record["text"])) for record in records
        ),
        "overall_distribution": _distribution(records),
        "discovery_distribution": _distribution(discovery),
        "holdout_distribution": _distribution(holdout),
        "word_count": {"min": min(word_counts), "max": max(word_counts)},
        "discovery_sha256": _file_sha256(discovery_path),
        "holdout_sha256": _file_sha256(holdout_path),
        "manual_review_sha256": _file_sha256(review_path),
        **provenance,
    }


def _length_class_valid(record: dict[str, object]) -> bool:
    minimum, maximum = _WORD_RANGES[str(record["intended_length_class"])]
    count = _word_count(str(record["text"]))
    return minimum <= count <= maximum


def _language_valid(record: dict[str, object]) -> bool:
    text = str(record["text"])
    language = str(record["language_class"])
    has_cyrillic = _CYRILLIC_RE.search(text) is not None
    has_latin = _LATIN_RE.search(text) is not None
    return {
        "ru": has_cyrillic and not has_latin,
        "en": has_latin and not has_cyrillic,
        "mixed": has_cyrillic and has_latin,
    }[language]


def _distribution(records: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    return {
        "categories": dict(
            sorted(Counter(str(record["category"]) for record in records).items())
        ),
        "languages": dict(
            sorted(Counter(str(record["language_class"]) for record in records).items())
        ),
        "length_classes": dict(
            sorted(
                Counter(
                    str(record["intended_length_class"]) for record in records
                ).items()
            )
        ),
    }


def _max_repeated_token_run(text: str) -> int:
    previous = ""
    longest = 0
    current = 0
    for token in (match.group(0).casefold() for match in _WORD_RE.finditer(text)):
        if token == previous:
            current += 1
        else:
            previous = token
            current = 1
        longest = max(longest, current)
    return longest


def _expanded(quotas: dict[str, int]) -> list[str]:
    return [name for name, count in quotas.items() for _ in range(count)]


def _choose(rng: random.Random, values: list[Any] | dict[str, Any]) -> Any:
    if isinstance(values, dict):
        return values
    return rng.choice(values)


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
