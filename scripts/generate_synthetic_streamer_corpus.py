"""Generate the fixed synthetic-proxy streamer and game workload corpus."""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from hashlib import sha256
from pathlib import Path

_CORPUS_ID = "streamer-game-voice-proxy-v1"
_SCHEMA_VERSION = 1
_DEFAULT_SEED = 20260730
_CATEGORY_QUOTAS = {
    "live_chat": 160,
    "game_commentary": 120,
    "game_review": 80,
    "game_dialogue": 70,
    "stream_event": 40,
    "transition": 30,
}
_LANGUAGE_QUOTAS = {"ru": 350, "en": 100, "mixed": 50}
_LENGTH_QUOTAS = {"short": 100, "medium": 200, "long": 125, "extended": 75}
_WORD_RANGES = {
    "short": (1, 5),
    "medium": (6, 14),
    "long": (15, 30),
    "extended": (31, 60),
}
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")

_RU_BASE = {
    "live_chat": [
        "Чат, вы это тоже заметили?",
        "Погодите, я сейчас дочитаю ваши сообщения.",
        "Спасибо за идею, она реально спасает этот забег.",
    ],
    "game_commentary": [
        "Босс вошёл во вторую фазу, держим позицию.",
        "Этот рейд сейчас проверит наш билд на прочность.",
        "FPS просел, но тайминг dodge всё ещё можно поймать.",
    ],
    "game_review": [
        "В этой игре отличный звук, но баланс прокачки спорный.",
        "Механика парирования простая, зато требует точного ритма.",
        "Patch notes обещают меньше гринда после 12 августа.",
    ],
    "game_dialogue": [
        "Капитан, ворота закрыты, а за стеной уже слышны шаги.",
        "Не трогай артефакт, пока не найдём инженера из Discord.",
        "Если выберем левый путь, город успеет подготовиться к ночи.",
    ],
    "stream_event": [
        "Спасибо за подписку, добро пожаловать в наш уютный хаос!",
        "Новый донат: сегодня тестируем самый странный билд недели.",
        "Ого, пять месяцев вместе, это уже серьёзный стаж.",
    ],
    "transition": [
        "Короткая пауза, проверяю звук и возвращаюсь через минуту.",
        "Следующая игра запускается, Steam сегодня думает особенно долго.",
        "Сцена готова: RTX работает, Discord не падает, можно начинать.",
    ],
}
_EN_BASE = {
    "live_chat": [
        "Chat, did you catch that detail?",
        "Give me one moment, I am reading the replies.",
        "That suggestion might save this run.",
    ],
    "game_commentary": [
        "The boss is entering phase two, stay behind the pillar.",
        "Our cooldown is back, so this is the damage window.",
        "The FPS dip is rough, but the fight is still playable.",
    ],
    "game_review": [
        "The combat feels sharp, although the upgrade path is too slow.",
        "This patch improves pacing but weakens the early game challenge.",
        "The new map has great atmosphere and confusing shortcuts.",
    ],
    "game_dialogue": [
        "Commander, the gate is sealed and the signal is getting closer.",
        "Do not touch the console until the engineer reaches the room.",
        "If we take the river route, the town may survive the night.",
    ],
    "stream_event": [
        "Thank you for the subscription, welcome to the late-night run.",
        "A new donation says we should try the risky build.",
        "Five months already, that deserves a proper victory screen.",
    ],
    "transition": [
        "Quick break while I check the audio and restart the lobby.",
        "The next game is loading; Steam has chosen a dramatic pause.",
        "Scene check complete: RTX is awake, Discord is calm, let us go.",
    ],
}
_MIXED_BASE = {
    "live_chat": [
        "Чат, кто видел этот Discord clip после boss fight?",
        "Секунду, проверю ваш Steam guide и отвечу в чате.",
        "Этот advice для рейда звучит лучше моего плана.",
    ],
    "game_commentary": [
        "Сейчас cooldown вернётся, и мы начинаем boss fight заново.",
        "FPS держится, хотя RTX уже просит пощады в этой сцене.",
        "Переходим в raid phase two, не тратьте ultimate раньше времени.",
    ],
    "game_review": [
        "В новых patch notes хороший баланс между loot и challenge.",
        "Этот билд выглядит мощно, но early game после него скучный.",
        "Steam review хвалят combat, а я пока спорю с камерой.",
    ],
    "game_dialogue": [
        "Капитан, boss уже рядом, включайте emergency protocol сейчас.",
        "Если Discord молчит, значит инженер снова чинит reactor в соло.",
        "Нам нужен stealth build, иначе patrol услышит каждый шаг.",
    ],
    "stream_event": [
        "Спасибо за subscription, сегодня ваш challenge идёт первым.",
        "Donation просит no-hit run, чат уже готовит мемы.",
        "Пять месяцев в party, это почти legendary achievement.",
    ],
    "transition": [
        "Короткий break: обновлю Discord, Steam и вернусь к рейду.",
        "Next segment через минуту, проверяю microphone и game capture.",
        "RTX прогрелась, patch notes прочитаны, начинаем второй акт.",
    ],
}
_RU_FILL = [
    "сейчас", "поэтому", "вчера", "после", "этого", "момента",
    "команда", "сразу", "проверит", "каждую", "деталь", "до", "финала",
    "и", "потом", "сравним", "результат", "с", "планом",
]
_EN_FILL = [
    "right", "now", "because", "the", "team", "needs", "to", "check",
    "every", "detail", "before", "the", "final", "round", "and", "compare",
    "the", "result", "afterward",
]
_MIXED_FILL = [
    "сейчас", "the", "team", "проверит", "каждый", "cooldown", "before",
    "финальный", "round", "и", "сравнит", "result", "после", "рейда",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    args = parser.parse_args()

    records = _build_records(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    audit = _audit(records, args.output)
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(
        json.dumps(audit, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False, sort_keys=True))
    return 0


def _build_records(seed: int) -> list[dict[str, object]]:
    rng = random.Random(seed)
    plans = _plans(rng)
    candidates = [
        _record_for_plan(rng, index, *plan)
        for index, plan in enumerate(plans)
    ]
    selected = _stratified_select(candidates, rng)
    if len(selected) != 500:
        raise RuntimeError("candidate pool cannot satisfy the fixed corpus quotas")
    return selected


def _plans(rng: random.Random) -> list[tuple[str, str, str]]:
    categories = _expanded(_CATEGORY_QUOTAS)
    languages = _expanded(_LANGUAGE_QUOTAS)
    lengths = _expanded(_LENGTH_QUOTAS)
    for values in (categories, languages, lengths):
        rng.shuffle(values)
    selected = list(zip(categories, languages, lengths, strict=True))
    extra = [rng.choice(selected) for _ in range(250)]
    return selected + extra


def _expanded(quotas: dict[str, int]) -> list[str]:
    return [name for name, count in quotas.items() for _ in range(count)]


def _record_for_plan(
    rng: random.Random,
    index: int,
    category: str,
    language: str,
    length_class: str,
) -> dict[str, object]:
    text = _expand_text(rng, category, language, length_class)
    return {
        "corpus_schema_version": _SCHEMA_VERSION,
        "corpus_id": _CORPUS_ID,
        "generation_seed": _DEFAULT_SEED,
        "generator_model": "deterministic-template-generator-v1",
        "generator_prompt_sha256": _generator_spec_sha256(),
        "label": f"synthetic-proxy-{index:03d}",
        "category": category,
        "language_class": language,
        "intended_length_class": length_class,
        "language": "auto",
        "speaker": "ryan",
        "text": text,
    }


def _expand_text(
    rng: random.Random,
    category: str,
    language: str,
    length_class: str,
) -> str:
    if length_class == "short":
        return _short_text(rng, language)
    bases = {"ru": _RU_BASE, "en": _EN_BASE, "mixed": _MIXED_BASE}[language]
    filler = {"ru": _RU_FILL, "en": _EN_FILL, "mixed": _MIXED_FILL}[language]
    text = rng.choice(bases[category])
    minimum, maximum = _WORD_RANGES[length_class]
    target = rng.randint(minimum, maximum)
    words = _word_count(text)
    extension: list[str] = []
    while words + len(extension) < target:
        extension.append(rng.choice(filler))
    if extension:
        separator = " " if text.endswith(("?", "!", ".")) else ", "
        text = text.rstrip(".?!") + separator + " ".join(extension) + "."
    return text


def _short_text(rng: random.Random, language: str) -> str:
    options = {
        "ru": (
            ["Чат", "Ого", "Так", "Рейд", "Босс", "Команда", "Сцена", "Стрим"],
            [
                "это победа",
                "почти готов",
                "идём дальше",
                "снова жив",
                "ждём патч",
                "ловим тайминг",
                "звучит отлично",
                "уже в Steam",
                "берём этот билд",
                "сохраняем момент",
            ],
        ),
        "en": (
            ["Chat", "Wow", "Okay", "Raid", "Boss", "Team", "Scene", "Stream"],
            [
                "that is a win",
                "is nearly ready",
                "we keep moving",
                "is still alive",
                "needs the patch",
                "find the timing",
                "sounds very good",
                "is on Steam",
                "take this build",
                "save that moment",
            ],
        ),
        "mixed": (
            ["Чат", "Ого", "Raid", "Boss", "Team", "Стрим", "RTX", "Discord"],
            [
                "это clean win",
                "почти ready",
                "идём дальше",
                "still alive",
                "ждём patch notes",
                "ловим timing",
                "звучит very good",
                "уже в Steam",
                "берём этот build",
                "save этот момент",
            ],
        ),
    }[language]
    return f"{rng.choice(options[0])}, {rng.choice(options[1])}."


def _stratified_select(
    records: list[dict[str, object]], rng: random.Random
) -> list[dict[str, object]]:
    pools: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for record in records:
        key = (
            str(record["category"]),
            str(record["language_class"]),
            str(record["intended_length_class"]),
        )
        pools.setdefault(key, []).append(record)
    for pool in pools.values():
        rng.shuffle(pool)
    targets = _plans(random.Random(_DEFAULT_SEED))[0:500]
    selected = []
    for category, language, length_class in targets:
        key = (category, language, length_class)
        pool = pools.get(key, [])
        if not pool:
            raise RuntimeError(f"no candidate remains for stratum {key}")
        selected.append(pool.pop())
    rng.shuffle(selected)
    for index, record in enumerate(selected, 1):
        record["label"] = f"synthetic-proxy-{index:03d}"
    return selected


def _generator_spec_sha256() -> str:
    specification = {
        "categories": _CATEGORY_QUOTAS,
        "languages": _LANGUAGE_QUOTAS,
        "lengths": _LENGTH_QUOTAS,
        "word_ranges": _WORD_RANGES,
    }
    return sha256(json.dumps(specification, sort_keys=True).encode("utf-8")).hexdigest()


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _audit(records: list[dict[str, object]], path: Path) -> dict[str, object]:
    texts = [str(record["text"]) for record in records]
    word_counts = [_word_count(text) for text in texts]
    categories = Counter(record["category"] for record in records)
    languages = Counter(record["language_class"] for record in records)
    lengths = Counter(record["intended_length_class"] for record in records)
    return {
        "corpus_schema_version": _SCHEMA_VERSION,
        "corpus_id": _CORPUS_ID,
        "record_count": len(records),
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "category_histogram": dict(sorted(categories.items())),
        "language_histogram": dict(sorted(languages.items())),
        "intended_length_histogram": dict(sorted(lengths.items())),
        "unique_text_count": len(set(texts)),
        "word_count_min": min(word_counts),
        "word_count_max": max(word_counts),
    }


if __name__ == "__main__":
    raise SystemExit(main())
